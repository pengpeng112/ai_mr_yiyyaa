"""历史重跑替代规则与当前结果投影测试（ACTIVE/007 E/F）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog
from app.services.current_result_filter import apply_current_result_filter
from app.services.historical_rerun_identity import (
    is_identity_ambiguous,
    make_business_identity_hash,
    make_candidate_hash,
)
from app.services.push_log_supersede import mark_historical_reaudit_superseded


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _log(**kwargs):
    defaults = {
        "push_time": datetime.now(),
        "trigger_type": "manual",
        "query_date": "2026-07-01",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "daily_increment",
        "status": "success",
        "pushed_flag": 1,
        "parse_status": "success",
        "source_record_key": "progress_vs_nursing::P001::1",
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def test_identity_hash_stable_and_mode_sensitive():
    a = make_business_identity_hash("k1", "progress_vs_nursing", "daily_increment", "P1", "1")
    b = make_business_identity_hash("k1", "progress_vs_nursing", "daily_increment", "P1", "1")
    c = make_business_identity_hash("k1", "progress_vs_nursing", "discharge_final", "P1", "1")
    assert a == b
    assert a != c
    assert is_identity_ambiguous("")
    assert not is_identity_ambiguous("k1")


def test_candidate_hash_ignores_order():
    items = [
        {"business_identity_hash": "h2", "source_record_key": "k2", "audit_type_code": "a", "query_date": "2026-07-02"},
        {"business_identity_hash": "h1", "source_record_key": "k1", "audit_type_code": "a", "query_date": "2026-07-01"},
    ]
    rev = list(reversed(items))
    assert make_candidate_hash(items) == make_candidate_hash(rev)


def test_success_qc_usable_supersedes_same_identity():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()

        new = _log(query_date="2026-07-10")
        db.add(new)
        db.commit()

        count = mark_historical_reaudit_superseded(db, new, expected_previous_id=old.id)
        db.commit()
        assert count == 1
        db.refresh(old)
        assert old.superseded_by == new.id
        assert old.superseded_at is not None
    finally:
        db.close()


def test_parse_failed_does_not_supersede():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()

        new = _log(parse_status="failed", query_date="2026-07-10")
        db.add(new)
        db.commit()

        count = mark_historical_reaudit_superseded(db, new, expected_previous_id=old.id)
        assert count == 0
        db.refresh(old)
        assert old.superseded_by is None
    finally:
        db.close()


def test_fallback_does_not_supersede():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()
        new = _log(parse_status="fallback")
        db.add(new)
        db.commit()
        assert mark_historical_reaudit_superseded(db, new) == 0
        db.refresh(old)
        assert old.superseded_by is None
    finally:
        db.close()


def test_empty_source_key_does_not_supersede():
    db = _db()
    try:
        old = _log(source_record_key="legacy::x")
        db.add(old)
        db.commit()
        new = _log(source_record_key="")
        db.add(new)
        db.commit()
        assert mark_historical_reaudit_superseded(db, new) == 0
    finally:
        db.close()


def test_different_audit_type_does_not_supersede():
    db = _db()
    try:
        old = _log(audit_type_code="progress_vs_nursing")
        db.add(old)
        db.commit()
        new = _log(audit_type_code="surgery_chain", source_record_key="progress_vs_nursing::P001::1")
        db.add(new)
        db.commit()
        assert mark_historical_reaudit_superseded(db, new) == 0
        db.refresh(old)
        assert old.superseded_by is None
    finally:
        db.close()


def test_concurrent_changed_returns_minus_one():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()
        # 模拟旧当前已被其他结果替代
        old.superseded_by = 999
        db.commit()

        new = _log(query_date="2026-07-11")
        db.add(new)
        db.commit()
        assert mark_historical_reaudit_superseded(db, new, expected_previous_id=old.id) == -1
    finally:
        db.close()


def test_current_result_filter_hides_superseded():
    db = _db()
    try:
        current = _log(source_record_key="k-current")
        old = _log(source_record_key="k-old", superseded_by=1)
        db.add_all([current, old])
        db.commit()

        rows = apply_current_result_filter(db.query(PushLog)).all()
        assert len(rows) == 1
        assert rows[0].source_record_key == "k-current"

        all_rows = apply_current_result_filter(db.query(PushLog), include_superseded=True).all()
        assert len(all_rows) == 2
    finally:
        db.close()
