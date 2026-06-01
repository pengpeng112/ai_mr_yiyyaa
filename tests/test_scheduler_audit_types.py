from types import SimpleNamespace

from app import scheduler


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
