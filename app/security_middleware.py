"""安全响应头与 Cookie-CSRF 中间件（023 P1-03 / 031 T1-5）。

- CSP：全前端资源本地化（/vendor/*），script-src 'self' 可用；style 允许
  'unsafe-inline'（Element Plus/内联 style 属性依赖）；不设 frame-ancestors/
  X-Frame-Options，避免破坏 Relay 反代移动端 H5 的既有展示路径。
  2026-08-30 追加 'unsafe-eval'：legacy 前端/index/log_detail/移动端 qc_detail
  均使用 vue.global 全量构建（运行时模板编译依赖 new Function），严格 'self'
  会 EvalError 崩页面。仍保留 script-src 'self'：外源与内联 <script> 注入依旧
  被阻断，eval 仅限同源已加载代码（内网系统风险可接受，决策记录）。
- CSRF：仅针对「写操作 + Cookie 认证」的组合要求 X-Requested-With 自定义头；
  Bearer 请求天然免疫 CSRF 不受限（兼容期程序化客户端不受影响）。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth import AUTH_COOKIE_NAME

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval'; "
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

# 登录豁免：旧会话的过期 Cookie 不能把用户锁死在门外（带旧 Cookie 的
# /login 必须放行以完成重新认证，成功后服务端滚动下发新 Cookie）；
# 内网直连 + SameSite=Lax 下登录 CSRF 风险可接受。logout 保持强校验。
# 移动端 H5 反馈豁免（037 RP-H / K-1）：/api/mobile/qc-feedback 的认证主体是
# body 里的 alert token（HMAC），浏览器残留的管理端 Cookie 只是附带；医生在
# 同浏览器登录过管理端时不应被 CSRF 门误伤 403。token 校验仍由路由负责。
_CSRF_EXEMPT_PATHS = (
    "/api/users/login",
    "/api/mobile/qc-feedback",
)


def register_security_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def cookie_csrf_and_security_headers(request: Request, call_next):
        # Cookie 会话下的写操作必须带 X-Requested-With（跨站表单无法伪造自定义头）
        if (
            request.method in _WRITE_METHODS
            and request.url.path not in _CSRF_EXEMPT_PATHS
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
