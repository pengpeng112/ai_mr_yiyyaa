"""手工推送覆盖原有质控结果（replace_current）测试。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog
from app.services.push_log_supersede import mark_historical_reaudit_superseded
from app.services.push_skip_policy import get_skip_reason
from app.services.push_types import PushConfig


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
        "source_record_key": "k1",
        "reviewed_flag": 0,
        "manual_override": 0,
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def test_replace_current_bypasses_unreviewed_pending():
    db = _db()
    try:
        db.add(_log())
        db.commit()
        reason, _ = get_skip_reason(db, "P001", "1", "progress_vs_nursing", "k1")
        assert reason == "unreviewed_pending"

        reason2, _ = get_skip_reason(
            db, "P001", "1", "progress_vs_nursing", "k1", replace_current=True
        )
        assert reason2 == ""
    finally:
        db.close()


def test_push_config_replace_flag():
    cfg = PushConfig(existing_result_policy="replace_current", alert_policy="suppress")
    assert cfg.replace_current is True
    cfg2 = PushConfig()
    assert cfg2.replace_current is False


def test_replace_success_supersedes_old_current():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()
        new = _log(query_date="2026-07-10", manual_override=1)
        db.add(new)
        db.commit()
        n = mark_historical_reaudit_superseded(db, new)
        db.commit()
        assert n == 1
        db.refresh(old)
        assert old.superseded_by == new.id
    finally:
        db.close()


def test_replace_failed_parse_does_not_supersede():
    db = _db()
    try:
        old = _log()
        db.add(old)
        db.commit()
        new = _log(parse_status="failed")
        db.add(new)
        db.commit()
        assert mark_historical_reaudit_superseded(db, new) == 0
        db.refresh(old)
        assert old.superseded_by is None
    finally:
        db.close()
