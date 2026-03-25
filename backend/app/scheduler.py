"""
APScheduler 定时任务调度模块
"""
import logging
import time
import json
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import load_config, decrypt_value
from app.oracle_client import fetch_records, group_by_patient, build_mr_text_combined
from app.dify_pusher import push_to_dify
from app.database import SessionLocal
from app.models import PushLog, SchedulerHistory

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_last_run_info: dict = {}


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler


def get_last_run_info() -> dict:
    return _last_run_info


def start_scheduler():
    """启动定时调度器"""
    global _scheduler
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")

    config = load_config()
    sched_cfg = config.get("scheduler", {})

    if sched_cfg.get("enabled", False):
        cron_expr = sched_cfg.get("cron", "0 6 * * *")
        _add_cron_job(cron_expr)

    _scheduler.start()
    logger.info("调度器已启动")


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("调度器已关闭")


def update_scheduler(enabled: bool, cron: str):
    """动态更新定时任务"""
    global _scheduler
    if not _scheduler:
        return

    # 移除旧任务
    if _scheduler.get_job("daily_push"):
        _scheduler.remove_job("daily_push")

    if enabled:
        _add_cron_job(cron)
        logger.info(f"定时任务已更新: cron={cron}")
    else:
        logger.info("定时任务已禁用")


def _add_cron_job(cron_expr: str):
    """根据 cron 表达式添加任务"""
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


def _daily_push_job():
    """定时推送任务入口"""
    global _last_run_info
    logger.info("定时推送任务开始执行")
    start_time = time.time()

    config = load_config()
    query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    # 解密 Oracle 密码
    oracle_cfg = config.get("oracle", {})
    try:
        oracle_cfg["password"] = decrypt_value(oracle_cfg.get("password_enc", ""))
    except Exception:
        oracle_cfg["password"] = ""

    # 解密 Dify API Key
    dify_cfg = config.get("dify", {})
    try:
        dify_cfg["api_key"] = decrypt_value(dify_cfg.get("api_key_enc", ""))
    except Exception:
        dify_cfg["api_key"] = ""

    # 科室过滤
    dept_cfg = config.get("departments", {})
    dept_list = dept_cfg.get("list", [])
    if dept_cfg.get("mode") == "exclude":
        # exclude 模式需要先查全部科室再排除
        dept_list = []  # 暂时传空（查全部），后续在结果中排除

    push_cfg = config.get("push", {})
    interval_ms = push_cfg.get("interval_ms", 500)

    db = SessionLocal()
    total = success = failed = 0

    try:
        records = fetch_records(oracle_cfg, dept_list, query_date)

        # exclude 模式过滤
        if dept_cfg.get("mode") == "exclude" and dept_cfg.get("list"):
            exclude_set = set(dept_cfg["list"])
            records = [r for r in records if r.get("科室") not in exclude_set]

        grouped = group_by_patient(records)
        total = len(grouped)

        for patient_id, patient_records in grouped.items():
            mr_text = build_mr_text_combined(patient_records)
            result = push_to_dify(mr_text, dify_cfg, patient_id)

            log = PushLog(
                push_time=datetime.now(),
                trigger_type="auto",
                query_date=query_date,
                patient_id=patient_id,
                patient_name=patient_records[0].get("姓名", ""),
                dept=patient_records[0].get("科室", ""),
                workflow_run_id=result.get("workflow_run_id", ""),
                task_id=result.get("task_id", ""),
                status=result.get("status", "failed"),
                ai_result=json.dumps(result.get("result", {}), ensure_ascii=False),
                inconsistency=1 if result.get("inconsistency") else 0,
                severity=result.get("severity", ""),
                error_msg=result.get("error", ""),
                elapsed_ms=result.get("elapsed_ms", 0),
                mr_text=mr_text,
            )
            db.add(log)

            if result.get("status") == "success":
                success += 1
            else:
                failed += 1

            time.sleep(interval_ms / 1000)

        db.commit()

        # 记录调度历史
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
        }

        logger.info(f"定时推送完成: total={total}, success={success}, failed={failed}")

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


def trigger_now(query_date: str = None, dept_override: list = None) -> str:
    """立即触发一次推送（用于手动触发）"""
    import threading
    import uuid

    task_id = str(uuid.uuid4())[:8]

    def _run():
        _daily_push_job()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return task_id
