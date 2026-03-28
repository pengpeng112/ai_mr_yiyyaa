"""
医疗记录一致性审计系统 - FastAPI 主入口
"""
import os
import logging
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

from app.config import LOG_DIR
from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routers import config as config_router
from app.routers import push, logs, scheduler, health, stats, notify, report


def _setup_logging():
    """配置日志：按组件分文件，支持轮转（10MB/文件，保留5个备份）"""
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    def _make_handler(filename: str) -> RotatingFileHandler:
        h = RotatingFileHandler(
            os.path.join(LOG_DIR, filename),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        h.setFormatter(fmt)
        return h

    # dify.log — 只收 dify_pusher 模块日志
    dify_logger = logging.getLogger("app.dify_pusher")
    dify_logger.addHandler(_make_handler("dify.log"))
    dify_logger.propagate = False   # 不再向上传播，避免重复到 app.log
    dify_logger.setLevel(logging.DEBUG)

    # oracle.log — 只收 oracle_client 模块日志
    oracle_logger = logging.getLogger("app.oracle_client")
    oracle_logger.addHandler(_make_handler("oracle.log"))
    oracle_logger.propagate = False
    oracle_logger.setLevel(logging.DEBUG)

    # push.log — 推送流程日志
    push_logger = logging.getLogger("app.routers.push")
    push_logger.addHandler(_make_handler("push.log"))
    push_logger.propagate = True    # 同时保留到 root（app.log）
    push_logger.setLevel(logging.INFO)

    # root logger → app.log + console
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(_make_handler("app.log"))
    root.addHandler(logging.StreamHandler())


_setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup / shutdown lifecycle."""
    logger.info("系统启动中 ...")
    init_db()
    start_scheduler()
    logger.info("系统启动完成")
    yield
    shutdown_scheduler()
    logger.info("系统已关闭")


app = FastAPI(
    title="医疗记录一致性审计系统",
    description="""
## 功能说明
- **配置管理**：Oracle连接、SQL模板、Dify接口及额外入参、科室过滤、定时规则
- **数据推送**：手动推送、定时自动推送、批量重推
- **日志查询**：推送历史、AI结果查看、CSV导出
- **数据统计**：成功率趋势、科室分布、异常排行、维度统计
- **质控报告**：HTML报告（支持嵌入iframe）、弹窗模式、JSON数据接口
- **预警通知**：企业微信/钉钉/邮件/HTTP回调
- **系统健康**：Oracle/Dify/调度器状态监控
    """,
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----- Routers -----
# report 路由包含 /report/{log_id} 和 /popup/{log_id}，必须在 static mount 之前注册
app.include_router(report.router, tags=["质控报告"])
app.include_router(config_router.router, prefix="/api/config", tags=["配置管理"])
app.include_router(push.router, prefix="/api/push", tags=["数据推送"])
app.include_router(logs.router, prefix="/api/logs", tags=["推送日志"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["定时任务"])
app.include_router(stats.router, prefix="/api/stats", tags=["数据统计"])
app.include_router(notify.router, prefix="/api/notify", tags=["预警通知"])
app.include_router(health.router, prefix="/api/health", tags=["系统健康"])

# ----- 前端静态文件 -----
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
