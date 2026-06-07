"""推送跳过策略 —— 判断是否应跳过推送。"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import PushLog, QCFeedback

logger = logging.getLogger(__name__)


def get_empty_lab_exam_skip_reason(payload: Dict[str, Any]) -> str:
    """检验/检查侧或病程/护理侧缺少可核查数据时跳过 Dify。"""
    if not isinstance(payload, dict):
        return ""
    if "abnormal_labs" not in payload and "abnormal_exams" not in payload:
        return ""

    lab_summary = payload.get("abnormal_labs") if isinstance(payload.get("abnormal_labs"), dict) else {}
    exam_summary = payload.get("abnormal_exams") if isinstance(payload.get("abnormal_exams"), dict) else {}
    lab_items = lab_summary.get("items") if isinstance(lab_summary.get("items"), list) else []
    exam_reports = exam_summary.get("reports") if isinstance(exam_summary.get("reports"), list) else []
    if not lab_items and not exam_reports:
        return "检验和检查报告均为空，跳过 Dify 推送"

    progress_context = payload.get("progress_context") if isinstance(payload.get("progress_context"), dict) else {}
    nursing_context = payload.get("nursing_context") if isinstance(payload.get("nursing_context"), dict) else {}
    progress_records = progress_context.get("records") if isinstance(progress_context.get("records"), list) else []
    nursing_records = nursing_context.get("records") if isinstance(nursing_context.get("records"), list) else []
    if not progress_records and not nursing_records:
        return "病程和护理记录均为空，跳过 Dify 推送"
    return ""


def apply_audit_type_scope(query, audit_type_code: str):
    """为查询添加审计类型过滤条件。"""
    code = str(audit_type_code or "progress_vs_nursing").strip() or "progress_vs_nursing"
    return query.filter(PushLog.audit_type_code == code)


def get_skip_reason(
    db: Session,
    patient_id: str,
    visit_number: str,
    audit_type_code: str = "progress_vs_nursing",
    source_record_key: str = "",
    audit_run_mode: str = "daily_increment",
) -> tuple[str, str]:
    """判断是否应跳过推送。

    跳过策略基于 source_record_key 精确匹配：
    - 同一条记录（同 key）未复核 → 跳过（unreviewed_pending）
    - 同一条记录（同 key）已复核 → 允许再次推送
    - 不同记录（不同 key）→ 正常推送（每日新增病历不受历史未复核影响）
    - 患者已整改且标记 suppress_ai_push → 跳过（rectified_suppressed）
    """
    # 1. 精确 source_record_key 匹配（未复核拦截，已复核继续检查整改抑制）
    if source_record_key:
        latest_by_key = (
            db.query(PushLog)
            .filter(PushLog.source_record_key == source_record_key)
            .filter(PushLog.status == "success")
            .filter(PushLog.pushed_flag == 1)
            .order_by(PushLog.push_time.desc())
            .first()
        )
        if latest_by_key:
            if latest_by_key.reviewed_flag == 0 and latest_by_key.manual_override == 0:
                return "unreviewed_pending", f"该记录已推送成功（ID={latest_by_key.id}）但尚未人工复核，已按规则跳过"

    # 2. 整改抑制检查（跨模式生效）
    query = (
        db.query(QCFeedback)
        .join(PushLog, QCFeedback.push_log_id == PushLog.id)
        .filter(QCFeedback.suppress_ai_push == True)
        .filter(QCFeedback.status == "rectified")
        .filter(PushLog.patient_id == patient_id)
    )
    query = apply_audit_type_scope(query, audit_type_code)
    if visit_number:
        query = query.filter(PushLog.visit_number == visit_number)
    if query.with_entities(QCFeedback.id).first() is not None:
        return "rectified_suppressed", "该患者已完成整改，已停止后续 AI 推送"

    return "", ""


def should_skip_patient(
    db: Session,
    patient_id: str,
    visit_number: str,
    audit_type_code: str = "progress_vs_nursing",
    source_record_key: str = "",
    audit_run_mode: str = "daily_increment",
) -> bool:
    """判断是否应跳过该患者。"""
    reason, _ = get_skip_reason(db, patient_id, visit_number, audit_type_code, source_record_key, audit_run_mode)
    return bool(reason)
