"""
APScheduler 定时任务调度模块
支持 oracle/postgresql 双数据源
"""
import logging
import time
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


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def get_last_run_info() -> dict:
    return _last_run_info


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        logger.info("调度器已在运行，跳过重复启动")
        return

    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    config = load_config()
    sched_cfg = config.get("scheduler", {})

    if sched_cfg.get("enabled", False):
        _add_cron_job(sched_cfg.get("cron", "0 6 * * *"))

    _scheduler.start()
    logger.info("调度器已启动")


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("调度器已关闭")


def update_scheduler(enabled: bool, cron: str):
    global _scheduler
    if not _scheduler:
        return

    if _scheduler.get_job("daily_push"):
        _scheduler.remove_job("daily_push")

    if enabled:
        _add_cron_job(cron)
        logger.info(f"定时任务已更新: cron={cron}")
    else:
        logger.info("定时任务已禁用")


def _add_cron_job(cron_expr: str):
    parts = cron_expr.split()
    if len(parts) != 5:
        logger.error(f"无效的 cron 表达式: {cron_expr}")
        return

    trigger = CronTrigger(
        minute=parts[0],
        hour=parts[1],
        day=parts[2],
        month=parts[3],
        day_of_week=parts[4],
    )
    _scheduler.add_job(
        _daily_push_job,
        trigger=trigger,
        id="daily_push",
        replace_existing=True,
        max_instances=1,
    )


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

    try:
        records = fetch_pg_records(db_cfg, dept_list, query_date) if data_source == "postgresql" else fetch_records(db_cfg, dept_list, query_date)

        dept_config = config.get("departments", {})
        dept_field = field_mapping.get("dept", "所在科室名称")
        records = ConfigParser.filter_departments(records, dept_config, dept_field)

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

        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            total_records=total,
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status="completed",
        )
        db.add(history)
        db.commit()

        _last_run_info = {
            "run_time": datetime.now().isoformat(),
            "query_date": query_date,
            "total": total,
            "success": success,
            "failed": failed,
            "duration_seconds": duration,
            "data_source": data_source,
        }

    except Exception as e:
        logger.error(f"定时推送异常: {e}", exc_info=True)
        duration = int(time.time() - start_time)
        history = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date=query_date,
            total_records=total,
            success_count=success,
            failed_count=failed,
            duration_seconds=duration,
            status="failed",
        )
        db.add(history)
        db.commit()
    finally:
        db.close()


def trigger_now(_query_date: str = None, _dept_override: list = None) -> str:
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        _daily_push_job(query_date_override=_query_date, dept_override=_dept_override)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return task_id
