"""
数据统计路由 —— /api/stats
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text
from datetime import datetime, timedelta

from app.database import get_db
from app.models import PushLog, AuditDimensionResult
from app.schemas import StatsSummary, DailyTrend, DeptDistribution, SeverityDistribution, DimensionStatsItem

router = APIRouter()


@router.get("/today", summary="今日推送统计")
def stats_today(db: Session = Depends(get_db)):
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)
    q = db.query(PushLog).filter(PushLog.push_time >= today_start, PushLog.push_time < tomorrow_start)
    total = q.count()
    success = q.filter(PushLog.status == "success").count()
    inconsistency = q.filter(PushLog.inconsistency == 1).count()
    return {
        "date": today_start.strftime("%Y-%m-%d"),
        "total": total,
        "success": success,
        "inconsistency": inconsistency,
    }


@router.get("/summary", response_model=StatsSummary, summary="总体统计")
def stats_summary(db: Session = Depends(get_db)):
    total = db.query(func.count(PushLog.id)).scalar() or 0
    success = db.query(func.count(PushLog.id)).filter(PushLog.status == "success").scalar() or 0
    failed = db.query(func.count(PushLog.id)).filter(PushLog.status == "failed").scalar() or 0
    inconsistency = db.query(func.count(PushLog.id)).filter(PushLog.inconsistency == 1).scalar() or 0

    return StatsSummary(
        total_pushes=total,
        success_count=success,
        failed_count=failed,
        success_rate=round(success / total * 100, 2) if total > 0 else 0,
        inconsistency_count=inconsistency,
        inconsistency_rate=round(inconsistency / success * 100, 2) if success > 0 else 0,
    )


@router.get("/daily", summary="每日趋势（折线图数据）")
def stats_daily(
    days: int = Query(30, ge=1, le=365, description="最近N天"),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
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
    return {"items": items}


@router.get("/dept", summary="科室分布（柱图数据）")
def stats_dept(db: Session = Depends(get_db)):
    rows = (
        db.query(
            PushLog.dept,
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
        )
        .filter(PushLog.dept.isnot(None))
        .group_by(PushLog.dept)
        .order_by(func.count(PushLog.id).desc())
        .all()
    )
    rows = [(d, t, i) for d, t, i in rows if str(d or "").strip()]

    return {
        "items": [
            DeptDistribution(
                dept=r.dept or "未知",
                total=r.total or 0,
                inconsistency=r.inconsistency or 0,
            )
            for r in rows
        ]
    }


@router.get("/severity", summary="严重等级分布（饼图数据）")
def stats_severity(db: Session = Depends(get_db)):
    rows = (
        db.query(
            PushLog.severity,
            func.count(PushLog.id).label("count"),
        )
        .filter(PushLog.inconsistency == 1)
        .group_by(PushLog.severity)
        .all()
    )

    return {
        "items": [
            SeverityDistribution(
                severity=r.severity or "unknown",
                count=r.count or 0,
            )
            for r in rows
        ]
    }


@router.get("/monthly", summary="月度汇总报表")
def stats_monthly(db: Session = Depends(get_db)):
    # SQLite 中用 substr 提取月份
    month_expr = func.substr(PushLog.query_date, 1, 7)
    rows = (
        db.query(
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
    return {"items": items}


@router.get("/anomaly-top", summary="异常高发科室/患者 Top10")
def anomaly_top(
    group_by: str = Query("dept", description="dept 或 patient"),
    db: Session = Depends(get_db),
):
    if group_by == "patient":
        rows = (
            db.query(
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
            ]
        }
    else:
        rows = (
            db.query(
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
            ]
        }


@router.get("/dimensions", summary="审计维度统计")
def stats_dimensions(
    date_from: str = Query(None, description="开始日期 yyyy-mm-dd"),
    date_to: str = Query(None, description="结束日期 yyyy-mm-dd"),
    dept: str = Query(None, description="科室筛选"),
    db: Session = Depends(get_db),
):
    """
    按审计维度统计各状态分布（✅通过 / ❌不一致 / ⚠️警告 / ❓未知）
    联查 audit_dimension_result + push_log 表
    """
    q = db.query(AuditDimensionResult).join(
        PushLog, AuditDimensionResult.push_log_id == PushLog.id
    )
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

    return {"items": items}
