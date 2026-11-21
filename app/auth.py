"""
JWT 认证与授权模块
支持密码加密、Token 生成与验证、用户认证

认证双轨（023 P1-03）：
- Authorization: Bearer <jwt>（兼容期保留，程序化客户端与旧会话继续可用）
- HttpOnly Cookie（med_audit_token，SameSite=Strict）——浏览器会话防 XSS 窃取
"""
import logging
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional
import jwt
import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Role, User

logger = logging.getLogger(__name__)

# ============ 密码加密配置 ============
# 2026-11-15 P0 存量修复：passlib 1.7.4 与 bcrypt>=5 不兼容（bcrypt.__about__ 已移除，
# import CryptContext 即炸 AttributeError → 全站登录/hash 不可用）。改为直用 bcrypt
# 模块（hashpw/checkpw），生成的 $2b$ 哈希与 passlib 旧哈希完全互通；
# bcrypt 算法上限 72 字节，超长密码按官方指引手动截断（hash/verify 同口径）。
_BCRYPT_ROUNDS = 12


class _BcryptContext:
    """passlib CryptContext 的最小兼容替身（schemes=["bcrypt"]）。"""

    schemes = ("bcrypt",)

    def hash(self, secret: str) -> str:
        return bcrypt.hashpw(
            (secret or "").encode("utf-8")[:72],
            bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
        ).decode("utf-8")

    def verify(self, secret: str, hashed: str) -> bool:
        try:
            return bcrypt.checkpw(
                (secret or "").encode("utf-8")[:72],
                (hashed or "").encode("utf-8"),
            )
        except ValueError:
            return False


pwd_context = _BcryptContext()

# ============ JWT 配置 ============
_DEFAULT_SECRET = "your-secret-key-change-in-production"
_MIN_PRODUCTION_SECRET_LENGTH = 32


def _resolve_runtime_environment(environ: dict[str, str] | None = None) -> str:
    """解析运行环境，兼容 APP_ENV 迁移但拒绝两个变量冲突。"""
    values = environ if environ is not None else os.environ
    aliases = {
        "prod": "production",
        "dev": "development",
        "test": "testing",
    }

    def _normalize(raw: object) -> str:
        value = str(raw or "").strip().lower()
        return aliases.get(value, value)

    environment = _normalize(values.get("ENVIRONMENT", ""))
    legacy = _normalize(values.get("APP_ENV", ""))
    if environment and legacy and environment != legacy:
        raise RuntimeError(
            "【安全】ENVIRONMENT 与 APP_ENV 配置冲突，请只保留一致的运行环境配置"
        )
    return environment or legacy or "development"


def _load_jwt_secret(environ: dict[str, str] | None = None) -> str:
    """读取 JWT 密钥并在生产环境执行强制门禁。"""
    values = environ if environ is not None else os.environ
    secret = str(values.get("JWT_SECRET_KEY", "") or "")
    runtime_environment = _resolve_runtime_environment(values)
    is_production = runtime_environment == "production"
    if is_production and (
        not secret
        or secret == _DEFAULT_SECRET
        or len(secret) < _MIN_PRODUCTION_SECRET_LENGTH
    ):
        raise RuntimeError(
            "【安全】生产环境必须通过 JWT_SECRET_KEY 设置不少于 32 个字符的随机密钥，"
            "禁止缺失、过短或使用默认值"
        )
    if not secret:
        logger.warning(
            "JWT_SECRET_KEY 使用开发环境默认值，仅适用于开发/测试环境；"
            "生产部署前请设置安全密钥"
        )
        return _DEFAULT_SECRET
    if secret == _DEFAULT_SECRET:
        if is_production:
            raise RuntimeError("【安全】生产环境禁止使用 JWT 默认密钥")
        logger.warning("JWT_SECRET_KEY 使用默认值，仅适用于开发/测试环境")
    return secret


JWT_SECRET_KEY = _load_jwt_secret()

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "24"))

# ============ 认证凭据（Bearer 兼容 + HttpOnly Cookie 双轨） ============
security = HTTPBearer(auto_error=False)

# 认证 Cookie 名（HttpOnly + SameSite=Strict；Secure 由 AUTH_COOKIE_SECURE 控制，
# 生产当前为 HTTP 内网直连，默认关闭避免 Cookie 无法发送）
AUTH_COOKIE_NAME = "med_audit_token"


def auth_cookie_secure() -> bool:
    return os.getenv("AUTH_COOKIE_SECURE", "").strip().lower() in {"1", "true", "yes", "on"}


def hash_password(password: str) -> str:
    """密码加密"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


# 与普通密码散列分开识别。旧版服务即使回滚也无法把此标记当作正式密码。
WECOM_SETUP_PASSWORD_PREFIX = "!wecom-setup:"


def verify_setup_password(plain_password: str, stored: str) -> bool:
    return bool(stored and stored.startswith(WECOM_SETUP_PASSWORD_PREFIX)) and verify_password(
        plain_password, stored.removeprefix(WECOM_SETUP_PASSWORD_PREFIX),
    )


def create_access_token(user_id: int, username: str, expires_delta: Optional[timedelta] = None,
                        *, auth_method: str = "") -> str:
    """生成 JWT Token"""
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)
    
    expire = datetime.utcnow() + expires_delta
    payload = {
        "sub": str(user_id),
        "username": username,
        "exp": expire,
        "iat": datetime.utcnow(),
        "auth_method": auth_method,
    }
    
    encoded_jwt = jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """验证 JWT Token

    2026-11-17 扩展：`sub` 形如 `his_empno:<工号>` 的 HIS 工号直登虚拟身份——
    不查应用库 User 表，由 get_current_user 构造只读虚拟用户（his_virtual=True）。
    """
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
        if isinstance(user_id, str) and user_id.startswith("his_empno:"):
            empno = user_id.split(":", 1)[1].strip()
            if not empno:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token",
                )
            return {
                "user_id": 0,
                "username": payload.get("username") or empno,
                "his_empno": empno,
                "his_full_name": payload.get("full_name") or "",
                "his_dept_code": payload.get("dept_code") or "",
                "his_dept_name": payload.get("dept_name") or "",
                "is_his_empno": True,
            }
        return {"user_id": int(user_id), "username": payload.get("username"),
                "auth_method": payload.get("auth_method")}
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_user(
    request: Request,
    credentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前认证用户（Bearer 优先，缺省回落 HttpOnly Cookie）"""
    token = credentials.credentials if credentials is not None else None
    if not token:
        token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        # 与 HTTPBearer(auto_error=True) 既有行为保持一致（403），避免兼容期语义漂移
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authenticated",
        )
    token_data = verify_token(token)

    if token_data.get("is_his_empno"):
        bound_account = db.query(User).filter(User.username == token_data["his_empno"]).first()
        if bound_account is not None and not bound_account.is_active and not bound_account.directory_pending:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        # HIS 工号直登虚拟身份（2026-11-17）：不落库、role_id=None（require_permission
        # 一律 403 = 天然只读），时效数据按 his_dept_code 限制。
        virtual = User(
            id=0,
            username=token_data.get("username") or token_data["his_empno"],
            full_name=token_data.get("his_full_name") or token_data["his_empno"],
            email="",
            role_id=None,
            dept_id=None,
            is_active=True,
        )
        virtual.his_virtual = True
        virtual.his_empno = token_data["his_empno"]
        virtual.his_dept_code = token_data.get("his_dept_code") or ""
        virtual.his_dept_name = token_data.get("his_dept_name") or ""
        return virtual

    user = db.query(User).filter(User.id == token_data["user_id"]).first()
    if user is None or not user.is_active or user.directory_pending:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    auth_method = token_data.get("auth_method")
    if user.password_setup_required and auth_method != "wecom":
        raise HTTPException(status_code=401, detail="WeCom password setup required")
    if auth_method not in {"password", "wecom", "isolated_demo"} \
            and requires_verified_login(db, user):
        raise HTTPException(status_code=401, detail="Please sign in with a password or WeCom again")

    request.state.auth_method = auth_method
    return user


def requires_verified_login(db, user):
    role = db.get(Role, user.role_id) if user.role_id is not None else None
    return bool(user.password_setup_required or user.timeliness_access_json or (role and (
        role.timeliness_access_json or role.name in {"admin", "timeliness_reader", "medical_affairs"}
    )))
