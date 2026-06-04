"""
质控反馈管理 API
支持反馈的 CRUD、状态流转、整改追踪、统计
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
import json
import logging

from app.database import get_db
from app.models import User, Role, QCFeedback, QCFeedbackHistory, Department, PushLog, AuditConclusion, AuditDimensionResult
from app.schemas import (
    QCFeedbackCreateRequest, QCFeedbackUpdateRequest, QCFeedbackRectifyRequest,
    QCFeedbackItem, QCFeedbackDetail, QCFeedbackListResponse, QCFeedbackStats,
    MessageResponse, QCFeedbackCaseListResponse, QCFeedbackCaseItem, QCFeedbackCaseDetail,
    AuditDimensionItem, QCFeedbackConfirmRequest, QCFeedbackBulkDeleteRequest
)
from sqlalchemy import func, case, or_, and_
from app.auth import get_current_user
from app.permissions import get_user_role
from app.services.patient_snapshot import extract_patient_snapshot, extract_raw_record_sections
from app.services.export_audit_service import record_export_audit
from app.services.audit_type_registry import AuditTypeRegistry

logger = logging.getLogger(__name__)

router = APIRouter()


from app.utils.json_utils import safe_json_loads as _safe_json_loads
from app.utils.text_utils import safe_text as _safe_mr_text


def _normalize_feedback_nullable_fields(feedback: Optional[QCFeedback]) -> Optional[QCFeedback]:
    """序列化前兜底历史 NULL，避免 Pydantic string 校验失败。"""
    if feedback is None:
        return None
    if feedback.rectification_text is None:
        feedback.rectification_text = ""
    if feedback.feedback_text is None:
        feedback.feedback_text = ""
    return feedback


def _check_feedback_permission(feedback: QCFeedback, current_user: User, db: Session):
    role_name = get_user_role(current_user.id, db)
    if role_name != "admin" and feedback.dept_id != current_user.dept_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No permission to access this feedback",
        )
    return role_name


def _mark_feedback_viewed(feedback: QCFeedback):
    feedback.is_viewed = True
    feedback.view_count = (feedback.view_count or 0) + 1
    feedback.viewed_at = datetime.now()
    feedback.updated_at = datetime.now()


def _visible_feedback_filter():
    return or_(QCFeedback.id.is_(None), QCFeedback.status != "deleted")


def _soft_delete_feedback_case(log: PushLog, current_user: User, db: Session) -> tuple[QCFeedback, bool]:
    role_name = get_user_role(current_user.id, db)
    feedback = (
        db.query(QCFeedback)
        .filter(QCFeedback.push_log_id == log.id)
        .order_by(QCFeedback.id.desc())
        .first()
    )

    if feedback:
        _check_feedback_permission(feedback, current_user, db)
    else:
        dept_ref = _resolve_department_by_name(db, log.dept)
        if role_name != "admin":
            dept_id = _resolve_confirm_dept_id(role_name, current_user.dept_id, dept_ref, feedback)
        else:
            fallback_dept = db.query(Department).order_by(Department.id.asc()).first()
            dept_id = dept_ref.id if dept_ref else (current_user.dept_id or (fallback_dept.id if fallback_dept else None))
            if not dept_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department mapping not found for this case")
        feedback = QCFeedback(
            push_log_id=log.id,
            dept_id=dept_id,
            severity=log.severity or "medium",
            status="pending",
            assigned_to=None,
            feedback_text="",
            is_viewed=False,
            view_count=0,
            rectification_clicked=False,
            suppress_ai_push=False,
            rectification_text="",
            rectification_date=None,
            created_by=current_user.id,
        )
        db.add(feedback)
        db.flush()

    old_status = feedback.status or ""
    changed = old_status != "deleted"
    if changed:
        db.add(
            QCFeedbackHistory(
                feedback_id=feedback.id,
                old_status=old_status,
                new_status="deleted",
                changed_by=current_user.id,
                change_reason="Case removed from feedback center",
            )
        )
        feedback.status = "deleted"
        feedback.updated_at = datetime.now()
    return feedback, changed


def _parse_focus_items(raw_text: str) -> list[str]:
    if not raw_text:
        return []
    try:
        value = json.loads(raw_text)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
    except Exception:
        pass
    return []


def _build_case_item(
    log: PushLog,
    conclusion: Optional[AuditConclusion],
    feedback: Optional[QCFeedback],
    dept_name: str,
    dept_id: Optional[int],
    issue_count: int,
    patient_snapshot: Optional[dict] = None,
    registry: Optional[AuditTypeRegistry] = None,
) -> QCFeedbackCaseItem:
    snapshot = patient_snapshot or {}
    registry = registry or AuditTypeRegistry()
    audit_type = registry.get_or_default(getattr(log, "audit_type_code", "") or "")
    severity = (getattr(conclusion, "severity", "") or log.severity or "")
    alert_level = (getattr(conclusion, "alert_level", "") or log.alert_level or "")
    closure_hours = getattr(conclusion, "closure_hours", 0) or 0
    push_strategy = getattr(conclusion, "push_strategy", "") or ""
    outcome_bucket = getattr(conclusion, "outcome_bucket", "") or ""
    overall_conclusion = getattr(conclusion, "overall_conclusion", "") or ""
    overall_qc_summary = getattr(conclusion, "overall_qc_summary", "") or ""
    focus_items = _parse_focus_items(getattr(conclusion, "focus_items", "") or "")
    feedback_status = feedback.status if feedback else "pending"
    feedback_text = feedback.feedback_text if feedback else ""
    reviewed_by = getattr(log, "reviewed_by", "") or ""
    reviewed_at = getattr(log, "reviewed_at", None)
    push_time = getattr(log, "push_time", None)
    push_time_text = push_time.strftime("%Y-%m-%d %H:%M:%S") if hasattr(push_time, "strftime") else str(push_time or "")

    return QCFeedbackCaseItem(
        log_id=log.id,
        feedback_id=feedback.id if feedback else None,
        dept_id=dept_id,
        dept_name=snapshot.get("dept_name", "") or dept_name,
        audit_type_code=(getattr(log, "audit_type_code", "") or audit_type.code),
        audit_type_name=audit_type.name,
        patient_id=snapshot.get("patient_id", "") or log.patient_id,
        patient_name=snapshot.get("patient_name", "") or log.patient_name or "",
        admission_no=snapshot.get("admission_no", "") or getattr(log, "admission_no", "") or "",
        query_date=push_time_text,
        push_time=push_time,
        severity=severity,
        risk_score=getattr(conclusion, "risk_score", 0) or log.risk_score or 0,
        overall_conclusion=overall_conclusion,
        overall_qc_summary=overall_qc_summary,
        alert_level=alert_level,
        closure_hours=closure_hours,
        push_strategy=push_strategy,
        outcome_bucket=outcome_bucket,
        issue_count=issue_count,
        focus_items=focus_items,
        feedback_status=feedback_status,
        feedback_text=feedback_text,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
        admission_date=snapshot.get("admission_date", ""),
        discharge_date=snapshot.get("discharge_date", ""),
        admission_diagnosis=snapshot.get("admission_diagnosis", ""),
        is_discharged=snapshot.get("is_discharged", ""),
        admission_dept_name=snapshot.get("admission_dept_name", ""),
        discharge_dept_name=snapshot.get("discharge_dept_name", ""),
        discharge_main_diagnosis=snapshot.get("discharge_main_diagnosis", ""),
        surgery=snapshot.get("surgery", ""),
        id_card=snapshot.get("id_card", ""),
        address=snapshot.get("address", ""),
        phone=snapshot.get("phone", ""),
    )


def _build_dimension_items(dimensions: list[AuditDimensionResult]) -> list[AuditDimensionItem]:
    items: list[AuditDimensionItem] = []
    for d in dimensions:
        medical_evidence = _safe_json_loads(getattr(d, "medical_evidence_json", "") or "[]", [])
        nursing_evidence = _safe_json_loads(getattr(d, "nursing_evidence_json", "") or "[]", [])
        extra_json = getattr(d, "extra_json", "") or "{}"
        extra = _safe_json_loads(extra_json, {})
        items.append(
            AuditDimensionItem(
                dimension=d.dimension,
                dimension_code=d.dimension_code or "",
                status=d.status or "",
                severity=d.severity or "",
                confidence=d.confidence or 0,
                medical_content=d.medical_content or "",
                nursing_content=d.nursing_content or "",
                explanation=(d.issue_summary or d.explanation or ""),
                issue_summary=d.issue_summary or "",
                recommendation=d.recommendation or "",
                alert_level=d.alert_level or "",
                closure_hours=d.closure_hours or 0,
                push_strategy=d.push_strategy or "",
                outcome_bucket=d.outcome_bucket or "",
                extra_json=extra_json,
                medical_evidence=medical_evidence if isinstance(medical_evidence, list) else [],
                nursing_evidence=nursing_evidence if isinstance(nursing_evidence, list) else [],
                extra=extra if isinstance(extra, dict) else {},
            )
        )
    return items


def _resolve_department_by_name(db: Session, dept_name: Optional[str]) -> Optional[Department]:
    normalized = str(dept_name or "").strip()
    if not normalized:
        return None

    dept = db.query(Department).filter(Department.name == normalized).first()
    if dept:
        return dept

    compact = "".join(normalized.split())
    if not compact:
        return None

    departments = db.query(Department).all()
    for item in departments:
        candidate = str(item.name or "").strip()
        if not candidate:
            continue
        if candidate == normalized or "".join(candidate.split()) == compact:
            return item
    return None


def _resolve_confirm_dept_id(
    role_name: str,
    current_user_dept_id: Optional[int],
    dept_ref: Optional[Department],
    feedback: Optional[QCFeedback] = None,
) -> int:
    if role_name != "admin":
        if not current_user_dept_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to confirm this case")
        if not dept_ref:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to confirm this case")
        if dept_ref.id != current_user_dept_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to confirm this case")
        return current_user_dept_id

    if dept_ref:
        return dept_ref.id
    if feedback and feedback.dept_id:
        return feedback.dept_id
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Department mapping not found for this case")


@router.get("/cases", response_model=QCFeedbackCaseListResponse, tags=["质控反馈"])
def list_feedback_cases(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=1000),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    dept_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_name = get_user_role(current_user.id, db)
    registry = AuditTypeRegistry()

    departments = db.query(Department).all()
    dept_by_name = {str(d.name or "").strip(): d for d in departments if str(d.name or "").strip()}
    current_dept_name = None
    if current_user.dept_id:
        current_dept = db.query(Department).filter(Department.id == current_user.dept_id).first()
        current_dept_name = current_dept.name if current_dept else None

    issue_count_subquery = (
        db.query(
            AuditDimensionResult.push_log_id.label("log_id"),
            func.count(AuditDimensionResult.id).label("issue_count"),
        )
        .group_by(AuditDimensionResult.push_log_id)
        .subquery()
    )

    latest_feedback_subquery = (
        db.query(
            QCFeedback.push_log_id.label("log_id"),
            func.max(QCFeedback.id).label("feedback_id"),
        )
        .group_by(QCFeedback.push_log_id)
        .subquery()
    )

    query = (
        db.query(
            PushLog,
            AuditConclusion,
            QCFeedback,
            issue_count_subquery.c.issue_count,
        )
        .outerjoin(AuditConclusion, AuditConclusion.push_log_id == PushLog.id)
        .outerjoin(latest_feedback_subquery, latest_feedback_subquery.c.log_id == PushLog.id)
        .outerjoin(QCFeedback, QCFeedback.id == latest_feedback_subquery.c.feedback_id)
        .outerjoin(issue_count_subquery, issue_count_subquery.c.log_id == PushLog.id)
        # 需求变更：质控反馈列表展示所有“推送成功”患者，不再只展示不一致病例
        .filter(PushLog.status == "success")
        .filter(PushLog.push_time >= datetime.now() - timedelta(days=days))
    )
    query = query.filter(_visible_feedback_filter())

    if role_name != "admin":
        dept_filters = [QCFeedback.dept_id == current_user.dept_id]
        if current_dept_name:
            dept_filters.append(and_(QCFeedback.id.is_(None), PushLog.dept == current_dept_name))
        query = query.filter(or_(*dept_filters))
    elif dept_id:
        dept_obj = db.query(Department).filter(Department.id == dept_id).first()
        dept_name = dept_obj.name if dept_obj else None
        query = query.filter(
            or_(
                QCFeedback.dept_id == dept_id,
                and_(QCFeedback.id.is_(None), PushLog.dept == dept_name),
            )
        )

    if status:
        if status == "pending":
            query = query.filter(or_(QCFeedback.id.is_(None), QCFeedback.status == "pending"))
        else:
            query = query.filter(QCFeedback.status == status)

    if severity:
        query = query.filter(or_(AuditConclusion.severity == severity, PushLog.severity == severity))

    if audit_type_code:
        audit_code = audit_type_code.strip()
        if audit_code == "progress_vs_nursing":
            query = query.filter(
                or_(
                    PushLog.audit_type_code == audit_code,
                    PushLog.audit_type_code.is_(None),
                    PushLog.audit_type_code == "",
                )
            )
        elif audit_code:
            query = query.filter(PushLog.audit_type_code == audit_code)

    if keyword:
        kw = keyword.strip()
        if kw:
            like_pattern = f"%{kw}%"
            query = query.filter(
                or_(
                    PushLog.patient_id.like(like_pattern),
                    PushLog.patient_name.like(like_pattern),
                    PushLog.admission_no.like(like_pattern),
                )
            )

    stats_row = query.with_entities(
        func.count(PushLog.id).label("total"),
        func.sum(
            case(
                (
                    or_(
                        AuditConclusion.severity == "high",
                        and_(
                            or_(AuditConclusion.severity.is_(None), AuditConclusion.severity == ""),
                            PushLog.severity == "high",
                        ),
                    ),
                    1,
                ),
                else_=0,
            )
        ).label("high"),
        func.sum(case((or_(QCFeedback.id.is_(None), QCFeedback.status == "pending"), 1), else_=0)).label("pending"),
        func.sum(case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
        func.sum(case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
        func.sum(case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
    ).one()

    total = stats_row.total or 0
    rows = (
        query.order_by(PushLog.push_time.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = []
    for log, conclusion, feedback, issue_count in rows:
        dept_ref = None
        if feedback and feedback.dept_id:
            dept_ref = db.query(Department).filter(Department.id == feedback.dept_id).first()
        elif log.dept:
            dept_ref = dept_by_name.get(str(log.dept).strip()) or _resolve_department_by_name(db, log.dept)
        resolved_dept_id = dept_ref.id if dept_ref else (feedback.dept_id if feedback else None)
        resolved_dept_name = dept_ref.name if dept_ref else (log.dept or "")
        snapshot = extract_patient_snapshot(log)
        item = _build_case_item(
            log=log,
            conclusion=conclusion,
            feedback=feedback,
            dept_name=resolved_dept_name,
            dept_id=resolved_dept_id,
            issue_count=issue_count or 0,
            patient_snapshot=snapshot,
            registry=registry,
        )
        items.append(item)

    stats = {
        "total": total,
        "high": stats_row.high or 0,
        "pending": stats_row.pending or 0,
        "acknowledged": stats_row.acknowledged or 0,
        "rectified": stats_row.rectified or 0,
        "closed": stats_row.closed or 0,
    }

    return QCFeedbackCaseListResponse(
        total=total,
        page=page,
        limit=limit,
        items=items,
        stats=stats,
    )


@router.get("/cases/{log_id}", response_model=QCFeedbackCaseDetail, tags=["质控反馈"])
def get_feedback_case_detail(
    log_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    role_name = get_user_role(current_user.id, db)
    registry = AuditTypeRegistry()
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    latest_feedback = (
        db.query(QCFeedback)
        .filter(QCFeedback.push_log_id == log_id)
        .order_by(QCFeedback.id.desc())
        .first()
    )

    dept_ref = None
    if latest_feedback and latest_feedback.dept_id:
        dept_ref = db.query(Department).filter(Department.id == latest_feedback.dept_id).first()
    elif log.dept:
        dept_ref = _resolve_department_by_name(db, log.dept)

    resolved_dept_id = dept_ref.id if dept_ref else (latest_feedback.dept_id if latest_feedback else None)
    resolved_dept_name = dept_ref.name if dept_ref else (log.dept or "")

    if latest_feedback and latest_feedback.status == "deleted":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    if role_name != "admin" and resolved_dept_id != current_user.dept_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to access this case")

    conclusion = db.query(AuditConclusion).filter(AuditConclusion.push_log_id == log_id).first()
    dimensions = (
        db.query(AuditDimensionResult)
        .filter(AuditDimensionResult.push_log_id == log_id)
        .order_by(AuditDimensionResult.id.asc())
        .all()
    )
    issue_count = len(dimensions)

    base_item = _build_case_item(
        log=log,
        conclusion=conclusion,
        feedback=latest_feedback,
        dept_name=resolved_dept_name,
        dept_id=resolved_dept_id,
        issue_count=issue_count,
        patient_snapshot=extract_patient_snapshot(log),
        registry=registry,
    )
    raw_sections = extract_raw_record_sections(log)

    dimension_items = _build_dimension_items(dimensions)

    feedback_detail = None
    if latest_feedback:
        latest_feedback = _normalize_feedback_nullable_fields(latest_feedback)
        history = (
            db.query(QCFeedbackHistory)
            .filter(QCFeedbackHistory.feedback_id == latest_feedback.id)
            .order_by(QCFeedbackHistory.changed_at.desc())
            .all()
        )
        feedback_detail = QCFeedbackDetail.from_orm(latest_feedback)
        feedback_detail.history = [item for item in history]

    return QCFeedbackCaseDetail(
        **base_item.model_dump(),
        dimensions=dimension_items,
        feedback=feedback_detail,
        mr_text=_safe_mr_text(log.mr_text),
        medical_documents_text=raw_sections.get("medical_documents_text", ""),
        nursing_records_text=raw_sections.get("nursing_records_text", ""),
    )


@router.delete("/cases/bulk", response_model=MessageResponse, tags=["质控反馈"])
def delete_feedback_cases_bulk(
    request: QCFeedbackBulkDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量从质控反馈中心移除病例；保留原始推送日志和审计结果。"""
    log_ids = list(dict.fromkeys(int(item) for item in request.log_ids if int(item) > 0))
    if not log_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="log_ids is required")

    logs = db.query(PushLog).filter(PushLog.id.in_(log_ids)).all()
    logs_by_id = {item.id: item for item in logs}
    deleted_count = 0
    missing_ids = []
    for log_id in log_ids:
        log = logs_by_id.get(log_id)
        if not log:
            missing_ids.append(log_id)
            continue
        _, changed = _soft_delete_feedback_case(log, current_user, db)
        if changed:
            deleted_count += 1
    db.commit()

    return MessageResponse(
        message="Cases deleted successfully",
        success=True,
        data={"requested": len(log_ids), "deleted": deleted_count, "missing_ids": missing_ids},
    )


@router.delete("/cases/{log_id}", response_model=MessageResponse, tags=["质控反馈"])
def delete_feedback_case(
    log_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从质控反馈中心移除病例；保留原始推送日志和审计结果。"""
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    _soft_delete_feedback_case(log, current_user, db)
    db.commit()

    return MessageResponse(message="Case deleted successfully", success=True, data={"log_id": log_id})


@router.post("/cases/{log_id}/confirm", response_model=MessageResponse, tags=["质控反馈"])
def confirm_feedback_case(
    log_id: int,
    request: QCFeedbackConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log = db.query(PushLog).filter(PushLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    role_name = get_user_role(current_user.id, db)

    feedback = (
        db.query(QCFeedback)
        .filter(QCFeedback.push_log_id == log_id)
        .order_by(QCFeedback.id.desc())
        .first()
    )

    if not feedback:
        dept_ref = _resolve_department_by_name(db, log.dept)
        dept_id = _resolve_confirm_dept_id(role_name, current_user.dept_id, dept_ref, feedback)

        feedback = QCFeedback(
            push_log_id=log.id,
            dept_id=dept_id,
            severity=log.severity or "medium",
            status=request.action,
            assigned_to=None,
            feedback_text=request.review_comment or "",
            is_viewed=True,
            viewed_at=datetime.now(),
            view_count=1,
            rectification_clicked=False,
            suppress_ai_push=(request.action == "acknowledged"),
            rectification_text="",
            rectification_date=None,
            created_by=current_user.id,
        )
        db.add(feedback)
        db.commit()
        db.refresh(feedback)
    else:
        _check_feedback_permission(feedback, current_user, db)
        old_status = feedback.status
        feedback.status = request.action
        feedback.feedback_text = request.review_comment or feedback.feedback_text
        feedback.suppress_ai_push = request.action == "acknowledged"
        feedback.is_viewed = True
        feedback.viewed_at = datetime.now()
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = datetime.now()

        if old_status != request.action:
            history = QCFeedbackHistory(
                feedback_id=feedback.id,
                old_status=old_status,
                new_status=request.action,
                changed_by=current_user.id,
                change_reason="Case confirmed",
            )
            db.add(history)

        db.commit()
        db.refresh(feedback)

    return MessageResponse(
        message="Case confirmed successfully",
        success=True,
        data={
            "log_id": log_id,
            "feedback_id": feedback.id,
            "status": feedback.status,
        },
    )


@router.get("", response_model=QCFeedbackListResponse, tags=["质控反馈"])
def list_feedback(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=1000),
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    dept_id: Optional[int] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取质控反馈列表
    
    - 普通用户只能看自己科室的反馈
    - 科室主任可以看本科室所有反馈
    - 管理员可以看全部反馈
    """
    role_name = get_user_role(current_user.id, db)
    
    # 构建查询
    query = db.query(QCFeedback).filter(QCFeedback.status != "deleted")
    
    # 权限过滤：非管理员只能看自己科室
    if role_name != "admin":
        query = query.filter(QCFeedback.dept_id == current_user.dept_id)
    
    # 状态过滤
    if status:
        query = query.filter(QCFeedback.status == status)
    
    # 严重程度过滤
    if severity:
        query = query.filter(QCFeedback.severity == severity)
    
    # 科室过滤（仅管理员可用）
    if dept_id and role_name == "admin":
        query = query.filter(QCFeedback.dept_id == dept_id)
    
    # 查询总数
    total = query.count()
    
    # 分页查询
    feedbacks = query.order_by(QCFeedback.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
    
    items = [QCFeedbackItem.from_orm(_normalize_feedback_nullable_fields(fb)) for fb in feedbacks]
    
    # 统计信息 —— 单次聚合查询替代 11 次 COUNT
    stats_query = db.query(
        func.count(QCFeedback.id).label("total"),
        func.sum(case((QCFeedback.severity == "high", 1), else_=0)).label("high"),
        func.sum(case((QCFeedback.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(case((QCFeedback.severity == "low", 1), else_=0)).label("low"),
        func.sum(case((QCFeedback.is_viewed.is_(True), 1), else_=0)).label("viewed"),
        func.sum(case((QCFeedback.rectification_clicked.is_(True), 1), else_=0)).label("rectification_clicked"),
        func.sum(case((QCFeedback.suppress_ai_push.is_(True), 1), else_=0)).label("suppressed"),
        func.sum(case((QCFeedback.status == "pending", 1), else_=0)).label("pending"),
        func.sum(case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
        func.sum(case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
        func.sum(case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
    )
    if role_name != "admin":
        stats_query = stats_query.filter(QCFeedback.dept_id == current_user.dept_id)
    
    row = stats_query.one()
    stats = QCFeedbackStats(
        total=row.total or 0,
        high=row.high or 0,
        medium=row.medium or 0,
        low=row.low or 0,
        viewed=row.viewed or 0,
        rectification_clicked=row.rectification_clicked or 0,
        suppressed=row.suppressed or 0,
        pending=row.pending or 0,
        acknowledged=row.acknowledged or 0,
        rectified=row.rectified or 0,
        closed=row.closed or 0,
    )
    
    return QCFeedbackListResponse(
        total=total,
        page=page,
        limit=limit,
        items=items,
        stats=stats.model_dump(),
    )


# ---- 静态路径路由必须在 /{feedback_id} 之前定义，否则会被路径参数截获 ----

@router.get("/stats/summary", response_model=QCFeedbackStats, tags=["质控反馈"])
def get_feedback_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取反馈统计信息
    """
    role_name = get_user_role(current_user.id, db)
    
    query = db.query(
        func.count(QCFeedback.id).label("total"),
        func.sum(case((QCFeedback.severity == "high", 1), else_=0)).label("high"),
        func.sum(case((QCFeedback.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(case((QCFeedback.severity == "low", 1), else_=0)).label("low"),
        func.sum(case((QCFeedback.is_viewed.is_(True), 1), else_=0)).label("viewed"),
        func.sum(case((QCFeedback.rectification_clicked.is_(True), 1), else_=0)).label("rectification_clicked"),
        func.sum(case((QCFeedback.suppress_ai_push.is_(True), 1), else_=0)).label("suppressed"),
        func.sum(case((QCFeedback.status == "pending", 1), else_=0)).label("pending"),
        func.sum(case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
        func.sum(case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
        func.sum(case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
    )
    
    # 权限过滤
    if role_name != "admin":
        query = query.filter(QCFeedback.dept_id == current_user.dept_id)
    
    row = query.one()
    stats = QCFeedbackStats(
        total=row.total or 0,
        high=row.high or 0,
        medium=row.medium or 0,
        low=row.low or 0,
        viewed=row.viewed or 0,
        rectification_clicked=row.rectification_clicked or 0,
        suppressed=row.suppressed or 0,
        pending=row.pending or 0,
        acknowledged=row.acknowledged or 0,
        rectified=row.rectified or 0,
        closed=row.closed or 0,
    )
    
    return stats


@router.get("/stats/dashboard", tags=["质控反馈"])
def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取仪表板统计（综合所有数据）
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    
    # 确定科室过滤
    dept_id = None
    if role_name != "admin":
        dept_id = current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return stats_service.get_dashboard_stats(dept_id)


@router.get("/stats/severity", tags=["质控反馈"])
def get_severity_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取按严重程度的统计
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return {"severity_distribution": stats_service.get_severity_distribution(dept_id)}


@router.get("/stats/status", tags=["质控反馈"])
def get_status_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取按状态的统计
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return {"status_distribution": stats_service.get_status_distribution(dept_id)}


@router.get("/stats/trend", tags=["质控反馈"])
def get_trend_stats(
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取趋势统计
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return {"daily_trend": stats_service.get_daily_trend(days, dept_id)}


@router.get("/stats/rectification-rate", tags=["质控反馈"])
def get_rectification_rate(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取整改率
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return stats_service.get_rectification_rate(dept_id)


@router.get("/stats/top-issues", tags=["质控反馈"])
def get_top_issues(
    limit: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取高频问题
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return {"top_issues": stats_service.get_top_issues(limit, dept_id)}


@router.get("/stats/user-workload", tags=["质控反馈"])
def get_user_workload(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取用户工作量
    """
    from app.services.feedback_stats import FeedbackStatsService
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    stats_service = FeedbackStatsService(db)
    return {"user_workload": stats_service.get_user_workload(dept_id)}


@router.get("/export/csv", tags=["质控反馈"])
def export_feedback_csv(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    dept_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    导出反馈为 CSV 格式
    """
    from app.services.export_service import FeedbackExportService
    from fastapi.responses import StreamingResponse
    
    role_name = get_user_role(current_user.id, db)
    
    export_service = FeedbackExportService(db)
    csv_data = export_service.export_to_csv(
        role_name=role_name,
        current_user_dept_id=current_user.dept_id,
        status=status,
        severity=severity,
        audit_type_code=audit_type_code,
        dept_id=dept_id if role_name == "admin" else None,
        days=days,
        keyword=keyword,
    )

    # 记录导出审计日志
    try:
        record_export_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username or "",
            export_type="qc_feedback",
            export_format="csv",
            filter_criteria={
                "status": status,
                "severity": severity,
                "audit_type_code": audit_type_code,
                "dept_id": dept_id if role_name == "admin" else current_user.dept_id,
                "days": days,
                "keyword": keyword,
            },
            record_count=getattr(export_service, "last_export_count", 0),
            status="success",
            request=request,
        )
    except Exception as exc:
        logger.error("导出审计日志记录失败: %s", exc, exc_info=True)
    
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )


@router.get("/export/excel", tags=["质控反馈"])
def export_feedback_excel(
    status: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    dept_id: Optional[int] = Query(None),
    days: int = Query(30, ge=1, le=365),
    keyword: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    request: Request = None,
):
    """
    导出反馈为 Excel 格式
    """
    from app.services.export_service import FeedbackExportService
    from fastapi.responses import StreamingResponse
    
    role_name = get_user_role(current_user.id, db)
    audit_code = (audit_type_code or "").strip()
    if not audit_code:
        error_msg = "audit_type_code is required for Excel export"
        try:
            record_export_audit(
                db=db,
                user_id=current_user.id,
                username=current_user.username or "",
                export_type="qc_feedback",
                export_format="excel",
                filter_criteria={
                    "status": status,
                    "severity": severity,
                    "audit_type_code": audit_type_code,
                    "dept_id": dept_id if role_name == "admin" else current_user.dept_id,
                    "days": days,
                    "keyword": keyword,
                },
                record_count=0,
                status="failed",
                error_msg=error_msg,
                request=request,
            )
        except Exception as audit_exc:
            logger.error("导出审计日志记录失败: %s", audit_exc, exc_info=True)
        raise HTTPException(status_code=400, detail=error_msg)
    
    export_service = FeedbackExportService(db)
    try:
        export_data, export_format = export_service.export_to_excel(
            role_name=role_name,
            current_user_dept_id=current_user.dept_id,
            status=status,
            severity=severity,
            audit_type_code=audit_code,
            dept_id=dept_id if role_name == "admin" else None,
            days=days,
            keyword=keyword,
        )
    except RuntimeError as exc:
        # 记录失败审计日志
        try:
            record_export_audit(
                db=db,
                user_id=current_user.id,
                username=current_user.username or "",
                export_type="qc_feedback",
                export_format="excel",
                filter_criteria={
                    "status": status,
                    "severity": severity,
                    "audit_type_code": audit_code,
                    "dept_id": dept_id if role_name == "admin" else current_user.dept_id,
                    "days": days,
                    "keyword": keyword,
                },
                record_count=0,
                status="failed",
                error_msg=str(exc),
                request=request,
            )
        except Exception as audit_exc:
            logger.error("导出审计日志记录失败: %s", audit_exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # 记录成功审计日志
    try:
        record_export_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username or "",
            export_type="qc_feedback",
            export_format=export_format,
            filter_criteria={
                "status": status,
                "severity": severity,
                "audit_type_code": audit_code,
                "dept_id": dept_id if role_name == "admin" else current_user.dept_id,
                "days": days,
                "keyword": keyword,
            },
            record_count=getattr(export_service, "last_export_count", 0),
            status="success",
            request=request,
        )
    except Exception as exc:
        logger.error("导出审计日志记录失败: %s", exc, exc_info=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    if export_format == "csv":
        return StreamingResponse(
            iter([export_data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=feedback_{timestamp}.csv"}
        )
    return StreamingResponse(
        iter([export_data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=feedback_{timestamp}.xlsx"}
    )


# ---- 路径参数路由在静态路由之后 ----

@router.get("/{feedback_id}", response_model=QCFeedbackDetail, tags=["质控反馈"])
def get_feedback_detail(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取反馈详情（包含历史记录）
    """
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    
    # 权限检查
    _check_feedback_permission(feedback, current_user, db)

    _mark_feedback_viewed(feedback)
    db.commit()
    db.refresh(feedback)
    
    # 获取历史记录
    history = db.query(QCFeedbackHistory).filter(
        QCFeedbackHistory.feedback_id == feedback_id
    ).order_by(QCFeedbackHistory.changed_at.desc()).all()
    
    feedback = _normalize_feedback_nullable_fields(feedback)
    detail = QCFeedbackDetail.from_orm(feedback)
    detail.history = [h for h in history]
    
    return detail


@router.post("", response_model=QCFeedbackItem, tags=["质控反馈"])
def create_feedback(
    request: QCFeedbackCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    创建质控反馈
    
    通常由审计员或质控人员创建
    """
    # 检查推送日志是否存在
    push_log = db.query(PushLog).filter(PushLog.id == request.push_log_id).first()
    if not push_log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Push log not found",
        )
    
    # 创建反馈
    feedback = QCFeedback(
        push_log_id=request.push_log_id,
        dept_id=request.dept_id,
        severity=request.severity,
        status="pending",
        feedback_text=request.feedback_text,
        assigned_to=request.assigned_to,
        suppress_ai_push=False,
        created_by=current_user.id,
    )
    
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    
    return QCFeedbackItem.from_orm(feedback)


@router.put("/{feedback_id}", response_model=QCFeedbackItem, tags=["质控反馈"])
def update_feedback(
    feedback_id: int,
    request: QCFeedbackUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新反馈状态或分配
    """
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    
    # 权限检查
    _check_feedback_permission(feedback, current_user, db)
    
    # 状态转换校验
    VALID_TRANSITIONS = {
        "pending": {"acknowledged", "closed"},
        "acknowledged": {"rectified", "closed"},
        "rectified": {"closed"},
        "closed": set(),  # 终态，不可继续流转
    }
    
    if request.status and request.status != feedback.status:
        allowed = VALID_TRANSITIONS.get(feedback.status, set())
        if request.status not in allowed:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state transition: {feedback.status} → {request.status}. "
                       f"Allowed: {', '.join(sorted(allowed)) if allowed else 'none (terminal state)'}",
            )
    
    # 记录状态变更历史
    if request.status and request.status != feedback.status:
        history = QCFeedbackHistory(
            feedback_id=feedback_id,
            old_status=feedback.status,
            new_status=request.status,
            changed_by=current_user.id,
            change_reason="Status updated",
        )
        db.add(history)
    
    # 更新字段
    if request.status is not None:
        feedback.status = request.status
        if request.status != "rectified":
            feedback.suppress_ai_push = False
    if request.assigned_to is not None:
        feedback.assigned_to = request.assigned_to
    if request.feedback_text is not None:
        feedback.feedback_text = request.feedback_text
    
    feedback.updated_at = datetime.now()
    
    db.commit()
    db.refresh(feedback)
    
    return QCFeedbackItem.from_orm(feedback)


@router.post("/{feedback_id}/rectify", response_model=QCFeedbackItem, tags=["质控反馈"])
def submit_rectification(
    feedback_id: int,
    request: QCFeedbackRectifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    提交整改说明
    
    将反馈状态从 pending/acknowledged 改为 rectified
    """
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    
    # 权限检查：只有分配给的人或科室主任可以提交整改
    _check_feedback_permission(feedback, current_user, db)
    
    # 记录状态变更
    old_status = feedback.status
    history = QCFeedbackHistory(
        feedback_id=feedback_id,
        old_status=old_status,
        new_status="rectified",
        changed_by=current_user.id,
        change_reason="Rectification submitted",
    )
    db.add(history)
    
    # 更新反馈
    feedback.status = "rectified"
    feedback.suppress_ai_push = True
    feedback.rectification_text = request.rectification_text
    feedback.rectification_date = datetime.now()
    feedback.updated_at = datetime.now()
    
    db.commit()
    db.refresh(feedback)
    
    return QCFeedbackItem.from_orm(feedback)


@router.post("/{feedback_id}/mark-viewed", response_model=QCFeedbackItem, tags=["质控反馈"])
def mark_feedback_viewed(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    _check_feedback_permission(feedback, current_user, db)
    _mark_feedback_viewed(feedback)
    db.commit()
    db.refresh(feedback)
    return QCFeedbackItem.from_orm(feedback)


@router.post("/{feedback_id}/mark-rectify-clicked", response_model=QCFeedbackItem, tags=["质控反馈"])
def mark_rectify_clicked(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    if not feedback:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

    _check_feedback_permission(feedback, current_user, db)
    feedback.rectification_clicked = True
    feedback.rectification_clicked_at = datetime.now()
    feedback.updated_at = datetime.now()
    db.commit()
    db.refresh(feedback)
    return QCFeedbackItem.from_orm(feedback)


@router.get("/{feedback_id}/history", tags=["质控反馈"])
def get_feedback_history(
    feedback_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取反馈的状态变更历史
    """
    feedback = db.query(QCFeedback).filter(QCFeedback.id == feedback_id).first()
    
    if not feedback:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feedback not found",
        )
    
    # 权限检查
    _check_feedback_permission(feedback, current_user, db)
    
    history = db.query(QCFeedbackHistory).filter(
        QCFeedbackHistory.feedback_id == feedback_id
    ).order_by(QCFeedbackHistory.changed_at.desc()).all()
    
    return {
        "feedback_id": feedback_id,
        "history": history,
    }
