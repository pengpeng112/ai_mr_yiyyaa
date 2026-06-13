"""
推送日志路由 —— /api/logs
"""
import csv
import io
import json
import logging
from datetime import datetime, timedelta
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.schemas import PushLogItem, PushLogDetail, PaginatedLogs, MessageResponse
from app.database import get_db
from app.models import PushLog, AuditDimensionResult, AuditConclusion, QCFeedback, QCFeedbackHistory, User, Role
from app.config import load_config
from app.dify_pusher import push_to_dify, parse_dify_structured_output
from app.services.config_parser import ConfigParser
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.export_audit_service import record_export_audit
from app.auth import get_current_user
from app.permissions import require_permission

router = APIRouter()
logger = logging.getLogger(__name__)

_SKIP_REASON_LABELS = {
    "unreviewed_pending": "已推送未复核",
    "rectified_suppressed": "已整改抑制推送",
    "empty_lab_exam": "检验检查数据为空",
    "empty_progress_nursing": "病程护理记录为空",
    "empty_both_sides": "检验检查和病程护理均为空",
    "empty_primary": "主数据源为空",
    "empty_frontpage": "首页/手术数据为空",
    "cancelled": "用户取消",
    "already_succeeded": "已有成功推送记录",
}


class PushLogBulkDeleteRequest(BaseModel):
    log_ids: list[int] = Field(..., min_length=1, max_length=1000, description="待删除的推送日志 ID")


class PushMarkerUpdateRequest(BaseModel):
    reviewed_flag: int = Field(..., ge=0, le=1, description="是否已人工复核（1/0）")
    manual_override: int = Field(0, ge=0, le=1, description="是否手动覆盖跳过规则（1/0）")
    skip_reason: str = Field("", max_length=200, description="跳过原因备注")


def _require_admin(current_user: User, db: Session):
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


from app.utils.json_utils import safe_json_loads as _safe_json_loads
from app.utils.text_utils import safe_text as _safe_text


def _extract_dept_from_request(log: PushLog, key: str) -> str:
    """从 PushLog.request_json 中提取 admission_dept_name / discharge_dept_name。"""
    from app.services.patient_snapshot import extract_patient_snapshot
    try:
        snapshot = extract_patient_snapshot(log)
        return snapshot.get(key, "")
    except Exception:
        return ""


def _skip_reason_label(value: str) -> str:
    text = _safe_text(value).strip()
    return _SKIP_REASON_LABELS.get(text, text)


def _failure_reason(log: PushLog) -> str:
    status = _safe_text(getattr(log, "status", "")).lower()
    if status == "skipped":
        label = _skip_reason_label(getattr(log, "skip_reason", ""))
        detail = _safe_text(getattr(log, "error_msg", ""))
        if label and detail and detail != label:
            return f"{label}：{detail}"
        return label or detail
    if status in {"failed", "error"}:
        return _safe_text(getattr(log, "error_msg", "")) or _safe_text(getattr(log, "parse_error", ""))
    return ""


def _build_stored_audit_snapshot(log_id: int, db: Session) -> dict:
    dimensions = (
        db.query(AuditDimensionResult)
        .filter(AuditDimensionResult.push_log_id == log_id)
        .order_by(AuditDimensionResult.id)
        .all()
    )
    conclusion = (
        db.query(AuditConclusion)
        .filter(AuditConclusion.push_log_id == log_id)
        .first()
    )

    dimension_rows = []
    for item in dimensions:
        issue_text = _safe_text(getattr(item, "issue_summary", "") or getattr(item, "explanation", ""))
        dimension_rows.append(
            {
                "dimension_code": _safe_text(getattr(item, "dimension_code", "")),
                "dimension": _safe_text(getattr(item, "dimension", "")),
                "status": _safe_text(getattr(item, "status", "")),
                "severity": _safe_text(getattr(item, "severity", "")),
                "confidence": float(getattr(item, "confidence", 0) or 0),
                "alert_level": _safe_text(getattr(item, "alert_level", "")),
                "closure_hours": int(getattr(item, "closure_hours", 0) or 0),
                "push_strategy": _safe_text(getattr(item, "push_strategy", "")),
                "outcome_bucket": _safe_text(getattr(item, "outcome_bucket", "")),
                "issue_summary": issue_text,
                "explanation": _safe_text(getattr(item, "explanation", "")),
                "recommendation": _safe_text(getattr(item, "recommendation", "")),
                "medical_content": _safe_text(getattr(item, "medical_content", "")),
                "nursing_content": _safe_text(getattr(item, "nursing_content", "")),
                "medical_evidence": _safe_json_loads(getattr(item, "medical_evidence_json", "[]"), []),
                "nursing_evidence": _safe_json_loads(getattr(item, "nursing_evidence_json", "[]"), []),
                "extra": _safe_json_loads(getattr(item, "extra_json", "{}"), {}),
            }
        )

    focus_items = []
    if conclusion:
        parsed_focus = _safe_json_loads(getattr(conclusion, "focus_items", "[]"), [])
        if isinstance(parsed_focus, list):
            focus_items = [str(item) for item in parsed_focus]

    conclusion_row = {
        "overall_conclusion": _safe_text(getattr(conclusion, "overall_conclusion", "")) if conclusion else "",
        "severity": _safe_text(getattr(conclusion, "severity", "")) if conclusion else "",
        "risk_score": int(getattr(conclusion, "risk_score", 0) or 0) if conclusion else 0,
        "has_inconsistency": int(getattr(conclusion, "has_inconsistency", 0) or 0) if conclusion else 0,
        "alert_level": _safe_text(getattr(conclusion, "alert_level", "")) if conclusion else "",
        "closure_hours": int(getattr(conclusion, "closure_hours", 0) or 0) if conclusion else 0,
        "push_strategy": _safe_text(getattr(conclusion, "push_strategy", "")) if conclusion else "",
        "outcome_bucket": _safe_text(getattr(conclusion, "outcome_bucket", "")) if conclusion else "",
        "focus_items": focus_items,
        "overall_qc_summary": _safe_text(getattr(conclusion, "overall_qc_summary", "")) if conclusion else "",
        "extra": _safe_json_loads(getattr(conclusion, "extra_json", "{}"), {}) if conclusion else {},
    }
    return {
        "dimensions": dimension_rows,
        "conclusion": conclusion_row,
    }


def _parse_dify_result_payload(response_json: str, ai_result: str = "") -> dict:
    """提取 Dify 原始结构化结果，仅用于调试展示。"""
    parsed = _safe_json_loads(response_json, {})
    if not parsed:
        parsed = _safe_json_loads(ai_result, {})
    if isinstance(parsed, str):
        parsed = _safe_json_loads(parsed, {})
    if not isinstance(parsed, dict):
        return {}

    result = parsed.get("result", parsed)
    if isinstance(result, str):
        result = _safe_json_loads(result, {})
    if isinstance(result, dict):
        return result
    return {}


def _build_audit_result_payload(stored_audit: dict) -> dict:
    """面向页面展示的标准化审计结果，避免重复 raw/stored 多套结构。"""
    stored = stored_audit if isinstance(stored_audit, dict) else {}
    conclusion = stored.get("conclusion") if isinstance(stored.get("conclusion"), dict) else {}
    dimensions = stored.get("dimensions") if isinstance(stored.get("dimensions"), list) else []
    return {
        "conclusion": conclusion,
        "dimensions": dimensions,
    }


def _build_raw_debug_payload(log: PushLog, dify_result: dict, stored_audit: dict) -> dict:
    """调试信息只保留原始 Dify 输出和解析状态，不重复本地标准化结果。"""
    conclusion = stored_audit.get("conclusion", {}) if isinstance(stored_audit, dict) else {}
    parse_warning = ""
    if isinstance(conclusion, dict):
        extra = conclusion.get("extra", {}) if isinstance(conclusion.get("extra"), dict) else {}
        parse_warning = _safe_text(extra.get("parse_warning", ""))
    return {
        "dify_result": dify_result if isinstance(dify_result, dict) else {},
        "parse_status": _safe_text(getattr(log, "parse_status", "")),
        "parse_error": _safe_text(getattr(log, "parse_error", "")),
        "parse_warning": parse_warning,
        "workflow_run_id": _safe_text(getattr(log, "workflow_run_id", "")),
        "task_id": _safe_text(getattr(log, "task_id", "")),
    }


def _parse_day(value: str, field_name: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}, expected yyyy-mm-dd")


def _to_push_log_item(log: PushLog, registry: AuditTypeRegistry | None = None) -> PushLogItem:
    registry = registry or AuditTypeRegistry()
    audit_type = registry.get_or_default(getattr(log, "audit_type_code", "") or "")
    return PushLogItem.model_validate({
        "id": log.id,
        "push_time": log.push_time,
        "trigger_type": _safe_text(log.trigger_type),
        "query_date": _safe_text(log.query_date),
        "patient_id": _safe_text(log.patient_id),
        "patient_name": _safe_text(log.patient_name),
        "dept": _safe_text(log.dept),
        "admission_dept_name": _safe_text(_extract_dept_from_request(log, "admission_dept_name")),
        "discharge_dept_name": _safe_text(_extract_dept_from_request(log, "discharge_dept_name")),
        "audit_type_code": _safe_text(getattr(log, "audit_type_code", "")) or audit_type.code,
        "audit_type_name": audit_type.name,
        "status": _safe_text(log.status),
        "inconsistency": int(log.inconsistency or 0),
        "severity": _safe_text(log.severity),
        "risk_score": int(log.risk_score or 0),
        "elapsed_ms": int(log.elapsed_ms or 0),
        "retry_count": int(log.retry_count or 0),
        "pushed_flag": int(getattr(log, "pushed_flag", 0) or 0),
        "reviewed_flag": int(getattr(log, "reviewed_flag", 0) or 0),
        "reviewed_at": getattr(log, "reviewed_at", None),
        "reviewed_by": _safe_text(getattr(log, "reviewed_by", "")),
        "manual_override": int(getattr(log, "manual_override", 0) or 0),
        "skip_reason": _safe_text(getattr(log, "skip_reason", "")),
        "skip_reason_label": _skip_reason_label(getattr(log, "skip_reason", "")),
        "error_msg": _safe_text(log.error_msg),
        "failure_reason": _failure_reason(log),
        "alert_level": _safe_text(log.alert_level),
    })


def _delete_push_logs(db: Session, log_ids: list[int]) -> int:
    ids = sorted({int(item) for item in log_ids if int(item) > 0})
    if not ids:
        return 0

    feedback_ids = [
        row[0]
        for row in db.query(QCFeedback.id).filter(QCFeedback.push_log_id.in_(ids)).all()
    ]
    if feedback_ids:
        db.query(QCFeedbackHistory).filter(QCFeedbackHistory.feedback_id.in_(feedback_ids)).delete(synchronize_session=False)
        db.query(QCFeedback).filter(QCFeedback.id.in_(feedback_ids)).delete(synchronize_session=False)
    db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id.in_(ids)).delete(synchronize_session=False)
    db.query(AuditConclusion).filter(AuditConclusion.push_log_id.in_(ids)).delete(synchronize_session=False)
    deleted = db.query(PushLog).filter(PushLog.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return int(deleted or 0)


def _to_push_log_detail(log: PushLog, registry: AuditTypeRegistry | None = None) -> PushLogDetail:
    registry = registry or AuditTypeRegistry()
    item = _to_push_log_item(log, registry=registry).model_dump()
    audit_type = registry.get_or_default(getattr(log, "audit_type_code", "") or "")
    item.update({
        "workflow_run_id": _safe_text(log.workflow_run_id),
        "task_id": _safe_text(log.task_id),
        "ai_result": _safe_text(log.ai_result),
        "mr_text": _safe_text(log.mr_text),
        "request_json": _safe_text(log.request_json),
        "response_json": _safe_text(log.response_json),
        "parse_status": _safe_text(log.parse_status),
        "parse_error": _safe_text(log.parse_error),
        "ai_version": _safe_text(log.ai_version) or "1.0",
        "audit_type_display": audit_type.display.model_dump() if audit_type.display else None,
    })
    return PushLogDetail.model_validate(item)


@router.get("", response_model=PaginatedLogs, summary="分页查询推送日志")
def query_logs(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=1000),
    status: str = Query(None, description="success|failed|skipped|pending"),
    dept: str = Query(None),
    date_from: str = Query(None, description="按查询日期筛选 yyyy-mm-dd"),
    date_to: str = Query(None, description="按查询日期筛选 yyyy-mm-dd"),
    push_time_from: str = Query(None, description="按推送时间筛选 yyyy-mm-dd"),
    push_time_to: str = Query(None, description="按推送时间筛选 yyyy-mm-dd"),
    patient_id: str = Query(None),
    audit_type_code: str = Query(None, description="核查类型编码"),
    reviewed_flag: int = Query(None, ge=0, le=1, description="人工复核标记：0未复核/1已复核"),
    manual_override: int = Query(None, ge=0, le=1, description="手动覆盖标记：0否/1是"),
    skip_reason: str = Query(None, description="跳过原因筛选"),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(PushLog)
    if status:
        q = q.filter(PushLog.status == status)
    if dept:
        q = q.filter(PushLog.dept == dept)
    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)
    if push_time_from:
        from_dt = _parse_day(push_time_from, "push_time_from")
        q = q.filter(PushLog.push_time >= from_dt)
    if push_time_to:
        to_dt = _parse_day(push_time_to, "push_time_to") + timedelta(days=1)
        q = q.filter(PushLog.push_time < to_dt)
    if patient_id:
        q = q.filter(PushLog.patient_id.contains(patient_id))
    if audit_type_code:
        if audit_type_code == "progress_vs_nursing":
            from sqlalchemy import or_
            q = q.filter(or_(PushLog.audit_type_code == audit_type_code, PushLog.audit_type_code == "", PushLog.audit_type_code.is_(None)))
        else:
            q = q.filter(PushLog.audit_type_code == audit_type_code)
    if reviewed_flag is not None:
        q = q.filter(PushLog.reviewed_flag == reviewed_flag)
    if manual_override is not None:
        q = q.filter(PushLog.manual_override == manual_override)
    if skip_reason:
        q = q.filter(PushLog.skip_reason == skip_reason)

    total = q.count()
    items = (
        q.order_by(desc(PushLog.push_time))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    registry = AuditTypeRegistry()

    return PaginatedLogs(
        total=total,
        page=page,
        limit=limit,
        items=[_to_push_log_item(i, registry=registry) for i in items],
    )


@router.get("/filters/options", summary="获取日志筛选选项")
def get_log_filter_options(db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    total = db.query(func.count(PushLog.id)).scalar() or 0

    reviewed_0 = db.query(func.count(PushLog.id)).filter(PushLog.reviewed_flag == 0).scalar() or 0
    reviewed_1 = db.query(func.count(PushLog.id)).filter(PushLog.reviewed_flag == 1).scalar() or 0

    override_0 = db.query(func.count(PushLog.id)).filter(PushLog.manual_override == 0).scalar() or 0
    override_1 = db.query(func.count(PushLog.id)).filter(PushLog.manual_override == 1).scalar() or 0

    reason_rows = (
        db.query(PushLog.skip_reason, func.count(PushLog.id))
        .filter(PushLog.skip_reason.isnot(None))
        .filter(PushLog.skip_reason != "")
        .group_by(PushLog.skip_reason)
        .order_by(desc(func.count(PushLog.id)))
        .all()
    )
    registry = AuditTypeRegistry()

    return {
        "total": int(total),
        "reviewed_flag_options": [
            {"value": 0, "label": "未复核", "count": int(reviewed_0)},
            {"value": 1, "label": "已复核", "count": int(reviewed_1)},
        ],
        "manual_override_options": [
            {"value": 0, "label": "未覆盖", "count": int(override_0)},
            {"value": 1, "label": "已覆盖", "count": int(override_1)},
        ],
        "skip_reason_options": [
            {
                "value": str(reason),
                "label": _SKIP_REASON_LABELS.get(str(reason), str(reason)),
                "count": int(cnt),
            }
            for reason, cnt in reason_rows
        ],
        "audit_type_options": [
            {"value": item.code, "label": item.name}
            for item in registry.list_all()
        ],
    }


@router.get("/skip-reasons/stats", summary="跳过原因统计")
def get_skip_reason_stats(
    date_from: str = Query(None),
    date_to: str = Query(None),
    push_time_from: str = Query(None),
    push_time_to: str = Query(None),
    dept: str = Query(None),
    audit_type_code: str = Query(None),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    q = db.query(PushLog.skip_reason, func.count(PushLog.id)).filter(PushLog.status == "skipped")

    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)
    if push_time_from:
        from_dt = _parse_day(push_time_from, "push_time_from")
        q = q.filter(PushLog.push_time >= from_dt)
    if push_time_to:
        to_dt = _parse_day(push_time_to, "push_time_to") + timedelta(days=1)
        q = q.filter(PushLog.push_time < to_dt)
    if dept:
        q = q.filter(PushLog.dept == dept)
    if audit_type_code:
        if audit_type_code == "progress_vs_nursing":
            from sqlalchemy import or_
            q = q.filter(or_(PushLog.audit_type_code == audit_type_code, PushLog.audit_type_code == "", PushLog.audit_type_code.is_(None)))
        else:
            q = q.filter(PushLog.audit_type_code == audit_type_code)

    q = q.group_by(PushLog.skip_reason).order_by(desc(func.count(PushLog.id)))
    rows = q.all()

    total = sum(count for _, count in rows)
    items = []
    for reason, count in rows:
        label = _SKIP_REASON_LABELS.get(reason or "", reason or "未知原因")
        items.append({
            "reason": reason or "",
            "label": label,
            "count": count,
            "percent": round(count / total * 100, 2) if total else 0,
        })

    return {
        "total_skipped": total,
        "items": items,
    }


# 注意：/export/csv 必须在 /{log_id} 之前定义，否则 "export" 会被当作 log_id 解析
@router.get("/export/csv", summary="导出 CSV")
def export_csv(
    status: str = Query(None),
    dept: str = Query(None),
    date_from: str = Query(None),
    date_to: str = Query(None),
    reviewed_flag: int = Query(None, ge=0, le=1),
    manual_override: int = Query(None, ge=0, le=1),
    skip_reason: str = Query(None),
    audit_type_code: str = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("export_reports")),
    request: Request = None,
):
    q = db.query(PushLog)
    if status:
        q = q.filter(PushLog.status == status)
    if dept:
        q = q.filter(PushLog.dept == dept)
    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)
    if reviewed_flag is not None:
        q = q.filter(PushLog.reviewed_flag == reviewed_flag)
    if manual_override is not None:
        q = q.filter(PushLog.manual_override == manual_override)
    if skip_reason:
        q = q.filter(PushLog.skip_reason == skip_reason)
    if audit_type_code:
        if audit_type_code == "progress_vs_nursing":
            from sqlalchemy import or_
            q = q.filter(or_(PushLog.audit_type_code == audit_type_code, PushLog.audit_type_code == "", PushLog.audit_type_code.is_(None)))
        else:
            q = q.filter(PushLog.audit_type_code == audit_type_code)

    EXPORT_MAX_ROWS = 10000
    logs = q.order_by(desc(PushLog.push_time)).limit(EXPORT_MAX_ROWS).all()

    output = io.StringIO()
    writer = csv.writer(output)
    registry = AuditTypeRegistry()
    writer.writerow([
        "ID", "推送时间", "触发类型", "查询日期", "患者ID", "姓名",
        "在院科室", "入院科室", "出院科室", "核查类型编码", "核查类型", "状态", "已复核", "手动覆盖", "跳过原因", "不一致", "严重程度", "风险分", "耗时(ms)", "重试次数", "错误信息",
    ])
    for log in logs:
        audit_type = registry.get_or_default(getattr(log, "audit_type_code", "") or "")
        admission = _extract_dept_from_request(log, "admission_dept_name")
        discharge = _extract_dept_from_request(log, "discharge_dept_name")
        writer.writerow([
            log.id, log.push_time, log.trigger_type, log.query_date,
            log.patient_id, log.patient_name, log.dept, admission, discharge, audit_type.code, audit_type.name, log.status,
            "是" if int(getattr(log, "reviewed_flag", 0) or 0) == 1 else "否",
            "是" if int(getattr(log, "manual_override", 0) or 0) == 1 else "否",
            _safe_text(getattr(log, "skip_reason", "")),
            "是" if log.inconsistency else "否", log.severity,
            int(getattr(log, "risk_score", 0) or 0), log.elapsed_ms, log.retry_count, log.error_msg,
        ])

    output.seek(0)
    filename = f"push_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # 记录导出审计日志
    try:
        record_export_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username or "",
            export_type="push_log",
            export_format="csv",
            filter_criteria={
                "status": status,
                "dept": dept,
                "date_from": date_from,
                "date_to": date_to,
                "reviewed_flag": reviewed_flag,
                "manual_override": manual_override,
                "skip_reason": skip_reason,
                "audit_type_code": audit_type_code,
            },
            record_count=len(logs),
            status="success",
            request=request,
        )
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.error("导出审计日志记录失败: %s", exc, exc_info=True)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{log_id}", response_model=PushLogDetail, summary="日志详情（含完整AI结果）")
def get_log_detail(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    detail = _to_push_log_detail(log, registry=AuditTypeRegistry()).model_dump()
    stored_audit = _build_stored_audit_snapshot(log_id, db)
    dify_result = _parse_dify_result_payload(log.response_json, log.ai_result)
    detail["stored_audit"] = stored_audit
    detail["audit_result"] = _build_audit_result_payload(stored_audit)
    detail["raw_debug"] = _build_raw_debug_payload(log, dify_result, stored_audit)
    return PushLogDetail.model_validate(detail)


@router.delete("/bulk/delete", response_model=MessageResponse, summary="批量删除推送日志")
def delete_logs_bulk(body: PushLogBulkDeleteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_admin(current_user, db)
    deleted = _delete_push_logs(db, body.log_ids)
    return MessageResponse(message="推送日志已删除", success=True, data={"requested": len(body.log_ids), "deleted": deleted})


@router.delete("/{log_id}", response_model=MessageResponse, summary="删除推送日志")
def delete_log(log_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _require_admin(current_user, db)
    deleted = _delete_push_logs(db, [log_id])
    if not deleted:
        raise HTTPException(status_code=404, detail="日志不存在")
    return MessageResponse(message="推送日志已删除", success=True, data={"deleted": deleted})


@router.post("/{log_id}/retry", response_model=MessageResponse, summary="单条重推")
def retry_single(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    config = load_config()
    push_settings = ConfigParser.get_push_settings(config)
    max_retry = push_settings["max_retry"]

    if log.retry_count >= max_retry:
        return MessageResponse(message=f"已达最大重试次数({max_retry})", success=False)

    if not log.request_json and not log.mr_text:
        return MessageResponse(message="无原始推送内容，无法重推", success=False)

    dify_cfg = ConfigParser.parse_dify_config(config)
    payload = json.loads(log.request_json) if log.request_json else log.mr_text
    dify_input = log.mr_text or (
        json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload or "")
    )
    result = push_to_dify(dify_input, dify_cfg, log.patient_id)

    log.status = result.get("status", "failed")
    log.pushed_flag = 1 if result.get("status") == "success" else 0
    log.reviewed_flag = 0
    log.reviewed_at = None
    log.reviewed_by = ""
    log.manual_override = 0
    log.skip_reason = ""
    log.workflow_run_id = result.get("workflow_run_id", "")
    log.task_id = result.get("task_id", "")
    log.ai_result = json.dumps(result.get("result", {}), ensure_ascii=False)
    log.response_json = json.dumps(result.get("result", {}), ensure_ascii=False)
    log.inconsistency = 1 if result.get("inconsistency") else 0
    log.severity = result.get("severity", "")
    log.risk_score = result.get("risk_score", 0)
    log.error_msg = result.get("error", "")
    log.elapsed_ms = result.get("elapsed_ms", 0)
    log.parse_status = "success" if result.get("parsed_output", {}).get("parse_success") else "failed"
    log.parse_error = result.get("parse_error", "")
    log.ai_version = result.get("parsed_output", {}).get("version", "1.0")
    log.alert_level = result.get("parsed_output", {}).get("alert_level", "")
    log.retry_count += 1
    log.push_time = datetime.now()
    log.trigger_type = "retry"

    # 清除旧的审计结果，保存新的
    db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == log_id).delete()
    db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).delete()

    parsed = result.get("parsed_output", {})
    if parsed and parsed.get("parse_success"):
        for dim in parsed.get("dimensions", []):
            db.add(AuditDimensionResult(
                push_log_id=log_id,
                dimension_code=dim.get("dimension_code", ""),
                dimension=dim.get("dimension", ""),
                status=dim.get("status", "❓"),
                severity=dim.get("severity", ""),
                confidence=float(dim.get("confidence", 0) or 0),
                medical_content=dim.get("medical_content", ""),
                nursing_content=dim.get("nursing_content", ""),
                explanation=dim.get("explanation", ""),
                issue_summary=dim.get("issue_summary", ""),
                recommendation=dim.get("recommendation", ""),
                medical_evidence_json=json.dumps(dim.get("medical_evidence", []), ensure_ascii=False),
                nursing_evidence_json=json.dumps(dim.get("nursing_evidence", []), ensure_ascii=False),
                alert_level=dim.get("alert_level", ""),
                closure_hours=dim.get("closure_hours", 0),
                push_strategy=dim.get("push_strategy", ""),
                outcome_bucket=dim.get("outcome_bucket", ""),
            ))
        focus_items = parsed.get("focus_items", [])
        db.add(AuditConclusion(
            push_log_id=log_id,
            has_inconsistency=1 if parsed.get("inconsistency") else 0,
            severity=parsed.get("severity", ""),
            risk_score=parsed.get("risk_score", 0),
            overall_conclusion=parsed.get("overall_conclusion", ""),
            focus_items=json.dumps(focus_items, ensure_ascii=False) if focus_items else "[]",
            audit_date=parsed.get("audit_date", ""),
            reasoning_brief=parsed.get("reasoning_brief", ""),
            ai_version=parsed.get("version", "1.0"),
            alert_level=parsed.get("alert_level", ""),
            closure_hours=parsed.get("closure_hours", 0),
            push_strategy=parsed.get("push_strategy", ""),
            outcome_bucket=parsed.get("outcome_bucket", ""),
            overall_qc_summary=parsed.get("overall_qc_summary", ""),
        ))

    db.commit()
    return MessageResponse(
        message=f"重推完成，状态: {result.get('status')}",
        success=result.get("status") == "success",
    )


@router.get("/{log_id}/marker", summary="查询推送标记")
def get_push_marker(log_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")
    return {
        "log_id": log.id,
        "patient_id": _safe_text(log.patient_id),
        "visit_number": _safe_text(log.visit_number),
        "pushed_flag": int(log.pushed_flag or 0),
        "reviewed_flag": int(log.reviewed_flag or 0),
        "reviewed_at": log.reviewed_at.isoformat() if getattr(log, "reviewed_at", None) else "",
        "reviewed_by": _safe_text(getattr(log, "reviewed_by", "")),
        "manual_override": int(getattr(log, "manual_override", 0) or 0),
        "skip_reason": _safe_text(getattr(log, "skip_reason", "")),
    }


@router.post("/{log_id}/marker", response_model=MessageResponse, summary="手动更新推送标记")
def update_push_marker(
    log_id: int,
    body: PushMarkerUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_admin(current_user, db)
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="日志不存在")

    log.reviewed_flag = int(body.reviewed_flag)
    log.reviewed_at = datetime.now() if body.reviewed_flag == 1 else None
    log.reviewed_by = _safe_text(current_user.username)
    log.manual_override = int(body.manual_override)
    log.skip_reason = _safe_text(body.skip_reason)
    db.commit()
    return MessageResponse(message="推送标记已更新")
