"""W1：契约不可用的新成功结果不得挤掉旧可用当前。

transport success + parse success + contract_valid=False 时 is_qc_usable 为假。
attach_success_push_log_as_current 必须沿用 061/D4 归档路径：新尝试 superseded_by
指向旧当前，旧结果与维度保持不动。既有 failed/fallback 门槛不在本文件改写。
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, _push_log_current_identity_index_ddl
from app.models import AuditDimensionResult, PushLog
from app.services.push_log_supersede import attach_success_push_log_as_current
from app.services.qc_status_semantics import is_qc_usable

SOURCE_KEY = "mode::daily_increment::progress_vs_nursing::SYN-W1::1"
PATIENT_ID = "SYN-W1"


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(_push_log_current_identity_index_ddl("push_log", "sqlite")))
    return sessionmaker(bind=engine)()


def _make_log(**kwargs):
    defaults = {
        "push_time": datetime.now(),
        "trigger_type": "auto",
        "query_date": "2026-10-11",
        "patient_id": PATIENT_ID,
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "daily_increment",
        "status": "success",
        "pushed_flag": 1,
        "parse_status": "success",
        "source_record_key": SOURCE_KEY,
        "contract_valid": True,
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def _seed_old_current(db):
    old = _make_log(contract_valid=True)
    db.add(old)
    db.flush()
    db.add(
        AuditDimensionResult(
            push_log_id=old.id,
            dimension_code="progress_vs_nursing",
            dimension="病程与护理一致性",
            status="❌",
            severity="medium",
        )
    )
    db.flush()
    return old


def _query_current(db):
    return (
        db.query(PushLog)
        .filter(
            PushLog.source_record_key == SOURCE_KEY,
            PushLog.audit_type_code == "progress_vs_nursing",
            PushLog.audit_run_mode == "daily_increment",
            PushLog.status == "success",
            PushLog.superseded_by.is_(None),
        )
        .all()
    )


def _contract_invalid_result():
    return {
        "status": "success",
        "workflow_run_id": "wr-w1",
        "task_id": "t-w1",
        "result": {},
        "parsed_output": {"parse_success": True, "dimensions": []},
        "elapsed_ms": 12,
        "inconsistency": False,
        "severity": "low",
        "risk_score": 0,
        "parse_error": "",
        "error": "",
        "contract_valid": False,
        "contract_errors": "validator_rejected",
    }


@pytest.mark.parametrize("contract_valid", [False, 0])
def test_contract_invalid_archives_attempt_and_keeps_old_current(contract_valid):
    """旧可用当前 + 新契约失败 → 旧仍为当前，新被归档。"""
    db = _make_db()
    try:
        old = _seed_old_current(db)
        old_id = old.id
        new_log = _make_log(contract_valid=contract_valid)
        assert new_log.status == "success"
        assert new_log.parse_status == "success"
        cv = False if new_log.contract_valid == 0 else new_log.contract_valid
        assert is_qc_usable(new_log.status, new_log.parse_status, cv) is False

        assert attach_success_push_log_as_current(db, new_log) == 0
        db.flush()

        assert old.superseded_by is None
        assert new_log.superseded_by == old_id
        assert [row.id for row in _query_current(db)] == [old_id]
        assert (
            db.query(AuditDimensionResult)
            .filter(AuditDimensionResult.push_log_id == old_id)
            .count()
        ) == 1
        assert (
            db.query(AuditDimensionResult)
            .filter(AuditDimensionResult.push_log_id == new_log.id)
            .count()
        ) == 0
    finally:
        db.close()


def test_unusable_contract_then_real_success_still_replaces():
    """本次契约不可用只归档；下一次真正可用结果仍可替代旧当前。"""
    db = _make_db()
    try:
        old = _seed_old_current(db)
        bad = _make_log(contract_valid=False)
        assert attach_success_push_log_as_current(db, bad) == 0
        assert bad.superseded_by == old.id
        assert old.superseded_by is None

        good = _make_log(contract_valid=True, parse_status="success")
        assert is_qc_usable(good.status, good.parse_status, True) is True
        assert attach_success_push_log_as_current(db, good) == 1
        db.commit()

        assert old.superseded_by == good.id
        assert bad.superseded_by == old.id
        assert [row.id for row in _query_current(db)] == [good.id]
    finally:
        db.close()


@pytest.mark.parametrize("path", ["serial", "bulk"])
def test_executors_keep_old_current_when_contract_invalid(monkeypatch, path):
    """串行与批量执行器都经 attach_success_push_log_as_current，契约失败不挤占当前槽。"""
    from types import SimpleNamespace

    from app.services.bulk_push_executor import BulkPushExecutor
    from app.services.push_executor import PushConfig, PushExecutor

    db = _make_db()
    try:
        old = _seed_old_current(db)
        db.commit()
        old_id = old.id
        result = _contract_invalid_result()

        def _new_log(*_args, **_kwargs):
            return _make_log(contract_valid=False)

        monkeypatch.setattr(
            PushExecutor,
            "_build_payload_and_mr_text",
            lambda *a: (
                SimpleNamespace(group_values={"patient_id": PATIENT_ID, "visit_number": "1"}),
                {"patient_info": {"patient_id": PATIENT_ID, "visit_number": "1"}},
                "synthetic-mr",
                PATIENT_ID,
                "1",
                [{}],
            ),
        )
        monkeypatch.setattr(PushExecutor, "_get_skip_reason", lambda *a, **k: ("", ""))
        monkeypatch.setattr(PushExecutor, "_create_push_log", _new_log)
        monkeypatch.setattr("app.services.push_idempotency.claim_execution", lambda *a, **k: (None, True, ""))
        monkeypatch.setattr(PushExecutor, "_save_audit_results", MagicMock())
        monkeypatch.setattr(
            "app.services.relay_alert_service.RelayAlertService.enqueue_high_severity_alerts",
            MagicMock(),
        )
        monkeypatch.setattr(
            "app.services.relay_alert_service.RelayAlertService.dispatch_pending",
            lambda *a, **k: {},
        )
        cfg = PushConfig(
            trigger_type="manual",
            query_date="2026-10-11",
            audit_type_code="progress_vs_nursing",
            alert_policy="suppress",
        )
        if path == "serial":
            monkeypatch.setattr("app.services.push_executor.push_to_dify", lambda *a, **k: result)
            actual = PushExecutor({})._push_single_record(db, PATIENT_ID, [{}], cfg)
            db.commit()
        else:
            monkeypatch.setattr(
                "app.services.bulk_push_executor.SessionLocal",
                sessionmaker(bind=db.get_bind()),
            )
            monkeypatch.setattr(BulkPushExecutor, "_push_with_empty_retry", lambda *a, **k: result)
            actual = BulkPushExecutor(
                {"base_url": "http://dify.local/v1", "api_key": "test"}
            )._process_single(PATIENT_ID, [{}], cfg)

        assert actual["status"] == "success"
        db.expire_all()
        currents = _query_current(db)
        assert [row.id for row in currents] == [old_id]
        rows = db.query(PushLog).all()
        assert len(rows) == 2
        new_row = next(row for row in rows if row.id != old_id)
        assert new_row.superseded_by == old_id
        assert new_row.parse_status == "success"
        assert (
            db.query(AuditDimensionResult)
            .filter(AuditDimensionResult.push_log_id == old_id)
            .count()
        ) == 1
    finally:
        db.close()
