"""
导出审计日志路由 —— /api/audit/logs
记录和查询数据导出行为
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.database import get_db
from app.models import ExportAuditLog, User, Role
from app.schemas import ExportAuditLogListResponse, ExportAuditLogItem, MessageResponse
from app.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_admin(current_user: User, db: Session):
    """检查当前用户是否为管理员"""
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if not role or role.name != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")


@router.get("/logs", response_model=ExportAuditLogListResponse, summary="查询导出审计日志")
def list_export_audit_logs(
    page: int = Query(1, ge=1, description="页码"),
    limit: int = Query(20, ge=1, le=200, description="每页条数"),
    export_type: Optional[str] = Query(None, description="导出类型: push_log | qc_feedback"),
    export_format: Optional[str] = Query(None, description="导出格式: csv | excel"),
    status: Optional[str] = Query(None, description="状态: success | failed"),
    user_id: Optional[int] = Query(None, description="用户ID"),
    date_from: Optional[str] = Query(None, description="开始日期 yyyy-mm-dd"),
    date_to: Optional[str] = Query(None, description="结束日期 yyyy-mm-dd"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    查询导出审计日志列表

    - 管理员可以查看所有导出记录
    - 普通用户只能查看自己的导出记录
    """
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    is_admin = role and role.name == "admin"

    q = db.query(ExportAuditLog)

    # 权限过滤：非管理员只能看自己
    if not is_admin:
        q = q.filter(ExportAuditLog.user_id == current_user.id)

    if export_type:
        q = q.filter(ExportAuditLog.export_type == export_type)
    if export_format:
        q = q.filter(ExportAuditLog.export_format == export_format)
    if status:
        q = q.filter(ExportAuditLog.status == status)
    if user_id and is_admin:
        q = q.filter(ExportAuditLog.user_id == user_id)
    if date_from:
        try:
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(ExportAuditLog.export_time >= from_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from, expected yyyy-mm-dd")
    if date_to:
        try:
            to_dt = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
            q = q.filter(ExportAuditLog.export_time < to_dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to, expected yyyy-mm-dd")

    total = q.count()
    items = (
        q.order_by(desc(ExportAuditLog.export_time))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return ExportAuditLogListResponse(
        total=total,
        page=page,
        limit=limit,
        items=[ExportAuditLogItem.model_validate(item) for item in items],
    )


@router.get("/logs/stats", summary="导出审计统计")
def get_export_audit_stats(
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取导出审计统计信息（管理员权限）
    """
    _require_admin(current_user, db)

    cutoff = datetime.now() - timedelta(days=days)
    q = db.query(ExportAuditLog).filter(ExportAuditLog.export_time >= cutoff)

    total = q.count()
    success_count = q.filter(ExportAuditLog.status == "success").count()
    failed_count = q.filter(ExportAuditLog.status == "failed").count()

    # 按导出类型统计
    type_stats = (
        db.query(
            ExportAuditLog.export_type,
            func.count(ExportAuditLog.id).label("count"),
        )
        .filter(ExportAuditLog.export_time >= cutoff)
        .group_by(ExportAuditLog.export_type)
        .all()
    )

    # 按导出格式统计
    format_stats = (
        db.query(
            ExportAuditLog.export_format,
            func.count(ExportAuditLog.id).label("count"),
        )
        .filter(ExportAuditLog.export_time >= cutoff)
        .group_by(ExportAuditLog.export_format)
        .all()
    )

    # 按用户统计（Top 10）
    user_stats = (
        db.query(
            ExportAuditLog.user_id,
            ExportAuditLog.username,
            func.count(ExportAuditLog.id).label("count"),
        )
        .filter(ExportAuditLog.export_time >= cutoff)
        .group_by(ExportAuditLog.user_id, ExportAuditLog.username)
        .order_by(desc(func.count(ExportAuditLog.id)))
        .limit(10)
        .all()
    )

    return {
        "period_days": days,
        "total": total,
        "success": success_count,
        "failed": failed_count,
        "by_type": [{"type": t, "count": c} for t, c in type_stats],
        "by_format": [{"format": f, "count": c} for f, c in format_stats],
        "top_users": [{"user_id": uid, "username": uname, "count": c} for uid, uname, c in user_stats],
    }
