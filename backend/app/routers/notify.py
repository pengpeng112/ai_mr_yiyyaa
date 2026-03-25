"""
预警通知路由 —— /api/notify
"""
from fastapi import APIRouter
from app.schemas import NotifyChannel, MessageResponse
from app.notifier import test_notify_channel

router = APIRouter()


@router.post("/test", summary="测试通知渠道")
def test_channel(channel: NotifyChannel):
    result = test_notify_channel(channel.model_dump())
    return result
