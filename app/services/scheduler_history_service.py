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
    audit_run_mode: str = "daily_increment",
    error_msg: str = "",
    error_code: str = "",
) -> str:
    """写入调度历史；应用库瞬时失败时 dispose 连接池并重试一次。

    P1-7: 新增 audit_run_mode 和 error_msg 字段。
    P011-8.1.2: 新增 error_code 字段，记录稳定错误码便于按层级聚合。
    error_msg 只保存受控摘要，不保存患者信息、连接串、密码或密钥。
    """
    from app.database import dispose_app_db_pool, is_transient_app_db_error

    safe_error = str(error_msg or "")[:500]
    for banned in ("password", "api_key", "secret", "token=", "dsn=", "jdbc:"):
        if banned in safe_error.lower():
            safe_error = f"[redacted:{banned}]"
            break

    # error_code 缺失但 error_msg 非空时，尝试从消息推断稳定错误码
    resolved_code = str(error_code or "").strip()
    if not resolved_code and safe_error:
        try:
            from app.oracle_client import classify_oracle_error
            resolved_code = classify_oracle_error(RuntimeError(safe_error))
        except Exception:
            resolved_code = ""

    def _write_once() -> None:
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
                audit_run_mode=str(audit_run_mode or "daily_increment").strip() or "daily_increment",
                error_code=resolved_code,
                error_msg=safe_error,
            )
            db.add(history)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    try:
        _write_once()
        return ""
    except Exception as exc:
        if is_transient_app_db_error(exc):
            dispose_app_db_pool(reason="scheduler_history_write_retry")
            try:
                _write_once()
                return ""
            except Exception as retry_exc:
                msg = f"history_persist_failed: {retry_exc}"
                logger.error("调度历史写入失败(重试后): %s", msg, exc_info=True)
                return msg
        msg = f"history_persist_failed: {exc}"
        logger.error("调度历史写入失败: %s", msg, exc_info=True)
        return msg
