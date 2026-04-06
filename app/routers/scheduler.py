"""
定时任务路由 —— /api/scheduler
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.database import get_db
from app.models import SchedulerHistory
from app.scheduler import get_scheduler, get_last_run_info, update_scheduler, trigger_now, is_scheduler_env_enabled
from app.config import load_config, update_section
from app.schemas import MessageResponse

router = APIRouter()


@router.get("/status", summary="调度器状态")
def scheduler_status():
    sched = get_scheduler()
    config = load_config().get("scheduler", {})
    last_run = get_last_run_info()

    running = sched is not None and sched.running if sched else False
    job = sched.get_job("daily_push") if sched else None
    next_run = str(job.next_run_time) if job and job.next_run_time else None
    diagnostics = []

    if not is_scheduler_env_enabled():
        diagnostics.append("ENABLE_SCHEDULER=false，调度器在当前进程被禁用")
    if config.get("enabled", False) and not running:
        diagnostics.append("配置已启用但调度器未运行，请检查启动日志与生命周期")
    if running and config.get("enabled", False) and job is None:
        diagnostics.append("调度器运行中但未找到 daily_push 任务，可能是 cron 非法或未成功添加")
    if running and config.get("enabled", False) and job is not None and not next_run:
        diagnostics.append("任务存在但 next_run 为空，可能处于暂停或触发器异常状态")
    if isinstance(last_run, dict) and last_run.get("last_error"):
        diagnostics.append(f"最近一次执行异常: {last_run.get('last_error')}")

    return {
        "running": running,
        "env_enabled": is_scheduler_env_enabled(),
        "enabled": config.get("enabled", False),
        "cron": config.get("cron", ""),
        "schedule_mode": config.get("schedule_mode", "daily"),
        "daily_time": config.get("daily_time", "06:00"),
        "interval_value": config.get("interval_value", 10),
        "interval_unit": config.get("interval_unit", "minutes"),
        "job_exists": job is not None,
        "job_id": job.id if job else None,
        "timezone": "Asia/Shanghai",
        "next_run": next_run,
        "last_error": last_run.get("last_error") if isinstance(last_run, dict) else None,
        "last_run": last_run,
        "diagnostics": diagnostics,
    }


@router.post("/start", response_model=MessageResponse, summary="启用定时任务")
def start_scheduler_route():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    sched_cfg["enabled"] = True
    update_section("scheduler", sched_cfg)
    result = update_scheduler(True, sched_cfg.get("cron", "0 6 * * *"))
    if result and not result.get("applied"):
        return MessageResponse(message=f"定时任务配置已保存，但未应用: {result.get('message', '')}", success=False)
    return MessageResponse(message="定时任务已启用")


@router.post("/stop", response_model=MessageResponse, summary="停用定时任务")
def stop_scheduler_route():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    sched_cfg["enabled"] = False
    update_section("scheduler", sched_cfg)
    update_scheduler(False, "")
    return MessageResponse(message="定时任务已停用")


@router.post("/trigger", summary="立即触发一次推送")
def trigger_now_route(query_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="可选，自定义查询日期 yyyy-mm-dd")):
    if query_date:
        datetime.strptime(query_date, "%Y-%m-%d")
    task_id = trigger_now(query_date)
    return {"message": "已触发推送任务", "task_id": task_id, "query_date": query_date or "昨天"}


@router.get("/history", summary="执行历史")
def scheduler_history(
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    q = db.query(SchedulerHistory)
    total = q.count()
    items = (
        q.order_by(desc(SchedulerHistory.run_time))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": h.id,
                "run_time": h.run_time.strftime("%Y-%m-%d %H:%M:%S") if h.run_time else "",
                "trigger_type": h.trigger_type,
                "query_date": h.query_date,
                "total_records": h.total_records,
                "success_count": h.success_count,
                "failed_count": h.failed_count,
                "duration_seconds": h.duration_seconds,
                "status": h.status,
            }
            for h in items
        ],
    }
