"""调度锁获取失败必须写入 SchedulerHistory。"""

from __future__ import annotations

from datetime import datetime
from unittest import mock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, SchedulerHistory


def test_daily_push_job_v2_writes_history_when_lock_not_acquired(monkeypatch):
    from app import scheduler as sched

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)

    written = {}

    def fake_write(**kwargs):
        written.update(kwargs)
        db = Session()
        try:
            db.add(
                SchedulerHistory(
                    run_time=datetime.now(),
                    trigger_type="auto",
                    query_date=kwargs["query_date"],
                    audit_type_code=kwargs["audit_type_code"],
                    total_records=kwargs["total_records"],
                    success_count=kwargs["success_count"],
                    failed_count=kwargs["failed_count"],
                    duration_seconds=kwargs["duration_seconds"],
                    status=kwargs["status"],
                    audit_run_mode=kwargs.get("audit_run_mode", "daily_increment"),
                    error_code=kwargs.get("error_code", ""),
                    error_msg=kwargs.get("error_msg", ""),
                )
            )
            db.commit()
        finally:
            db.close()
        return ""

    monkeypatch.setattr(
        sched,
        "_acquire_scheduler_run_lock_impl",
        lambda lock_name: (False, "other-owner", f"scheduler lock is running by other-owner"),
    )
    monkeypatch.setattr(
        "app.services.scheduler_history_service.write_scheduler_history_safe",
        fake_write,
    )

    # 避免真实解锁路径
    with mock.patch.object(sched, "_daily_push_job_v2_unlocked") as unlocked:
        sched._daily_push_job_v2(
            query_date_override="2026-07-15",
            audit_run_mode_override="discharge_final",
            lock_name="discharge_push",
        )
        unlocked.assert_not_called()

    assert written["query_date"] == "2026-07-15"
    assert written["audit_type_code"] == "__scheduler_lock__"
    assert written["status"] == "failed"
    assert written["total_records"] == 0
    assert written["audit_run_mode"] == "discharge_final"
    assert written["error_code"] == "scheduler_lock_not_acquired"

    rows = Session().query(SchedulerHistory).all()
    assert len(rows) == 1
    assert rows[0].audit_type_code == "__scheduler_lock__"
    assert rows[0].status == "failed"
