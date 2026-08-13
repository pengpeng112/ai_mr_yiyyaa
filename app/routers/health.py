"""
系统健康检查路由 —— /api/health

F 包：
- /live 仅进程存活，无外部依赖
- /ready 需权限的深度就绪
- / 兼容深检路径增加短时缓存，避免高频 probe 打业务库
"""
import concurrent.futures
import logging
import threading
import time
from datetime import datetime
from fastapi import APIRouter, Depends

from app.config import load_config, decrypt_value
from app.database import test_app_db_connection
from app.oracle_client import test_oracle_connection
from app.postgresql_client import test_pg_connection
from app.scheduler import get_scheduler, get_last_run_info, is_scheduler_env_enabled
from app.schemas import HealthResponse, PublicHealthResponse
from app.auth import get_current_user
from app.models import User
from app.permissions import require_permission

router = APIRouter()
logger = logging.getLogger(__name__)

_HEALTH_DB_TIMEOUT = 5  # 各组件检测超时秒数
_HEALTH_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="health-check")
_HEALTH_PENDING = threading.BoundedSemaphore(value=2)

# 兼容深检缓存：默认 30s，避免 30s interval 的外部监控叠打 Oracle
_DEEP_HEALTH_CACHE_TTL_SECONDS = 30
_deep_health_lock = threading.Lock()
_deep_health_cache: dict | None = None
_deep_health_cache_at: float = 0.0


@router.get("/live", summary="进程存活探针")
def live_health():
    """仅确认 FastAPI 进程可响应，不访问数据库、Dify 或业务数据源。"""
    return {"status": "alive", "timestamp": datetime.now()}


def _run_with_timeout(fn, timeout=_HEALTH_DB_TIMEOUT):
    if not _HEALTH_PENDING.acquire(blocking=False):
        return {"status": "timeout", "message": "已有健康检查仍在执行，跳过本次检测"}
    future = _HEALTH_EXECUTOR.submit(fn)
    try:
        result = future.result(timeout=timeout)
        return result
    except concurrent.futures.TimeoutError:
        future.cancel()
        return {"status": "timeout", "message": f"检测超时({timeout}s)"}
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
    finally:
        if future.done() or future.cancelled():
            _HEALTH_PENDING.release()
        else:
            future.add_done_callback(lambda _f: _HEALTH_PENDING.release())


def _compute_overall_health() -> HealthResponse:
    config = load_config()
    app_db_health = _run_with_timeout(test_app_db_connection)

    data_source = (config.get("data_source", {}) or {}).get("type", "oracle")

    if data_source == "fixture":
        db_health = {
            "status": "up",
            "message": "脱敏合成 fixture 数据源（无外部数据库连接）",
            "synthetic": True,
        }
        db_component_name = "fixture"
    elif data_source == "postgresql":
        pg_cfg = config.get("postgresql", {}).copy()
        try:
            pg_cfg["password"] = decrypt_value(pg_cfg.get("password_enc", ""))
        except Exception:
            pg_cfg["password"] = ""
        db_health = _run_with_timeout(lambda: test_pg_connection(pg_cfg))
        db_component_name = "postgresql"
    else:
        oracle_cfg = config.get("oracle", {}).copy()
        try:
            oracle_cfg["password"] = decrypt_value(oracle_cfg.get("password_enc", ""))
        except Exception:
            oracle_cfg["password"] = ""
        db_health = _run_with_timeout(lambda: test_oracle_connection(oracle_cfg))
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
    if "oracle" not in components:
        components["oracle"] = {"status": "disabled", "message": "当前未启用"}
    if "postgresql" not in components:
        components["postgresql"] = {"status": "disabled", "message": "当前未启用"}

    return HealthResponse(
        status=overall,
        timestamp=datetime.now(),
        components=components,
    )


def _get_cached_overall_health(*, force_refresh: bool = False) -> HealthResponse:
    global _deep_health_cache, _deep_health_cache_at
    now = time.monotonic()
    with _deep_health_lock:
        if (
            not force_refresh
            and _deep_health_cache is not None
            and (now - _deep_health_cache_at) < _DEEP_HEALTH_CACHE_TTL_SECONDS
        ):
            cached = HealthResponse.model_validate(_deep_health_cache)
            # 标记缓存命中，便于运维识别
            if isinstance(cached.components, dict):
                cached.components = dict(cached.components)
                cached.components["deep_check_cache"] = {
                    "status": "hit",
                    "ttl_seconds": _DEEP_HEALTH_CACHE_TTL_SECONDS,
                    "age_seconds": round(now - _deep_health_cache_at, 2),
                    "note": "兼容 /api/health 深检缓存；高频 probe 请改用 /api/health/live",
                }
            return cached

    result = _compute_overall_health()
    # 不缓存密码等敏感字段：HealthResponse 本身不含密钥
    payload = result.model_dump() if hasattr(result, "model_dump") else result.dict()
    with _deep_health_lock:
        _deep_health_cache = payload
        _deep_health_cache_at = time.monotonic()
    if isinstance(result.components, dict):
        result.components = dict(result.components)
        result.components["deep_check_cache"] = {
            "status": "miss",
            "ttl_seconds": _DEEP_HEALTH_CACHE_TTL_SECONDS,
            "note": "兼容 /api/health 深检缓存；高频 probe 请改用 /api/health/live",
        }
    return result


@router.get("", response_model=PublicHealthResponse, summary="匿名健康摘要")
def overall_health(force_refresh: bool = False):
    """
    匿名兼容路径仅返回进程级安全摘要；详细组件原因请使用授权 /ready。
    """
    # 匿名探针不触发数据库、Oracle 或 Dify 深检，避免被无认证请求放大；
    # force_refresh 参数仅为兼容旧调用方保留，不再具有深检语义。
    return PublicHealthResponse(status="alive", timestamp=datetime.now())


@router.get("/ready", response_model=HealthResponse, summary="授权就绪检查")
def ready_health(_user: User = Depends(require_permission("view_scheduler"))):
    """供运维读取带组件原因的就绪状态；匿名调用只应使用 /live。"""
    # ready 走强制刷新，避免运维误读过期缓存
    result = _get_cached_overall_health(force_refresh=True)
    config = load_config()
    dify = config.get("dify", {}) or {}
    targets = dify.get("targets", []) or []
    enabled_targets = [t for t in targets if isinstance(t, dict) and t.get("enabled", True)]
    if not enabled_targets and dify.get("base_url"):
        enabled_targets = [dify]
    invalid_targets = [
        str(t.get("name") or "default")
        for t in enabled_targets
        if not str(t.get("base_url") or "").strip()
        or not str(t.get("api_key_enc") or t.get("api_key") or "").strip()
    ]
    result.components["dify_config"] = {
        "status": "up" if enabled_targets and not invalid_targets else "down",
        "configured_targets": len(enabled_targets),
        "invalid_targets": invalid_targets,
    }
    audit_codes = {
        str(item.get("code") or "").strip()
        for item in (config.get("audit_types", []) or [])
        if isinstance(item, dict) and str(item.get("code") or "").strip()
    }
    missing_scheduler_codes = []
    scheduler_cfgs = []
    for section in ("scheduler_daily", "scheduler_discharge"):
        cfg = config.get(section, {}) or {}
        if cfg.get("enabled"):
            scheduler_cfgs.append((section, cfg))
            missing_scheduler_codes.extend(
                code for code in (cfg.get("audit_type_codes", []) or []) if code not in audit_codes
            )
    sched = get_scheduler()
    missing_jobs = []
    if is_scheduler_env_enabled():
        expected_jobs = {
            "daily_push" if section == "scheduler_daily" else "discharge_push"
            for section, _cfg in scheduler_cfgs
        }
        missing_jobs = sorted(job_id for job_id in expected_jobs if not sched or not sched.get_job(job_id))
    result.components["scheduler_ready"] = {
        "status": "up" if not missing_scheduler_codes and not missing_jobs else "down",
        "missing_audit_type_codes": sorted(set(missing_scheduler_codes)),
        "missing_jobs": missing_jobs,
        "last_run": get_last_run_info(),
    }
    result.components["config"] = {
        "status": "up" if isinstance(config, dict) and audit_codes else "down",
    }
    critical_statuses = [
        c.get("status") for c in result.components.values() if isinstance(c, dict)
    ]
    if any(status in {"down", "error", "timeout"} for status in critical_statuses):
        result.status = "degraded" if result.components.get("app_db", {}).get("status") == "up" else "unhealthy"
    return result


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
