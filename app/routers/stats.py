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
        try:
            span = q.with_entities(func.min(PushLog.query_date), func.max(PushLog.query_date)).first()
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
    total = q.count()
    success = q.filter(PushLog.status == "success").count()
    skipped = q.filter(PushLog.status == "skipped").count()
    inconsistency = q.filter(PushLog.inconsistency == 1).count()
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
