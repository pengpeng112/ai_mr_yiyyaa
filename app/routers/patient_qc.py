"""
患者质控总览 API
以 patient_id + visit_number + dept 为中心，聚合展示该患者本次住院的所有质控结果。
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    PushLog, AuditConclusion, AuditDimensionResult,
    QCFeedback, QCFeedbackHistory, User, Department,
)
from app.services.patient_snapshot import extract_patient_snapshot
from app.permissions import require_role, get_user_role
from app.auth import get_current_user
from app.schemas import QuickActionRequest, MessageResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# 严重度排序
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "": 0, None: 0}

# 问题维度判断
_ISSUE_STATUSES = {"fail", "warning", "risk"}


def _safe_json_loads(value, default=None):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return default or {}
    try:
        return json.loads(text)
    except Exception:
        return default or {}


def _format_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


def _extract_evidence_summary(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
        return payload.get("evidence_summary") or payload.get("evidence_title") or ""
    except Exception:
        return ""


def _get_snapshot_info(log: PushLog) -> dict:
    """从 push_log 的 request_json 中提取患者快照。"""
    return extract_patient_snapshot(log)


def _is_issue(dim: AuditDimensionResult) -> bool:
    """判断一个维度是否为问题。"""
    return (
        dim.status in _ISSUE_STATUSES
        or (dim.severity or "") in {"high", "medium"}
        or bool((dim.issue_summary or "").strip())
    )


def _alert_level_for_severity(severity: str) -> str:
    return {"high": "red", "medium": "yellow", "low": "blue"}.get(severity, "")


@router.get("/patients", summary="患者质控总览 - 患者聚合列表")
def list_patient_qc_patients(
    patient_id: Optional[str] = Query(None),
    patient_name: Optional[str] = Query(None),
    admission_no: Optional[str] = Query(None),
    visit_number: Optional[str] = Query(None),
    dept: Optional[str] = Query(None),
    discharge_dept_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询患者质控聚合列表（SQL 聚合 + 分页，避免全量加载）。"""
    from sqlalchemy import func, case, or_, literal_column

    severity_rank_expr = case(
        (AuditDimensionResult.severity == "high", 3),
        (AuditDimensionResult.severity == "medium", 2),
        (AuditDimensionResult.severity == "low", 1),
        else_=0,
    )
    severity_rank_map = {"high": 3, "medium": 2, "low": 1}

    base_filters = [PushLog.status == "success"]

    # ---- Step 1: SQL 聚合分组 ----
    base = db.query(
        PushLog.patient_id.label("pid"),
        PushLog.visit_number.label("vn"),
        PushLog.dept.label("dp"),
        func.count(PushLog.id).label("push_log_count"),
        func.max(PushLog.push_time).label("latest_push_time"),
        func.count(func.distinct(PushLog.audit_type_code)).label("audit_type_count"),
    )

    # 时间筛选
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            base_filters.append(PushLog.push_time >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            base_filters.append(PushLog.push_time <= dt_to)
        except ValueError:
            pass
    if audit_type_code:
        base_filters.append(PushLog.audit_type_code == audit_type_code)
    if patient_id:
        base_filters.append(PushLog.patient_id.like(f"%{patient_id}%"))
    if patient_name:
        base_filters.append(PushLog.patient_name.like(f"%{patient_name}%"))
    if admission_no:
        base_filters.append(PushLog.admission_no.like(f"%{admission_no}%"))
    if visit_number:
        base_filters.append(PushLog.visit_number == visit_number)
    if dept:
        base_filters.append(PushLog.dept.like(f"%{dept}%"))
    if discharge_dept_name:
        base_filters.append(PushLog.request_json.like(f'%"discharge_dept_name":"%{discharge_dept_name}%"'))

    base = base.filter(*base_filters)

    if severity in severity_rank_map:
        severity_subq = db.query(
            PushLog.patient_id.label("pid"),
            PushLog.visit_number.label("vn"),
            PushLog.dept.label("dp"),
            func.max(severity_rank_expr).label("severity_rank"),
        ).join(
            AuditDimensionResult, AuditDimensionResult.push_log_id == PushLog.id
        ).filter(*base_filters).group_by(
            PushLog.patient_id, PushLog.visit_number, PushLog.dept
        ).subquery()
        base = base.join(
            severity_subq,
            (PushLog.patient_id == severity_subq.c.pid)
            & (PushLog.visit_number == severity_subq.c.vn)
            & (PushLog.dept == severity_subq.c.dp),
        ).filter(severity_subq.c.severity_rank == severity_rank_map[severity])

    if status:
        feedback_subq = db.query(
            PushLog.patient_id.label("pid"),
            PushLog.visit_number.label("vn"),
            PushLog.dept.label("dp"),
            func.sum(case((QCFeedback.status == status, 1), else_=0)).label("status_count"),
        ).join(
            QCFeedback, QCFeedback.push_log_id == PushLog.id
        ).filter(*base_filters).group_by(
            PushLog.patient_id, PushLog.visit_number, PushLog.dept
        ).subquery()
        base = base.join(
            feedback_subq,
            (PushLog.patient_id == feedback_subq.c.pid)
            & (PushLog.visit_number == feedback_subq.c.vn)
            & (PushLog.dept == feedback_subq.c.dp),
        ).filter(feedback_subq.c.status_count > 0)

    grouped_subq = base.group_by(
        PushLog.patient_id, PushLog.visit_number, PushLog.dept
    ).subquery()

    # 总数
    total = db.query(func.count(literal_column("*"))).select_from(grouped_subq).scalar() or 0

    # 分页查询分组
    offset = (page - 1) * limit
    groups = db.query(grouped_subq).order_by(
        grouped_subq.c.latest_push_time.desc()
    ).offset(offset).limit(limit).all()

    if not groups:
        return {"total": total, "items": []}

    # ---- Step 2: 只对当前页的分组查询维度和反馈统计 ----
    # 构建 OR 条件匹配 (patient_id, visit_number, dept)
    page_conditions = []
    for g in groups:
        page_conditions.append(
            (PushLog.patient_id == g.pid)
            & (PushLog.visit_number == g.vn)
            & (PushLog.dept == g.dp)
        )
    page_logs = db.query(PushLog).filter(
        PushLog.status == "success", or_(*page_conditions)
    ).all()
    page_log_ids = [l.id for l in page_logs]

    # 按分组 key 索引 log
    logs_by_group: dict[str, list] = {}
    for l in page_logs:
        k = f"{l.patient_id}::{l.visit_number}::{l.dept}"
        logs_by_group.setdefault(k, []).append(l)

    # 批量加载维度和反馈（仅当前页的 log IDs）
    dims_by_log: dict[int, list] = {}
    fb_by_log: dict[int, list] = {}
    if page_log_ids:
        for d in db.query(AuditDimensionResult).filter(
            AuditDimensionResult.push_log_id.in_(page_log_ids)
        ).all():
            dims_by_log.setdefault(d.push_log_id, []).append(d)
        for f in db.query(QCFeedback).filter(
            QCFeedback.push_log_id.in_(page_log_ids)
        ).all():
            fb_by_log.setdefault(f.push_log_id, []).append(f)

    # ---- Step 3: 组装结果 ----
    result_items = []
    for g in groups:
        gkey = f"{g.pid}::{g.vn}::{g.dp}"
        g_logs = logs_by_group.get(gkey, [])
        if not g_logs:
            continue

        g_dims = [d for lid in [l.id for l in g_logs] for d in dims_by_log.get(lid, [])]
        g_fbs = [f for lid in [l.id for l in g_logs] for f in fb_by_log.get(lid, [])]

        high_count = sum(1 for d in g_dims if d.severity == "high")
        medium_count = sum(1 for d in g_dims if d.severity == "medium")
        low_count = sum(1 for d in g_dims if d.severity == "low")
        issue_count = sum(1 for d in g_dims if _is_issue(d))
        pending_count = sum(1 for f in g_fbs if f.status == "pending")
        resolved_count = sum(1 for f in g_fbs if f.status in {"rectified", "closed"})

        all_severities = [d.severity for d in g_dims if d.severity]
        highest = max(all_severities, key=lambda s: _SEVERITY_RANK.get(s, 0)) if all_severities else ""

        # 患者姓名：只对当前页的记录解析 request_json
        first_log = g_logs[0]
        snapshot = _get_snapshot_info(first_log)

        result_items.append({
            "patient_id": g.pid,
            "visit_number": g.vn,
            "patient_name": snapshot.get("patient_name") or first_log.patient_name or "",
            "admission_no": snapshot.get("admission_no") or first_log.admission_no or "",
            "dept": g.dp or first_log.dept or "",
            "admission_dept_name": snapshot.get("admission_dept_name") or "",
            "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
            "latest_push_time": _format_dt(g.latest_push_time),
            "audit_type_count": int(g.audit_type_count or 0),
            "push_log_count": int(g.push_log_count or 0),
            "issue_count": issue_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "pending_count": pending_count,
            "resolved_count": resolved_count,
            "highest_severity": highest,
            "alert_level": _alert_level_for_severity(highest),
        })

    return {"total": total, "items": result_items}


@router.get("/patient-detail", summary="患者质控总览 - 患者详情")
def get_patient_qc_detail(
    patient_id: str = Query(...),
    visit_number: str = Query(...),
    dept: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询某患者本次住院的完整质控详情。"""
    q = db.query(PushLog).filter(
        PushLog.patient_id == patient_id,
        PushLog.visit_number == visit_number,
        PushLog.status == "success",
    )
    if dept:
        q = q.filter(PushLog.dept == dept)
    logs = q.order_by(PushLog.push_time.desc()).all()

    if not logs:
        raise HTTPException(status_code=404, detail="no records found for this patient")

    # 患者信息
    first_log = logs[0]
    snapshot = _get_snapshot_info(first_log)
    request_json = _safe_json_loads(getattr(first_log, "request_json", "") or "")
    patient_info_req = request_json.get("patient_info", {}) if isinstance(request_json.get("patient_info"), dict) else {}

    patient = {
        "patient_id": patient_id,
        "visit_number": visit_number,
        "patient_name": snapshot.get("patient_name") or first_log.patient_name or "",
        "admission_no": snapshot.get("admission_no") or first_log.admission_no or "",
        "dept": snapshot.get("dept_name") or first_log.dept or "",
        "admission_date": snapshot.get("admission_date") or "",
        "discharge_date": snapshot.get("discharge_date") or "",
        "admission_diagnosis": snapshot.get("admission_diagnosis") or "",
        "discharge_main_diagnosis": snapshot.get("discharge_main_diagnosis") or "",
        "admission_dept_name": snapshot.get("admission_dept_name") or "",
        "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
        "surgery": snapshot.get("surgery") or "",
    }

    # 按审计类型分组
    log_ids = [l.id for l in logs]
    all_dimensions = db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    all_conclusions = db.query(AuditConclusion).filter(
        AuditConclusion.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    all_feedbacks = db.query(QCFeedback).filter(
        QCFeedback.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    # 用户映射
    user_ids = set()
    for fb in all_feedbacks:
        if fb.assigned_to:
            user_ids.add(fb.assigned_to)
    users = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            users[u.id] = u.full_name or u.username

    # 构建审计分组
    conclusion_map = {c.push_log_id: c for c in all_conclusions}
    dim_map: dict[int, list[AuditDimensionResult]] = {}
    for d in all_dimensions:
        dim_map.setdefault(d.push_log_id, []).append(d)
    feedback_map: dict[int, list[QCFeedback]] = {}
    for f in all_feedbacks:
        feedback_map.setdefault(f.push_log_id, []).append(f)

    audit_groups_dict: dict[str, dict] = {}
    for log in logs:
        code = log.audit_type_code or "unknown"
        if code not in audit_groups_dict:
            audit_groups_dict[code] = {
                "audit_type_code": code,
                "audit_type_name": code,
                "latest_push_time": _format_dt(log.push_time),
                "overall_conclusion": "",
                "overall_qc_summary": "",
                "severity": "",
                "alert_level": "",
                "logs": [],
            }

        conclusion = conclusion_map.get(log.id)
        dims = dim_map.get(log.id, [])
        fbs = feedback_map.get(log.id, [])

        # 填充总体结论（取最新）
        if conclusion and not audit_groups_dict[code]["overall_conclusion"]:
            audit_groups_dict[code]["overall_conclusion"] = conclusion.overall_conclusion or ""
            audit_groups_dict[code]["overall_qc_summary"] = conclusion.overall_qc_summary or ""
            audit_groups_dict[code]["severity"] = conclusion.severity or ""
            audit_groups_dict[code]["alert_level"] = conclusion.alert_level or ""

        # 维度
        dimensions_list = []
        for dim in dims:
            dimensions_list.append({
                "dimension_code": dim.dimension_code or "",
                "dimension_name": dim.dimension or "",
                "status": dim.status or "",
                "severity": dim.severity or "",
                "alert_level": dim.alert_level or "",
                "issue_summary": dim.issue_summary or "",
                "medical_evidence": _safe_json_loads(dim.medical_evidence_json, []),
                "nursing_evidence": _safe_json_loads(dim.nursing_evidence_json, []),
                "recommendation": dim.recommendation or "",
                "explanation": dim.explanation or "",
            })

        # 反馈
        fb_info = {"status": "pending", "feedback_text": "", "assigned_to_name": ""}
        if fbs:
            fb = fbs[0]
            fb_info["status"] = fb.status or "pending"
            fb_info["feedback_text"] = fb.feedback_text or ""
            fb_info["assigned_to_name"] = users.get(fb.assigned_to, "") if fb.assigned_to else ""

        audit_groups_dict[code]["logs"].append({
            "push_log_id": log.id,
            "push_time": _format_dt(log.push_time),
            "status": log.status or "",
            "parse_status": log.parse_status or "",
            "parse_error": log.parse_error or "",
            "overall_conclusion": (conclusion.overall_conclusion or "") if conclusion else "",
            "overall_qc_summary": (conclusion.overall_qc_summary or "") if conclusion else "",
            "severity": log.severity or "",
            "alert_level": log.alert_level or "",
            "inconsistency": bool(log.inconsistency),
            "risk_score": log.risk_score or 0,
            "dimensions": dimensions_list,
            "feedback": fb_info,
        })

    audit_groups = list(audit_groups_dict.values())

    # 汇总统计
    all_dims = all_dimensions
    high_count = sum(1 for d in all_dims if d.severity == "high")
    medium_count = sum(1 for d in all_dims if d.severity == "medium")
    low_count = sum(1 for d in all_dims if d.severity == "low")
    issue_count = sum(1 for d in all_dims if _is_issue(d))
    pending_count = sum(1 for f in all_feedbacks if f.status == "pending")
    resolved_count = sum(1 for f in all_feedbacks if f.status in {"rectified", "closed"})

    all_severities = [d.severity for d in all_dims if d.severity]
    highest = max(all_severities, key=lambda s: _SEVERITY_RANK.get(s, 0)) if all_severities else ""

    summary = {
        "audit_type_count": len(audit_groups),
        "push_log_count": len(logs),
        "issue_count": issue_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "pending_count": pending_count,
        "resolved_count": resolved_count,
        "highest_severity": highest,
    }

    return {"patient": patient, "summary": summary, "audit_groups": audit_groups}


@router.get("/relay-alert/logs", summary="前置机推送日志查询")
def list_relay_alert_logs(
    patient_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    viewed_flag: Optional[int] = Query(None, description="查看状态 1=已查看 0=未查看"),
    dept: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询前置机推送日志。"""
    from app.models import QCRecordAlertLog

    q = db.query(QCRecordAlertLog)
    if patient_id:
        q = q.filter(QCRecordAlertLog.patient_id.like(f"%{patient_id}%"))
    if status:
        q = q.filter(QCRecordAlertLog.status == status)
    if viewed_flag is not None:
        q = q.filter(QCRecordAlertLog.viewed_flag == viewed_flag)
    if dept:
        q = q.filter(QCRecordAlertLog.dept.like(f"%{dept}%"))
    if severity:
        q = q.filter(QCRecordAlertLog.severity == severity)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(QCRecordAlertLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            q = q.filter(QCRecordAlertLog.created_at <= dt_to)
        except ValueError:
            pass

    total = q.count()
    items = q.order_by(QCRecordAlertLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "push_log_id": item.push_log_id,
                "dimension_code": item.dimension_code,
                "patient_id": item.patient_id,
                "dept": item.dept,
                "severity": item.severity,
                "alert_level": item.alert_level,
                "status": item.status,
                "retry_count": item.retry_count,
                "last_error": item.last_error,
                "sent_at": _format_dt(item.sent_at),
                "created_at": _format_dt(item.created_at),
                "viewed_flag": int(getattr(item, "viewed_flag", 0) or 0),
                "viewed_at": _format_dt(getattr(item, "viewed_at", None)),
                "last_viewed_at": _format_dt(getattr(item, "last_viewed_at", None)),
                "view_count": int(getattr(item, "view_count", 0) or 0),
                "viewer_name": getattr(item, "viewer_name", "") or "",
                "viewer_userid": getattr(item, "viewer_userid", "") or "",
                "evidence_summary": _extract_evidence_summary(getattr(item, "payload_json", "")),
            }
            for item in items
        ],
    }


@router.get("/relay-alert/summary", summary="前置机推送日志统计")
def relay_alert_summary(
    patient_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    viewed_flag: Optional[int] = Query(None),
    dept: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询前置机推送日志统计（全量口径，用于首页 KPI）。"""
    from app.models import QCRecordAlertLog

    q = db.query(QCRecordAlertLog)
    if patient_id:
        q = q.filter(QCRecordAlertLog.patient_id.like(f"%{patient_id}%"))
    if status:
        q = q.filter(QCRecordAlertLog.status == status)
    if viewed_flag is not None:
        q = q.filter(QCRecordAlertLog.viewed_flag == viewed_flag)
    if dept:
        q = q.filter(QCRecordAlertLog.dept.like(f"%{dept}%"))
    if severity:
        q = q.filter(QCRecordAlertLog.severity == severity)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(QCRecordAlertLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            q = q.filter(QCRecordAlertLog.created_at <= dt_to)
        except ValueError:
            pass

    total = q.count()
    success = q.filter(QCRecordAlertLog.status == "success").count()
    failed = q.filter(QCRecordAlertLog.status == "failed").count()
    pending = q.filter(QCRecordAlertLog.status == "pending").count()
    suppressed = q.filter(QCRecordAlertLog.status == "suppressed").count()
    viewed = q.filter(QCRecordAlertLog.viewed_flag == 1).count()
    unviewed = q.filter(QCRecordAlertLog.viewed_flag == 0, QCRecordAlertLog.status != "suppressed").count()

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "suppressed": suppressed,
        "viewed": viewed,
        "unviewed": unviewed,
        "success_rate": round(success * 100 / total, 2) if total else None,
        "view_rate": round(viewed * 100 / total, 2) if total else None,
    }


@router.post("/relay-alert/retry/{alert_id}", summary="重试前置机推送")
def retry_relay_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """重试一条失败的前置机推送记录。"""
    from app.models import QCRecordAlertLog
    from app.services.relay_alert_service import RelayAlertService
    from app.config import load_config

    alert = db.query(QCRecordAlertLog).filter(QCRecordAlertLog.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status == "success":
        return {"message": "already sent", "status": "success"}
    if alert.status == "suppressed":
        raise HTTPException(status_code=400, detail="suppressed alert cannot be retried")
    if alert.status not in ("failed", "pending"):
        raise HTTPException(status_code=400, detail="only failed or pending alerts can be retried")

    config = load_config()
    service = RelayAlertService(db, config)
    ok = service.send_one(alert)
    db.commit()

    return {"message": "sent" if ok else "failed", "status": alert.status, "last_error": alert.last_error}


@router.post("/feedback/quick-action", response_model=MessageResponse, summary="医生快捷操作")
def feedback_quick_action(
    body: QuickActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """医生快捷操作：已整改/未处理/其他原因。"""
    if body.action == "other" and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="其他原因需要填写说明")

    # 查找 PushLog
    log = db.query(PushLog).filter(PushLog.id == body.push_log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="push log not found")

    from app.routers.qc_feedback import (
        _check_feedback_permission,
        _resolve_confirm_dept_id,
        _resolve_department_by_name,
    )

    # 查找或创建 QCFeedback
    feedback = db.query(QCFeedback).filter(
        QCFeedback.push_log_id == body.push_log_id,
        QCFeedback.status != "deleted",
    ).order_by(QCFeedback.id.desc()).first()

    if feedback:
        _check_feedback_permission(feedback, current_user, db)

    now = datetime.now()

    if not feedback:
        # 首次操作，自动创建 feedback
        role_name = get_user_role(current_user.id, db) or ""
        dept_ref = _resolve_department_by_name(db, log.dept)
        dept_id = _resolve_confirm_dept_id(role_name, current_user.dept_id, dept_ref, feedback)
        feedback = QCFeedback(
            push_log_id=log.id,
            dept_id=dept_id,
            severity=log.severity or "medium",
            status="pending",
            is_viewed=False,
            view_count=0,
            created_by=current_user.id,
        )
        db.add(feedback)
        db.flush()

    old_status = feedback.status

    if body.action == "rectified":
        feedback.status = "rectified"
        feedback.suppress_ai_push = True
        feedback.rectification_text = body.reason or "已整改"
        feedback.rectification_date = now
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now
        db.add(QCFeedbackHistory(
            feedback_id=feedback.id,
            old_status=old_status,
            new_status="rectified",
            changed_by=current_user.id,
            change_reason="医生快捷操作：已整改",
        ))

    elif body.action == "pending":
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now

    elif body.action == "other":
        feedback.status = "closed"
        feedback.suppress_ai_push = False
        feedback.feedback_text = (body.reason or "").strip()
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now
        db.add(QCFeedbackHistory(
            feedback_id=feedback.id,
            old_status=old_status,
            new_status="closed",
            changed_by=current_user.id,
            change_reason=f"医生快捷操作：其他原因 - {body.reason}",
        ))

    db.commit()
    return MessageResponse(message=f"操作成功：{body.action}")


@router.get("/export/patient-visit-summary", summary="导出患者就诊数据汇总")
def export_patient_visit_summary(
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """从 TEMP_PAT_VISIT_LIST 临时表出发，关联业务库各表和应用库 PushLog，导出 Excel。"""
    from fastapi.responses import Response
    from app.services.patient_visit_export_service import export_patient_visit_summary as _export

    try:
        xlsx_bytes, fmt = _export(db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    filename = f"patient_visit_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
