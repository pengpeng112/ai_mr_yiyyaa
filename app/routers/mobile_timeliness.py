# -*- coding: utf-8 -*-
"""企业微信手机端「病历超时解锁查询与时效统计」H5 门户（2026-11-16）。

复用 app/routers/timeliness.py 的底层查询/可见性/状态机函数与 app/routers/users.py
的登录链路（限流/密码校验/JWT+Cookie 下发），不复制不改坏状态机逻辑。

路由注册顺序死坑（见任务书 §〇.5）：本 router 必须在 app/main.py 中先于
mobile_qc.router 注册——否则 `GET /mobile/qc/timeliness` 会被
`mobile_qc` 的 `/mobile/qc/{alert_id:int}` 捕获成 422。
"""
from __future__ import annotations

import logging
import os
import pathlib
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.timeliness.models import TLApproval, TLEvent, TLRule, TLScanRun
from app.permissions import require_permission
from app.schemas import LoginRequest, UserInfo
from app.routers import timeliness as timeliness
from app.routers import users as users_router
from app.services.dept_visibility import visible_dept_names

from app.auth import AUTH_COOKIE_NAME, auth_cookie_secure, create_access_token
from app.permissions import get_user_permissions as _get_user_permissions_list
from app.permissions import get_user_role as _get_user_role

logger = logging.getLogger(__name__)
router = APIRouter()

PERM_VIEW = timeliness.PERM_VIEW
PERM_ADMIN = timeliness.PERM_ADMIN
PERM_APPROVE = timeliness.PERM_APPROVE

# 全院已上线的三个锁定节点（手机端字典置顶展示，pinned=True）。
_PINNED_MONITOR_CODES = ("JH04.02.001", "JH04.02.002", "JH04.02.011")

_ROLE_LABELS = {
    "admin": "系统管理员",
    "auditor": "质控审核员",
    "dept_manager": "科室管理员",
    "clinician": "临床医师",
}

_ACTION_TYPE_LABELS = {
    "NOTIFY": "企微预警通知",
    "TIMELINESS_NOTIFY": "企微预警通知",
    "JHEMR_INSERT_MONITOR": "写入病历锁定项",
    "JHEMR_APPROVE": "回写解锁审批",
    "APPROVAL_EXEMPT": "扣罚豁免",
    "APPROVAL_EXEMPT_CANCEL": "取消扣罚豁免",
    "EVENT_EXEMPT": "事件人工豁免",
}

_EVENT_STATUS_LABELS = {
    "OVERDUE": "已超时未签",
    "WARNING": "临期预警",
    "APPLYING": "申请解锁中",
    "APPROVED": "已解锁待签",
    "EXEMPT": "已豁免",
    "COMPLETED_ON_TIME": "按时完成",
    "COMPLETED_LATE": "超时完成",
    "PENDING": "未到期",
    "CANCELLED": "已取消",
}

_MONITOR_TYPE_LABELS = {
    "0": "新建超时拦截",
    "1": "草稿审签拦截",
}

_APPLY_CHANNEL_LABELS = {
    "JHEMR_NATIVE": "嘉和客户端",
    "PC_WEB": "质控网页端",
    "WECOM_H5": "企微手机端",
}

# ---- 手动同步 15 秒冷却（防刷锁；sync 本身是只读拉取 177） ----
_mobile_sync_lock = threading.Lock()
_last_mobile_sync_ts = 0.0
_last_mobile_sync_stats: dict[str, Any] = {}
MOBILE_SYNC_COOLDOWN_SECONDS = 15.0


def reset_mobile_sync_throttle() -> None:
    """清空同步冷却（单测与手动恢复用）。"""
    global _last_mobile_sync_ts, _last_mobile_sync_stats
    with _mobile_sync_lock:
        _last_mobile_sync_ts = 0.0
        _last_mobile_sync_stats = {}


# ---------- 页面与静态桥接（外壳免登录，鉴权由 API 完成） ----------

def _render_h5_page() -> HTMLResponse:
    html_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "static" / "templates" / "mobile" / "timeliness_h5.html"
    )
    if not html_path.exists():
        raise HTTPException(status_code=500, detail="H5 page not found")
    html = html_path.read_text("utf-8")
    if os.getenv("TEST_ISOLATED_MODE", "").strip().lower() in {"1", "true", "yes", "on"}:
        banner = (
            '<div style="position:fixed;z-index:99999;left:0;right:0;top:0;padding:8px;'
            'text-align:center;background:#f59e0b;color:#451a03;font:700 13px system-ui">'
            "SYNTHETIC TEST DATA / 脱敏合成测试数据</div>"
        )
        html = html.replace("<body", '<body style="padding-top:36px"', 1).replace(
            "</body>", banner + "</body>"
        )
    response = HTMLResponse(content=html)
    # 企业微信内置浏览器缓存防御：入口 HTML 一律禁止缓存
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/mobile/qc/timeliness", response_class=HTMLResponse, summary="病历时效质控 H5（企微手机端入口）")
def mobile_timeliness_page():
    return _render_h5_page()


@router.get("/mobile/timeliness", response_class=HTMLResponse, include_in_schema=False)
def mobile_timeliness_page_alias():
    return _render_h5_page()


@router.get("/scripts/mobile/vue.global.prod.js", include_in_schema=False)
def mobile_vue_bridge():
    """Vue 静态桥接：宿主机 :3000 Nginx 只转发 /scripts/mobile/，无 /vendor/。

    经此路由把 static/vendor/vue.global.prod.js 以同一路径返回，保证
    :8000 直连、:3000 反代、公网前置机三种访问形态 100% 可达。
    """
    vue_path = (
        pathlib.Path(__file__).resolve().parent.parent.parent
        / "static" / "vendor" / "vue.global.prod.js"
    )
    if not vue_path.exists():
        raise HTTPException(status_code=404, detail="vue vendor not found")
    return FileResponse(vue_path, media_type="application/javascript")


@router.get("/api/mobile/timeliness/ping", summary="手机端连通性探测（供前端自动选 API 前缀）")
def mobile_ping():
    return {"ok": True, "service": "mobile-timeliness"}


# ---------- 认证与会话 ----------

@router.post("/api/mobile/timeliness/login", summary="手机端登录（与 /api/users/login 同链路：限流+JWT+Cookie）")
async def mobile_login(body: LoginRequest, response: Response, db: Session = Depends(get_db)):
    # 直接委托 users.login：登录限流（5 次/5 分钟）、密码校验、JWT 签发与
    # HttpOnly Cookie 下发完全一致；本路径已在 security_middleware 的
    # _CSRF_EXEMPT_PATHS 中豁免（残留旧 Cookie 时不被 CSRF 门误拦 403）。
    return await users_router.login(request=body, response=response, db=db)


# ---- 工号免登（2026-11-17：企业微信嵌入传参 ?empno=工号） ----

# 免登签发的 JWT 有效期（短于电脑端默认，降低工号链接被转发的冒充窗口）。
EMPNO_TOKEN_HOURS = 8


def _empno_login_enabled() -> bool:
    return os.getenv("MOBILE_TIMELINESS_EMPNO_LOGIN", "true").strip().lower() not in {
        "0", "false", "no", "off",
    }


class EmpnoLoginRequest(BaseModel):
    """POST /login/empno：企业微信嵌入免登（仅用户名=工号 的系统账号）。"""

    empno: str = Field(..., min_length=1, max_length=64, description="工号（系统用户名）")


@router.post("/api/mobile/timeliness/login/empno",
             summary="工号免登（企微嵌入传参；用户名=工号 的在用账号；8h 短时 JWT；可 env 关闭）")
def mobile_login_empno(body: EmpnoLoginRequest, response: Response,
                       db: Session = Depends(get_db)):
    if not _empno_login_enabled():
        raise HTTPException(
            status_code=403,
            detail="empno auto login is disabled (MOBILE_TIMELINESS_EMPNO_LOGIN=false)",
        )
    empno = str(body.empno or "").strip()
    if not empno:
        raise HTTPException(status_code=400, detail="empno required")
    # 防刷：与密码登录同款限流（独立键空间，不影响密码登录计数）
    users_router._check_login_rate_limit("empno:" + empno)
    user = db.query(User).filter(User.username == empno).first()
    if not user or not user.is_active:
        users_router._record_login_attempt("empno:" + empno)
        logger.warning(
            "mobile empno login rejected: error_type=%s", "user_not_found_or_inactive",
        )
        raise HTTPException(
            status_code=401,
            detail="empno not bound to an active system account",
        )
    users_router._clear_login_attempts("empno:" + empno)

    token = create_access_token(user.id, user.username, expires_delta=timedelta(hours=EMPNO_TOKEN_HOURS))
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=EMPNO_TOKEN_HOURS * 3600,
        httponly=True,
        samesite="strict",
        secure=auth_cookie_secure(),
        path="/",
    )
    logger.info("mobile empno login ok: username=%s scope=empno(8h)", user.username)

    permissions = _get_user_permissions_list(user.id, db)
    role_name = _get_user_role(user.id, db)
    dept_name = None
    if user.dept_id:
        from app.models import Department

        dept = db.query(Department).filter(Department.id == user.dept_id).first()
        dept_name = dept.name if dept else None
    user_info = UserInfo(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        dept_id=user.dept_id,
        dept_name=dept_name,
        role=role_name,
        permissions=permissions,
        is_active=user.is_active,
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_info.model_dump(),
    }


@router.get("/api/mobile/timeliness/me", summary="手机端当前用户与操作能力")
def mobile_me(current_user: User = Depends(require_permission(PERM_VIEW)),
              db: Session = Depends(get_db)):
    role_name = None
    if current_user.role_id:
        from app.models import Role

        role = db.query(Role).filter(Role.id == current_user.role_id).first()
        role_name = role.name if role else None
    dept_name = None
    if current_user.dept_id:
        from app.models import Department

        dept = db.query(Department).filter(Department.id == current_user.dept_id).first()
        dept_name = dept.name if dept else None
    can_approve = timeliness._user_has_permission(db, current_user, PERM_ADMIN) or \
        timeliness._user_has_permission(db, current_user, PERM_APPROVE)
    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "role": role_name,
            "role_label": _ROLE_LABELS.get(role_name or "", role_name or ""),
            "dept_name": dept_name,
        },
        "capabilities": {
            "can_approve": bool(can_approve),
            "can_exempt": bool(timeliness._user_has_permission(db, current_user, PERM_ADMIN)),
            "jhemr_write_enabled": timeliness._jhemr_write_enabled(),
        },
    }


# ---------- 字典 ----------

@router.get("/api/mobile/timeliness/dicts", summary="手机端筛选项字典（科室/监控项/规则，受科室可见性约束）")
def mobile_dicts(current_user: User = Depends(require_permission(PERM_VIEW)),
                 db: Session = Depends(get_db)):
    names = visible_dept_names(db, current_user)
    dept_rows = db.query(timeliness.Department).order_by(timeliness.Department.id).all()
    departments = []
    for d in dept_rows:
        if names is not None and (d.name or "") not in names:
            continue
        departments.append({"code": d.code, "name": d.name})

    pinned, others = [], []
    for item in timeliness.MONITOR_ITEM_DICT:
        target = pinned if item["code"] in _PINNED_MONITOR_CODES else others
        target.append({**item, "pinned": item["code"] in _PINNED_MONITOR_CODES})
    monitor_items = pinned + others

    rules = [
        {"rule_code": r.rule_code, "rule_name": r.rule_name}
        for r in db.query(TLRule).filter(TLRule.enabled == True).order_by(TLRule.rule_code).all()  # noqa: E712
    ]
    return {"departments": departments, "monitor_items": monitor_items, "rules": rules}


# ---------- 顶部实时总览 ----------

def _month_start(now: datetime) -> datetime:
    return datetime(now.year, now.month, 1)


@router.get("/api/mobile/timeliness/overview", summary="手机端顶部实时总览（受科室可见性约束）")
def mobile_overview(current_user: User = Depends(require_permission(PERM_VIEW)),
                    db: Session = Depends(get_db)):
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = _month_start(now)

    aq = timeliness._apply_approval_visibility(db.query(TLApproval), db, current_user)
    pending_approvals = aq.filter(TLApproval.flag == "1").count()
    today_approvals = aq.filter(TLApproval.apply_date_time >= today_start).count()
    month_query = aq.filter(TLApproval.apply_date_time >= month_start)
    month_approvals_total = month_query.count()
    month_approved = month_query.filter(TLApproval.flag == "2").count()
    month_exempt = month_query.filter(TLApproval.penalty_exempt == True).count()  # noqa: E712
    penalty_rows = month_query.filter(TLApproval.flag == "2").all()
    month_penalty_amount = sum(
        (row.penalty_amount if row.penalty_amount is not None else 200)
        for row in penalty_rows if not bool(row.penalty_exempt)
    )

    eq = timeliness._apply_visibility(db.query(TLEvent), db, current_user)
    in_hosp_overdue = eq.filter(TLEvent.status == "OVERDUE").count()
    in_hosp_warning = eq.filter(TLEvent.status == "WARNING").count()
    in_hosp_applying = eq.filter(TLEvent.status == "APPLYING").count()

    last_scan = (
        db.query(TLScanRun)
        .filter(TLScanRun.status == "SUCCESS")
        .order_by(TLScanRun.id.desc())
        .first()
    )
    return {
        "pending_approvals": int(pending_approvals),
        "today_approvals": int(today_approvals),
        "month_approvals_total": int(month_approvals_total),
        "month_approved": int(month_approved),
        "month_exempt": int(month_exempt),
        "month_penalty_amount": int(month_penalty_amount),
        "in_hosp_overdue": int(in_hosp_overdue),
        "in_hosp_warning": int(in_hosp_warning),
        "in_hosp_applying": int(in_hosp_applying),
        "last_scan_at": last_scan.finished_at.isoformat() if last_scan and last_scan.finished_at else None,
        "jhemr_write_enabled": timeliness._jhemr_write_enabled(),
    }


# ---------- 超时解锁查询与操作（Tab 1） ----------

def _approval_mobile_fields(row: TLApproval, display: dict[str, dict[str, str]]) -> dict[str, Any]:
    """在 _approval_dict 基础上补充纯中文友好字段（前端不猜码值）。"""
    item = timeliness._approval_dict(row, display)
    monitor_code = str(row.monitor_code or "").strip()
    monitor_meta = next(
        (m for m in timeliness.MONITOR_ITEM_DICT if m["code"] == monitor_code), None,
    )
    item["monitor_label"] = (monitor_meta or {}).get("label") or item.get("rule_name") or monitor_code
    item["type_label"] = _MONITOR_TYPE_LABELS.get(str(row.type or "").strip(), "超时拦截")
    item["flag_label"] = "待审批锁定" if str(row.flag or "").strip() == "1" else (
        "已审批解锁" if str(row.flag or "").strip() == "2" else "未申请"
    )
    item["approve_user_name"] = (display.get("staff") or {}).get(row.approve_user_id or "", "")
    item["approve_channel_label"] = _APPLY_CHANNEL_LABELS.get(
        str(row.approve_channel or "").strip(), ""
    )
    if str(row.flag or "").strip() == "2" and not bool(row.penalty_exempt):
        item["effective_penalty"] = row.penalty_amount if row.penalty_amount is not None else 200
    else:
        item["effective_penalty"] = 0
    return item


def _candidate_approval_rows(query, limit_candidates: int = 400) -> list[TLApproval]:
    return (
        query.order_by(TLApproval.apply_date_time.desc(), TLApproval.id.desc())
        .limit(limit_candidates)
        .all()
    )


def _approval_matches_keyword(row: TLApproval, item: dict[str, Any], keyword: str) -> bool:
    text = keyword.strip().lower()
    if not text:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            row.patient_id, item.get("patient_name"), row.apply_user_id,
            item.get("apply_user_name"), row.dept_code, item.get("dept_name"),
            row.apply_reason, item.get("rule_name"),
        )
    ).lower()
    return text in haystack


@router.get("/api/mobile/timeliness/approvals", summary="手机端超时解锁申请列表（受科室可见性约束，keyword 内存安全模糊搜索）")
def mobile_approvals(
    status_tab: str = Query("all", description="pending|approved|exempt|all"),
    month: str | None = Query(None, description="YYYY-MM；空或 all 不限月份"),
    dept: str | None = None,
    monitor_code: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission(PERM_VIEW)),
    db: Session = Depends(get_db),
):
    query = db.query(TLApproval)
    query = timeliness._apply_approval_visibility(query, db, current_user)

    tab = str(status_tab or "all").strip().lower()
    if tab == "pending":
        query = query.filter(TLApproval.flag == "1")
    elif tab == "approved":
        query = query.filter(TLApproval.flag == "2")
    elif tab == "exempt":
        query = query.filter(TLApproval.penalty_exempt == True)  # noqa: E712
    elif tab != "all":
        raise HTTPException(status_code=400, detail=f"invalid status_tab: {status_tab}")

    month_text = str(month or "").strip()
    if month_text and month_text.lower() != "all":
        try:
            start = datetime.strptime(month_text, "%Y-%m")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid month: {month}") from exc
        end = datetime(start.year + (start.month // 12), (start.month % 12) + 1, 1)
        query = query.filter(TLApproval.apply_date_time >= start, TLApproval.apply_date_time < end)

    if dept is not None and str(dept).strip():
        dept_codes = timeliness._resolve_dept_filter(db, dept)
        if not dept_codes:
            return {"total": 0, "page": page, "limit": limit, "items": []}
        query = query.filter(TLApproval.dept_code.in_(dept_codes))
    if monitor_code and str(monitor_code).strip():
        query = query.filter(TLApproval.monitor_code == str(monitor_code).strip())

    kw = str(keyword or "").strip()
    display = timeliness._display_maps(db)
    if kw:
        # 防慢查：最多取最新 400 条候选，姓名/科室等中文名在内存中子串匹配后分页
        rows = _candidate_approval_rows(query, 400)
        patient_pairs = [(r.patient_id, str(r.visit_id)) for r in rows]
        display = {**display, "patient": timeliness._patient_name_map(patient_pairs)}
        items = []
        for row in rows:
            item = _approval_mobile_fields(row, display)
            if _approval_matches_keyword(row, item, kw):
                items.append(item)
        total = len(items)
        offset = (page - 1) * limit
        return {"total": total, "page": page, "limit": limit,
                "items": items[offset:offset + limit]}

    total = query.count()
    rows = (
        query.order_by(TLApproval.apply_date_time.desc(), TLApproval.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    display = {**display, "patient": timeliness._patient_name_map(
        [(r.patient_id, str(r.visit_id)) for r in rows])}
    return {"total": total, "page": page, "limit": limit,
            "items": [_approval_mobile_fields(r, display) for r in rows]}


@router.post("/api/mobile/timeliness/approvals/sync", summary="手机端手动同步最新申请（只读拉取；15 秒冷却防刷）")
def mobile_sync_approvals(current_user: User = Depends(require_permission(PERM_VIEW)),
                          db: Session = Depends(get_db)):
    global _last_mobile_sync_ts, _last_mobile_sync_stats
    with _mobile_sync_lock:
        now = time.monotonic()
        if _last_mobile_sync_ts and now - _last_mobile_sync_ts < MOBILE_SYNC_COOLDOWN_SECONDS:
            return {
                "message": "刚完成同步，请稍后再试",
                "throttled": True,
                "data": dict(_last_mobile_sync_stats),
            }
    try:
        stats = timeliness.sync_approvals(db, timeliness.load_config())
    except (timeliness.TimelinessNotConfigured, timeliness.TimelinessPermissionMissing) as exc:
        raise HTTPException(status_code=503, detail=f"readonly source unavailable: {exc}") from exc
    with _mobile_sync_lock:
        _last_mobile_sync_ts = time.monotonic()
        _last_mobile_sync_stats = dict(stats)
    return {"message": "同步完成", "throttled": False, "data": dict(stats)}


@router.post("/api/mobile/timeliness/approvals/{approval_id}/exempt", summary="手机端扣罚豁免/取消豁免（需 timeliness_admin，与电脑端同审计）")
def mobile_exempt_approval(approval_id: int,
                           body: timeliness.ApprovalExemptRequest,
                           current_user: User = Depends(require_permission(PERM_ADMIN)),
                           db: Session = Depends(get_db)):
    return timeliness.exempt_approval(approval_id, body, current_user, db)


def _require_approve_or_admin(db: Session, current_user: User) -> None:
    if timeliness._user_has_permission(db, current_user, PERM_ADMIN) or \
            timeliness._user_has_permission(db, current_user, PERM_APPROVE):
        return
    raise HTTPException(
        status_code=403,
        detail="requires timeliness_approve or timeliness_admin permission",
    )


@router.post("/api/mobile/timeliness/approvals/{approval_id}/approve", summary="手机端同意解锁（approve/admin 权限；真实执行成功落企微渠道；写闸关 409）")
def mobile_approve_approval(approval_id: int,
                            body: timeliness.ApprovalApproveRequest,
                            current_user: User = Depends(require_permission(PERM_VIEW)),
                            db: Session = Depends(get_db)):
    _require_approve_or_admin(db, current_user)
    result = timeliness.approve_approval(approval_id, body, current_user, db)
    try:
        data = result.data or {}
        if result.message == "approved and written back to JHEMR" and data.get("mode") == "EXECUTED":
            approval = db.query(TLApproval).filter(TLApproval.id == approval_id).first()
            if approval is not None and approval.approve_channel != "WECOM_H5":
                approval.approve_channel = "WECOM_H5"
                db.commit()
    except Exception:  # noqa: BLE001 — 渠道标记失败不影响审批结果返回
        db.rollback()
    return result


# ---------- 在院实时预警/超时（Tab 2） ----------

def _remain_text(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return ""
    delta = deadline - now
    seconds = delta.total_seconds()
    overdue = seconds < 0
    minutes = abs(seconds) / 60.0
    if minutes >= 60:
        text = f"{minutes / 60.0:.1f} 小时"
    else:
        text = f"{int(minutes)} 分钟"
    return (f"已超时 {text}" if overdue else f"剩余 {text}")


def _event_mobile_fields(event: TLEvent, display: dict[str, dict[str, str]], now: datetime) -> dict[str, Any]:
    item = timeliness._event_dict(event, display)
    item["status_label"] = _EVENT_STATUS_LABELS.get(str(event.status or "").strip(), event.status)
    item["remain_text"] = _remain_text(event.deadline, now)
    return item


def _event_matches_keyword(event: TLEvent, item: dict[str, Any], keyword: str) -> bool:
    text = keyword.strip().lower()
    if not text:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            event.patient_id, item.get("patient_name"), event.dept_code,
            item.get("dept_name"), event.responsible_doctor_id,
            item.get("responsible_doctor_name"), item.get("rule_name"),
        )
    ).lower()
    return text in haystack


@router.get("/api/mobile/timeliness/events", summary="手机端在院预警/超时列表（deadline 升序，受科室可见性约束）")
def mobile_events(
    status: str = Query("OVERDUE", description="OVERDUE|WARNING|APPLYING|PENDING|ACTIVE_RISK"),
    dept: str | None = None,
    rule_code: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_permission(PERM_VIEW)),
    db: Session = Depends(get_db),
):
    query = db.query(TLEvent)
    query = timeliness._apply_visibility(query, db, current_user)

    status_text = str(status or "OVERDUE").strip().upper()
    if status_text == "ACTIVE_RISK":
        query = query.filter(TLEvent.status.in_(["OVERDUE", "WARNING", "APPLYING"]))
    elif status_text:
        if status_text not in timeliness.EVENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status: {status}")
        query = query.filter(TLEvent.status == status_text)

    if rule_code and str(rule_code).strip():
        query = query.filter(TLEvent.rule_code == str(rule_code).strip())
    if dept is not None and str(dept).strip():
        dept_codes = timeliness._resolve_dept_filter(db, dept)
        if not dept_codes:
            return {"total": 0, "page": page, "limit": limit, "items": []}
        query = query.filter(TLEvent.dept_code.in_(dept_codes))

    now = datetime.now()
    display = timeliness._display_maps(db)
    kw = str(keyword or "").strip()
    if kw:
        rows = (
            query.order_by(TLEvent.deadline.asc(), TLEvent.id.desc())
            .limit(400)
            .all()
        )
        display = {**display, "patient": timeliness._patient_name_map(
            [(r.patient_id, str(r.visit_id)) for r in rows])}
        items = []
        for row in rows:
            item = _event_mobile_fields(row, display, now)
            if _event_matches_keyword(row, item, kw):
                items.append(item)
        total = len(items)
        offset = (page - 1) * limit
        return {"total": total, "page": page, "limit": limit,
                "items": items[offset:offset + limit]}

    total = query.count()
    rows = (
        query.order_by(TLEvent.deadline.asc(), TLEvent.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    display = {**display, "patient": timeliness._patient_name_map(
        [(r.patient_id, str(r.visit_id)) for r in rows])}
    return {"total": total, "page": page, "limit": limit,
            "items": [_event_mobile_fields(r, display, now) for r in rows]}


@router.get("/api/mobile/timeliness/events/{event_id}", summary="手机端事件详情（委托电脑端同款：状态历史+动作留痕+中文标签）")
def mobile_event_detail(event_id: int,
                        current_user: User = Depends(require_permission(PERM_VIEW)),
                        db: Session = Depends(get_db)):
    detail = timeliness.get_event(event_id, current_user, db)
    for action in detail.get("action_logs") or []:
        action["action_label"] = _ACTION_TYPE_LABELS.get(
            str(action.get("action_type") or "").strip(), action.get("action_type") or "—")
    return detail


@router.post("/api/mobile/timeliness/events/{event_id}/exempt", summary="手机端事件人工豁免（需 timeliness_admin，与电脑端同审计）")
def mobile_exempt_event(event_id: int,
                        body: timeliness.EventExemptRequest,
                        current_user: User = Depends(require_permission(PERM_ADMIN)),
                        db: Session = Depends(get_db)):
    return timeliness.exempt_event(event_id, body, current_user, db)


# ---------- 多维统计（Tab 3） ----------

def _on_time_rate(completed: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return round(completed * 100.0 / total, 1)


@router.get("/api/mobile/timeliness/stats", summary="手机端多维统计（汇总/科室排行/文书节点分布/医师扣罚榜）")
def mobile_stats(month: str | None = Query(None, description="YYYY-MM，缺省当月"),
                 dept: str | None = None,
                 current_user: User = Depends(require_permission(PERM_VIEW)),
                 db: Session = Depends(get_db)):
    month_text = str(month or "").strip() or datetime.now().strftime("%Y-%m")
    rows = timeliness._monthly_rows(db, current_user, month_text)
    display = timeliness._display_maps(db)
    for row in rows:
        row["dept_name"] = (display["dept"] or {}).get(row.get("dept_code") or "", "")
        row["responsible_doctor_name"] = (display["staff"] or {}).get(
            row.get("responsible_doctor_id") or "", "")

    if dept is not None and str(dept).strip():
        dept_codes = timeliness._resolve_dept_filter(db, dept)
        rows = [r for r in rows if (r.get("dept_code") or "") in set(dept_codes)]

    totals = {
        "total": sum(r["total"] for r in rows),
        "completed_on_time": sum(r["completed_on_time"] for r in rows),
        "completed_late": sum(r["completed_late"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "warning": sum(r["warning"] for r in rows),
        "pending": sum(r["pending"] for r in rows),
        "approval_count": sum(r["approval_count"] for r in rows),
        "approved_unlock_count": sum(r["approved_unlock_count"] for r in rows),
        "exempt_count": sum(r["exempt_count"] for r in rows),
        "penalty_amount_total": sum(r["penalty_amount_total"] for r in rows),
    }
    summary = {
        "month": month_text,
        **totals,
        "on_time_rate": _on_time_rate(totals["completed_on_time"], totals["total"]),
    }

    # 科室排行按 dept_code 合并（同一科室多医生行先聚合再计算按时率）
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = row.get("dept_code") or ""
        bucket = merged.setdefault(code, {
            "dept_code": code,
            "dept_name": row.get("dept_name") or code or "",
            "total": 0, "completed_on_time": 0, "completed_late": 0,
            "overdue": 0, "approval_count": 0, "approved_unlock_count": 0,
            "exempt_count": 0, "penalty_amount_total": 0,
        })
        for key in ("total", "completed_on_time", "completed_late", "overdue",
                    "approval_count", "approved_unlock_count", "exempt_count",
                    "penalty_amount_total"):
            bucket[key] += row[key]
    dept_ranking = []
    for bucket in merged.values():
        bucket["on_time_rate"] = _on_time_rate(bucket["completed_on_time"], bucket["total"])
        dept_ranking.append(bucket)

    # 文书节点分布：当月可见事件按规则聚合（时间窗与 _monthly_rows 对齐）
    try:
        month_start = datetime.strptime(month_text, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid month: {month_text}") from exc
    month_end = datetime(month_start.year + (month_start.month // 12), (month_start.month % 12) + 1, 1)
    rule_query = timeliness._apply_visibility(db.query(TLEvent), db, current_user)
    rule_events = rule_query.filter(TLEvent.t0 >= month_start, TLEvent.t0 < month_end).all()
    rule_map: dict[str, dict[str, Any]] = {}
    for event in rule_events:
        bucket = rule_map.setdefault(event.rule_code, {
            "rule_code": event.rule_code, "rule_name": "",
            "total": 0, "completed_on_time": 0, "completed_late": 0,
            "overdue": 0, "warning": 0, "pending": 0,
        })
        bucket["total"] += 1
        for key in ("completed_on_time", "completed_late", "overdue", "warning", "pending"):
            if event.status == key.upper():
                bucket[key] += 1
                break
    rule_names = {
        r.rule_code: (r.rule_name or "")
        for r in db.query(TLRule.rule_code, TLRule.rule_name).all()
    }
    rule_breakdown = []
    for bucket in rule_map.values():
        bucket["rule_name"] = rule_names.get(bucket["rule_code"], bucket["rule_code"])
        bucket["on_time_rate"] = _on_time_rate(bucket["completed_on_time"], bucket["total"])
        rule_breakdown.append(bucket)
    rule_breakdown.sort(key=lambda b: (-b["overdue"], -b["total"]))

    doctor_penalties = []
    for row in rows:
        if row["approval_count"] <= 0 and row["overdue"] <= 0 and row["completed_late"] <= 0:
            continue
        doctor_penalties.append({
            "dept_code": row.get("dept_code") or "",
            "dept_name": row.get("dept_name") or row.get("dept_code") or "",
            "doctor_id": row.get("responsible_doctor_id") or "",
            "doctor_name": row.get("responsible_doctor_name") or row.get("responsible_doctor_id") or "未登记医师",
            "total": row["total"],
            "overdue": row["overdue"],
            "completed_late": row["completed_late"],
            "approval_count": row["approval_count"],
            "approved_unlock_count": row["approved_unlock_count"],
            "exempt_count": row["exempt_count"],
            "penalty_amount_total": row["penalty_amount_total"],
        })
    doctor_penalties.sort(key=lambda d: (-d["penalty_amount_total"], -d["overdue"]))
    doctor_penalties = doctor_penalties[:100]

    return {
        "summary": summary,
        "dept_ranking": dept_ranking,
        "rule_breakdown": rule_breakdown,
        "doctor_penalties": doctor_penalties,
    }
