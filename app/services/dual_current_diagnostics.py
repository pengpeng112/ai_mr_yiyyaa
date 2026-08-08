"""P2-10: 只读双当前诊断与对账服务。

不输出患者标识或病历正文；仅输出聚合计数。
供 reconciliation 和生产验收使用。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import AuditDimensionResult, HistoricalRerunItem, PushLog
from app.services.current_result_filter import apply_current_result_filter
from app.services.qc_status_semantics import is_qc_usable

logger = logging.getLogger(__name__)


def diagnose_dual_currents(db: Session, limit: int = 100) -> Dict[str, Any]:
    """检测同业务身份多当前 qc_usable 结果。返回聚合计数，不返回患者标识。"""
    current_q = apply_current_result_filter(
        db.query(PushLog).filter(
            PushLog.status == "success",
            PushLog.pushed_flag == 1,
        )
    )
    total_current = current_q.count()

    empty_key_count = current_q.filter(
        or_(PushLog.source_record_key.is_(None), PushLog.source_record_key == "")
    ).count()
    non_empty_key_count = total_current - empty_key_count

    # 按业务身份分组检测多当前
    identity_groups = (
        apply_current_result_filter(
            db.query(
                PushLog.patient_id,
                PushLog.visit_number,
                PushLog.audit_type_code,
                PushLog.audit_run_mode,
                func.count(PushLog.id).label("cnt"),
            ).filter(
                PushLog.status == "success",
                PushLog.pushed_flag == 1,
            )
        )
        .group_by(
            PushLog.patient_id,
            PushLog.visit_number,
            PushLog.audit_type_code,
            PushLog.audit_run_mode,
        )
        .having(func.count(PushLog.id) > 1)
        .limit(limit)
        .all()
    )
    multi_current_groups = len(identity_groups)

    return {
        "total_current_qc_usable": total_current,
        "source_record_key_empty": empty_key_count,
        "source_record_key_non_empty": non_empty_key_count,
        "multi_current_identity_groups": multi_current_groups,
    }


def diagnose_historical_rerun_items(db: Session, batch_id: Optional[int] = None) -> Dict[str, Any]:
    """历史批次 item 状态聚合。"""
    q = db.query(
        HistoricalRerunItem.status,
        func.count(HistoricalRerunItem.id),
    )
    if batch_id:
        q = q.filter(HistoricalRerunItem.batch_id == batch_id)
    rows = q.group_by(HistoricalRerunItem.status).all()
    return {str(status): int(count) for status, count in rows}


def diagnose_contract_invalid(db: Session) -> Dict[str, Any]:
    """检测 contract_invalid 的 PushLog 聚合计数。"""
    # contract_invalid 通过 parse_status=success 但维度不合法来识别
    # 这里使用 audit_dimension_result 中的非法组合来近似
    invalid_combos = (
        db.query(func.count(AuditDimensionResult.id))
        .filter(
            AuditDimensionResult.status == "unknown",
            AuditDimensionResult.severity == "medium",
        )
        .scalar()
    )
    return {
        "unknown_medium_dimensions": int(invalid_combos or 0),
    }


def full_reconciliation_report(db: Session, batch_id: Optional[int] = None) -> Dict[str, Any]:
    """完整对账报告：聚合所有诊断维度。不输出患者标识。"""
    dual = diagnose_dual_currents(db)
    items = diagnose_historical_rerun_items(db, batch_id)
    contract = diagnose_contract_invalid(db)

    superseded_count = (
        db.query(func.count(PushLog.id))
        .filter(PushLog.superseded_by.isnot(None))
        .scalar()
    )

    return {
        "dual_current": dual,
        "historical_rerun_items": items,
        "contract": contract,
        "superseded_total": int(superseded_count or 0),
        "generated_at": __import__("datetime").datetime.now().isoformat(),
    }
