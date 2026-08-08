"""ACTIVE/002 幂等 execution/attempt 基础测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushAttempt, PushExecution, PushLog
from app.services.push_idempotency import claim_execution, finish_execution, make_idempotency_key


def test_idempotency_key_changes_with_mode_and_version():
    first = make_idempotency_key("source-1", "admission_vs_first_progress", "daily_increment", "v1")
    assert first == make_idempotency_key("source-1", "admission_vs_first_progress", "daily_increment", "v1")
    assert first != make_idempotency_key("source-1", "admission_vs_first_progress", "discharge_final", "v1")
    # P1-5: source_version 不再参与 key，同一身份不同 version 产生相同 key
    assert first == make_idempotency_key("source-1", "admission_vs_first_progress", "daily_increment", "v2")


def test_execution_and_attempt_models_are_separate():
    assert PushExecution.__tablename__ != PushAttempt.__tablename__
    exec_names = {c.name for c in PushExecution.__table__.constraints if getattr(c, "name", None)}
    att_names = {c.name for c in PushAttempt.__table__.constraints if getattr(c, "name", None)}
    exec_idx = {i.name for i in PushExecution.__table__.indexes if getattr(i, "name", None)}
    att_idx = {i.name for i in PushAttempt.__table__.indexes if getattr(i, "name", None)}
    assert "uq_push_execution_key_mode" in exec_names or "uq_push_execution_key_mode" in exec_idx
    assert "uq_push_attempt_no" in att_names or "uq_push_attempt_no" in att_idx


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def test_claim_only_one_owner_for_same_key():
    db = _db()
    try:
        e1, c1, r1 = claim_execution(db, "src::1", "progress_vs_nursing", "daily_increment")
        db.commit()
        assert c1 is True and r1 == "claimed"
        assert e1.status == "running"

        e2, c2, r2 = claim_execution(db, "src::1", "progress_vs_nursing", "daily_increment")
        assert c2 is False and r2 == "in_flight"
        assert e2.id == e1.id
    finally:
        db.close()


def test_lease_expired_can_be_reclaimed():
    db = _db()
    try:
        e1, c1, _ = claim_execution(db, "src::2", "progress_vs_nursing", "daily_increment", lease_seconds=1)
        db.commit()
        e1.lease_until = datetime.now() - timedelta(seconds=5)
        db.commit()

        e2, c2, r2 = claim_execution(db, "src::2", "progress_vs_nursing", "daily_increment")
        db.commit()
        assert c2 is True and r2 == "claimed"
        assert e2.id == e1.id
        attempts = db.query(PushAttempt).filter(PushAttempt.execution_id == e2.id).count()
        assert attempts == 2
    finally:
        db.close()


def test_same_version_reviewed_skips():
    db = _db()
    try:
        e1, c1, _ = claim_execution(db, "src::3", "progress_vs_nursing", "daily_increment")
        db.commit()
        log = PushLog(
            push_time=datetime.now(),
            trigger_type="manual",
            query_date="2026-07-01",
            patient_id="P1",
            status="success",
            pushed_flag=1,
            reviewed_flag=1,
            source_record_key="src::3",
            audit_type_code="progress_vs_nursing",
            audit_run_mode="daily_increment",
        )
        db.add(log)
        db.flush()
        finish_execution(db, e1, "success", push_log_id=log.id, reviewed_flag=1)
        db.commit()

        e2, c2, r2 = claim_execution(db, "src::3", "progress_vs_nursing", "daily_increment")
        assert c2 is False and r2 == "same_version_reviewed"
    finally:
        db.close()


def test_force_claim_allows_historical_rerun():
    db = _db()
    try:
        e1, _, _ = claim_execution(db, "src::4", "progress_vs_nursing", "daily_increment")
        finish_execution(db, e1, "success", push_log_id=1, reviewed_flag=1)
        db.commit()

        # P1-5: source_version 不参与 key，force 可重新 claim 已完成的同身份 execution
        e2, c2, r2 = claim_execution(
            db,
            "src::4",
            "progress_vs_nursing",
            "daily_increment",
            source_version="hist_rerun:9",
            force=True,
        )
        assert c2 is True and r2 == "claimed"
        # 统一 key 后复用同一 execution 记录
        assert e2.id == e1.id
    finally:
        db.close()
