"""
数据统计路由 —— /api/stats
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text
from datetime import datetime, timedelta

from app.database import get_db, engine
from app.models import PushLog, AuditDimensionResult, User
from app.schemas import StatsSummary, DailyTrend, DeptDistribution, SeverityDistribution, DimensionStatsItem
from app.auth import get_current_user
from app.permissions import require_permission
from app.services.dept_visibility import apply_push_log_visibility
from app.services.current_result_filter import apply_current_result_filter
from app.services.ttl_cache import app_ttl_cache

router = APIRouter()

# 035/RP3：统计口径元数据（与 scheduler 状态页时区口径一致）
_STATS_TIMEZONE = "Asia/Shanghai"


def _stats_metadata(q=None, *, filters=None, date_from=None, date_to=None, semantics="current-only") -> dict:
    """构造统计响应元数据块。

    - generated_at/timezone：生成时刻与服务器时区口径；
    - date_from/date_to：显式窗口优先，否则用同一查询的 min/max query_date 推导
      实际数据覆盖窗口（空数据时为 None）；
    - filters：影响口径的筛选条件快照；
    - semantics：结果版本口径（current-only=仅当前结果，all-results=含历史版本）。
    """
    if (date_from is None or date_to is None) and q is not None:
        # WP01 T3（064 总计划）：MIN/MAX(query_date) 全表扫放 300s TTL 缓存——
        # /stats/severity 与 /stats/anomaly-top 不再每次二次全表扫描。
        try:
            import hashlib as _hashlib

            # engine 指纹：生产单例稳定命中；测试内存库每 fixture 新 engine → 隔离
            _bound_key = "stats:date_bounds:" + _hashlib.md5(
                (str(q) + str(id(engine))).encode("utf-8")
            ).hexdigest()
            span = app_ttl_cache.get_or_set(
                _bound_key, 300,
                lambda: q.with_entities(
                    func.min(PushLog.query_date), func.max(PushLog.query_date)
                ).first(),
            )
        except Exception:
            span = None
        if span is not None:
            date_from = date_from or span[0]
            date_to = date_to or span[1]
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "timezone": _STATS_TIMEZONE,
        "date_from": date_from,
        "date_to": date_to,
        "filters": filters or {},
        "semantics": semantics,
    }


def _month_expr():
    if engine.dialect.name == "oracle":
        return func.to_char(PushLog.query_date, "YYYY-MM")
    return func.substr(PushLog.query_date, 1, 7)


def _business_push_log_query(db: Session, current_user: User):
    """业务统计默认只看当前结果（隐藏已替代历史版本）。"""
    q = apply_push_log_visibility(db.query(PushLog), current_user, db)
    return apply_current_result_filter(q, include_superseded=False)


@router.get("/today", summary="今日推送统计")
def stats_today(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_reports"))):
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    q = _business_push_log_query(db, current_user).filter(
        PushLog.push_time >= today_start, PushLog.push_time < tomorrow_start
    )
    # WP01 T3（064 总计划）：4 条 COUNT 合并为 1 条 SUM(CASE) 聚合
    row = q.with_entities(
        func.count(PushLog.id).label("total"),
        func.sum(case((PushLog.status == "success", 1), else_=0)).label("success"),
        func.sum(case((PushLog.status == "skipped", 1), else_=0)).label("skipped"),
        func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
    ).first()
    total = int(row.total or 0) if row else 0
    success = int(row.success or 0) if row else 0
    skipped = int(row.skipped or 0) if row else 0
    inconsistency = int(row.inconsistency or 0) if row else 0
    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "total": total,
        "success": success,
        "skipped": skipped,
        "inconsistency": inconsistency,
        "_meta": _stats_metadata(
            filters={"window": "today", "push_time": today_start.strftime("%Y-%m-%d")},
            date_from=today_start.strftime("%Y-%m-%d"),
            date_to=today_start.strftime("%Y-%m-%d"),
        ),
    }


@router.get("/summary", response_model=StatsSummary, summary="总体统计")
def stats_summary(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_reports"))):
    base_q = _business_push_log_query(db, current_user)
    total = base_q.count()
    success = base_q.filter(PushLog.status == "success").count()
    failed = base_q.filter(PushLog.status == "failed").count()
    inconsistency = base_q.filter(PushLog.inconsistency == 1).count()

    return StatsSummary(
        total_pushes=total,
        success_count=success,
        failed_count=failed,
        success_rate=round(success / total * 100, 2) if total > 0 else 0,
        inconsistency_count=inconsistency,
        inconsistency_rate=round(inconsistency / success * 100, 2) if success > 0 else 0,
        meta=_stats_metadata(base_q),
    )


@router.get("/daily", summary="每日趋势（折线图数据）")
def stats_daily(
    days: int = Query(30, ge=1, le=365, description="最近N天"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    q = _business_push_log_query(db, current_user)
    # 优先按 query_date 最近 N 个自然日窗口，避免无边界时前端空白
    date_from = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    q = q.filter(PushLog.query_date >= date_from)
    rows = (
        q.with_entities(
            PushLog.query_date,
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((PushLog.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
        )
        .group_by(PushLog.query_date)
        .order_by(PushLog.query_date.desc())
        .limit(days)
        .all()
    )

    items = [
        DailyTrend(
            date=r.query_date,
            total=r.total or 0,
            success=r.success or 0,
            failed=r.failed or 0,
            inconsistency=r.inconsistency or 0,
        )
        for r in rows
    ]
    items.reverse()  # 按时间正序
    return {
        "items": items,
        "_meta": _stats_metadata(
            filters={"days": days},
            date_from=date_from,
            date_to=datetime.now().strftime("%Y-%m-%d"),
        ),
    }


@router.get("/dept", summary="科室分布（柱图数据）")
def stats_dept(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_reports"))):
    q = _business_push_log_query(db, current_user)
    rows = (
        q.with_entities(
            PushLog.dept,
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
        )
        .filter(PushLog.dept.isnot(None))
        .group_by(PushLog.dept)
        .order_by(func.count(PushLog.id).desc())
        .all()
    )

    return {
        "items": [
            DeptDistribution(
                dept=str(d or "").strip() or "未知",
                total=int(t or 0),
                inconsistency=int(i or 0),
            )
            for d, t, i in rows
            if str(d or "").strip()
        ],
        "_meta": _stats_metadata(q, filters={"group_by": "dept"}),
    }


@router.get("/severity", summary="严重等级分布（饼图数据）")
def stats_severity(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_reports"))):
    """严重度分布：优先统计不一致结果；若无不一致则回退为成功结果的严重度计数。"""
    q = _business_push_log_query(db, current_user)
    rows = (
        q.with_entities(
            PushLog.severity,
            func.count(PushLog.id).label("count"),
        )
        .filter(PushLog.inconsistency == 1)
        .group_by(PushLog.severity)
        .all()
    )
    items = [
        SeverityDistribution(severity=(r.severity or "unknown"), count=r.count or 0)
        for r in rows
        if (r.count or 0) > 0
    ]
    # 全空时回退：按成功记录 severity 计数（兼容 severity 有值但 inconsistency 未置位）
    if not items:
        rows2 = (
            q.with_entities(
                PushLog.severity,
                func.count(PushLog.id).label("count"),
            )
            .filter(PushLog.status == "success")
            .group_by(PushLog.severity)
            .all()
        )
        items = [
            SeverityDistribution(severity=(r.severity or "unknown"), count=r.count or 0)
            for r in rows2
            if (r.count or 0) > 0 and str(r.severity or "").strip()
        ]
    return {
        "items": items,
        "_meta": _stats_metadata(q, filters={"scope": "inconsistency-first"}),
    }


@router.get("/monthly", summary="月度汇总报表")
def stats_monthly(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_reports"))):
    month_expr = _month_expr()
    q = _business_push_log_query(db, current_user)
    rows = (
        q.with_entities(
            month_expr.label("month"),
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((PushLog.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
        )
        .group_by(month_expr)
        .order_by(month_expr.desc())
        .limit(12)
        .all()
    )

    items = [
        {
            "month": r.month,
            "total": r.total or 0,
            "success": r.success or 0,
            "failed": r.failed or 0,
            "inconsistency": r.inconsistency or 0,
            "success_rate": round((r.success or 0) / r.total * 100, 2) if r.total else 0,
            "inconsistency_rate": round((r.inconsistency or 0) / (r.success or 1) * 100, 2),
        }
        for r in rows
    ]
    items.reverse()
    return {
        "items": items,
        "_meta": _stats_metadata(q, filters={"months": 12}),
    }


@router.get("/anomaly-top", summary="异常高发科室/患者 Top10")
def anomaly_top(
    group_by: str = Query("dept", description="dept 或 patient"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    if group_by == "patient":
        q = _business_push_log_query(db, current_user)
        rows = (
            q.with_entities(
                PushLog.patient_id,
                PushLog.patient_name,
                PushLog.dept,
                func.count(PushLog.id).label("count"),
            )
            .filter(PushLog.inconsistency == 1)
            .group_by(PushLog.patient_id, PushLog.patient_name, PushLog.dept)
            .order_by(func.count(PushLog.id).desc())
            .limit(10)
            .all()
        )
        return {
            "items": [
                {
                    "patient_id": r.patient_id,
                    "patient_name": r.patient_name,
                    "dept": r.dept,
                    "inconsistency_count": r.count,
                }
                for r in rows
            ],
            "_meta": _stats_metadata(q, filters={"group_by": "patient", "top": 10, "inconsistency_only": True}),
        }
    else:
        q = _business_push_log_query(db, current_user)
        rows = (
            q.with_entities(
                PushLog.dept,
                func.count(PushLog.id).label("count"),
            )
            .filter(PushLog.inconsistency == 1)
            .group_by(PushLog.dept)
            .order_by(func.count(PushLog.id).desc())
            .limit(10)
            .all()
        )
        return {
            "items": [
                {"dept": r.dept or "未知", "inconsistency_count": r.count}
                for r in rows
            ],
            "_meta": _stats_metadata(q, filters={"group_by": "dept", "top": 10, "inconsistency_only": True}),
        }


@router.get("/dimensions", summary="审计维度统计")
def stats_dimensions(
    date_from: str = Query(None, description="开始日期 yyyy-mm-dd"),
    date_to: str = Query(None, description="结束日期 yyyy-mm-dd"),
    dept: str = Query(None, description="科室筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    """
    按审计维度统计各状态分布（✅通过 / ❌不一致 / ⚠️警告 / ❓未知）
    联查 audit_dimension_result + push_log 表
    """
    q = db.query(AuditDimensionResult).join(
        PushLog, AuditDimensionResult.push_log_id == PushLog.id
    )
    q = apply_push_log_visibility(q, current_user, db, dept_column=PushLog.dept)
    if date_from:
        q = q.filter(PushLog.query_date >= date_from)
    if date_to:
        q = q.filter(PushLog.query_date <= date_to)
    if dept:
        q = q.filter(PushLog.dept == dept)

    rows = (
        q.with_entities(
            AuditDimensionResult.dimension,
            func.count(AuditDimensionResult.id).label("total"),
            func.sum(case((AuditDimensionResult.status == "pass", 1), else_=0)).label("pass_count"),
            func.sum(case((AuditDimensionResult.status == "fail", 1), else_=0)).label("fail_count"),
            func.sum(case((AuditDimensionResult.status == "warn", 1), else_=0)).label("warn_count"),
            func.sum(case((AuditDimensionResult.status == "unknown", 1), else_=0)).label("unknown_count"),
        )
        .group_by(AuditDimensionResult.dimension)
        .order_by(AuditDimensionResult.dimension)
        .all()
    )

    items = []
    for r in rows:
        total = r.total or 0
        pass_count = r.pass_count or 0
        items.append(DimensionStatsItem(
            dimension=r.dimension,
            total=total,
            pass_count=pass_count,
            fail_count=r.fail_count or 0,
            warn_count=r.warn_count or 0,
            unknown_count=r.unknown_count or 0,
            pass_rate=round(pass_count / total * 100, 2) if total > 0 else 0,
        ))

    return {
        "items": items,
        # 注意：维度统计联查 audit_dimension_result，未套用当前结果过滤（含历史版本行）
        "_meta": _stats_metadata(
            q,
            filters={"date_from": date_from, "date_to": date_to, "dept": dept},
            semantics="all-results",
        ),
    }


# ---- WP01 T3（064 总计划）：质控总览单接口聚合 ----
# 前端首屏原为 10~14 个串行请求；本接口 30s TTL 缓存一次返回全部区块。
# 硬约束：high_risk_recent 不加载 4 个 CLOB（defer + OUTER JOIN 结论摘要）；
# timeliness 区严禁调用 _display_maps/_patient_name_map/V_QYBR。

_WECOM_PREARCHIVE_TIMEOUT = 2.0  # 秒；预检 BFF fail-open 超时


def _prearchive_overview_block() -> dict:
    """预检区块：sidecar 不可达/超时 fail-open；独立 60s 缓存。"""
    cache_key = "wb_overview:prearchive"
    cached = app_ttl_cache.get(cache_key)
    if cached is not None:
        return cached
    block = {
        "available": False,
        "mode": "unconfigured",
        "total_checked": 0,
        "issue_records": 0,
        "pending_review": 0,
        "rules_active": 0,
        "status_message": "归档前形式预检暂未接入数据",
    }
    try:
        from app.services.prearchive_admin_client import PrearchiveAdminClient

        client = PrearchiveAdminClient()
        if client.enabled and client.base_url:
            # 只取 1 行，目的仅 total 计数（白名单目标 /api/admin/checks）
            result = client.call("GET", "/api/admin/checks", actor=None,
                                 query={"page": 1, "page_size": 1})
            payload = result.get("json") or {}
            total = int(payload.get("total") or 0)
            block.update({
                "available": True,
                "mode": "connected",
                "total_checked": total,
                "status_message": "预检服务已连通",
            })
    except Exception:  # noqa: BLE001 — Disabled/Unavailable/Timeout/任何异常一律 fail-open
        block["status_message"] = "预检服务未连通或超时（fail-open）"

    # rules_active：本地生效规则条数（fail-open 0）
    try:
        from app.services.prearchive_rules_view import load_prearchive_rules_view

        view = load_prearchive_rules_view()
        block["rules_active"] = sum(
            len(c.get("rules") or []) for c in view.get("categories") or []
        )
    except Exception:
        pass

    app_ttl_cache.set(cache_key, block, 60)
    return block


def _timeliness_overview_block(db: Session, current_user: User, scope=None) -> dict:
    """时效区块：轻量聚合 SQL；口径见 064 §5.1.3（严禁 V_QYBR/姓名映射）。"""
    from app.services.data_scope import apply_tlevent_scope, resolve_user_data_scope
    from app.timeliness.models import TLEvent, TLApproval, TLScanRun
    from app.timeliness.engine.state import (
        COMPLETED_ON_TIME as _ON_TIME,
        COMPLETED_LATE as _LATE,
    )

    resolved = scope or resolve_user_data_scope(db, current_user)
    eq = apply_tlevent_scope(db.query(TLEvent), resolved)

    warning = eq.filter(TLEvent.status == "WARNING").count()
    overdue = eq.filter(TLEvent.status == "OVERDUE").count()

    aq = apply_tlevent_scope(db.query(TLApproval), resolved, model=TLApproval)
    locked_pending = aq.filter(TLApproval.flag == "1").count()

    now = datetime.now()
    month_start = datetime(now.year, now.month, 1)
    month_end = datetime(now.year + (now.month // 12), (now.month % 12) + 1, 1)
    month_q = aq.filter(
        TLApproval.apply_date_time >= month_start, TLApproval.apply_date_time < month_end
    )
    month_locked_total = month_q.count()
    month_unlocked = month_q.filter(TLApproval.flag == "2").count()

    ev_q = eq.filter(TLEvent.t0 >= month_start, TLEvent.t0 < month_end)
    month_total_events = ev_q.count()
    completed = ev_q.filter(TLEvent.status.in_([_ON_TIME, _LATE])).count()
    on_time = ev_q.filter(TLEvent.status == _ON_TIME).count()
    month_on_time_rate = round(on_time / completed * 100, 1) if completed else 0.0

    last_scan = db.query(TLScanRun).order_by(TLScanRun.id.desc()).first()
    last_scan_at = None
    last_scan_duration_ms = None
    if last_scan is not None:
        if last_scan.started_at and last_scan.finished_at:
            last_scan_duration_ms = int(
                (last_scan.finished_at - last_scan.started_at).total_seconds() * 1000
            )
        finished = last_scan.finished_at or last_scan.started_at
        last_scan_at = finished.isoformat() if finished else None

    return {
        "inpatient_warning": int(warning),
        "inpatient_overdue": int(overdue),
        "locked_pending": int(locked_pending),
        "month_locked_total": int(month_locked_total),
        "month_unlocked": int(month_unlocked),
        "month_on_time_rate": float(month_on_time_rate),
        "month_total_events": int(month_total_events),
        "last_scan_at": last_scan_at,
        "last_scan_duration_ms": last_scan_duration_ms,
    }


def _ai_qc_overview_block(db: Session, current_user: User, days: int) -> dict:
    """AI 内涵质控区块：today 合并 SQL + severity 分布 + 近 N 天趋势 + 科室 TOP
    + 近 14 天高危样本（defer CLOB + OUTER JOIN 结论摘要）。"""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    tq = _business_push_log_query(db, current_user).filter(
        PushLog.push_time >= today_start, PushLog.push_time < tomorrow_start
    )
    today_row = tq.with_entities(
        func.count(PushLog.id).label("total"),
        func.sum(case((PushLog.status == "success", 1), else_=0)).label("success"),
        func.sum(case((PushLog.status == "failed", 1), else_=0)).label("failed"),
        func.sum(case((PushLog.severity == "high", 1), else_=0)).label("high"),
    ).first()

    # severity 分布（与 /stats/severity 同口径：优先不一致，空则回退成功记录）
    sq = _business_push_log_query(db, current_user)
    sev_rows = (
        sq.with_entities(PushLog.severity, func.count(PushLog.id).label("count"))
        .filter(PushLog.inconsistency == 1)
        .group_by(PushLog.severity)
        .all()
    )
    if not any((r.count or 0) > 0 for r in sev_rows):
        sev_rows = (
            sq.with_entities(PushLog.severity, func.count(PushLog.id).label("count"))
            .filter(PushLog.status == "success")
            .group_by(PushLog.severity)
            .all()
        )
    severity_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    for r in sev_rows:
        key = str(r.severity or "").strip().lower() or "none"
        if key in severity_counts:
            severity_counts[key] += int(r.count or 0)

    # 近 N 天趋势（单 SQL group by query_date）
    date_from = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    trend_rows = (
        _business_push_log_query(db, current_user)
        .with_entities(
            PushLog.query_date,
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.severity == "high", 1), else_=0)).label("high"),
            func.sum(case((PushLog.severity == "medium", 1), else_=0)).label("medium"),
            func.sum(case((PushLog.severity == "low", 1), else_=0)).label("low"),
        )
        .filter(PushLog.query_date >= date_from)
        .group_by(PushLog.query_date)
        .order_by(PushLog.query_date.desc())
        .limit(days)
        .all()
    )
    daily_trend = [
        {"date": str(r.query_date), "total": int(r.total or 0), "high": int(r.high or 0),
         "medium": int(r.medium or 0), "low": int(r.low or 0)}
        for r in trend_rows
    ]
    daily_trend.reverse()

    # 科室 TOP（不一致计数 + 高危计数，单 SQL）
    top_rows = (
        _business_push_log_query(db, current_user)
        .with_entities(
            PushLog.dept,
            func.count(PushLog.id).label("anomaly_count"),
            func.sum(case((PushLog.severity == "high", 1), else_=0)).label("high_count"),
        )
        .filter(PushLog.inconsistency == 1, PushLog.dept.isnot(None))
        .group_by(PushLog.dept)
        .order_by(func.count(PushLog.id).desc())
        .limit(10)
        .all()
    )
    top_depts = [
        {"name": str(r.dept or "").strip() or "未知",
         "anomaly_count": int(r.anomaly_count or 0),
         "high_count": int(r.high_count or 0)}
        for r in top_rows
        if str(r.dept or "").strip()
    ]

    # 近 14 天高危样本：复用 _business_push_log_query（科室隔离 + 仅当前有效版本）+ 仅指定标量列（零 CLOB）
    risk_from = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    from app.models import AuditConclusion
    risk_rows = (
        _business_push_log_query(db, current_user)
        .outerjoin(AuditConclusion, AuditConclusion.push_log_id == PushLog.id)
        .with_entities(
            PushLog.id, PushLog.patient_id, PushLog.patient_name, PushLog.visit_number,
            PushLog.dept, PushLog.audit_type_code, PushLog.severity,
            PushLog.push_time, PushLog.reviewed_flag,
            AuditConclusion.overall_conclusion,
        )
        .filter(
            PushLog.status == "success",
            PushLog.severity == "high",
            PushLog.query_date >= risk_from,
        )
        # 列查询只 SELECT 指定列（含 overall_conclusion），4 个 CLOB 不在 SQL 中——
        # 天然不加载；defer 仅适用于整实体查询（此处使用会 ArgumentError）。
        .order_by(PushLog.push_time.desc())
        .limit(15)
        .all()
    )
    from app.services.audit_type_registry import AuditTypeRegistry
    registry = AuditTypeRegistry()
    high_risk_recent = []
    for r in risk_rows:
        audit_type = registry.get_or_default(str(r.audit_type_code or ""))
        high_risk_recent.append({
            "id": r.id,
            "patient_id": str(r.patient_id or ""),
            "patient_name": str(r.patient_name or ""),
            "visit_number": r.visit_number,
            "dept": str(r.dept or ""),
            "audit_type_code": str(r.audit_type_code or "") or audit_type.code,
            "audit_type_name": audit_type.name,
            "severity": str(r.severity or "high"),
            "push_time": r.push_time.isoformat() if r.push_time else None,
            "summary": str(r.overall_conclusion or "")[:300],
            "reviewed_flag": bool(r.reviewed_flag),
        })

    today_high_risk = int(today_row.high or 0) if today_row else 0
    return {
        "today_pushed": int(today_row.total or 0) if today_row else 0,
        "today_success": int(today_row.success or 0) if today_row else 0,
        "today_failed": int(today_row.failed or 0) if today_row else 0,
        "today_high_risk": today_high_risk,
        "severity_counts": severity_counts,
        "daily_trend": daily_trend,
        "top_depts": top_depts,
        "high_risk_recent": high_risk_recent,
    }


@router.get("/workbench-overview", summary="质控总览单接口聚合（首屏 10~14 请求收敛为 1；30s TTL）")
def workbench_overview(
    days: int = Query(30, ge=1, le=90),
    force_refresh: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    from app.services.data_scope import (
        apply_alert_scope,
        resolve_user_data_scope,
    )
    scope = resolve_user_data_scope(db, current_user)
    if scope.is_all:
        scope_key = "all"
    else:
        codes_sig = ",".join(sorted(scope.dept_codes))
        names_sig = ",".join(sorted(scope.dept_names))
        scope_key = f"{scope.scope}:{codes_sig}|{names_sig}" if (codes_sig or names_sig) else f"{scope.scope}:none"
    cache_key = f"wb_overview:{scope_key}:{days}"
    if not force_refresh:
        cached = app_ttl_cache.get(cache_key)
        if cached is not None:
            return cached

    # relay 区块：与 /patient-qc/relay-alert/summary 同口径（单 SQL + 统一数据范围）
    from app.models import QCRecordAlertLog
    from sqlalchemy import case as _case
    relay_q = apply_alert_scope(db.query(QCRecordAlertLog), scope)
    relay_row = relay_q.with_entities(
        func.count(QCRecordAlertLog.id).label("total"),
        func.sum(_case((QCRecordAlertLog.status == "success", 1), else_=0)).label("success"),
        func.sum(_case((QCRecordAlertLog.status == "failed", 1), else_=0)).label("failed"),
        func.sum(_case((QCRecordAlertLog.status == "pending", 1), else_=0)).label("pending"),
        func.sum(_case((QCRecordAlertLog.viewed_flag == 1, 1), else_=0)).label("viewed"),
        func.sum(_case(
                ((QCRecordAlertLog.viewed_flag == 0) & (QCRecordAlertLog.status != "suppressed"), 1), else_=0
            )).label("unviewed"),
    ).first()

    # system 区块：调度器真实运行态 + 下次触发时间（零额外 DB 查询）
    from app import scheduler as scheduler_module
    sched = scheduler_module.get_scheduler()
    scheduler_running = bool(sched and getattr(sched, "running", False))
    daily_next_run = None
    discharge_next_run = None
    if sched is not None:
        try:
            daily_job = sched.get_job("daily_push")
            if daily_job and daily_job.next_run_time:
                daily_next_run = daily_job.next_run_time.isoformat()
            discharge_job = sched.get_job("discharge_push")
            if discharge_job and discharge_job.next_run_time:
                discharge_next_run = discharge_job.next_run_time.isoformat()
        except Exception:
            pass
    system_block = {
        "status": "ok",
        "scheduler_running": scheduler_running,
        "daily_next_run": daily_next_run,
        "discharge_next_run": discharge_next_run,
    }

    payload = {
        "cached_at": datetime.now().isoformat(),
        "days": days,
        "scope_label": scope.label,
        "ai_qc": _ai_qc_overview_block(db, current_user, days),
        "timeliness": _timeliness_overview_block(db, current_user, scope=scope),
        "prearchive": _prearchive_overview_block(),
        "relay": {
            "total": int(relay_row.total or 0) if relay_row else 0,
            "success": int(relay_row.success or 0) if relay_row else 0,
            "failed": int(relay_row.failed or 0) if relay_row else 0,
            "pending": int(relay_row.pending or 0) if relay_row else 0,
            "viewed": int(relay_row.viewed or 0) if relay_row else 0,
            "unviewed": int(relay_row.unviewed or 0) if relay_row else 0,
        },
        "system": system_block,
    }
    app_ttl_cache.set(cache_key, payload, 30)
    return payload
