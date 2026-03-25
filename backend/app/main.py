"""
医疗记录一致性审计系统 - FastAPI 主入口
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os
import logging

from app.database import init_db
from app.scheduler import start_scheduler, shutdown_scheduler
from app.routers import config as config_router
from app.routers import push, logs, scheduler, health, stats, notify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            os.path.join(os.getenv("LOG_DIR", "logs"), "app.log"),
            encoding="utf-8",
        ),
    ],
)
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
- **配置管理**：Oracle连接、Dify接口、科室过滤、定时规则
- **数据推送**：手动推送、定时自动推送、批量重推
- **日志查询**：推送历史、AI结果查看、CSV导出
- **数据统计**：成功率趋势、科室分布、异常排行
- **预警通知**：企业微信/钉钉/邮件/HTTP回调
- **系统健康**：Oracle/Dify/调度器状态监控
    """,
    version="1.0.0",
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
app.include_router(config_router.router, prefix="/api/config", tags=["⚙️ 配置管理"])
app.include_router(push.router, prefix="/api/push", tags=["🚀 数据推送"])
app.include_router(logs.router, prefix="/api/logs", tags=["📋 推送日志"])
app.include_router(scheduler.router, prefix="/api/scheduler", tags=["⏰ 定时任务"])
app.include_router(stats.router, prefix="/api/stats", tags=["📊 数据统计"])
app.include_router(notify.router, prefix="/api/notify", tags=["🔔 预警通知"])
app.include_router(health.router, prefix="/api/health", tags=["💚 系统健康"])

# ----- 前端静态文件（如存在） -----
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
