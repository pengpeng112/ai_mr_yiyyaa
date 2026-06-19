"""
短期报告 Token 模块 —— 用于 /report/{log_id} HTML 打印页的临时认证。
不落库，HMAC-SHA256 签名。格式: {log_id}.{user_id}.{expire_ts}.{signature}
"""
import hashlib
import hmac
import logging
import time

logger = logging.getLogger(__name__)

REPORT_TOKEN_TTL = 300  # 5 分钟


def _secret() -> str:
    import os
    from app.config import load_config
    try:
        s = load_config().get("encryption", {}).get("report_token_secret", "")
        if s:
            return s
    except Exception:
        pass
    env_secret = os.getenv("SECRET_KEY", "")
    if env_secret:
        return env_secret[:32]
    logging.getLogger(__name__).warning(
        "report_token 签名密钥未配置（encryption.report_token_secret 和 SECRET_KEY 均缺失）"
        "——生产环境必须设置 SECRET_KEY 环境变量，否则 report token 可被伪造"
    )
    _env = os.getenv("APP_ENV", "development").lower()
    if _env in ("production", "prod"):
        raise RuntimeError("report token signing secret not configured in production")
    return "dev-fallback-report-key"[:32]


def generate_report_token(log_id: int, user_id: int, ttl: int = REPORT_TOKEN_TTL) -> str:
    secret = _secret()
    expire_ts = int(time.time()) + ttl
    msg = f"report:{log_id}:{user_id}:{expire_ts}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{log_id}.{user_id}.{expire_ts}.{sig}"


def verify_report_token(token: str, expected_log_id: int) -> bool:
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 4:
        return False
    log_id_str, _user_id_str, expire_ts_str, sig = parts
    if not log_id_str.isdigit() or not expire_ts_str.isdigit():
        return False
    if int(log_id_str) != expected_log_id:
        return False
    if int(expire_ts_str) < int(time.time()):
        return False
    secret = _secret()
    msg = f"report:{log_id_str}:{_user_id_str}:{expire_ts_str}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(sig, expected)
