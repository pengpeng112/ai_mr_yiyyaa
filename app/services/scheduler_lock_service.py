"""
调度运行锁服务 —— 从 scheduler.py 拆分，负责获取/释放/查询调度锁。
"""
import logging
import os
import socket
import threading
import uuid
from datetime import datetime

from app.database import SessionLocal
from app.models import SchedulerRunLock

logger = logging.getLogger(__name__)

# 默认锁名称，与 scheduler.py 中 _RUN_LOCK_NAME 保持一致
DEFAULT_LOCK_NAME = "daily_push"


def _make_lock_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex[:8]}"


def get_scheduler_lock_info(lock_name: str = DEFAULT_LOCK_NAME) -> dict:
    db = SessionLocal()
    try:
        lock = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == lock_name).first()
        if not lock:
            return {"status": "idle", "owner_id": "", "acquired_at": None, "heartbeat_at": None}
        return {
            "status": lock.status,
            "owner_id": lock.owner_id or "",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
            "heartbeat_at": lock.heartbeat_at.isoformat() if lock.heartbeat_at else None,
        }
    finally:
        db.close()


def acquire_scheduler_run_lock(lock_name: str = DEFAULT_LOCK_NAME) -> tuple[bool, str, str]:
    owner_id = _make_lock_owner()
    db = SessionLocal()
    try:
        now = datetime.now()
        updated = db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == lock_name,
            SchedulerRunLock.status != "running",
        ).update(
            {
                "owner_id": owner_id,
                "status": "running",
                "acquired_at": now,
                "heartbeat_at": now,
                "released_at": None,
            },
            synchronize_session=False,
        )
        if updated:
            db.commit()
            return True, owner_id, "acquired"

        existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == lock_name).first()
        if existing:
            db.rollback()
            return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"

        db.add(SchedulerRunLock(
            lock_name=lock_name,
            owner_id=owner_id,
            status="running",
            acquired_at=now,
            heartbeat_at=now,
        ))
        try:
            db.commit()
            return True, owner_id, "acquired"
        except Exception:
            db.rollback()
            existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == lock_name).first()
            if existing and existing.status == "running":
                return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"
            raise
    finally:
        db.close()


def release_scheduler_run_lock(owner_id: str, lock_name: str = DEFAULT_LOCK_NAME) -> None:
    db = SessionLocal()
    try:
        db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == lock_name,
            SchedulerRunLock.owner_id == owner_id,
            SchedulerRunLock.status == "running",
        ).update(
            {
                "status": "idle",
                "released_at": datetime.now(),
                "heartbeat_at": datetime.now(),
            },
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error("调度运行锁释放失败 owner_id=%s", owner_id, exc_info=True)
    finally:
        db.close()
