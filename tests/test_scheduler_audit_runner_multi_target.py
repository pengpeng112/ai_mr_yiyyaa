"""006: 自动任务 daily/discharge 多节点接线测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import encrypt_value
from app.services import scheduler_audit_runner as runner
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.push_executor import PushExecutor, PushResult


def _audit(code="jyjc_vs_bcnursing", builder="generic_multi_source"):
    return SimpleNamespace(
        code=code,
        name=code,
        payload={"builder": builder},
        dify=SimpleNamespace(
            model_dump=lambda: {
                "base_url": "http://audit/v1",
                "api_key_enc": encrypt_value("audit-key"),
                "workflow_input_variable": "mr_txt",
                "workflow_output_key": "aa",
                "user_identifier": "u",
                "timeout_seconds": 90,
                "extra_inputs": {"mr_type": "检验检查与病程护理核查"},
                "full_debug_log": False,
            }
        ),
    )


def _legacy_audit():
    return _audit(code="progress_vs_nursing", builder="legacy_progress_nursing")


def _base_config(targets=None):
    return {
        "dify": {
            "base_url": "http://global/v1",
            "api_key_enc": encrypt_value("global-key"),
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "user_identifier": "u",
            "timeout_seconds": 90,
            "extra_inputs": {},
            "target_strategy": "round_robin",
            "circuit_breaker_failures": 3,
            "circuit_breaker_seconds": 60,
            "targets": targets or [],
        },
        "notify": {},
        "departments": {"mode": "include", "list": []},
    }


@pytest.fixture
def mock_db(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr(runner, "SessionLocal", lambda: db)
    return db


def test_daily_multi_source_zero_targets_uses_push_executor(monkeypatch, mock_db):
    captured = {}

    def _load_bundles(**kwargs):
        return [SimpleNamespace(bundle_id="p1_1")]

    class _PE:
        def __init__(self, *a, **k):
            captured["executor"] = "serial"
            captured["dify"] = a[0] if a else k.get("dify_config")

        def execute(self, db, grouped, push_config):
            captured["push_config"] = push_config
            return PushResult(total=1, success=1, failed=0, skipped=0, results=[{"status": "success"}])

    class _BE:
        def __init__(self, *a, **k):
            captured["executor"] = "bulk"

    monkeypatch.setattr(runner, "load_patient_bundles", _load_bundles)
    monkeypatch.setattr(runner, "PushExecutor", _PE)
    monkeypatch.setattr(runner, "BulkPushExecutor", _BE)
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda at, mode: at)
    monkeypatch.setattr(runner, "effective_parallel_workers", lambda *a, **k: (2, ""))

    result = runner.run_daily_push_for_audit_type(
        config=_base_config([]),
        data_source="oracle",
        db_cfg={},
        audit_type=_audit(),
        query_date="2026-07-15",
        dept_list=[],
        push_settings={"interval_ms": 0, "max_retry": 0, "parallel_workers": 2},
        field_mapping={},
        audit_run_mode="daily_increment",
    )
    assert captured["executor"] == "serial"
    assert result["executor_mode"] == "serial"
    assert result["pool"]["use_bulk"] is False


def test_daily_multi_source_two_targets_uses_bulk_with_strategy(monkeypatch, mock_db):
    captured = {}
    targets = [
        {
            "name": "a",
            "base_url": "http://a/v1",
            "api_key_enc": encrypt_value("k1"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        },
        {
            "name": "b",
            "base_url": "http://b/v1",
            "api_key_enc": encrypt_value("k2"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        },
    ]

    def _load_bundles(**kwargs):
        return [SimpleNamespace(bundle_id="p1_1"), SimpleNamespace(bundle_id="p2_1")]

    class _BE:
        def __init__(self, *a, **k):
            captured["kwargs"] = k
            captured["dify_config"] = k.get("dify_config") or (a[0] if a else {})

        def execute(self, grouped, push_config, on_item_done=None, stop_check=None):
            captured["push_config"] = push_config
            captured["grouped_count"] = len(grouped)
            return PushResult(
                total=2,
                success=2,
                failed=0,
                skipped=0,
                results=[{"status": "success"}, {"status": "success"}],
            )

        def get_target_metrics(self):
            return {"a": {"selected": 1, "success": 1, "failed": 0, "empty": 0}}

    monkeypatch.setattr(runner, "load_patient_bundles", _load_bundles)
    monkeypatch.setattr(runner, "BulkPushExecutor", _BE)
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda at, mode: at)
    monkeypatch.setattr(runner, "effective_parallel_workers", lambda *a, **k: (2, ""))

    cfg = _base_config(targets)
    cfg["dify"]["target_strategy"] = "weighted_random"
    cfg["dify"]["circuit_breaker_seconds"] = 120
    result = runner.run_daily_push_for_audit_type(
        config=cfg,
        data_source="oracle",
        db_cfg={},
        audit_type=_audit(),
        query_date="2026-07-15",
        dept_list=[],
        push_settings={"interval_ms": 0, "max_retry": 0, "parallel_workers": 2},
        field_mapping={},
        audit_run_mode="daily_increment",
    )
    assert result["executor_mode"] == "bulk"
    assert captured["kwargs"]["target_strategy"] == "weighted_random"
    assert captured["kwargs"]["circuit_breaker_seconds"] == 120
    assert captured["dify_config"]["workflow_output_key"] == "aa"
    assert captured["push_config"].audit_type_code == "jyjc_vs_bcnursing"
    assert result["target_metrics"]["a"]["selected"] == 1


def test_discharge_multi_source_two_targets_bulk(monkeypatch, mock_db):
    captured = {}
    targets = [
        {
            "name": "a",
            "base_url": "http://a/v1",
            "api_key_enc": encrypt_value("k1"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        }
    ]

    def _load_bundles(**kwargs):
        captured["date_dimension"] = kwargs.get("date_dimension")
        return [SimpleNamespace(bundle_id="p1_1")]

    class _BE:
        def __init__(self, *a, **k):
            captured["bulk"] = True

        def execute(self, grouped, push_config, on_item_done=None, stop_check=None):
            captured["audit_run_mode"] = push_config.audit_run_mode
            return PushResult(total=1, success=1, failed=0, skipped=0, results=[{"status": "success"}])

        def get_target_metrics(self):
            return {}

    monkeypatch.setattr(runner, "load_patient_bundles", _load_bundles)
    monkeypatch.setattr(runner, "BulkPushExecutor", _BE)
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda at, mode: at)
    monkeypatch.setattr(runner, "effective_parallel_workers", lambda *a, **k: (1, ""))

    result = runner.run_daily_push_for_audit_type(
        config=_base_config(targets),
        data_source="oracle",
        db_cfg={},
        audit_type=_audit(),
        query_date="2026-07-15",
        dept_list=[],
        push_settings={"interval_ms": 0, "max_retry": 0, "parallel_workers": 1},
        field_mapping={},
        audit_run_mode="discharge_final",
    )
    assert captured["bulk"] is True
    assert captured["date_dimension"] == "discharge_date"
    assert captured["audit_run_mode"] == "discharge_final"
    assert result["executor_mode"] == "bulk"


def test_legacy_daily_two_targets_bulk(monkeypatch, mock_db):
    captured = {}
    targets = [
        {
            "name": "a",
            "base_url": "http://a/v1",
            "api_key_enc": encrypt_value("k1"),
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        }
    ]

    monkeypatch.setattr(runner, "fetch_records", lambda *a, **k: [{"患者ID": "1", "次数": "1"}])
    monkeypatch.setattr(runner, "group_by_patient", lambda records, fm: {"1_1": records})
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda at, mode: at)
    monkeypatch.setattr(runner, "effective_parallel_workers", lambda *a, **k: (1, ""))

    class _BE:
        def __init__(self, *a, **k):
            captured["bulk"] = True
            captured["base_url"] = (k.get("dify_config") or {}).get("base_url")

        def execute(self, grouped, push_config, on_item_done=None, stop_check=None):
            return PushResult(total=1, success=1, failed=0, skipped=0, results=[{"status": "success"}])

        def get_target_metrics(self):
            return {"a": {"selected": 1, "success": 1, "failed": 0, "empty": 0}}

    monkeypatch.setattr(runner, "BulkPushExecutor", _BE)

    result = runner.run_daily_push_for_audit_type(
        config=_base_config(targets),
        data_source="oracle",
        db_cfg={"query_sql": "SELECT 1 {dept_filter}"},
        audit_type=_legacy_audit(),
        query_date="2026-07-15",
        dept_list=[],
        push_settings={"interval_ms": 0, "max_retry": 0, "parallel_workers": 1},
        field_mapping={"patient_id": "患者ID", "visit_number": "次数", "dept": "所在科室名称"},
        audit_run_mode="daily_increment",
    )
    assert captured["bulk"] is True
    assert result["executor_mode"] == "bulk"


def test_pool_unavailable_marks_failed_history(monkeypatch, mock_db):
    targets = [
        {
            "name": "broken",
            "base_url": "http://a/v1",
            "api_key_enc": "invalid",
            "timeout_seconds": 30,
            "weight": 1,
            "enabled": True,
        }
    ]
    monkeypatch.setattr(runner, "load_patient_bundles", lambda **k: [SimpleNamespace(bundle_id="p1")])
    monkeypatch.setattr(runner, "audit_type_for_run_mode", lambda at, mode: at)
    monkeypatch.setattr(runner, "effective_parallel_workers", lambda *a, **k: (1, ""))

    with pytest.raises(RuntimeError, match="dify_target_pool_unavailable"):
        runner.run_daily_push_for_audit_type(
            config=_base_config(targets),
            data_source="oracle",
            db_cfg={},
            audit_type=_audit(),
            query_date="2026-07-15",
            dept_list=[],
            push_settings={"interval_ms": 0, "max_retry": 0, "parallel_workers": 1},
            field_mapping={},
            audit_run_mode="daily_increment",
        )
    # history 写入 failed
    assert mock_db.add.called
    history = mock_db.add.call_args[0][0]
    assert history.status == "failed"
