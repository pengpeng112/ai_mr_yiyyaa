"""
预警通知路由 —— /api/notify
"""
import os

from fastapi import APIRouter, Depends, HTTPException, status
from app.schemas import NotifyChannel, MessageResponse
from app.notifier import test_notify_channel
from app.permissions import require_permission
from app.security_utils import public_error_message
from app.models import User

router = APIRouter()


def _notify_test_enabled() -> bool:
    """通知测试默认只在非生产环境开启，生产必须显式配置开关。"""
    raw = os.getenv("NOTIFY_TEST_ENABLED")
    if raw is not None:
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}
    environment = str(os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()
    return environment not in {"production", "prod"}


@router.post("/test", summary="测试通知渠道")
def test_channel(
    channel: NotifyChannel,
    _user: User = Depends(require_permission("manage_config")),
):
    if not _notify_test_enabled():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="生产环境已禁用通知测试")
    try:
        result = test_notify_channel(channel.model_dump())
    except ValueError as exc:
        return {"success": False, "message": public_error_message(exc, "通知测试配置无效")}
    return result
