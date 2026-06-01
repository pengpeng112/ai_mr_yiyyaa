"""
无状态签名 Token 模块
用于医生端 H5 页面访问质控详情和提交反馈，不落库。
格式: {alert_id}.{expire_ts}.{signature}
"""
import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)


def generate_alert_token(alert_id: int, secret: str, ttl_hours: int = 72) -> str:
    """生成有效期 ttl_hours 小时的签名 token。"""
    expire_ts = int(time.time()) + ttl_hours * 3600
    msg = f"{alert_id}.{expire_ts}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{alert_id}.{expire_ts}.{sig}"


def verify_alert_token(token: str, secret: str) -> int | None:
    """验证 token，返回 alert_id 或 None（过期/无效）。"""
    if not token or not secret:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    alert_id_str, expire_ts_str, sig = parts
    if not alert_id_str.isdigit() or not expire_ts_str.isdigit():
        return None
    if int(expire_ts_str) < int(time.time()):
        return None
    msg = f"{alert_id_str}.{expire_ts_str}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return int(alert_id_str)
