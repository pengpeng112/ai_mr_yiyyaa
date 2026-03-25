"""
系统健康检查路由 —— /api/health
"""
from datetime import datetime
from fastapi import APIRouter

from app.config import load_config, decrypt_value
from app.oracle_client import test_oracle_connection
from app.dify_pusher import test_dify_connection
from app.scheduler import get_scheduler
from app.schemas import HealthResponse

router = APIRouter()


@router.get("", response_model=HealthResponse, summary="整体健康状态")
def overall_health():
    config = load_config()

    # Oracle
    oracle_cfg = config.get("oracle", {})
    try:
        oracle_cfg["password"] = decrypt_value(oracle_cfg.get("password_enc", ""))
    except Exception:
        oracle_cfg["password"] = ""
    oracle_health = test_oracle_connection(oracle_cfg)

    # Dify
    dify_cfg = config.get("dify", {})
    try:
        dify_cfg["api_key"] = decrypt_value(dify_cfg.get("api_key_enc", ""))
    except Exception:
        dify_cfg["api_key"] = ""
    dify_health = test_dify_connection(dify_cfg)

    # Scheduler
    sched = get_scheduler()
    sched_running = sched is not None and sched.running if sched else False
    job = sched.get_job("daily_push") if sched else None
    next_run = str(job.next_run_time) if job else None
    scheduler_health = {
        "status": "running" if sched_running else "stopped",
        "next_run": next_run,
    }

    # 综合状态
    components_up = [
        oracle_health.get("status") == "up",
        dify_health.get("status") == "up",
    ]
    if all(components_up):
        overall = "healthy"
    elif any(components_up):
        overall = "degraded"
    else:
        overall = "unhealthy"

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(),
        components={
            "oracle": oracle_health,
            "dify": dify_health,
            "scheduler": scheduler_health,
        },
    )


@router.get("/oracle", summary="Oracle 连通性检查")
def oracle_ping():
    config = load_config().get("oracle", {})
    try:
        config["password"] = decrypt_value(config.get("password_enc", ""))
    except Exception:
        config["password"] = ""
    return test_oracle_connection(config)


@router.get("/dify", summary="Dify 连通性检查")
def dify_ping():
    config = load_config().get("dify", {})
    try:
        config["api_key"] = decrypt_value(config.get("api_key_enc", ""))
    except Exception:
        config["api_key"] = ""
    return test_dify_connection(config)
