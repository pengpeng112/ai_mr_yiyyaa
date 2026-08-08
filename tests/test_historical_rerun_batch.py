"""历史重跑批次创建与状态控制测试。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import HistoricalRerunBatch, HistoricalRerunItem
from app.services.historical_rerun_service import (
    create_batch_from_preview,
    get_batch_dict,
    set_batch_control,
)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _preview():
    candidates = [
        {
            "business_identity_hash": "h1",
            "source_record_key": "k1",
            "audit_type_code": "progress_vs_nursing",
            "audit_run_mode": "daily_increment",
            "patient_id": "P1",
            "visit_number": "1",
            "query_date": "2026-07-01",
            "dept": "耳科",
            "previous_current_push_log_id": 10,
            "category": "pushable",
        },
        {
            "business_identity_hash": "h2",
            "source_record_key": "",
            "audit_type_code": "progress_vs_nursing",
            "audit_run_mode": "daily_increment",
            "patient_id": "P2",
            "visit_number": "1",
            "query_date": "2026-07-01",
            "dept": "",
            "previous_current_push_log_id": None,
            "category": "identity_ambiguous",
        },
    ]
    from app.services.historical_rerun_identity import make_candidate_hash

    return {
        "date_from": "2026-07-01",
        "date_to": "2026-07-01",
        "date_dimension": "query_date",
        "audit_type_codes": ["progress_vs_nursing"],
        "dept_filter": [],
        "candidate_hash": make_candidate_hash(candidates),
        "config_snapshot_hash": "cfg",
        "candidates": candidates,
    }


def test_create_batch_requires_reason_and_hash():
    db = _db()
    try:
        preview = _preview()
        try:
            create_batch_from_preview(
                db, preview, actor="admin", reason="", confirm_candidate_hash=preview["candidate_hash"]
            )
            assert False, "should require reason"
        except ValueError:
            pass

        try:
            create_batch_from_preview(
                db, preview, actor="admin", reason="审批-1", confirm_candidate_hash="wrong"
            )
            assert False, "should require matching hash"
        except LookupError:
            pass

        batch = create_batch_from_preview(
            db, preview, actor="admin", reason="审批-1", confirm_candidate_hash=preview["candidate_hash"]
        )
        db.commit()
        assert batch.id
        assert batch.status == "confirmed"
        items = db.query(HistoricalRerunItem).filter(HistoricalRerunItem.batch_id == batch.id).all()
        assert len(items) == 2
        statuses = {i.status for i in items}
        assert "pending" in statuses
        assert "identity_ambiguous" in statuses
    finally:
        db.close()


def test_pause_resume_cancel():
    db = _db()
    try:
        preview = _preview()
        batch = create_batch_from_preview(
            db, preview, actor="admin", reason="审批-2", confirm_candidate_hash=preview["candidate_hash"]
        )
        db.commit()
        batch = set_batch_control(db, batch.id, "resume")
        db.commit()
        assert batch.status == "running"

        batch = set_batch_control(db, batch.id, "pause")
        db.commit()
        assert batch.status == "paused"

        batch = set_batch_control(db, batch.id, "cancel")
        db.commit()
        assert batch.status == "cancelled"
        pending = (
            db.query(HistoricalRerunItem)
            .filter(
                HistoricalRerunItem.batch_id == batch.id,
                HistoricalRerunItem.status == "pending",
            )
            .count()
        )
        assert pending == 0
        data = get_batch_dict(batch)
        assert data["id"] == batch.id
        assert data["status"] == "cancelled"
    finally:
        db.close()
