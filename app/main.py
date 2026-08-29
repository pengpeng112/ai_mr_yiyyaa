"""
医疗记录一致性审计系统 - FastAPI 主入口
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from contextlib import asynccontextmanager
import os
import logging
from logging.handlers import RotatingFileHandler

from app.config import load_config, validate_runtime_config
from app.database import init_db
from app.security_utils import public_error_message
from app.auth import _resolve_runtime_environment
from app.security_middleware import register_security_middleware
from app.scheduler import start_scheduler, shutdown_scheduler
from app.services.isolated_mode import assert_demo_runtime_allowed, demo_mode_enabled
from app.routers import config as config_router
from app.routers import push, logs, scheduler, health, stats, notify, report, users, menu, qc_feedback, roles, permissions, departments, demo, audit_types, audit, patient_qc, mobile_qc, patients, historical_rerun
from app.routers import metrics as metrics_router

# ---- 日志配置 ----
LOG_DIR = os.getenv("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 主日志：应用运行日志（支持日志轮转，单文件 10MB，保留 5 个备份）
_handlers: list[logging.Handler] = [logging.StreamHandler()]
try:
    _file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "app.log"),
        encoding="utf-8",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    _handlers.append(_file_handler)
except (PermissionError, OSError) as e:
    print(f"[WARN] 无法写入日志文件 {LOG_DIR}/app.log: {e}，仅使用控制台输出")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=_handlers,
)

# 审计详细日志：Dify 请求/响应 + Oracle 查询详情（轮转）
try:
    audit_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, "audit_detail.log"),
        encoding="utf-8",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    audit_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    audit_level_name = str(os.getenv("AUDIT_LOG_LEVEL", "INFO")).strip().upper()
    audit_level = getattr(logging, audit_level_name, logging.INFO)
    audit_handler.setLevel(audit_level)

    # 注册审计日志器
    for logger_name in ("audit.dify", "audit.oracle", "audit.relay_alert"):
        audit_logger = logging.getLogger(logger_name)
        audit_logger.setLevel(audit_level)
        audit_logger.addHandler(audit_handler)
        # 同时输出到主日志（INFO 级别）
        audit_logger.propagate = True
except (PermissionError, OSError) as e:
    print(f"[WARN] 无法写入审计日志文件 {LOG_DIR}/audit_detail.log: {e}，审计日志仅输出到控制台")

logger = logging.getLogger(__name__)
assert_demo_runtime_allowed()


def _api_docs_enabled() -> bool:
    environment = _resolve_runtime_environment()
    default = "false" if environment in {"production", "prod"} else "true"
    return str(os.getenv("ENABLE_API_DOCS", default)).strip().lower() == "true"


def _get_cors_origins():
    """获取CORS允许的源地址，提供更安全的默认值"""
    allowed_origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8080,http://localhost:3000,http://127.0.0.1:8080"
    )

    environment = _resolve_runtime_environment()

    # 生产环境禁止使用通配符
    if allowed_origins.strip() == "*":
        if environment in {"production", "prod"}:
            logger.error(
                "生产环境禁止使用通配符 '*' 作为 CORS 来源！"
                "请设置 ALLOWED_ORIGINS 环境变量为具体域名列表。"
                "已回退到空列表（拒绝所有跨域请求）。"
            )
            return []
        else:
            logger.warning("开发环境使用通配符 '*' 作为 CORS 来源，请勿在生产环境使用")

    return [origin.strip() for origin in allowed_origins.split(",") if origin.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    logger.info("系统启动中 ...")
    init_db()
    config_warnings = validate_runtime_config(load_config())
    for warning in config_warnings:
        logger.warning(f"配置自检告警: {warning}")

    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
        start_scheduler()
    else:
        logger.info("调度器已通过 ENABLE_SCHEDULER=false 禁用")
    logger.info("系统启动完成")
    yield
    if os.getenv("ENABLE_SCHEDULER", "true").lower() == "true":
        shutdown_scheduler()
    logger.info("系统已关闭")


app = FastAPI(
    title="医疗记录一致性审计系统",
    description="""
## 功能说明
- **配置管理**：Oracle连接（含SQL可视化编辑）、Dify接口（含参数映射）、科室过滤、定时规则
- **数据推送**：手动推送、定时自动推送、批量重推
- **日志查询**：推送历史、AI结果查看、CSV导出
- **审计报告**：质控报告页面（HTML + JSON）、维度级别统计
- **数据统计**：成功率趋势、科室分布、异常排行、维度统计
- **预警通知**：企业微信/钉钉/邮件/HTTP回调
- **系统健康**：Oracle/Dify/调度器状态监控
    """,
    version="1.1.0",
    docs_url="/docs" if _api_docs_enabled() else None,
    redoc_url="/redoc" if _api_docs_enabled() else None,
    openapi_url="/openapi.json" if _api_docs_enabled() else None,
    lifespan=lifespan,
)


@app.middleware("http")
async def synthetic_test_metadata(request: Request, call_next):
    response = await call_next(request)
    if os.getenv("TEST_ISOLATED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        response.headers["X-Synthetic-Test-Data"] = "true"
        response.headers["X-Demo-Run-Id"] = os.getenv("DEMO_RUN_ID", "")
        response.headers["Cache-Control"] = "no-store"
        if response.headers.get("Content-Disposition"):
            response.headers["X-Synthetic-Export"] = "SYNTHETIC_TEST_DATA"
    return response


# CSP 响应头 + Cookie 会话 CSRF 防护（023 P1-03）
register_security_middleware(app)


@app.middleware("http")
async def metrics_request_counter(request: Request, call_next):
    """请求计数（023 P1-09 本地部分）：按路由模板+状态码类聚合，纯内存。"""
    from app import metrics as _metrics

    response = await call_next(request)
    try:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "") or "unrouted"
        _metrics.record_request(request.method, route_path, response.status_code)
    except Exception:  # 指标失败不得影响请求路径
        pass
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, str):
        detail = public_error_message(detail, "请求处理失败")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": detail,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(_request: Request, exc: Exception):
    logger.error("未处理异常: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": "INTERNAL_ERROR",
            "message": "服务内部错误",
        },
    )

# 更安全的CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With"],
)

# ----- Routers -----
app.include_router(config_router.router, prefix="/api/config", tags=["⚙️ 配置管理"])
app.include_router(audit_types.router, prefix="/api/audit-types", tags=["🧩 审计类型"])
app.include_router(push.router, prefix="/api/push", tags=["🚀 手动推送"])
app.include_router(historical_rerun.router, prefix="/api/push/historical-rerun", tags=["🔄 历史重新核查"])
app.include_router(logs.router, prefix="/api/logs", tags=["📋 推送日志"])
app.include_router(metrics_router.router, prefix="/api/metrics", tags=["📈 运行指标"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["⏰ 定时任务"])
app.include_router(stats.router, prefix="/api/stats", tags=["📊 数据统计"])
app.include_router(notify.router, prefix="/api/notify", tags=["🔔 预警通知"])
app.include_router(health.router, prefix="/api/health", tags=["💚 系统健康"])

# RBAC 和质控反馈路由
app.include_router(users.router, prefix="/api/users", tags=["👤 用户认证"])
app.include_router(menu.router, prefix="/api", tags=["📋 菜单"])
app.include_router(qc_feedback.router, prefix="/api/qc/feedback", tags=["📝 质控反馈"])

# 演示模式路由（本地测试用）
if demo_mode_enabled():
    app.include_router(demo.router, tags=["🎬 演示模式"])

# Phase 2: 角色、权限、科室管理
app.include_router(roles.router, prefix="/api/roles", tags=["🎭 角色管理"])
app.include_router(permissions.router, prefix="/api/permissions", tags=["🔐 权限管理"])
app.include_router(departments.router, prefix="/api/departments", tags=["🏥 科室管理"])
app.include_router(patient_qc.router, prefix="/api/patient-qc", tags=["🧑‍⚕️ 患者质控总览"])
app.include_router(patients.router, prefix="/api/patients", tags=["🏥 患者清单"])
app.include_router(audit.router, prefix="/api/audit", tags=["📋 导出审计"])
app.include_router(mobile_qc.router, tags=["📱 医生端 H5"])

# 前置机推送配置
from app.routers import relay_config
app.include_router(relay_config.router, prefix="/api/relay", tags=["📡 前置机推送配置"])

# 报告路由（必须在 static mount 之前，否则会被静态文件拦截）
app.include_router(report.router, tags=["📄 审计报告"])


def resolve_ui_default_entry(raw: str | None = None) -> str:
    """解析默认前端入口：legacy（默认）| ui-next。

    - legacy：`/` 与 `/index.html` 仍为旧 static 首页
    - ui-next：仅 `/` 重定向到 `/ui-next/`，`/index.html` 仍可回 legacy
    不移动、不删除 static 文件。
    """
    value = (raw if raw is not None else os.getenv("UI_DEFAULT_ENTRY", "legacy")).strip().lower()
    if value in {"ui-next", "uinext", "next", "ui_next"}:
        return "ui-next"
    return "legacy"


# ----- 前端静态文件（如存在） -----
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    _ui_default_entry = resolve_ui_default_entry()
    logging.getLogger(__name__).info("UI_DEFAULT_ENTRY=%s", _ui_default_entry)

    @app.get("/", include_in_schema=False)
    async def root_ui_entry():
        """默认入口开关：阶段 A 保持 legacy；阶段 B 可改为 ui-next。"""
        if resolve_ui_default_entry() == "ui-next":
            return RedirectResponse(url="/ui-next/", status_code=307)
        index_path = os.path.join(static_dir, "index.html")
        if os.path.isfile(index_path):
            return FileResponse(index_path)
        raise HTTPException(status_code=404, detail="legacy index not found")

    def _ui_next_index_response() -> FileResponse:
        """ui-next 入口 HTML 禁止缓存，避免浏览器长期卡在旧 index/旧 Workbench 分包。"""
        index_path = os.path.join(static_dir, "ui-next", "index.html")
        if not os.path.isfile(index_path):
            raise HTTPException(status_code=404, detail="ui-next index not found")
        resp = FileResponse(index_path, media_type="text/html; charset=utf-8")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["X-Med-Audit-UI"] = "ui-next-no-cache"
        return resp

    @app.get("/ui-next", include_in_schema=False)
    @app.get("/ui-next/", include_in_schema=False)
    async def ui_next_index_entry():
        return _ui_next_index_response()

    @app.get("/ui-next/index.html", include_in_schema=False)
    async def ui_next_index_html():
        return _ui_next_index_response()

    @app.get("/ui-next/{spa_path:path}", include_in_schema=False)
    async def ui_next_spa_fallback(spa_path: str):
        """支持 Vue history 深链，同时继续提供构建产物中的真实静态文件。"""
        ui_root = os.path.realpath(os.path.join(static_dir, "ui-next"))
        candidate = os.path.realpath(os.path.join(ui_root, spa_path))
        if candidate == ui_root or candidate.startswith(ui_root + os.sep):
            if os.path.isfile(candidate):
                return FileResponse(candidate)
        if spa_path.startswith("assets/") or "." in os.path.basename(spa_path):
            raise HTTPException(status_code=404, detail="ui-next asset not found")
        return _ui_next_index_response()

    @app.middleware("http")
    async def ui_next_html_no_cache(request: Request, call_next):
        """兜底：无论由路由还是 StaticFiles 提供，ui-next 入口 HTML 一律禁止缓存。"""
        response = await call_next(request)
        path = request.url.path or ""
        if path in {"/ui-next", "/ui-next/", "/ui-next/index.html"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
            response.headers["X-Med-Audit-UI"] = "ui-next-no-cache"
        return response

    # html=True：/index.html、/log_detail.html、/ui-next/assets、mobile、report 等仍由静态目录提供
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
