from app.services.bulk_push_executor import BulkPushExecutor
from app.services.push_executor import PushConfig
import pytest


def _build_executor(**kwargs):
    return BulkPushExecutor(
        dify_config={
            "name": "default",
            "base_url": "http://dify-a/v1",
            "api_key": "k1",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "user_identifier": "u1",
            "timeout_seconds": 30,
        },
        **kwargs,
    )


def test_round_robin_with_weighted_ring_selects_targets_in_order():
    executor = _build_executor(
        dify_targets=[
            {
                "name": "a",
                "base_url": "http://dify-a/v1",
                "api_key": "k1",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u1",
                "timeout_seconds": 30,
                "weight": 1,
                "enabled": True,
            },
            {
                "name": "b",
                "base_url": "http://dify-b/v1",
                "api_key": "k2",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u2",
                "timeout_seconds": 30,
                "weight": 2,
                "enabled": True,
            },
        ],
        target_strategy="round_robin",
    )

    picked = [executor._pick_target().name for _ in range(4)]
    assert picked == ["a", "b", "b", "a"]

    metrics = executor.get_target_metrics()
    assert metrics["a"]["selected"] == 2
    assert metrics["b"]["selected"] == 2


def test_empty_output_retry_then_success(monkeypatch):
    executor = _build_executor(
        empty_retry_max=2,
        empty_retry_backoff_ms=0,
    )
    calls = {"n": 0}

    def _fake_push(_dify_input, _cfg, _patient_id):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"status": "success", "result": {"aa": ""}}
        return {
            "status": "success",
            "result": {"aa": "ok"},
            "workflow_run_id": "wr-1",
            "elapsed_ms": 12,
        }

    monkeypatch.setattr("app.services.bulk_push_executor.push_to_dify", _fake_push)
    result = executor._push_with_empty_retry("payload", "p001")

    assert result["status"] == "success"
    assert result["_empty_retry_count"] == 2
    assert calls["n"] == 3

    metrics = executor.get_target_metrics()["default"]
    assert metrics["selected"] == 3
    assert metrics["empty"] == 2
    assert metrics["success"] == 1
    assert metrics["failed"] == 2


def test_circuit_breaker_skips_open_target():
    executor = _build_executor(
        dify_targets=[
            {
                "name": "a",
                "base_url": "http://dify-a/v1",
                "api_key": "k1",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u1",
                "timeout_seconds": 30,
                "weight": 1,
                "enabled": True,
            },
            {
                "name": "b",
                "base_url": "http://dify-b/v1",
                "api_key": "k2",
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u2",
                "timeout_seconds": 30,
                "weight": 1,
                "enabled": True,
            },
        ],
        circuit_breaker_failures=2,
        circuit_breaker_seconds=60,
    )

    executor._record_target_result("a", success=False, empty=False)
    executor._record_target_result("a", success=False, empty=False)

    picked = executor._pick_target()
    assert picked.name == "b"


def test_execute_aggregates_success_skipped_failed_and_callbacks(monkeypatch):
    executor = _build_executor(max_workers=3)
    grouped = {
        "p001_1": [{}],
        "p002_1": [{}],
        "p003_1": [{}],
    }
    statuses = {
        "p001_1": "success",
        "p002_1": "skipped",
        "p003_1": "error",
    }

    def _fake_process_single(patient_id, _records, _cfg):
        status = statuses[patient_id]
        return {
            "patient_id": patient_id,
            "status": status,
            "inconsistency": False,
            "severity": "",
            "workflow_run_id": "",
            "elapsed_ms": 0,
        }

    monkeypatch.setattr(executor, "_process_single", _fake_process_single)
    callback_statuses = []
    result = executor.execute(
        grouped_records=grouped,
        push_config=PushConfig(trigger_type="manual", query_date="2026-04-06"),
        on_item_done=lambda s: callback_statuses.append(s),
    )

    assert result.total == 3
    assert result.success == 1
    assert result.failed == 1
    assert len(result.results) == 3
    assert sorted(callback_statuses) == ["error", "skipped", "success"]


def test_process_single_passes_source_key_and_run_mode_to_skip(monkeypatch):
    executor = _build_executor()
    captured = {}

    class FakeDB:
        def add(self, item):
            self.item = item

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    class FakeBundle:
        group_values = {"patient_id": "p001", "visit_number": "1"}
        sources = {"primary": [{"patient_id": "p001", "visit_number": "1"}]}
        primary_source = "primary"

    def fake_build_payload(self, patient_id, patient_records, push_config):
        return FakeBundle(), {"mr_text": "text"}, "text", None, "1", patient_records

    def fake_get_skip_reason(self, db, patient_id, visit_number, audit_type_code, source_record_key="", audit_run_mode="daily_increment"):
        captured.update({
            "patient_id": patient_id,
            "visit_number": visit_number,
            "audit_type_code": audit_type_code,
            "source_record_key": source_record_key,
            "audit_run_mode": audit_run_mode,
        })
        return "unreviewed_pending", "already pushed"

    monkeypatch.setattr("app.services.bulk_push_executor.SessionLocal", lambda: FakeDB())
    monkeypatch.setattr("app.services.bulk_push_executor.PushExecutor._build_payload_and_mr_text", fake_build_payload)
    monkeypatch.setattr("app.services.bulk_push_executor.PushExecutor._get_skip_reason", fake_get_skip_reason)
    monkeypatch.setattr("app.services.bulk_push_executor.PushExecutor._create_skipped_push_log", lambda *args, **kwargs: object())

    audit_type = {
        "code": "demo_type",
        "group_key": ["patient_id", "visit_number"],
        "payload": {"builder": "generic_multi_source"},
    }
    push_config = PushConfig(
        trigger_type="manual",
        query_date="2026-04-06",
        audit_type_code="demo_type",
        audit_type=audit_type,
        audit_run_mode="discharge_final",
    )

    result = executor._process_single("p001_1", [{}], push_config)

    assert result["status"] == "skipped"
    assert captured["audit_type_code"] == "demo_type"
    assert captured["audit_run_mode"] == "discharge_final"
    assert captured["source_record_key"] == "mode::discharge_final::demo_type::p001::1"


def test_init_raises_when_all_targets_disabled():
    with pytest.raises(ValueError):
        _build_executor(
            dify_targets=[
                {
                    "name": "a",
                    "base_url": "http://dify-a/v1",
                    "api_key": "k1",
                    "workflow_input_variable": "mr_txt",
                    "workflow_output_key": "aa",
                    "user_identifier": "u1",
                    "timeout_seconds": 30,
                    "weight": 1,
                    "enabled": False,
                }
            ]
        )
