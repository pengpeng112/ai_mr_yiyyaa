"""PushLog 替代链服务。

- mark_daily_logs_superseded：出院终末替代日常增量（既有专用规则，勿改语义）
- mark_historical_reaudit_superseded：历史手工重跑成功后替代同身份当前结果（ACTIVE/007）
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import or_

from app.models import PushLog
from app.services.qc_status_semantics import is_qc_usable

logger = logging.getLogger(__name__)


def mark_daily_logs_superseded(db, discharge_push_log: PushLog) -> int:
    if discharge_push_log.audit_run_mode != "discharge_final":
        return 0
    if discharge_push_log.status != "success":
        return 0
    # 003 §3.1：parse_failed/fallback 的终末结果不得 supersede。
    # 历史空 parse_status 视为 legacy 可用（上线前字段未写）；仅显式失败/回退拦截。
    parse_status = str(getattr(discharge_push_log, "parse_status", "") or "").strip().lower()
    if parse_status in {"failed", "fallback"}:
        logger.info(
            "mark_daily_logs_superseded skip: discharge 不可用 parse_status=%s discharge_id=%s",
            parse_status,
            getattr(discharge_push_log, "id", None),
        )
        return 0

    # P0-2: contract_invalid 结果不得 supersede
    contract_valid = getattr(discharge_push_log, "contract_valid", None)
    if contract_valid is False:
        logger.info(
            "mark_daily_logs_superseded skip: contract_invalid discharge_id=%s",
            getattr(discharge_push_log, "id", None),
        )
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


# 临时占用 supersede 槽位（非真实 PushLog id）；add/flush 新 success 后会回填为新 id
_TEMP_SUPERSEDE_MARKER = -1


def attach_success_push_log_as_current(db, new_log: PushLog) -> int:
    """将 success PushLog 落为当前结果，并释放同身份旧 success 当前槽位。

    背景：015/C1 唯一索引约束「同 source_record_key+type+mode 仅一条 success 当前」。
    若先 INSERT 再 supersede，会触发 ORA-00001。本函数顺序为：
    1) 旧 success 当前临时 superseded_by=-1（腾出唯一槽）
    2) add + flush 新日志拿到 id
    3) 旧行 superseded_by 回填为新 id

    返回被替代的旧当前条数。非 success 或无 key 时仅 add/flush，返回 0。
    """
    if new_log is None:
        return 0

    key = str(getattr(new_log, "source_record_key", "") or "").strip()
    status = str(getattr(new_log, "status", "") or "").strip()
    priors: list[PushLog] = []
    if status == "success" and key:
        audit_type_code = str(getattr(new_log, "audit_type_code", "") or "").strip()
        audit_run_mode = str(getattr(new_log, "audit_run_mode", "") or "daily_increment").strip()
        priors = (
            db.query(PushLog)
            .filter(
                PushLog.source_record_key == key,
                PushLog.audit_type_code == audit_type_code,
                PushLog.audit_run_mode == audit_run_mode,
                PushLog.status == "success",
                PushLog.superseded_by.is_(None),
            )
            .all()
        )
        now = datetime.now()
        for old in priors:
            old.superseded_by = _TEMP_SUPERSEDE_MARKER
            old.superseded_at = now
        if priors:
            db.flush()

    db.add(new_log)
    db.flush()

    if not priors:
        return 0

    count = 0
    now = datetime.now()
    for old in priors:
        # 若 new_log 尚未有 id（极端情况），保留 -1 并打日志
        new_id = getattr(new_log, "id", None)
        if not new_id:
            logger.error("attach_success_push_log_as_current: new_log 无 id，旧行仍为临时 marker")
            break
        old.superseded_by = int(new_id)
        old.superseded_at = now
        count += 1
    if count:
        logger.info(
            "attach_success_push_log_as_current: new_id=%s key=%s superseded_count=%s",
            getattr(new_log, "id", None),
            key,
            count,
        )
    return count


def mark_historical_reaudit_superseded(
    db,
    new_push_log: PushLog,
    *,
    expected_previous_id: Optional[int] = None,
    require_same_source_key: bool = True,
) -> int:
    """历史重新核查成功后，将同业务身份的旧当前结果标记为被替代。

    门槛（全部满足才允许替代）：
    - status=success + pushed_flag=1 + parse_status=success（qc_usable）
    - 同 audit_type_code / patient_id / visit_number / audit_run_mode
    - 同 source_record_key（空 key 不得自动替代）
    - 若提供 expected_previous_id，旧当前结果 ID 必须仍匹配，否则 concurrent_changed

    注意：不得复用 mark_daily_logs_superseded（后者硬编码 discharge_final 前置条件）。
    """
    if not new_push_log or not getattr(new_push_log, "id", None):
        return 0

    if not is_qc_usable(new_push_log.status, getattr(new_push_log, "parse_status", ""), getattr(new_push_log, "contract_valid", None)):
        logger.info(
            "mark_historical_reaudit_superseded skip: not qc_usable new_id=%s status=%s parse=%s",
            new_push_log.id,
            getattr(new_push_log, "status", None),
            getattr(new_push_log, "parse_status", None),
        )
        return 0

    if int(getattr(new_push_log, "pushed_flag", 0) or 0) != 1:
        return 0

    source_key = str(getattr(new_push_log, "source_record_key", "") or "").strip()
    if require_same_source_key and not source_key:
        logger.info(
            "mark_historical_reaudit_superseded skip: empty source_record_key new_id=%s",
            new_push_log.id,
        )
        return 0

    patient_id = str(new_push_log.patient_id or "").strip()
    visit_number = str(new_push_log.visit_number or "").strip()
    audit_type_code = str(new_push_log.audit_type_code or "").strip()
    audit_run_mode = str(getattr(new_push_log, "audit_run_mode", "") or "daily_increment").strip()

    if not patient_id or not visit_number:
        logger.warning(
            "mark_historical_reaudit_superseded skip: missing patient/visit new_id=%s",
            new_push_log.id,
        )
        return 0

    query = db.query(PushLog).filter(
        PushLog.id != new_push_log.id,
        PushLog.patient_id == patient_id,
        PushLog.visit_number == visit_number,
        PushLog.audit_type_code == audit_type_code,
        PushLog.audit_run_mode == audit_run_mode,
        PushLog.status == "success",
        PushLog.pushed_flag == 1,
        PushLog.superseded_by.is_(None),
    )
    if require_same_source_key:
        query = query.filter(PushLog.source_record_key == source_key)

    if expected_previous_id is not None:
        current = query.filter(PushLog.id == int(expected_previous_id)).first()
        if current is None:
            logger.info(
                "mark_historical_reaudit_superseded concurrent_changed: expected_prev=%s new_id=%s",
                expected_previous_id,
                new_push_log.id,
            )
            return -1  # 约定：-1 表示 concurrent_changed
        targets = [current]
    else:
        targets = query.all()

    if not targets:
        return 0

    superseded_at = datetime.now()
    count = 0
    for old in targets:
        old.superseded_by = new_push_log.id
        old.superseded_at = superseded_at
        count += 1

    logger.info(
        "mark_historical_reaudit_superseded: new_id=%s audit_type=%s patient_id=%s visit=%s superseded_count=%s",
        new_push_log.id,
        audit_type_code,
        patient_id,
        visit_number,
        count,
    )
    return count
