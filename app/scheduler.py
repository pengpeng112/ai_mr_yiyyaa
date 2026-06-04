"""
APScheduler 定时任务调度模块
支持 oracle/postgresql 双数据源
"""
import logging
import os
import socket
import time
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

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run_info: dict = {}
_scheduler_lock = threading.Lock()
_info_lock = threading.Lock()
_RUN_LOCK_NAME = "daily_push"


def get_scheduler() -> BackgroundScheduler | None:
    with _scheduler_lock:
        return _scheduler


def get_last_run_info() -> dict:
    with _info_lock:
        return dict(_last_run_info)


def _make_lock_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}:{uuid.uuid4().hex[:8]}"


def get_scheduler_lock_info() -> dict:
    db = SessionLocal()
    try:
        lock = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
        if not lock:
            return {"status": "idle", "owner_id": "", "acquired_at": None, "heartbeat_at": None}
        return {
            "status": lock.status,
            "owner_id": lock.owner_id or "",
            "acquired_at": lock.acquired_at.isoformat() if lock.acquired_at else None,
            "heartbeat_at": lock.heartbeat_at.isoformat() if lock.heartbeat_at else None,
        }
    finally:
        db.close()


def _acquire_scheduler_run_lock() -> tuple[bool, str, str]:
    owner_id = _make_lock_owner()
    db = SessionLocal()
    try:
        now = datetime.now()
        updated = db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == _RUN_LOCK_NAME,
            SchedulerRunLock.status != "running",
        ).update(
            {
                "owner_id": owner_id,
                "status": "running",
                "acquired_at": now,
                "heartbeat_at": now,
                "released_at": None,
            },
            synchronize_session=False,
        )
        if updated:
            db.commit()
            return True, owner_id, "acquired"

        existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
        if existing:
            db.rollback()
            return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"

        db.add(SchedulerRunLock(
            lock_name=_RUN_LOCK_NAME,
            owner_id=owner_id,
            status="running",
            acquired_at=now,
            heartbeat_at=now,
        ))
        try:
            db.commit()
            return True, owner_id, "acquired"
        except Exception:
            db.rollback()
            existing = db.query(SchedulerRunLock).filter(SchedulerRunLock.lock_name == _RUN_LOCK_NAME).first()
            if existing and existing.status == "running":
                return False, existing.owner_id or "", f"scheduler lock is running by {existing.owner_id or 'unknown'}"
            raise
    finally:
        db.close()


def _release_scheduler_run_lock(owner_id: str) -> None:
    db = SessionLocal()
    try:
        db.query(SchedulerRunLock).filter(
            SchedulerRunLock.lock_name == _RUN_LOCK_NAME,
            SchedulerRunLock.owner_id == owner_id,
            SchedulerRunLock.status == "running",
        ).update(
            {
                "status": "idle",
                "released_at": datetime.now(),
                "heartbeat_at": datetime.now(),
            },
            synchronize_session=False,
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.error("调度运行锁释放失败 owner_id=%s", owner_id, exc_info=True)
    finally:
        db.close()


def is_scheduler_env_enabled() -> bool:
    import os
    return os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"


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
        sched_cfg = config.get("scheduler", {})

        if sched_cfg.get("enabled", False):
            ok, msg = _add_cron_job(sched_cfg.get("cron", "0 6 * * *"))
            if not ok:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = msg
                    globals()["_last_run_info"] = new_info
                logger.error("定时任务初始化失败: %s", msg)

        # 注册数据留存清理定时任务
        _add_retention_cleanup_job()

        _scheduler.start()
        logger.info("调度器已启动")


def shutdown_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            _scheduler = None
            logger.info("调度器已关闭")


def update_scheduler(enabled: bool, cron: str):
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

        if _scheduler.get_job("daily_push"):
            _scheduler.remove_job("daily_push")

        if enabled:
            ok, msg = _add_cron_job(cron)
            if not ok:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = msg
                    globals()["_last_run_info"] = new_info
                return {"applied": False, "message": msg, "next_run": None}
            job = _scheduler.get_job("daily_push")
            next_run = str(job.next_run_time) if job and job.next_run_time else None
            logger.info(f"定时任务已更新: cron={cron}, next_run={next_run}")
            return {"applied": True, "message": "ok", "next_run": next_run}
        logger.info("定时任务已禁用")
        return {"applied": True, "message": "disabled", "next_run": None}


def _add_cron_job(cron_expr: str):
    valid, message = validate_cron_expression(cron_expr)
    if not valid:
        return False, message

    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone="Asia/Shanghai")
        _scheduler.add_job(
            _daily_push_job_v2,
            trigger=trigger,
            id="daily_push",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        return True, "ok"
    except Exception as e:
        logger.error("添加定时任务失败: %s", e, exc_info=True)
        return False, str(e)


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


def _retention_cleanup_job():
    """数据留存清理任务入口"""
    logger.info("数据留存清理任务开始执行")
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


def _run_daily_push_for_audit_type(
    config: dict,
    data_source: str,
    db_cfg: dict,
    audit_type,
    query_date: str,
    dept_list: list,
    push_settings: dict,
    field_mapping: dict,
) -> dict:
    start_time = time.time()
    db = SessionLocal()
    grouped = {}
    success = 0
    failed = 0
    skipped = 0
    status = "completed"
    raw_rows = 0
    filtered_rows = 0
    pending_error = None
    history_persist_error = ""

    try:
        payload_cfg = audit_type.payload or {}
        if str(payload_cfg.get("builder") or "") == "legacy_progress_nursing":
            records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
            raw_rows = len(records)
            dept_config = config.get("departments", {})
            dept_field = field_mapping.get("dept", "所在科室名称")
            records = ConfigParser.filter_departments(records, dept_config, dept_field)
            filtered_rows = len(records)
            grouped = group_by_patient(records, field_mapping)
            dify_legacy = ConfigParser.parse_dify_config(config)
            persisted = ConfigParser.parse_persisted_dify_targets(config)
            if persisted:
                executor = BulkPushExecutor(
                    dify_config=dify_legacy,
                    notify_config=config.get("notify", {}),
                    field_mapping=field_mapping,
                    dify_targets=persisted,
                )
            else:
                executor = PushExecutor(dify_legacy, config.get("notify", {}), field_mapping)
        else:
            bundles = load_patient_bundles(
                audit_type=audit_type,
                root_config=config,
                query_date=query_date,
                date_dimension="query_date",
                dept_filter=dept_list,
            )
            raw_rows = len(bundles)
            filtered_rows = len(bundles)
            grouped = {bundle.bundle_id: bundle for bundle in bundles}
            override_dify = audit_type.dify.model_dump()
            if override_dify.get("api_key_enc") and not override_dify.get("api_key"):
                override_dify["api_key"] = ConfigParser.parse_dify_config({"dify": override_dify}).get("api_key", "")

            persisted = ConfigParser.parse_persisted_dify_targets(config)
            if persisted:
                executor = BulkPushExecutor(
                    dify_config=override_dify,
                    notify_config=config.get("notify", {}),
                    field_mapping=field_mapping,
                    dify_targets=persisted,
                )
            else:
                executor = PushExecutor(override_dify, config.get("notify", {}), field_mapping)

        push_config = PushConfig(
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type.code,
            audit_type=audit_type,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        if isinstance(executor, BulkPushExecutor):
            result = executor.execute(grouped, push_config)
        else:
            result = executor.execute(db, grouped, push_config)
        success = int(result.success)
        failed = int(result.failed)
        skipped = int(getattr(result, "skipped", 0) or len([item for item in result.results if str(item.get("status", "")) == "skipped"]))

        skip_reason_counts = {}
        for item in result.results:
            if str(item.get("status", "")) == "skipped":
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
        logger.info(
            "[推送漏斗] trigger=auto audit_type=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
            audit_type.code,
            query_date,
            raw_rows,
            filtered_rows,
            len(grouped),
            success,
            failed,
            skipped,
        )
        if skip_reason_counts:
            logger.info(
                "[推送漏斗] trigger=auto audit_type=%s query_date=%s skip_reason_counts=%s",
                audit_type.code,
                query_date,
                skip_reason_counts,
            )
    except Exception as exc:
        db.rollback()
        status = "failed"
        pending_error = exc
        logger.error("定时推送类型执行异常: audit_type=%s err=%s", getattr(audit_type, "code", ""), exc, exc_info=True)
    finally:
        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            audit_type_code=audit_type.code,
            total_records=len(grouped),
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status=status,
        )
        try:
            db.add(history)
            db.commit()
        except Exception as persist_error:
            db.rollback()
            history_persist_error = f"history_persist_failed: {persist_error}"
            logger.error("定时任务历史写入失败: audit_type=%s err=%s", audit_type.code, persist_error, exc_info=True)
        db.close()

    if pending_error:
        raise pending_error
    return {
        "total": len(grouped),
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "history_persist_error": history_persist_error,
    }


def _daily_push_job(query_date_override: str = None, dept_override: list = None):
    global _last_run_info
    logger.info("定时推送任务开始执行")
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    scheduler_cfg = config.get("scheduler", {}) or {}
    scheduler_dept_filter = scheduler_cfg.get("dept_filter")
    dept_list = dept_override if dept_override is not None else (scheduler_dept_filter if scheduler_dept_filter else ConfigParser.get_department_list(config))
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    registry = AuditTypeRegistry(config)
    audit_types = registry.list_default_schedule()

    total = success = failed = 0
    runtime_error = ""
    run_status = "completed"
    history_persist_errors: list[str] = []

    try:
        for audit_type in audit_types:
            payload_cfg = audit_type.payload or {}
            if str(payload_cfg.get("builder") or "") == "legacy_progress_nursing":
                records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
                raw_rows = len(records)
                dept_config = config.get("departments", {})
                dept_field = field_mapping.get("dept", "所在科室名称")
                records = ConfigParser.filter_departments(records, dept_config, dept_field)
                filtered_rows = len(records)
                grouped = group_by_patient(records, field_mapping)
                dify_cfg = ConfigParser.parse_dify_config(config)
                persisted = ConfigParser.parse_persisted_dify_targets(config)
                if persisted:
                    executor = BulkPushExecutor(
                        dify_config=dify_cfg,
                        notify_config=config.get("notify", {}),
                        field_mapping=field_mapping,
                        dify_targets=persisted,
                    )
                else:
                    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
            else:
                bundles = load_patient_bundles(
                    audit_type=audit_type,
                    root_config=config,
                    query_date=query_date,
                    date_dimension="query_date",
                    dept_filter=dept_list,
                )
                raw_rows = len(bundles)
                filtered_rows = len(bundles)
                grouped = {bundle.bundle_id: bundle for bundle in bundles}
                override_dify = audit_type.dify.model_dump()
                if override_dify.get("api_key_enc") and not override_dify.get("api_key"):
                    override_dify["api_key"] = ConfigParser.parse_dify_config({"dify": override_dify}).get("api_key", "")

                persisted = ConfigParser.parse_persisted_dify_targets(config)
                if persisted:
                    executor = BulkPushExecutor(
                        dify_config=override_dify,
                        notify_config=config.get("notify", {}),
                        field_mapping=field_mapping,
                        dify_targets=persisted,
                    )
                else:
                    executor = PushExecutor(override_dify, config.get("notify", {}), field_mapping)

            total += len(grouped)
            push_config = PushConfig(
                trigger_type="auto",
                query_date=query_date,
                audit_type_code=audit_type.code,
                audit_type=audit_type,
                interval_ms=push_settings["interval_ms"],
                max_retry=push_settings["max_retry"],
                notify_enabled=True,
            )
            if isinstance(executor, BulkPushExecutor):
                result = executor.execute(grouped, push_config)
            else:
                result = executor.execute(db, grouped, push_config)
            success += result.success
            failed += result.failed
            skipped = len([item for item in result.results if str(item.get("status", "")) == "skipped"])
            skip_reason_counts = {}
            for item in result.results:
                if str(item.get("status", "")) == "skipped":
                    reason = str(item.get("skip_reason", "unknown") or "unknown")
                    skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
            logger.info(
                "[推送漏斗] trigger=auto audit_type=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
                audit_type.code,
                query_date,
                raw_rows,
                filtered_rows,
                len(grouped),
                result.success,
                result.failed,
                skipped,
            )
            if skip_reason_counts:
                logger.info(
                    "[推送漏斗] trigger=auto audit_type=%s query_date=%s skip_reason_counts=%s",
                    audit_type.code,
                    query_date,
                    skip_reason_counts,
                )

        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": "",
        }
        with _info_lock:
            _last_run_info = new_info

    except Exception as e:
        logger.error(f"定时推送异常: {e}", exc_info=True)
        db.rollback()
        run_status = "failed"
        runtime_error = str(e)
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": str(e),
        }
        with _info_lock:
            _last_run_info = new_info
    finally:
        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            total_records=total,
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status=run_status,
        )
        try:
            db.add(history)
            db.commit()
        except Exception as persist_error:
            db.rollback()
            logger.error("定时任务历史写入失败: %s", persist_error, exc_info=True)
            persist_msg = f"history_persist_failed: {persist_error}"
            if runtime_error:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = f"{runtime_error} | {persist_msg}"
                    _last_run_info = new_info
            else:
                with _info_lock:
                    new_info = dict(_last_run_info)
                    new_info["last_error"] = persist_msg
                    _last_run_info = new_info
        db.close()


def _daily_push_job_v2(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None):
    global _last_run_info
    acquired, owner_id, message = _acquire_scheduler_run_lock()
    if not acquired:
        logger.warning("定时推送任务(v2)跳过：%s", message)
        with _info_lock:
            new_info = dict(_last_run_info)
            new_info.update({
                "run_time": datetime.now().isoformat(),
                "last_error": message,
                "lock_owner": owner_id,
            })
            _last_run_info = new_info
        return
    try:
        _daily_push_job_v2_unlocked(query_date_override=query_date_override, dept_override=dept_override, audit_type_codes_override=audit_type_codes_override)
    finally:
        _release_scheduler_run_lock(owner_id)


def _daily_push_job_v2_unlocked(query_date_override: str = None, dept_override: list = None, audit_type_codes_override: list[str] | None = None):
    global _last_run_info
    logger.info("定时推送任务(v2)开始执行")
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    scheduler_cfg = config.get("scheduler", {}) or {}
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
            logger.warning("定时任务 audit_type_codes 全部无效，回退 default_for_schedule")
            audit_types = registry.list_default_schedule()
    else:
        audit_types = registry.list_default_schedule()

    resolved_audit_type_codes = [item.code for item in audit_types]

    total = 0
    success = 0
    failed = 0
    runtime_error = ""
    history_persist_errors: list[str] = []

    try:
        for audit_type in audit_types:
            summary = _run_daily_push_for_audit_type(
                config=config,
                data_source=data_source,
                db_cfg=db_cfg,
                audit_type=audit_type,
                query_date=query_date,
                dept_list=dept_list,
                push_settings=push_settings,
                field_mapping=field_mapping,
            )
            total += int(summary.get("total", 0))
            success += int(summary.get("success", 0))
            failed += int(summary.get("failed", 0))
            if summary.get("history_persist_error"):
                history_persist_errors.append(str(summary["history_persist_error"]))

        last_error = " | ".join(history_persist_errors)
        new_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "audit_type_codes": resolved_audit_type_codes,
            "dept_filter": dept_list,
            "total": total,
            "success": success,
            "failed": failed,
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
            "dept_filter": dept_list,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": int(time.time() - start_time),
            "data_source": data_source,
            "last_error": last_error,
        }
        with _info_lock:
            _last_run_info = new_info
        raise


def trigger_now(_query_date: str = None, _dept_override: list = None, audit_type_codes: list[str] | None = None) -> str:
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        try:
            _daily_push_job_v2(query_date_override=_query_date, dept_override=_dept_override, audit_type_codes_override=audit_type_codes)
        except Exception as e:
            logger.error("手动触发推送线程发生未处理异常: %s", e, exc_info=True)
            with _info_lock:
                new_info = dict(_last_run_info)
                new_info["last_error"] = f"trigger_thread_crash: {e}"
                globals()["_last_run_info"] = new_info

    t = threading.Thread(target=_run, daemon=True, name=f"push-{task_id}")
    t.start()
    return task_id
