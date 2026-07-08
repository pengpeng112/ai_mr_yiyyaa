from types import SimpleNamespace

from app import scheduler
from app.services import scheduler_audit_runner as runner


def test_daily_push_job_v2_aggregates_per_audit_type_and_history_errors(monkeypatch):
    monkeypatch.setattr(scheduler, "load_config", lambda: {"scheduler": {}, "notify": {}})
    monkeypatch.setattr(scheduler.ConfigParser, "get_data_source_type", lambda _config: "oracle")
    monkeypatch.setattr(scheduler.ConfigParser, "parse_oracle_config", lambda _config: {"dsn": "x"})
    monkeypatch.setattr(scheduler.ConfigParser, "get_department_list", lambda _config: [])
    monkeypatch.setattr(scheduler.ConfigParser, "get_push_settings", lambda _config: {"interval_ms": 1, "max_retry": 1})
    monkeypatch.setattr(scheduler.ConfigParser, "get_field_mapping", lambda _config, _source: {})

    audit_types = [
        SimpleNamespace(code="type_a", name="A"),
        SimpleNamespace(code="type_b", name="B"),
    ]
    monkeypatch.setattr(
        scheduler,
        "AuditTypeRegistry",
        lambda _config: SimpleNamespace(list_default_schedule=lambda: audit_types),
    )

    calls = []

    def _fake_run_daily_push_for_audit_type(**kwargs):
        calls.append(kwargs["audit_type"].code)
        if kwargs["audit_type"].code == "type_a":
            return {"total": 2, "success": 1, "failed": 1, "skipped": 0, "history_persist_error": ""}
        return {"total": 3, "success": 3, "failed": 0, "skipped": 0, "history_persist_error": "history_persist_failed: sqlite busy"}

    monkeypatch.setattr(scheduler, "_run_daily_push_for_audit_type", _fake_run_daily_push_for_audit_type)

    scheduler._daily_push_job_v2(query_date_override="2026-04-06", dept_override=[])

    info = scheduler.get_last_run_info()
    assert calls == ["type_a", "type_b"]
    assert info["query_date"] == "2026-04-06"
    assert info["total"] == 5
    assert info["success"] == 4
    assert info["failed"] == 1
    assert "history_persist_failed" in info["last_error"]


def test_daily_push_job_v2_uses_scheduler_dept_filter(monkeypatch):
    monkeypatch.setattr(scheduler, "load_config", lambda: {"scheduler": {"dept_filter": ["020103"]}, "notify": {}})
    monkeypatch.setattr(scheduler.ConfigParser, "get_data_source_type", lambda _config: "oracle")
    monkeypatch.setattr(scheduler.ConfigParser, "parse_oracle_config", lambda _config: {"dsn": "x"})
    monkeypatch.setattr(scheduler.ConfigParser, "get_department_list", lambda _config: ["old"])
    monkeypatch.setattr(scheduler.ConfigParser, "get_push_settings", lambda _config: {"interval_ms": 1, "max_retry": 1})
    monkeypatch.setattr(scheduler.ConfigParser, "get_field_mapping", lambda _config, _source: {})

    audit_type = SimpleNamespace(code="type_a", name="A")
    monkeypatch.setattr(
        scheduler,
        "AuditTypeRegistry",
        lambda _config: SimpleNamespace(list_default_schedule=lambda: [audit_type]),
    )

    seen = {}

    def _fake_run_daily_push_for_audit_type(**kwargs):
        seen["dept_list"] = kwargs["dept_list"]
        return {"total": 1, "success": 1, "failed": 0, "skipped": 0, "history_persist_error": ""}

    monkeypatch.setattr(scheduler, "_run_daily_push_for_audit_type", _fake_run_daily_push_for_audit_type)

    scheduler._daily_push_job_v2_unlocked(query_date_override="2026-04-06")

    assert seen["dept_list"] == ["020103"]
    assert scheduler.get_last_run_info()["dept_filter"] == ["020103"]


def _run_scheduler_bulk_worker_case(monkeypatch, db_type: str, requested_workers: int) -> int:
    captured = {}

    class FakeDB:
        def add(self, _item):
            return None

        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    class FakeBulkPushExecutor:
        def __init__(self, *args, **kwargs):
            captured["max_workers"] = kwargs.get("max_workers")

        def execute(self, grouped, _push_config):
            return SimpleNamespace(success=len(grouped), failed=0, skipped=0, results=[])

    audit_type = SimpleNamespace(
        code="generic_type",
        payload={"builder": "generic_multi_source"},
        dify=SimpleNamespace(model_dump=lambda: {"base_url": "http://dify", "api_key": "k"}),
    )
    bundle = SimpleNamespace(bundle_id="p1")

    monkeypatch.setattr(runner, "SessionLocal", lambda: FakeDB())
    monkeypatch.setattr(runner, "get_app_db_type", lambda: db_type)
    monkeypatch.setattr(runner, "BulkPushExecutor", FakeBulkPushExecutor)
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda item, _mode: item)
    monkeypatch.setattr(runner, "load_patient_bundles", lambda **_kwargs: [bundle])
    monkeypatch.setattr(runner.ConfigParser, "parse_persisted_dify_targets", lambda _config: [{"name": "default"}])

    runner.run_daily_push_for_audit_type(
        config={"notify": {}},
        data_source="oracle",
        db_cfg={},
        audit_type=audit_type,
        query_date="2026-04-06",
        dept_list=[],
        push_settings={"interval_ms": 1, "max_retry": 1, "parallel_workers": requested_workers},
        field_mapping={},
    )
    return captured["max_workers"]


def test_scheduler_bulk_parallel_workers_capped_in_sqlite(monkeypatch):
    assert _run_scheduler_bulk_worker_case(monkeypatch, "sqlite", 32) == 4


def test_scheduler_bulk_parallel_workers_not_capped_in_oracle(monkeypatch):
    assert _run_scheduler_bulk_worker_case(monkeypatch, "oracle", 16) == 16
