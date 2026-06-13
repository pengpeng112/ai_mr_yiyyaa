"""
调度历史服务 —— 从 scheduler.py 拆分，负责调度历史写入与错误记录。
"""
import logging
from datetime import datetime

from app.database import SessionLocal
from app.models import SchedulerHistory

logger = logging.getLogger(__name__)


def write_scheduler_history_safe(
    query_date: str,
    audit_type_code: str,
    total_records: int,
    success_count: int,
    failed_count: int,
    duration_seconds: int,
    status: str,
) -> str:
    db = SessionLocal()
    try:
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type_code,
            total_records=total_records,
            success_count=success_count,
            failed_count=failed_count,
            duration_seconds=duration_seconds,
            status=status,
        )
        db.add(history)
        db.commit()
        return ""
    except Exception as exc:
        db.rollback()
        msg = f"history_persist_failed: {exc}"
        logger.error("调度历史写入失败: %s", msg, exc_info=True)
        return msg
    finally:
        db.close()
