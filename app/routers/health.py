"""
系统健康检查路由 —— /api/health
"""
from datetime import datetime
from fastapi import APIRouter, Depends

from app.config import load_config, decrypt_value
from app.database import test_app_db_connection
from app.oracle_client import test_oracle_connection
from app.postgresql_client import test_pg_connection
from app.scheduler import get_scheduler
from app.schemas import HealthResponse
from app.auth import get_current_user
from app.models import User

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="整体健康状态")
def overall_health():
    config = load_config()
    app_db_health = test_app_db_connection()

    data_source = (config.get("data_source", {}) or {}).get("type", "oracle")

    # 当前数据源健康状态
    if data_source == "postgresql":
        pg_cfg = config.get("postgresql", {}).copy()
        try:
            pg_cfg["password"] = decrypt_value(pg_cfg.get("password_enc", ""))
        except Exception:
            pg_cfg["password"] = ""
        db_health = test_pg_connection(pg_cfg)
        db_component_name = "postgresql"
    else:
        oracle_cfg = config.get("oracle", {}).copy()
        try:
            oracle_cfg["password"] = decrypt_value(oracle_cfg.get("password_enc", ""))
        except Exception:
            oracle_cfg["password"] = ""
        db_health = test_oracle_connection(oracle_cfg)
        db_component_name = "oracle"

    dify_health = {
        "status": "disabled",
        "message": "已关闭自动检测，请使用 /api/config/dify/test 或 /api/health/dify 手动检测",
    }

    sched = get_scheduler()
    sched_running = sched is not None and sched.running if sched else False
    job = sched.get_job("daily_push") if sched else None
    scheduler_health = {
        "status": "running" if sched_running else "stopped",
        "next_run": str(job.next_run_time) if job else None,
    }

    components_up = [
        app_db_health.get("status") == "up",
        db_health.get("status") == "up",
    ]
    if all(components_up):
        overall = "healthy"
    elif any(components_up):
        overall = "degraded"
    else:
        overall = "unhealthy"

    components = {
        "app_db": app_db_health,
        db_component_name: db_health,
        "dify": dify_health,
        "scheduler": scheduler_health,
    }
    # 为兼容前端，始终返回 oracle/postgresql 两个键
    if "oracle" not in components:
        components["oracle"] = {"status": "disabled", "message": "当前未启用"}
    if "postgresql" not in components:
        components["postgresql"] = {"status": "disabled", "message": "当前未启用"}

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(),
        components=components,
    )


@router.get("/oracle", summary="Oracle 连通性检查")
def oracle_ping(_user: User = Depends(get_current_user)):
    cfg = load_config().get("oracle", {}).copy()
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    return test_oracle_connection(cfg)


@router.get("/postgresql", summary="PostgreSQL 连通性检查")
def postgresql_ping(_user: User = Depends(get_current_user)):
    cfg = load_config().get("postgresql", {}).copy()
    try:
        cfg["password"] = decrypt_value(cfg.get("password_enc", ""))
    except Exception:
        cfg["password"] = ""
    return test_pg_connection(cfg)


@router.get("/dify", summary="Dify 连通性检查")
def dify_ping(_user: User = Depends(get_current_user)):
    from app.dify_pusher import test_dify_connection

    cfg = load_config().get("dify", {}).copy()
    try:
        cfg["api_key"] = decrypt_value(cfg.get("api_key_enc", ""))
    except Exception:
        cfg["api_key"] = ""
    return test_dify_connection(cfg)
