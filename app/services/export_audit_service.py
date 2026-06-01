"""
导出审计日志服务 —— 记录数据导出行为
"""
import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import ExportAuditLog

logger = logging.getLogger(__name__)


def record_export_audit(
    db: Session,
    user_id: int,
    username: str,
    export_type: str,
    export_format: str,
    filter_criteria: dict,
    record_count: int,
    status: str = "success",
    error_msg: str = "",
    request: Optional[Request] = None,
) -> ExportAuditLog:
    """记录导出审计日志

    Args:
        db: 数据库会话
        user_id: 用户ID
        username: 用户名
        export_type: 导出类型 (push_log | qc_feedback)
        export_format: 导出格式 (csv | excel)
        filter_criteria: 筛选条件字典
        record_count: 导出的记录数
        status: 导出状态 (success | failed)
        error_msg: 错误信息
        request: FastAPI 请求对象，用于获取 IP 和 User-Agent

    Returns:
        创建的 ExportAuditLog 记录
    """
    ip_address = ""
    user_agent = ""
    if request is not None:
        try:
            # 尝试从请求头获取真实 IP（考虑反向代理）
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                ip_address = forwarded.split(",")[0].strip()
            else:
                real_ip = request.headers.get("x-real-ip")
                if real_ip:
                    ip_address = real_ip.strip()
                elif hasattr(request.client, "host"):
                    ip_address = str(request.client.host or "")
            user_agent = request.headers.get("user-agent", "")
        except Exception as exc:
            logger.warning("获取请求信息失败: %s", exc)

    audit_log = ExportAuditLog(
        export_time=datetime.now(),
        user_id=user_id,
        username=username or "",
        export_type=export_type,
        export_format=export_format,
        filter_criteria=json.dumps(filter_criteria, ensure_ascii=False, default=str) if filter_criteria else "",
        record_count=record_count,
        ip_address=ip_address,
        user_agent=user_agent,
        status=status,
        error_msg=error_msg,
    )
    db.add(audit_log)
    db.commit()
    db.refresh(audit_log)
    logger.info(
        "[AUDIT] 导出记录: user=%s type=%s format=%s count=%s status=%s ip=%s",
        username, export_type, export_format, record_count, status, ip_address,
    )
    return audit_log
