"""调度运行锁的活动租约、陈旧接管和双模式隔离测试。"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, SchedulerRunLock


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def test_stale_running_lock_is_atomically_reclaimed(monkeypatch):
    from app.services import scheduler_lock_service as service

    Session = _session_factory()
    db = Session()
    old_heartbeat = datetime.now() - service.STALE_LOCK_TIMEOUT - timedelta(minutes=1)
    db.add(SchedulerRunLock(
        lock_name="discharge_push",
        owner_id="dead-container:123",
        status="running",
        acquired_at=old_heartbeat,
        heartbeat_at=old_heartbeat,
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(service, "SessionLocal", Session)

    acquired, owner, reason = service.acquire_scheduler_run_lock("discharge_push")

    assert acquired is True
    assert owner
    assert reason == "acquired_stale_override"
    row = Session().query(SchedulerRunLock).filter_by(lock_name="discharge_push").one()
    assert row.status == "running"
    assert row.owner_id == owner
    assert row.owner_id != "dead-container:123"
    assert row.released_at is None


def test_second_recovery_cannot_reclaim_new_owner(monkeypatch):
    """首次接管刷新 heartbeat 后，第二个恢复者只能看到 busy。"""
    from app.services import scheduler_lock_service as service

    Session = _session_factory()
    db = Session()
    old_heartbeat = datetime.now() - service.STALE_LOCK_TIMEOUT - timedelta(minutes=1)
    db.add(SchedulerRunLock(
        lock_name="discharge_push",
        owner_id="dead-container:123",
        status="running",
        acquired_at=old_heartbeat,
        heartbeat_at=old_heartbeat,
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(service, "SessionLocal", Session)

    first_acquired, first_owner, _ = service.acquire_scheduler_run_lock("discharge_push")
    second_acquired, second_owner, second_reason = service.acquire_scheduler_run_lock("discharge_push")

    assert first_acquired is True
    assert second_acquired is False
    assert second_owner == first_owner
    assert first_owner in second_reason


def test_fresh_running_lock_is_not_reclaimed(monkeypatch):
    from app.services import scheduler_lock_service as service

    Session = _session_factory()
    db = Session()
    db.add(SchedulerRunLock(
        lock_name="discharge_push",
        owner_id="active-worker",
        status="running",
        acquired_at=datetime.now(),
        heartbeat_at=datetime.now(),
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(service, "SessionLocal", Session)

    acquired, owner, reason = service.acquire_scheduler_run_lock("discharge_push")

    assert acquired is False
    assert owner == "active-worker"
    assert "active-worker" in reason
    assert Session().query(SchedulerRunLock).filter_by(lock_name="discharge_push").one().owner_id == "active-worker"


def test_lock_diagnostics_expose_stale_state(monkeypatch):
    from app.services import scheduler_lock_service as service

    Session = _session_factory()
    db = Session()
    old_heartbeat = datetime.now() - service.STALE_LOCK_TIMEOUT - timedelta(seconds=1)
    db.add(SchedulerRunLock(
        lock_name="discharge_push",
        owner_id="dead-worker",
        status="running",
        acquired_at=old_heartbeat,
        heartbeat_at=old_heartbeat,
    ))
    db.commit()
    db.close()
    monkeypatch.setattr(service, "SessionLocal", Session)

    info = service.get_scheduler_lock_info("discharge_push")

    assert info["status"] == "running"
    assert info["is_stale"] is True
    assert info["heartbeat_age_seconds"] > info["stale_threshold_seconds"]


def test_daily_and_discharge_locks_are_independent(monkeypatch):
    from app.services import scheduler_lock_service as service

    Session = _session_factory()
    monkeypatch.setattr(service, "SessionLocal", Session)

    daily_acquired, daily_owner, _ = service.acquire_scheduler_run_lock("daily_push")
    discharge_acquired, discharge_owner, _ = service.acquire_scheduler_run_lock("discharge_push")

    assert daily_acquired is True
    assert discharge_acquired is True
    assert daily_owner != discharge_owner
    rows = Session().query(SchedulerRunLock).all()
    assert {row.lock_name for row in rows} == {"daily_push", "discharge_push"}


def test_scheduler_status_exposes_both_named_locks(monkeypatch):
    from app.routers import scheduler as router

    class _Scheduler:
        running = True

        @staticmethod
        def get_job(_job_id):
            return None

    seen = []
    monkeypatch.setattr(router, "get_scheduler", lambda: _Scheduler())
    monkeypatch.setattr(router, "load_config", lambda: {
        "scheduler_daily": {"enabled": True},
        "scheduler_discharge": {"enabled": True},
    })
    monkeypatch.setattr(router, "get_last_run_info", lambda: {})
    monkeypatch.setattr(router, "is_scheduler_env_enabled", lambda: True)
    monkeypatch.setattr(
        router,
        "get_scheduler_lock_info",
        lambda name: seen.append(name) or {
            "status": "running" if name == "discharge_push" else "idle",
            "owner_id": "old-owner" if name == "discharge_push" else "",
            "heartbeat_age_seconds": 20000 if name == "discharge_push" else None,
            "stale_threshold_seconds": 14400,
            "is_stale": name == "discharge_push",
        },
    )

    payload = router.scheduler_status(_user=None)

    assert seen == ["daily_push", "discharge_push"]
    assert payload["run_lock"] == payload["run_locks"]["daily_push"]
    assert payload["run_locks"]["discharge_push"]["is_stale"] is True
    assert any("discharge_push" in item and "陈旧" in item for item in payload["diagnostics"])
