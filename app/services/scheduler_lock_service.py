"""
调度运行锁服务 —— 从 scheduler.py 拆分，负责获取/释放/查询调度锁。
"""
import logging
import os
import socket
import threading
import uuid
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models import SchedulerRunLock

logger = logging.getLogger(__name__)

DEFAULT_LOCK_NAME = "daily_push"
STALE_LOCK_TIMEOUT = timedelta(hours=4)


def _make_lock_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex[:8]}"


def get_scheduler_lock_info(lock_name: str = DEFAULT_LOCK_NAME) -> dict:
    db = SessionLocal()
    try:
        lock = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == lock_name).first()
        if not lock:
            return {
                "status": "idle",
                "owner_id": "",
                "acquired_at": None,
                "heartbeat_at": None,
                "heartbeat_age_seconds": None,
                "stale_threshold_seconds": int(STALE_LOCK_TIMEOUT.total_seconds()),
                "is_stale": False,
            }
        heartbeat = lock.heartbeat_at or lock.acquired_at
        heartbeat_age_seconds = None
        is_stale = False
        if heartbeat:
            heartbeat_age_seconds = max(0, int((datetime.now() - heartbeat).total_seconds()))
            is_stale = heartbeat_age_seconds > STALE_LOCK_TIMEOUT.total_seconds()
        return {
            "status": lock.status,
            "owner_id": lock.owner_id or "",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
            "heartbeat_at": lock.heartbeat_at.isoformat() if lock.heartbeat_at else None,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "stale_threshold_seconds": int(STALE_LOCK_TIMEOUT.total_seconds()),
            "is_stale": is_stale if lock.status == "running" else False,
        }
    finally:
        db.close()


def acquire_scheduler_run_lock(lock_name: str = DEFAULT_LOCK_NAME) -> tuple[bool, str, str]:
    owner_id = _make_lock_owner()
    db = SessionLocal()
    try:
        now = datetime.now()

        existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == lock_name).first()
        if existing and existing.status == "running":
            heartbeat = existing.heartbeat_at or existing.acquired_at
            if heartbeat and (now - heartbeat) > STALE_LOCK_TIMEOUT:
                # 采用旧 owner + 旧 heartbeat 做 CAS。仅凭一次 SELECT 判断 stale
                # 再 UPDATE 会允许两个恢复者同时接管同一把锁，导致任务双跑。
                logger.warning(
                    "调度锁 %s 已超时(heartbeat=%s, 超过%s)，强制接管 old_owner=%s",
                    lock_name, heartbeat, STALE_LOCK_TIMEOUT, existing.owner_id,
                )
                reclaimed = db.query(SchedulerRunLock).filter(
                    SchedulerRunLock.lock_name == lock_name,
                    SchedulerRunLock.status == "running",
                    SchedulerRunLock.owner_id == (existing.owner_id or ""),
                    SchedulerRunLock.heartbeat_at == existing.heartbeat_at,
                ).update(
                    {
                        "owner_id": owner_id,
                        "acquired_at": now,
                        "heartbeat_at": now,
                        "released_at": None,
                    },
                    synchronize_session=False,
                )
                if reclaimed:
                    db.commit()
                    return True, owner_id, "acquired_stale_override"
                # Another process won the CAS. Re-read only for a truthful reason;
                # never start a task after losing the ownership race.
                db.rollback()
                current = db.query(SchedulerRunLock).filter(
                    SchedulerRunLock.lock_name == lock_name,
                ).first()
                return False, (current.owner_id if current else "") or "", (
                    f"scheduler lock is running by {(current.owner_id if current else '') or 'unknown'}"
                )
            db.rollback()
            return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"

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


def heartbeat_scheduler_run_lock(owner_id: str, lock_name: str = DEFAULT_LOCK_NAME) -> bool:
    """刷新当前持有者的运行锁心跳；锁已被接管或释放时不覆盖状态。"""
    db = SessionLocal()
    try:
        updated = db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == lock_name,
            SchedulerRunLock.owner_id == owner_id,
            SchedulerRunLock.status == "running",
        ).update(
            {"heartbeat_at": datetime.now()},
            synchronize_session=False,
        )
        db.commit()
        return bool(updated)
    except Exception:
        db.rollback()
        logger.error("调度运行锁心跳刷新失败 owner_id=%s", owner_id, exc_info=True)
        return False
    finally:
        db.close()
