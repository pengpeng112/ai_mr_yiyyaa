"""
医疗记录一致性审计系统 - FastAPI 主入口
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
import logging
from logging.handlers import RotatingFileHandler

from app.config import load_config, validate_runtime_config
from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routers import config as config_router
from app.routers import push, logs, scheduler, health, stats, notify, report, users, menu, qc_feedback, roles, permissions, departments, demo, audit_types, audit, patient_qc, mobile_qc

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
    audit_handler.setLevel(logging.DEBUG)

    # 注册审计日志器
    for logger_name in ("audit.dify", "audit.oracle", "audit.relay_alert"):
        audit_logger = logging.getLogger(logger_name)
        audit_logger.setLevel(logging.DEBUG)
        audit_logger.addHandler(audit_handler)
        # 同时输出到主日志（INFO 级别）
        audit_logger.propagate = True
except (PermissionError, OSError) as e:
    print(f"[WARN] 无法写入审计日志文件 {LOG_DIR}/audit_detail.log: {e}，审计日志仅输出到控制台")

logger = logging.getLogger(__name__)


def _get_cors_origins():
    """获取CORS允许的源地址，提供更安全的默认值"""
    allowed_origins = os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:8080,http://localhost:3000,http://127.0.0.1:8080"
    )

    environment = os.getenv("ENVIRONMENT", "development")

    # 生产环境禁止使用通配符
    if allowed_origins.strip() == "*":
        if environment == "production":
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
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": f"HTTP_{exc.status_code}",
            "message": str(exc.detail),
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
app.include_router(logs.router, prefix="/api/logs", tags=["📋 推送日志"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["⏰ 定时任务"])
app.include_router(stats.router, prefix="/api/stats", tags=["📊 数据统计"])
app.include_router(notify.router, prefix="/api/notify", tags=["🔔 预警通知"])
app.include_router(health.router, prefix="/api/health", tags=["💚 系统健康"])

# RBAC 和质控反馈路由
app.include_router(users.router, prefix="/api/users", tags=["👤 用户认证"])
app.include_router(menu.router, prefix="/api", tags=["📋 菜单"])
app.include_router(qc_feedback.router, prefix="/api/qc/feedback", tags=["📝 质控反馈"])

# 演示模式路由（本地测试用）
if os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"):
    app.include_router(demo.router, tags=["🎬 演示模式"])

# Phase 2: 角色、权限、科室管理
app.include_router(roles.router, prefix="/api/roles", tags=["🎭 角色管理"])
app.include_router(permissions.router, prefix="/api/permissions", tags=["🔐 权限管理"])
app.include_router(departments.router, prefix="/api/departments", tags=["🏥 科室管理"])
app.include_router(patient_qc.router, prefix="/api/patient-qc", tags=["🧑‍⚕️ 患者质控总览"])
app.include_router(audit.router, prefix="/api/audit", tags=["📋 导出审计"])
app.include_router(mobile_qc.router, tags=["📱 医生端 H5"])

# 报告路由（必须在 static mount 之前，否则会被静态文件拦截）
app.include_router(report.router, tags=["📄 审计报告"])

# ----- 前端静态文件（如存在） -----
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
