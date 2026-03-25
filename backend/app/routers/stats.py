"""
数据统计路由 —— /api/stats
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, case, text

from app.database import get_db
from app.models import PushLog
from app.schemas import StatsSummary, DailyTrend, DeptDistribution, SeverityDistribution

router = APIRouter()


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
        .filter(PushLog.dept != "")
        .group_by(PushLog.dept)
        .order_by(func.count(PushLog.id).desc())
        .all()
    )

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
    rows = (
        db.query(
            func.substr(PushLog.query_date, 1, 7).label("month"),
            func.count(PushLog.id).label("total"),
            func.sum(case((PushLog.status == "success", 1), else_=0)).label("success"),
            func.sum(case((PushLog.status == "failed", 1), else_=0)).label("failed"),
            func.sum(case((PushLog.inconsistency == 1, 1), else_=0)).label("inconsistency"),
        )
        .group_by(func.substr(PushLog.query_date, 1, 7))
        .order_by(func.substr(PushLog.query_date, 1, 7).desc())
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
