"""
定时任务路由 —— /api/scheduler
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.database import get_db
from app.models import SchedulerHistory
from app.scheduler import get_scheduler, get_last_run_info, update_scheduler, trigger_now, is_scheduler_env_enabled, get_scheduler_lock_info
from app.config import load_config, update_section
from app.schemas import MessageResponse
from app.permissions import require_permission

router = APIRouter()


@router.get("/status", summary="调度器状态")
def scheduler_status(_user=Depends(require_permission("view_scheduler"))):
    sched = get_scheduler()
    config = load_config()
    daily_cfg = config.get("scheduler_daily", {}) or {}
    discharge_cfg = config.get("scheduler_discharge", {}) or {}

    if daily_cfg or discharge_cfg:
        has_dual = True
        legacy_cfg = config.get("scheduler", {}) or {}
    else:
        has_dual = False
        legacy_cfg = config.get("scheduler", {}) or {}
        daily_cfg = legacy_cfg

    last_run = get_last_run_info()
    lock_info = get_scheduler_lock_info()

    running = sched is not None and sched.running if sched else False
    daily_job = sched.get_job("daily_push") if sched else None
    discharge_job = sched.get_job("discharge_push") if sched else None
    daily_next = str(daily_job.next_run_time) if daily_job and daily_job.next_run_time else None
    discharge_next = str(discharge_job.next_run_time) if discharge_job and discharge_job.next_run_time else None
    diagnostics = []

    if not is_scheduler_env_enabled():
        diagnostics.append("ENABLE_SCHEDULER=false，调度器在当前进程被禁用")
    if not running:
        diagnostics.append("调度器未运行，请检查启动日志与生命周期")
    if running and not daily_job and not discharge_job:
        diagnostics.append("调度器运行中但未找到任何任务，可能是 cron 非法或未成功添加")
    if isinstance(last_run, dict) and last_run.get("last_error"):
        diagnostics.append(f"最近一次执行异常: {last_run.get('last_error')}")
    if lock_info.get("status") == "running":
        diagnostics.append(f"已有调度任务运行中: {lock_info.get('owner_id') or 'unknown'}")

    return {
        "running": running,
        "env_enabled": is_scheduler_env_enabled(),
        "has_dual": has_dual,
        "daily": {
            "enabled": daily_cfg.get("enabled", False),
            "cron": daily_cfg.get("cron", ""),
            "schedule_mode": daily_cfg.get("schedule_mode", "daily"),
            "daily_time": daily_cfg.get("daily_time", "10:00"),
            "interval_value": daily_cfg.get("interval_value", 10),
            "interval_unit": daily_cfg.get("interval_unit", "minutes"),
            "audit_run_mode": daily_cfg.get("audit_run_mode", "daily_increment"),
            "audit_type_codes": daily_cfg.get("audit_type_codes") or [],
            "dept_filter": daily_cfg.get("dept_filter"),
            "next_run": daily_next,
        },
        "discharge": {
            "enabled": discharge_cfg.get("enabled", False),
            "cron": discharge_cfg.get("cron", ""),
            "schedule_mode": discharge_cfg.get("schedule_mode", "daily"),
            "daily_time": discharge_cfg.get("daily_time", "11:00"),
            "interval_value": discharge_cfg.get("interval_value", 10),
            "interval_unit": discharge_cfg.get("interval_unit", "minutes"),
            "audit_run_mode": discharge_cfg.get("audit_run_mode", "discharge_final"),
            "audit_type_codes": discharge_cfg.get("audit_type_codes") or [],
            "dept_filter": discharge_cfg.get("dept_filter"),
            "next_run": discharge_next,
        } if has_dual or discharge_cfg else None,
        "legacy": {
            "enabled": legacy_cfg.get("enabled", False),
            "cron": legacy_cfg.get("cron", ""),
            "schedule_mode": legacy_cfg.get("schedule_mode", "daily"),
            "daily_time": legacy_cfg.get("daily_time", "06:00"),
            "interval_value": legacy_cfg.get("interval_value", 10),
            "interval_unit": legacy_cfg.get("interval_unit", "minutes"),
            "audit_run_mode": legacy_cfg.get("audit_run_mode", "daily_increment"),
            "audit_type_codes": legacy_cfg.get("audit_type_codes") or [],
            "dept_filter": legacy_cfg.get("dept_filter"),
        },
        "timezone": "Asia/Shanghai",
        "last_error": last_run.get("last_error") if isinstance(last_run, dict) else None,
        "last_run": last_run,
        "run_lock": lock_info,
        "diagnostics": diagnostics,
    }


@router.post("/start", response_model=MessageResponse, summary="启用定时任务")
def start_scheduler_route(
    job_id: str = Query("daily_push", pattern=r"^(daily_push|discharge_push)$", description="任务ID：daily_push 或 discharge_push"),
    _user=Depends(require_permission("manage_scheduler")),
):
    config = load_config()
    if job_id == "discharge_push":
        sched_cfg = config.get("scheduler_discharge", {}) or {}
        section = "scheduler_discharge"
    else:
        sched_cfg = config.get("scheduler_daily") or config.get("scheduler", {}) or {}
        section = "scheduler_daily" if config.get("scheduler_daily") else "scheduler"
    sched_cfg["enabled"] = True
    update_section(section, sched_cfg)
    if job_id == "discharge_push":
        audit_run_mode = sched_cfg.get("audit_run_mode", "discharge_final")
        default_cron = "0 11 * * *"
    else:
        audit_run_mode = sched_cfg.get("audit_run_mode", "daily_increment")
        default_cron = "0 6 * * *"
    result = update_scheduler(True, sched_cfg.get("cron", default_cron), audit_run_mode, job_id)
    if result and not result.get("applied"):
        return MessageResponse(message=f"定时任务配置已保存，但未应用: {result.get('message', '')}", success=False)
    return MessageResponse(message=f"定时任务已启用: {job_id}")


@router.post("/stop", response_model=MessageResponse, summary="停用定时任务")
def stop_scheduler_route(
    job_id: str = Query("daily_push", pattern=r"^(daily_push|discharge_push)$", description="任务ID：daily_push 或 discharge_push"),
    _user=Depends(require_permission("manage_scheduler")),
):
    config = load_config()
    if job_id == "discharge_push":
        sched_cfg = config.get("scheduler_discharge", {}) or {}
        section = "scheduler_discharge"
    else:
        sched_cfg = config.get("scheduler_daily") or config.get("scheduler", {}) or {}
        section = "scheduler_daily" if config.get("scheduler_daily") else "scheduler"
    sched_cfg["enabled"] = False
    update_section(section, sched_cfg)
    update_scheduler(False, "", "daily_increment", job_id)
    return MessageResponse(message=f"定时任务已停用: {job_id}")


@router.post("/trigger", summary="立即触发一次推送")
def trigger_now_route(
    query_date: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="可选，自定义查询日期 yyyy-mm-dd"),
    audit_type_codes: str | None = Query(None, description="逗号分隔的审计类型编码，临时覆盖本次执行"),
    dept_filter: str | None = Query(None, description="逗号分隔的科室编码或名称，临时覆盖本次执行"),
    audit_run_mode: str | None = Query(None, pattern=r"^(daily_increment|discharge_final)$", description="质控运行模式"),
    _user=Depends(require_permission("manage_scheduler")),
):
    if query_date:
        datetime.strptime(query_date, "%Y-%m-%d")

    codes = []
    if audit_type_codes:
        codes = [item.strip() for item in audit_type_codes.split(",") if item.strip()]
    depts = []
    if dept_filter:
        depts = [item.strip() for item in dept_filter.split(",") if item.strip()]

    _mode = audit_run_mode or "daily_increment"
    task_id = trigger_now(query_date, _dept_override=depts if dept_filter is not None else None, audit_type_codes=codes or None, _audit_run_mode=_mode)
    return {
        "message": "已触发推送任务",
        "task_id": task_id,
        "query_date": query_date or "昨天",
        "audit_type_codes": codes,
        "dept_filter": depts,
        "audit_run_mode": _mode,
    }


@router.get("/history", summary="执行历史")
def scheduler_history(
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("view_scheduler")),
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
                "audit_type_code": getattr(h, "audit_type_code", "") or "progress_vs_nursing",
                "total_records": h.total_records,
                "success_count": h.success_count,
                "failed_count": h.failed_count,
                "duration_seconds": h.duration_seconds,
                "status": h.status,
            }
            for h in items
        ],
    }
