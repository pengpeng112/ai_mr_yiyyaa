"""
APScheduler 定时任务调度模块
支持 oracle/postgresql 双数据源
"""
import logging
import time
import threading
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import load_config
from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.database import SessionLocal
from app.models import SchedulerHistory

from app.services import ConfigParser, PushExecutor, PushConfig

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run_info: dict = {}
_scheduler_lock = threading.Lock()
_info_lock = threading.Lock()


def get_scheduler() -> BackgroundScheduler | None:
    with _scheduler_lock:
        return _scheduler


def get_last_run_info() -> dict:
    with _info_lock:
        return dict(_last_run_info)


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
            _daily_push_job,
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


def _daily_push_job(query_date_override: str = None, dept_override: list = None):
    global _last_run_info
    logger.info("定时推送任务开始执行")
    start_time = time.time()

    config = load_config()
    query_date = query_date_override or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = ConfigParser.parse_postgresql_config(config) if data_source == "postgresql" else ConfigParser.parse_oracle_config(config)
    dify_cfg = ConfigParser.parse_dify_config(config)
    dept_list = dept_override if dept_override is not None else ConfigParser.get_department_list(config)
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    db = SessionLocal()
    total = success = failed = 0
    run_status = "completed"
    duration = 0
    runtime_error = ""

    try:
        records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)
        raw_rows = len(records)

        dept_config = config.get("departments", {})
        dept_field = field_mapping.get("dept", "所在科室名称")
        records = ConfigParser.filter_departments(records, dept_config, dept_field)
        filtered_rows = len(records)

        grouped = group_by_patient(records, field_mapping)
        total = len(grouped)

        push_config = PushConfig(
            trigger_type="auto",
            query_date=query_date,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )

        executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)

        success = result.success
        failed = result.failed
        skipped = len([item for item in result.results if str(item.get("status", "")) == "skipped"])
        skip_reason_counts = {}
        for item in result.results:
            if str(item.get("status", "")) == "skipped":
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
        logger.info(
            "[推送漏斗] trigger=auto query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
            query_date,
            raw_rows,
            filtered_rows,
            total,
            success,
            failed,
            skipped,
        )
        if skip_reason_counts:
            logger.info("[推送漏斗] trigger=auto query_date=%s skip_reason_counts=%s", query_date, skip_reason_counts)

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


def trigger_now(_query_date: str = None, _dept_override: list = None) -> str:
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        try:
            _daily_push_job(query_date_override=_query_date, dept_override=_dept_override)
        except Exception as e:
            logger.error("手动触发推送线程发生未处理异常: %s", e, exc_info=True)
            with _info_lock:
                new_info = dict(_last_run_info)
                new_info["last_error"] = f"trigger_thread_crash: {e}"
                globals()["_last_run_info"] = new_info

    t = threading.Thread(target=_run, daemon=True, name=f"push-{task_id}")
    t.start()
    return task_id
