"""审计结果写入服务 —— 保存/清除结构化审计结果。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import AuditConclusion, AuditDimensionResult
from app.services.audit_result_mapper import map_conclusion_row, map_dimension_row

logger = logging.getLogger(__name__)


def save_audit_results(db: Session, push_log_id: int, dify_result: Dict[str, Any], audit_type_code: str = ""):
    """将结构化审计结果存入数据库。"""
    parsed = dify_result.get("parsed_output", {})
    if not parsed:
        return

    parse_success = parsed.get("parse_success", False)
    fallback_inference = parsed.get("fallback_inference", False)
    should_save_summary = parse_success or fallback_inference or parsed.get("inconsistency")
    if not should_save_summary:
        return

    known_dim_keys = {
        "dimension_code", "dimension", "dimension_name", "status", "severity", "confidence",
        "medical_content", "nursing_content", "explanation", "issue_summary",
        "recommendation", "medical_evidence", "nursing_evidence", "alert_level",
        "closure_hours", "push_strategy", "outcome_bucket", "extra",
    }
    for dim in parsed.get("dimensions", []) if should_save_summary else []:
        mapped_row, extra_json = map_dimension_row(dim, audit_type_code)
        unknown_keys = set(dim.keys()) - known_dim_keys
        if unknown_keys:
            logger.warning(
                "Dimension item 包含未知字段 (将被忽略): %s | dimension=%s",
                unknown_keys,
                dim.get("dimension") or dim.get("dimension_name", ""),
            )
        dim_result = AuditDimensionResult(
            push_log_id=push_log_id,
            dimension_code=mapped_row.get("dimension_code", ""),
            dimension=mapped_row.get("dimension", ""),
            status=mapped_row.get("status", "❓"),
            severity=mapped_row.get("severity", ""),
            confidence=mapped_row.get("confidence", 0),
            medical_content=mapped_row.get("medical_content", ""),
            nursing_content=mapped_row.get("nursing_content", ""),
            explanation=mapped_row.get("explanation", ""),
            issue_summary=mapped_row.get("issue_summary", ""),
            recommendation=mapped_row.get("recommendation", ""),
            medical_evidence_json=mapped_row.get("medical_evidence_json", "[]"),
            nursing_evidence_json=mapped_row.get("nursing_evidence_json", "[]"),
            alert_level=mapped_row.get("alert_level", ""),
            closure_hours=mapped_row.get("closure_hours", 0),
            push_strategy=mapped_row.get("push_strategy", ""),
            outcome_bucket=mapped_row.get("outcome_bucket", ""),
        )
        try:
            dim_result.extra_json = extra_json
        except Exception:
            pass
        db.add(dim_result)

    overall_conclusion = parsed.get("overall_conclusion", "")
    reasoning_brief = parsed.get("reasoning_brief", "")
    if fallback_inference and not overall_conclusion:
        overall_conclusion = "Dify 输出解析失败，已按关键词回退判断处理。"
    if fallback_inference and not reasoning_brief:
        reasoning_brief = overall_conclusion

    conclusion_row, conclusion_extra_json = map_conclusion_row(parsed)
    conclusion = AuditConclusion(
        push_log_id=push_log_id,
        has_inconsistency=conclusion_row.get("has_inconsistency", 0),
        severity=conclusion_row.get("severity", ""),
        risk_score=conclusion_row.get("risk_score", 0),
        overall_conclusion=overall_conclusion,
        focus_items=conclusion_row.get("focus_items", "[]"),
        audit_date=conclusion_row.get("audit_date", ""),
        reasoning_brief=reasoning_brief,
        ai_version=conclusion_row.get("ai_version", "1.0"),
        alert_level=conclusion_row.get("alert_level", ""),
        closure_hours=conclusion_row.get("closure_hours", 0),
        push_strategy=conclusion_row.get("push_strategy", ""),
        outcome_bucket=conclusion_row.get("outcome_bucket", ""),
        overall_qc_summary=conclusion_row.get("overall_qc_summary", ""),
    )
    try:
        conclusion.extra_json = conclusion_extra_json
    except Exception:
        pass
    db.add(conclusion)


def clear_audit_results(db: Session, push_log_id: int):
    """清除旧的结构化审计结果（重推前调用）。"""
    db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id == push_log_id
    ).delete()
    db.query(AuditConclusion).filter(
        AuditConclusion.push_log_id == push_log_id
    ).delete()
