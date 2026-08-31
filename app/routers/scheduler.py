"""
定时任务路由 —— /api/scheduler
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, timedelta
from typing import Optional

from app.database import get_db
from app.models import SchedulerHistory
from app.scheduler import get_scheduler, get_last_run_info, update_scheduler, trigger_now, is_scheduler_env_enabled, get_scheduler_lock_info
from app.config import load_config, update_section
from app.schemas import MessageResponse
from app.permissions import require_permission
from app.services.scheduler_run_summary import (
    attach_history_item_flags,
    build_scheduler_run_summary,
    sanitize_error_summary,
)

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
    daily_lock_info = get_scheduler_lock_info("daily_push")
    discharge_lock_info = get_scheduler_lock_info("discharge_push")
    run_locks = {
        "daily_push": daily_lock_info,
        "discharge_push": discharge_lock_info,
    }

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
        diagnostics.append(
            f"最近一次执行异常: {sanitize_error_summary(last_run.get('last_error'))}"
        )
    for lock_name, lock_info in run_locks.items():
        if lock_info.get("status") != "running":
            continue
        if lock_info.get("is_stale"):
            diagnostics.append(
                f"调度锁疑似陈旧: {lock_name}，"
                f"心跳已中断 {lock_info.get('heartbeat_age_seconds')} 秒；"
                "下次同名任务将通过原子接管恢复"
            )
        else:
            diagnostics.append(
                f"已有调度任务运行中: {lock_name} / "
                f"{lock_info.get('owner_id') or 'unknown'}"
            )

    # 最近一次运行完整性线索（不查库；完整明细见 /run-summary）
    last_run_view = None
    if isinstance(last_run, dict) and last_run:
        last_run_view = dict(last_run)
        last_run_view["last_error"] = sanitize_error_summary(last_run.get("last_error"))
        # 不能仅因 failed=0 推导成功
        failed_n = int(last_run.get("failed") or 0)
        last_error = str(last_run.get("last_error") or "").strip()
        if last_error:
            last_run_view["completeness_hint"] = "partial_or_failed"
            last_run_view["incomplete"] = True
            diagnostics.append("最近一次运行存在类型级错误，PushLog failed=0 不能代表整体成功")
        elif failed_n > 0:
            last_run_view["completeness_hint"] = "has_push_failures"
            last_run_view["incomplete"] = True
        else:
            last_run_view["completeness_hint"] = "needs_run_summary"
            last_run_view["incomplete"] = False

    # discharge_final 类型级生效性诊断（035/RP2：合法类型 fallback 未生效从 info 日志升级为可见告警）
    from app.services.scheduler_run_modes import discharge_effectiveness_warnings
    discharge_warnings = discharge_effectiveness_warnings(config)
    for warn_item in discharge_warnings:
        diagnostics.append(
            f"出院终末模式生效性告警: {warn_item.get('code')}"
            + (f".{warn_item.get('source')}" if warn_item.get("source") else "")
            + f" — {warn_item.get('detail')}"
        )

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
        "last_error": sanitize_error_summary(last_run.get("last_error")) if isinstance(last_run, dict) else None,
        "last_run": last_run_view if last_run_view is not None else last_run,
        # run_lock 保留旧客户端的 daily_push 单锁响应；新客户端读取 run_locks。
        "run_lock": daily_lock_info,
        "run_locks": run_locks,
        "discharge_effectiveness": {
            "checked": bool(discharge_cfg.get("enabled")),
            "warnings": discharge_warnings,
        },
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
        sched_cfg["enabled"] = True
        sched_cfg.setdefault("audit_run_mode", "discharge_final")
        sched_cfg.setdefault("cron", "0 11 * * *")
        sched_cfg.setdefault("schedule_mode", "daily")
        sched_cfg.setdefault("daily_time", "11:00")
        sched_cfg.setdefault("audit_type_codes", ["progress_vs_nursing"])
        sched_cfg.setdefault("dept_filter", [])
    else:
        daily_cfg = config.get("scheduler_daily") or {}
        sched_cfg = daily_cfg if daily_cfg.get("enabled") is not None else (config.get("scheduler") or {})
        section = "scheduler_daily" if (daily_cfg and daily_cfg.get("enabled") is not None) else "scheduler"
        sched_cfg["enabled"] = True
        sched_cfg.setdefault("audit_run_mode", "daily_increment")
        sched_cfg.setdefault("cron", "0 6 * * *")
        sched_cfg.setdefault("schedule_mode", "daily")
        sched_cfg.setdefault("daily_time", "06:00")
        sched_cfg.setdefault("audit_type_codes", [])
        sched_cfg.setdefault("dept_filter", [])
    update_section(section, sched_cfg)
    if job_id == "discharge_push":
        audit_run_mode = sched_cfg["audit_run_mode"]
        default_cron = "0 11 * * *"
    else:
        audit_run_mode = sched_cfg["audit_run_mode"]
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
        daily_cfg = config.get("scheduler_daily") or {}
        sched_cfg = daily_cfg if daily_cfg.get("enabled") is not None else (config.get("scheduler") or {})
        section = "scheduler_daily" if (daily_cfg and daily_cfg.get("enabled") is not None) else "scheduler"
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
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    status: Optional[str] = None,
    trigger_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    audit_run_mode: Optional[str] = None,
    db: Session = Depends(get_db),
    _user=Depends(require_permission("view_scheduler")),
):
    allowed_status = {"running", "completed", "failed", "cancelled"}
    allowed_trigger = {"auto", "manual", "retry"}
    allowed_modes = {"daily_increment", "discharge_final"}
    if status and status not in allowed_status:
        raise HTTPException(status_code=422, detail="invalid status")
    if trigger_type and trigger_type not in allowed_trigger:
        raise HTTPException(status_code=422, detail="invalid trigger_type")
    if audit_run_mode and audit_run_mode not in allowed_modes:
        raise HTTPException(status_code=422, detail="invalid audit_run_mode")

    def parse_date(value: Optional[str], name: str):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"invalid {name}")

    from_dt = parse_date(date_from, "date_from")
    to_dt = parse_date(date_to, "date_to")
    if from_dt and to_dt and from_dt > to_dt:
        raise HTTPException(status_code=422, detail="date_from must be before or equal to date_to")
    q = db.query(SchedulerHistory)
    if status:
        q = q.filter(SchedulerHistory.status == status)
    if trigger_type:
        q = q.filter(SchedulerHistory.trigger_type == trigger_type)
    if audit_run_mode:
        q = q.filter(SchedulerHistory.audit_run_mode == audit_run_mode)
    if from_dt:
        q = q.filter(SchedulerHistory.run_time >= from_dt)
    if to_dt:
        q = q.filter(SchedulerHistory.run_time < to_dt + timedelta(days=1))
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
            attach_history_item_flags(
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
                    "audit_run_mode": getattr(h, "audit_run_mode", "") or "",
                    "error_code": getattr(h, "error_code", "") or "",
                    "error_msg": sanitize_error_summary(getattr(h, "error_msg", "")),
                }
            )
            for h in items
        ],
    }


@router.get("/run-summary", summary="调度运行完整性汇总（按日+模式派生）")
def scheduler_run_summary(
    query_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="业务查询日期 yyyy-mm-dd"),
    audit_run_mode: str = Query(
        "daily_increment",
        pattern=r"^(daily_increment|discharge_final)$",
        description="质控运行模式",
    ),
    db: Session = Depends(get_db),
    _user=Depends(require_permission("view_scheduler")),
):
    """复用 per-type SchedulerHistory + PushLog 聚合，不新建父 run 表。"""
    datetime.strptime(query_date, "%Y-%m-%d")
    config = load_config()
    if audit_run_mode == "discharge_final":
        section = config.get("scheduler_discharge") or {}
    else:
        section = config.get("scheduler_daily") or config.get("scheduler") or {}
    configured = section.get("audit_type_codes") or []
    if not isinstance(configured, list):
        configured = []
    configured = [str(c or "").strip() for c in configured if str(c or "").strip()]

    from app.services.scheduler_lock_service import get_scheduler_lock_info as get_named_scheduler_lock_info

    lock_name = "discharge_push" if audit_run_mode == "discharge_final" else "daily_push"
    lock_info = get_named_scheduler_lock_info(lock_name)
    lock_running = str(lock_info.get("status") or "") == "running"

    summary = build_scheduler_run_summary(
        db,
        query_date=query_date,
        audit_run_mode=audit_run_mode,
        configured_codes=configured,
        lock_running=lock_running,
    )
    return summary


@router.post("/directed-retry", summary="定向补跑接口（003-B 桩：仅校验，不执行生产写）")
def directed_retry_stub(
    query_date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    audit_run_mode: str = Query(..., pattern=r"^(daily_increment|discharge_final)$"),
    audit_type_code: str = Query(..., min_length=1, max_length=64),
    dry_run: bool = Query(True, description="必须为 true；生产写操作未开放"),
    _user=Depends(require_permission("manage_scheduler")),
):
    """
    B 包仅交付权限与参数校验测试桩。
    真正补跑属于 G，且依赖 002 幂等门或书面应急轨特批。
    """
    datetime.strptime(query_date, "%Y-%m-%d")
    code = str(audit_type_code or "").strip()
    if not code or code.startswith("__"):
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Invalid audit_type_code")
    if not dry_run:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail="Production directed retry is disabled until G approval and 002 gate",
        )
    return {
        "accepted": True,
        "dry_run": True,
        "executed": False,
        "query_date": query_date,
        "audit_run_mode": audit_run_mode,
        "audit_type_code": code,
        "message": "参数校验通过；未执行补跑。生产补跑需 G 包书面批准且 002 就绪。",
        "required_gates": ["ACTIVE/002", "production_change_approval", "A_B_C_E_done"],
    }
