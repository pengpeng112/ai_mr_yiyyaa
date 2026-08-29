"""
APScheduler 定时任务调度模块
支持 oracle/postgresql 双数据源
"""
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import load_config
from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.database import SessionLocal
from app.models import SchedulerHistory, SchedulerRunLock
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.config_parser import ConfigParser
from app.services.data_source_loader import load_patient_bundles
from app.services.push_executor import PushExecutor, PushConfig
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.retention_service import run_retention_cleanup

# ── 新拆分模块 ──
from app.services.scheduler_lock_service import (
    get_scheduler_lock_info as _get_scheduler_lock_info,
    acquire_scheduler_run_lock as _acquire_scheduler_run_lock_impl,
    heartbeat_scheduler_run_lock as _heartbeat_scheduler_run_lock_impl,
    release_scheduler_run_lock as _release_scheduler_run_lock_impl,
    _make_lock_owner as _make_lock_owner_impl,
    DEFAULT_LOCK_NAME,
)
from app.services.scheduler_history_service import (
    write_scheduler_history_safe as _write_scheduler_history_safe_impl,
)
from app.services.scheduler_run_modes import (
    resolve_audit_run_mode as _resolve_audit_run_mode_impl,
    audit_type_for_run_mode as _audit_type_for_run_mode_impl,
)
from app.services.scheduler_run_summary import sanitize_error_summary

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run_info: dict = {}
_scheduler_lock = threading.Lock()
_info_lock = threading.Lock()
_RUN_LOCK_NAME = DEFAULT_LOCK_NAME


# ── 兼容包装：调度锁 ──

def _make_lock_owner() -> str:
    return _make_lock_owner_impl()


def get_scheduler_lock_info(lock_name: str = _RUN_LOCK_NAME) -> dict:
    """返回指定调度任务锁；默认值保留旧调用方的 daily_push 语义。"""
    return _get_scheduler_lock_info(lock_name)


def _acquire_scheduler_run_lock() -> tuple[bool, str, str]:
    return _acquire_scheduler_run_lock_impl(_RUN_LOCK_NAME)


def _release_scheduler_run_lock(owner_id: str) -> None:
    _release_scheduler_run_lock_impl(owner_id, _RUN_LOCK_NAME)


# ── 兼容包装：调度历史 ──

def _write_scheduler_history_safe(
    query_date: str,
    audit_type_code: str,
    total_records: int,
    success_count: int,
    failed_count: int,
    duration_seconds: int,
    status: str,
    audit_run_mode: str = "daily_increment",
    error_msg: str = "",
    error_code: str = "",
) -> str:
    return _write_scheduler_history_safe_impl(
        query_date=query_date,
        audit_type_code=audit_type_code,
        total_records=total_records,
        success_count=success_count,
        failed_count=failed_count,
        duration_seconds=duration_seconds,
        status=status,
        audit_run_mode=audit_run_mode,
        error_msg=error_msg,
        error_code=error_code,
    )


def _record_scheduler_error(msg: str) -> None:
    with _info_lock:
        new_info = dict(_last_run_info)
        new_info["last_error"] = msg
        globals()["_last_run_info"] = new_info


# ── 兼容包装：运行模式 ──

def _resolve_audit_run_mode(sched_cfg: dict, default: str = "daily_increment") -> str:
    return _resolve_audit_run_mode_impl(sched_cfg, default)


def _audit_type_for_run_mode(audit_type, audit_run_mode: str):
    return _audit_type_for_run_mode_impl(audit_type, audit_run_mode)


# ── 对外 API ──

def get_scheduler() -> BackgroundScheduler | None:
    with _scheduler_lock:
        return _scheduler


def get_last_run_info() -> dict:
    with _info_lock:
        return dict(_last_run_info)


def is_scheduler_env_enabled() -> bool:
    if os.getenv("ENABLE_SCHEDULER", "true").lower() != "true":
        return False
    try:
        workers = int(os.getenv("WEB_CONCURRENCY", os.getenv("UVICORN_WORKERS", "1")) or "1")
    except (TypeError, ValueError):
        logger.error("worker 数配置无效，安全起见禁用进程内调度器")
        return False
    if workers > 1:
        logger.error("检测到多 worker(%s)，禁用进程内调度器；请使用独立单实例 scheduler 进程", workers)
        return False
    return True


def validate_cron_expression(cron_expr: str) -> tuple[bool, str]:
    expr = str(cron_expr or "").strip()
    parts = expr.split()
    if len(parts) != 5:
        return False, "Cron表达式必须包含5个部分: 分 时 日 月 周"
    try:
        CronTrigger.from_crontab(expr, timezone="Asia/Shanghai")
    except Exception as e:
        return False, f"Cron表达式无效: {e}"
    return True, "ok"


def start_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler and _scheduler.running:
            logger.info("调度器已在运行，跳过重复启动")
            return

        if not is_scheduler_env_enabled():
            logger.info("调度器已通过 ENABLE_SCHEDULER=false 禁用")
            return

        _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

        config = load_config()
        sched_daily = config.get("scheduler_daily", {}) or {}
        sched_discharge = config.get("scheduler_discharge", {}) or {}

        daily_enabled = sched_daily.get("enabled", False)
        discharge_enabled = sched_discharge.get("enabled", False)

        if daily_enabled or discharge_enabled:
            if daily_enabled:
                daily_cron = sched_daily.get("cron", "0 10 * * *")
                daily_mode = _resolve_audit_run_mode(sched_daily)
                ok, msg = _add_cron_job_with_mode("daily_push", daily_cron, daily_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("每日增量调度初始化失败: %s", msg)
                else:
                    logger.info("每日增量调度已注册: cron=%s mode=%s", daily_cron, daily_mode)

            if discharge_enabled:
                discharge_cron = sched_discharge.get("cron", "0 11 * * *")
                discharge_mode = _resolve_audit_run_mode(sched_discharge, "discharge_final")
                ok, msg = _add_cron_job_with_mode("discharge_push", discharge_cron, discharge_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("出院终末调度初始化失败: %s", msg)
                else:
                    logger.info("出院终末调度已注册: cron=%s mode=%s", discharge_cron, discharge_mode)
        else:
            sched_cfg = config.get("scheduler", {}) or {}
            if sched_cfg.get("enabled", False):
                legacy_mode = _resolve_audit_run_mode(sched_cfg)
                ok, msg = _add_cron_job_with_mode("daily_push", sched_cfg.get("cron", "0 6 * * *"), legacy_mode)
                if not ok:
                    _record_scheduler_error(msg)
                    logger.error("定时任务初始化失败: %s", msg)

        _add_retention_cleanup_job()

        _scheduler.start()
        logger.info("调度器已启动")


def _add_cron_job_with_mode(job_id: str, cron_expr: str, audit_run_mode: str):
    valid, message = validate_cron_expression(cron_expr)
    if not valid:
        return False, message
    try:
        from functools import partial
        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
        job_func = partial(_daily_push_job_v2, audit_run_mode_override=audit_run_mode, lock_name=job_id)
        _scheduler.add_job(
            job_func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        return True, "ok"
    except Exception as e:
        logger.error("添加定时任务失败 job_id=%s: %s", job_id, e, exc_info=True)
        return False, str(e)


def shutdown_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("调度器已关闭")


def update_scheduler(enabled: bool, cron: str, audit_run_mode: str = "daily_increment", job_id: str = "daily_push"):
    global _scheduler
    if not is_scheduler_env_enabled():
        return {
            "applied": False,
            "message": "ENABLE_SCHEDULER=false，当前进程未启用调度器，仅保存配置",
            "next_run": None,
        }

    with _scheduler_lock:
        if not _scheduler:
            return {
                "applied": False,
                "message": "调度器未启动，配置已保存待重启后生效",
                "next_run": None,
            }

        if _scheduler.get_job(job_id):
            _scheduler.remove_job(job_id)

        if enabled:
            ok, msg = _add_cron_job_with_mode(job_id, cron, audit_run_mode)
            if not ok:
                _record_scheduler_error(msg)
                return {"applied": False, "message": msg, "next_run": None}
            job = _scheduler.get_job(job_id)
            next_run = str(job.next_run_time) if job and job.next_run_time else None
            logger.info("定时任务已更新: job_id=%s cron=%s mode=%s next_run=%s", job_id, cron, audit_run_mode, next_run)
            return {"applied": True, "message": "ok", "next_run": next_run}
        logger.info("定时任务已禁用: job_id=%s", job_id)
        return {"applied": True, "message": "disabled", "next_run": None}


# Deprecated: 旧版单调度器包装，请使用 _add_cron_job_with_mode()
def _add_cron_job(cron_expr: str):
    return _add_cron_job_with_mode("daily_push", cron_expr, "daily_increment")


def _add_retention_cleanup_job():
    """注册数据留存清理定时任务"""
    try:
        config = load_config()
        retention_cfg = config.get("data_retention", {}) or {}
        if not retention_cfg.get("enabled", True):
            logger.info("数据留存清理已禁用，跳过注册")
            return

        cron_expr = retention_cfg.get("cleanup_cron", "0 2 * * 0")  # 默认每周日凌晨2点
        valid, message = validate_cron_expression(cron_expr)
        if not valid:
            logger.error("数据留存清理定时任务 Cron 表达式无效: %s", message)
            return

        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
        _scheduler.add_job(
            _retention_cleanup_job,
            trigger=trigger,
            id="retention_cleanup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("数据留存清理定时任务已注册: cron=%s", cron_expr)
    except Exception as e:
        logger.error("注册数据留存清理定时任务失败: %s", e, exc_info=True)


# ── 数据留存清理 ──

def _retention_cleanup_job():
    """数据留存清理任务入口"""
    logger.info("数据留存清理任务开始执行")
    from app.services.scheduler_lock_service import acquire_scheduler_run_lock, release_scheduler_run_lock
    acquired, owner_id, reason = acquire_scheduler_run_lock("retention_cleanup")
    if not acquired:
        logger.info("数据留存清理跳过：已有实例执行中 reason=%s", reason)
        return
    heartbeat_stop = threading.Event()

    def refresh_heartbeat() -> None:
        from app.services.scheduler_lock_service import heartbeat_scheduler_run_lock
        while not heartbeat_stop.wait(60):
            if not heartbeat_scheduler_run_lock(owner_id, "retention_cleanup"):
                logger.warning("数据留存运行锁心跳未刷新")

    heartbeat_thread = threading.Thread(
        target=refresh_heartbeat,
        name="scheduler-lock-heartbeat-retention",
        daemon=True,
    )
    heartbeat_thread.start()
    db = SessionLocal()
    try:
        config = load_config()
        retention_cfg = config.get("data_retention", {}) or {}
        result = run_retention_cleanup(db, retention_cfg)
        logger.info("数据留存清理任务完成: %s", result)
    except Exception as e:
        logger.error("数据留存清理任务异常: %s", e, exc_info=True)
    finally:
        db.close()
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=5)
        release_scheduler_run_lock(owner_id, "retention_cleanup")


# ── 调度配置解析 ──

def _resolve_scheduler_cfg(config: dict, audit_run_mode: str) -> dict:
    if audit_run_mode == "discharge_final":
        discharge = config.get("scheduler_discharge") or {}
        if discharge:
            return discharge
        return {
            "enabled": False,
            "audit_run_mode": "discharge_final",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": [],
            "cron": "0 11 * * *",
            "schedule_mode": "daily",
            "daily_time": "11:00",
        }
    daily = config.get("scheduler_daily") or {}
    if daily:
        return daily
    return config.get("scheduler", {}) or {}


# ── 单审计类型执行器（委托到 scheduler_audit_runner） ──
from app.services.scheduler_audit_runner import run_daily_push_for_audit_type as _run_daily_push_for_audit_type_impl

def _run_daily_push_for_audit_type(
    config: dict,
    data_source: str,
    db_cfg: dict,
    audit_type,
    query_date: str,
    dept_list: list,
    push_settings: dict,
    field_mapping: dict,
    audit_run_mode: str = "daily_increment",
) -> dict:
    return _run_daily_push_for_audit_type_impl(
        config=config,
        data_source=data_source,
        db_cfg=db_cfg,
        audit_type=audit_type,
        query_date=query_date,
        dept_list=dept_list,
        push_settings=push_settings,
        field_mapping=field_mapping,
        audit_run_mode=audit_run_mode,
    )


# ── 调度主路径 ──
def _record_scheduler_metric(lock_name: str, outcome: str) -> None:
    """调度漏斗计数（P1-09）；指标失败不得影响调度主链路。"""
    try:
        from app import metrics as _metrics
        _metrics.record_scheduler_run(lock_name, outcome)
    except Exception:
        pass


# 唯一入口：_daily_push_job_v2() + _add_cron_job_with_mode()
# 旧版 _daily_push_job（单调度器、引用未定义 db）已于 015/G11 删除。

def _daily_push_job_v2(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None, audit_run_mode_override: str = "daily_increment", lock_name: str = "daily_push"):
    global _last_run_info
    acquired, owner_id, message = _acquire_scheduler_run_lock_impl(lock_name)
    if not acquired:
        logger.warning("定时推送任务(v2)跳过：%s", message)
        query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        with _info_lock:
            new_info = dict(_last_run_info)
            new_info.update({
                "run_time": datetime.now().isoformat(),
                "query_date": query_date,
                "audit_run_mode": audit_run_mode_override,
                "last_error": message,
                "lock_owner": owner_id,
                "lock_name": lock_name,
                "skipped_reason": "scheduler_lock_not_acquired",
            })
            _last_run_info = new_info
        # 落库可见：锁获取失败不得静默跳过（不改变锁语义，仅写历史）
        try:
            from app.services.scheduler_history_service import write_scheduler_history_safe
            hist_err = write_scheduler_history_safe(
                query_date=query_date,
                audit_type_code="__scheduler_lock__",
                total_records=0,
                success_count=0,
                failed_count=0,
                duration_seconds=0,
                status="failed",
                audit_run_mode=audit_run_mode_override,
                error_msg=message,
                error_code="scheduler_lock_not_acquired",
            )
            if hist_err:
                logger.error("锁跳过历史写入失败: %s", hist_err)
            else:
                logger.info(
                    "调度锁未获取已写入 SchedulerHistory: lock=%s mode=%s query_date=%s reason=%s",
                    lock_name,
                    audit_run_mode_override,
                    query_date,
                    message,
                )
        except Exception:
            logger.exception("调度锁未获取时写入 SchedulerHistory 异常")
        _record_scheduler_metric(lock_name, "skipped_lock")
        return
    heartbeat_stop = threading.Event()

    def refresh_heartbeat() -> None:
        while not heartbeat_stop.wait(60):
            if not _heartbeat_scheduler_run_lock_impl(owner_id, lock_name):
                logger.warning("定时推送运行锁心跳未刷新: lock=%s", lock_name)

    heartbeat_thread = threading.Thread(
        target=refresh_heartbeat,
        name=f"scheduler-lock-heartbeat-{lock_name}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        _daily_push_job_v2_unlocked(
            query_date_override=query_date_override,
            dept_override=dept_override,
            audit_type_codes_override=audit_type_codes_override,
            audit_run_mode=audit_run_mode_override,
        )
        _record_scheduler_metric(lock_name, "completed")
    except Exception:
        _record_scheduler_metric(lock_name, "failed")
        raise
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=5)
        _release_scheduler_run_lock_impl(owner_id, lock_name)


def _daily_push_job_v2_unlocked(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None, audit_run_mode: str = "daily_increment"):
    global _last_run_info
    import time
    logger.info("定时推送任务(v2)开始执行 mode=%s", audit_run_mode)
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    scheduler_cfg = _resolve_scheduler_cfg(config, audit_run_mode)
    scheduler_dept_filter = scheduler_cfg.get("dept_filter")
    dept_list = dept_override if dept_override is not None else (scheduler_dept_filter if scheduler_dept_filter else ConfigParser.get_department_list(config))
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    registry = AuditTypeRegistry(config)
    configured_codes = audit_type_codes_override if audit_type_codes_override is not None else scheduler_cfg.get("audit_type_codes") or []
    if not isinstance(configured_codes, list):
        configured_codes = []
    configured_codes = [str(code or "").strip() for code in configured_codes if str(code or "").strip()]
    configured_codes = list(dict.fromkeys(configured_codes))

    if configured_codes:
        audit_types = []
        for code in configured_codes:
            try:
                audit_types.append(registry.get(code))
            except KeyError:
                logger.warning("定时任务配置的审计类型不存在，已忽略: %s", code)
        if not audit_types:
            if audit_run_mode == "discharge_final":
                logger.error("出院终末调度 audit_type_codes 全部无效，拒绝回退每日默认审计类型")
                duration = int(time.time() - start_time)
                error_msg = "discharge_final audit_type_codes invalid: " + ",".join(configured_codes)
                _write_scheduler_history_safe(
                    query_date=query_date,
                    audit_type_code="__scheduler__",
                    total_records=0,
                    success_count=0,
                    failed_count=0,
                    duration_seconds=duration,
                    status="failed",
                    audit_run_mode=audit_run_mode,
                    error_msg=error_msg,
                    error_code="scheduler_audit_types_invalid",
                )
                with _info_lock:
                    _last_run_info = {
                        "run_time": datetime.now().isoformat(),
                        "query_date": query_date,
                        "audit_type_codes": [],
                        "audit_run_mode": audit_run_mode,
                        "dept_filter": dept_list,
                        "total": 0,
                        "success": 0,
                        "failed": 0,
                        "duration_seconds": duration,
                        "data_source": data_source,
                        "last_error": error_msg,
                    }
                return
            else:
                logger.warning("定时任务 audit_type_codes 全部无效，回退 default_for_schedule")
                audit_types = registry.list_default_schedule()
    else:
        audit_types = registry.list_default_schedule()

    resolved_audit_type_codes = [item.code for item in audit_types]

    total = 0
    success_count = 0
    failed_count = 0
    runtime_error = ""
    history_persist_errors: list[str] = []
    audit_type_errors: list[str] = []

    try:
        for audit_type in audit_types:
            try:
                summary = _run_daily_push_for_audit_type(
                    config=config,
                    data_source=data_source,
                    db_cfg=db_cfg,
                    audit_type=audit_type,
                    query_date=query_date,
                    dept_list=dept_list,
                    push_settings=push_settings,
                    field_mapping=field_mapping,
                    audit_run_mode=audit_run_mode,
                )
            except Exception as exc:
                message = f"{audit_type.code}: {exc}"
                audit_type_errors.append(message)
                failed_count += 1
                logger.error("定时推送单个审计类型失败，继续执行后续类型: %s", message, exc_info=True)
                continue
            total += int(summary.get("total", 0))
            success_count += int(summary.get("success", 0))
            failed_count += int(summary.get("failed", 0))
            if summary.get("history_persist_error"):
                history_persist_errors.append(str(summary["history_persist_error"]))

        last_error = " | ".join([*audit_type_errors, *history_persist_errors])
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "audit_type_codes": resolved_audit_type_codes,
            "audit_run_mode": audit_run_mode,
            "dept_filter": dept_list,
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": last_error,
        }
        with _info_lock:
            _last_run_info = new_info
    except Exception as exc:
        logger.error("定时推送异常: %s", exc, exc_info=True)
        runtime_error = str(exc)
        last_error = runtime_error
        if history_persist_errors:
            last_error = f"{runtime_error} | {' | '.join(history_persist_errors)}"
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "audit_type_codes": resolved_audit_type_codes,
            "audit_run_mode": audit_run_mode,
            "dept_filter": dept_list,
            "total": total,
            "success": success_count,
            "failed": failed_count,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": last_error,
        }
        with _info_lock:
            _last_run_info = new_info
        raise


def trigger_now(_query_date: str = None, _dept_override: list = None, audit_type_codes: list[str] | None = None, _audit_run_mode: str = "daily_increment") -> str:
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        try:
            _daily_push_job_v2(
                query_date_override=_query_date,
                dept_override=_dept_override,
                audit_type_codes_override=audit_type_codes,
                audit_run_mode_override=_audit_run_mode,
            )
        except Exception as e:
            logger.error("手动触发推送线程发生未处理异常: %s", e, exc_info=True)
            with _info_lock:
                new_info = dict(_last_run_info)
                new_info["last_error"] = f"trigger_thread_crash: {e}"
                globals()["_last_run_info"] = new_info

    t = threading.Thread(target=_run, daemon=True, name=f"push-{task_id}")
    t.start()
    return task_id
