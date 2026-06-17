"""出院终末覆盖在院质控日志服务。"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import or_

from app.models import PushLog

logger = logging.getLogger(__name__)


def mark_daily_logs_superseded(db, discharge_push_log: PushLog) -> int:
    if discharge_push_log.audit_run_mode != "discharge_final":
        return 0
    if discharge_push_log.status != "success":
        return 0

    visit_number = str(discharge_push_log.visit_number or "").strip()
    if not visit_number:
        logger.warning(
            "mark_daily_logs_superseded skip: visit_number 为空 discharge_id=%s patient_id=%s",
            discharge_push_log.id,
            discharge_push_log.patient_id,
        )
        return 0

    query = db.query(PushLog).filter(
        PushLog.patient_id == discharge_push_log.patient_id,
        PushLog.visit_number == discharge_push_log.visit_number,
        PushLog.audit_run_mode == "daily_increment",
        PushLog.status == "success",
        PushLog.superseded_by.is_(None),
    ).filter(
        or_(
            PushLog.source_record_key.is_(None),
            PushLog.source_record_key == "",
            PushLog.source_record_key.not_like("mode::discharge_final::%"),
        )
    )

    if discharge_push_log.audit_type_code == "progress_vs_nursing":
        query = query.filter(
            or_(
                PushLog.audit_type_code == "progress_vs_nursing",
                PushLog.audit_type_code == "",
                PushLog.audit_type_code.is_(None),
            )
        )
    else:
        query = query.filter(
            PushLog.audit_type_code == discharge_push_log.audit_type_code
        )

    superseded_at = datetime.now()

    try:
        count = query.update(
            {
                "superseded_by": discharge_push_log.id,
                "superseded_at": superseded_at,
            },
            synchronize_session=False,
        )
    except Exception:
        logger.exception(
            "mark_daily_logs_superseded update failed discharge_id=%s",
            discharge_push_log.id,
        )
        raise

    result = int(count or 0)
    if result:
        logger.info(
            "mark_daily_logs_superseded: discharge_id=%s audit_type=%s patient_id=%s visit=%s superseded_count=%s",
            discharge_push_log.id,
            discharge_push_log.audit_type_code,
            discharge_push_log.patient_id,
            discharge_push_log.visit_number,
            result,
        )
    return result


def ensure_supersede(db, discharge_push_log: PushLog) -> int:
    """调用 mark_daily_logs_superseded，失败时记录日志并抛出异常。

    确保覆盖失败时外层事务回滚，避免出院日志成功但 daily 未标记覆盖。
    """
    try:
        return mark_daily_logs_superseded(db, discharge_push_log)
    except Exception:
        logger.error(
            "ensure_supersede failed: discharge_id=%s",
            discharge_push_log.id, exc_info=True,
        )
        raise
