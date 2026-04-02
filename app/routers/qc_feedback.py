"""
质控反馈管理 API
支持反馈的 CRUD、状态流转、整改追踪、统计
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional

from app.database import get_db
from app.models import User, Role, QCFeedback, QCFeedbackHistory, Department, PushLog
from app.schemas import (
    QCFeedbackCreateRequest, QCFeedbackUpdateRequest, QCFeedbackRectifyRequest,
    QCFeedbackItem, QCFeedbackDetail, QCFeedbackListResponse, QCFeedbackStats,
    MessageResponse
)
from sqlalchemy import func
from app.auth import get_current_user
from app.permissions import get_user_role

router = APIRouter()


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


@router.get("", response_model=QCFeedbackListResponse, tags=["质控反馈"])
async def list_feedback(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
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
    query = db.query(QCFeedback)
    
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
    
    items = [QCFeedbackItem.from_orm(fb) for fb in feedbacks]
    
    # 统计信息 —— 单次聚合查询替代 11 次 COUNT
    stats_query = db.query(
        func.count(QCFeedback.id).label("total"),
        func.sum(func.case((QCFeedback.severity == "high", 1), else_=0)).label("high"),
        func.sum(func.case((QCFeedback.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(func.case((QCFeedback.severity == "low", 1), else_=0)).label("low"),
        func.sum(func.case((QCFeedback.is_viewed.is_(True), 1), else_=0)).label("viewed"),
        func.sum(func.case((QCFeedback.rectification_clicked.is_(True), 1), else_=0)).label("rectification_clicked"),
        func.sum(func.case((QCFeedback.suppress_ai_push.is_(True), 1), else_=0)).label("suppressed"),
        func.sum(func.case((QCFeedback.status == "pending", 1), else_=0)).label("pending"),
        func.sum(func.case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
        func.sum(func.case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
        func.sum(func.case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
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
        stats=stats.dict(),
    )


# ---- 静态路径路由必须在 /{feedback_id} 之前定义，否则会被路径参数截获 ----

@router.get("/stats/summary", response_model=QCFeedbackStats, tags=["质控反馈"])
async def get_feedback_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取反馈统计信息
    """
    role_name = get_user_role(current_user.id, db)
    
    query = db.query(
        func.count(QCFeedback.id).label("total"),
        func.sum(func.case((QCFeedback.severity == "high", 1), else_=0)).label("high"),
        func.sum(func.case((QCFeedback.severity == "medium", 1), else_=0)).label("medium"),
        func.sum(func.case((QCFeedback.severity == "low", 1), else_=0)).label("low"),
        func.sum(func.case((QCFeedback.is_viewed.is_(True), 1), else_=0)).label("viewed"),
        func.sum(func.case((QCFeedback.rectification_clicked.is_(True), 1), else_=0)).label("rectification_clicked"),
        func.sum(func.case((QCFeedback.suppress_ai_push.is_(True), 1), else_=0)).label("suppressed"),
        func.sum(func.case((QCFeedback.status == "pending", 1), else_=0)).label("pending"),
        func.sum(func.case((QCFeedback.status == "acknowledged", 1), else_=0)).label("acknowledged"),
        func.sum(func.case((QCFeedback.status == "rectified", 1), else_=0)).label("rectified"),
        func.sum(func.case((QCFeedback.status == "closed", 1), else_=0)).label("closed"),
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
async def get_dashboard_stats(
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
async def get_severity_stats(
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
async def get_status_stats(
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
async def get_trend_stats(
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
async def get_rectification_rate(
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
async def get_top_issues(
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
async def get_user_workload(
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
async def export_feedback_csv(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    导出反馈为 CSV 格式
    """
    from app.services.export_service import FeedbackExportService
    from fastapi.responses import StreamingResponse
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    export_service = FeedbackExportService(db)
    csv_data = export_service.export_to_csv(dept_id)
    
    return StreamingResponse(
        iter([csv_data]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"}
    )


@router.get("/export/excel", tags=["质控反馈"])
async def export_feedback_excel(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    导出反馈为 Excel 格式
    """
    from app.services.export_service import FeedbackExportService
    from fastapi.responses import StreamingResponse
    
    role_name = get_user_role(current_user.id, db)
    dept_id = None if role_name == "admin" else current_user.dept_id
    
    export_service = FeedbackExportService(db)
    excel_data = export_service.export_to_excel(dept_id)
    
    return StreamingResponse(
        iter([excel_data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"}
    )


# ---- 路径参数路由在静态路由之后 ----

@router.get("/{feedback_id}", response_model=QCFeedbackDetail, tags=["质控反馈"])
async def get_feedback_detail(
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
    
    detail = QCFeedbackDetail.from_orm(feedback)
    detail.history = [h for h in history]
    
    return detail


@router.post("", response_model=QCFeedbackItem, tags=["质控反馈"])
async def create_feedback(
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
async def update_feedback(
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
async def submit_rectification(
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
async def mark_feedback_viewed(
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
async def mark_rectify_clicked(
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
async def get_feedback_history(
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
