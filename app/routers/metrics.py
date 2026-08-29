"""可观测性指标 API（023 P1-09 本地部分）。

GET /api/metrics —— 需登录；返回进程内累计的请求计数、Dify 延迟与调度漏斗快照。
纯内存数据，重启清零，不替代运维平台。
"""
from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.metrics import snapshot
from app.models import User

router = APIRouter()


@router.get("", summary="运行指标快照(内存)")
def get_metrics(_user: User = Depends(get_current_user)):
    return snapshot()
