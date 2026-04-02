"""
定时任务路由 —— /api/scheduler
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database import get_db
from app.models import SchedulerHistory
from app.scheduler import get_scheduler, get_last_run_info, update_scheduler, trigger_now
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
    next_run = str(job.next_run_time) if job else None

    return {
        "running": running,
        "enabled": config.get("enabled", False),
        "cron": config.get("cron", ""),
        "next_run": next_run,
        "last_run": last_run,
    }


@router.post("/start", response_model=MessageResponse, summary="启用定时任务")
def start_scheduler_route():
    config = load_config()
    sched_cfg = config.get("scheduler", {})
    sched_cfg["enabled"] = True
    update_section("scheduler", sched_cfg)
    update_scheduler(True, sched_cfg.get("cron", "0 6 * * *"))
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
def trigger_now_route():
    task_id = trigger_now()
    return {"message": "已触发推送任务", "task_id": task_id}


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
                "run_time": h.run_time.isoformat() if h.run_time else "",
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
