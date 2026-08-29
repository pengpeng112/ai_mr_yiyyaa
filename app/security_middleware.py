"""安全响应头与 Cookie-CSRF 中间件（023 P1-03）。

- CSP：全前端资源本地化（/vendor/*），script-src 'self' 可用；style 允许
  'unsafe-inline'（Element Plus/内联 style 属性依赖）；不设 frame-ancestors/
  X-Frame-Options，避免破坏 Relay 反代移动端 H5 的既有展示路径。
- CSRF：仅针对「写操作 + Cookie 认证」的组合要求 X-Requested-With 自定义头；
  Bearer 请求天然免疫 CSRF 不受限（兼容期程序化客户端不受影响）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import AUTH_COOKIE_NAME

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)

_WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

CSRF_MISSING_HEADER_MESSAGE = "Missing CSRF header (X-Requested-With) for cookie-authenticated write"


def register_security_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def cookie_csrf_and_security_headers(request: Request, call_next):
        # Cookie 会话下的写操作必须带 X-Requested-With（跨站表单无法伪造自定义头）
        if (
            request.method in _WRITE_METHODS
            and request.cookies.get(AUTH_COOKIE_NAME)
            and not request.headers.get("authorization")
            and not request.headers.get("x-requested-with")
        ):
            return JSONResponse(
                status_code=403,
                content={"code": "HTTP_403", "message": CSRF_MISSING_HEADER_MESSAGE},
            )

        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
