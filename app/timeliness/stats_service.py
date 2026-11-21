# -*- coding: utf-8 -*-
"""病历时效统计分析聚合服务（WP03 T1，064 总计划需求 4）。

口径与 `_monthly_rows` 一致：
- 锁定次数 = TLApproval 中 apply_date_time 落在统计区间的行数（dept 按 dept_code、医生按 apply_user_id）；
- flag='1'=待审批锁定、'2'=已解锁、penalty_exempt=已豁免、
  有效扣罚 = flag='2' 且未豁免的 COALESCE(penalty_amount, 200) 合计；
- 事件按 TLEvent.t0 落区间（on_time/late/overdue/warning 状态分桶）；
- 按时率 = ON_TIME/(ON_TIME+LATE)*100，分母 0 记 0.0，保留 1 位；
- 平均超时小时 = OVERDUE+COMPLETED_LATE 的 overdue_minutes 平均/60，保留 1 位。

全部 SQL 聚合（func.count/sum(case)/group_by），禁止全表拉 Python 计数；
可见性复用 timeliness_visibility + _filter_dept（内部委托 data_scope）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models import Department, User
from app.timeliness.models import TLApproval, TLEvent, TLRule


def _day_bucket(col, dialect_name: str):
    """日期按天截断（方言分支）：Oracle=TRUNC(DATE)；SQLite=date() → 'YYYY-MM-DD' 字符串。"""
    if dialect_name == "oracle":
        return func.trunc(col)
    return func.date(col)


def _day_str(value: Any) -> str | None:
    """聚合结果统一格式化为 YYYY-MM-DD。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text or None


def compute_timeliness_analytics(
    db: Session, *,
    current_user: User,
    date_from: date,
    date_to: date,
    dept_code: str | None = None,
    top_n: int = 15,
) -> dict:
    """计算统计区间内的时效分析聚合（科室/医生排名、规则分布、每日趋势）。"""
    from app.routers.timeliness import _filter_dept, _display_maps
    from app.services.timeliness_access import timeliness_visibility

    window_start = datetime(date_from.year, date_from.month, date_from.day)
    window_end = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
    dialect_name = db.get_bind().dialect.name

    visibility = timeliness_visibility(db, current_user)

    # ---- 事件聚合（单 SQL：按天×状态计数 + 全窗状态分桶依赖趋势行；另做两条全窗聚合） ----
    event_q = db.query(TLEvent).filter(TLEvent.t0 >= window_start, TLEvent.t0 < window_end)
    event_q = visibility.apply(event_q, TLEvent.dept_code)
    event_q = _filter_dept(event_q, TLEvent.dept_code, db, current_user, dept_code)

    trend_rows = (
        event_q.with_entities(
            _day_bucket(TLEvent.t0, dialect_name).label("day"),
            func.count(TLEvent.id).label("total"),
            func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
            func.sum(case((TLEvent.status == "COMPLETED_ON_TIME", 1), else_=0)).label("on_time"),
            func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
        )
        .group_by(_day_bucket(TLEvent.t0, dialect_name))
        .all()
    )

    # 全窗事件状态分桶（单 SQL）
    status_row = event_q.with_entities(
        func.count(TLEvent.id).label("total"),
        func.sum(case((TLEvent.status == "COMPLETED_ON_TIME", 1), else_=0)).label("on_time"),
        func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
        func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
        func.sum(case((TLEvent.status == "WARNING", 1), else_=0)).label("warning"),
        func.sum(case(
            (TLEvent.status.in_(["OVERDUE", "COMPLETED_LATE"]), TLEvent.overdue_minutes),
            else_=None,
        )).label("overdue_minutes_sum"),
        func.count(case(
            (TLEvent.status.in_(["OVERDUE", "COMPLETED_LATE"]), TLEvent.overdue_minutes),
            else_=None,
        )).label("overdue_minutes_cnt"),
    ).first()

    total_events = int(status_row.total or 0) if status_row else 0
    on_time_count = int(status_row.on_time or 0) if status_row else 0
    late_completed_count = int(status_row.late or 0) if status_row else 0
    overdue_count = int(status_row.overdue or 0) if status_row else 0
    warning_count = int(status_row.warning or 0) if status_row else 0
    completed_total = on_time_count + late_completed_count
    on_time_rate = round(on_time_count * 100.0 / completed_total, 1) if completed_total else 0.0
    od_sum = int(status_row.overdue_minutes_sum or 0) if status_row and status_row.overdue_minutes_sum else 0
    od_cnt = int(status_row.overdue_minutes_cnt or 0) if status_row and status_row.overdue_minutes_cnt else 0
    avg_overdue_hours = round((od_sum / od_cnt) / 60.0, 1) if od_cnt else 0.0

    # ---- 锁定聚合（单 SQL 全窗 + 按天趋势） ----
    approval_q = db.query(TLApproval).filter(
        TLApproval.apply_date_time >= window_start, TLApproval.apply_date_time < window_end
    )
    approval_q = visibility.apply(approval_q, TLApproval.dept_code)
    approval_q = _filter_dept(approval_q, TLApproval.dept_code, db, current_user, dept_code)

    approval_row = approval_q.with_entities(
        func.count(TLApproval.id).label("locked"),
        func.sum(case((TLApproval.flag == "1", 1), else_=0)).label("pending"),
        func.sum(case((TLApproval.flag == "2", 1), else_=0)).label("unlocked"),
        func.sum(case((TLApproval.penalty_exempt == True, 1), else_=0)).label("exempt"),  # noqa: E712
        func.sum(case(
            ((TLApproval.flag == "2") & (TLApproval.penalty_exempt != True),
             func.coalesce(TLApproval.penalty_amount, 200)), else_=0,
        )).label("penalty"),
    ).first()
    locked_count = int(approval_row.locked or 0) if approval_row else 0
    locked_pending = int(approval_row.pending or 0) if approval_row else 0
    unlocked_count = int(approval_row.unlocked or 0) if approval_row else 0
    exempt_count = int(approval_row.exempt or 0) if approval_row else 0
    penalty_amount_total = int(approval_row.penalty or 0) if approval_row else 0

    lock_trend_rows = (
        approval_q.with_entities(
            _day_bucket(TLApproval.apply_date_time, dialect_name).label("day"),
            func.count(TLApproval.id).label("locked"),
        )
        .group_by(_day_bucket(TLApproval.apply_date_time, dialect_name))
        .all()
    )

    # ---- 科室排名（事件聚合 + 锁定聚合 Python 按 dept_code 合并） ----
    dept_event_rows = (
        event_q.with_entities(
            TLEvent.dept_code,
            func.count(TLEvent.id).label("total"),
            func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
            func.sum(case((TLEvent.status == "COMPLETED_ON_TIME", 1), else_=0)).label("on_time"),
            func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
        )
        .group_by(TLEvent.dept_code)
        .all()
    )
    dept_lock_rows = (
        approval_q.with_entities(
            TLApproval.dept_code,
            func.count(TLApproval.id).label("locked"),
            func.sum(case((TLApproval.flag == "1", 1), else_=0)).label("pending"),
            func.sum(case(
                ((TLApproval.flag == "2") & (TLApproval.penalty_exempt != True),
                 func.coalesce(TLApproval.penalty_amount, 200)), else_=0,
            )).label("penalty"),
        )
        .group_by(TLApproval.dept_code)
        .all()
    )

    dept_map: dict[str, dict[str, Any]] = {}
    for r in dept_event_rows:
        code = str(r.dept_code or "")
        bucket = dept_map.setdefault(code, {
            "dept_code": code, "dept_name": "", "locked_count": 0, "locked_pending": 0,
            "overdue_count": int(r.overdue or 0), "total_events": int(r.total or 0),
            "on_time": int(r.on_time or 0), "late": int(r.late or 0),
            "penalty_amount_total": 0,
        })
    for r in dept_lock_rows:
        code = str(r.dept_code or "")
        bucket = dept_map.setdefault(code, {
            "dept_code": code, "dept_name": "", "locked_count": 0, "locked_pending": 0,
            "overdue_count": 0, "total_events": 0, "on_time": 0, "late": 0,
            "penalty_amount_total": 0,
        })
        bucket["locked_count"] = int(r.locked or 0)
        bucket["locked_pending"] = int(r.pending or 0)
        bucket["penalty_amount_total"] = int(r.penalty or 0)

    dept_names_map = {
        (d.code or d.name or "").strip(): (d.name or "").strip()
        for d in db.query(Department).all()
    }
    dept_ranking = []
    for code, bucket in dept_map.items():
        done = bucket["on_time"] + bucket["late"]
        dept_ranking.append({
            "dept_code": code,
            "dept_name": dept_names_map.get(code, code or "未知"),
            "locked_count": bucket["locked_count"],
            "locked_pending": bucket["locked_pending"],
            "overdue_count": bucket["overdue_count"],
            "total_events": bucket["total_events"],
            "on_time_rate": round(bucket["on_time"] * 100.0 / done, 1) if done else 0.0,
            "penalty_amount_total": bucket["penalty_amount_total"],
        })
    dept_ranking.sort(key=lambda r: (-r["locked_count"], -r["overdue_count"]))
    dept_ranking = dept_ranking[:top_n]

    # ---- 医生排名（事件按 (responsible_doctor_id, dept_code)、锁定按 (apply_user_id, dept_code) 合并） ----
    doc_event_rows = (
        event_q.with_entities(
            TLEvent.responsible_doctor_id,
            TLEvent.dept_code,
            func.count(TLEvent.id).label("total"),
            func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
            func.sum(case((TLEvent.status == "COMPLETED_ON_TIME", 1), else_=0)).label("on_time"),
            func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
            func.sum(case(
                (TLEvent.status.in_(["OVERDUE", "COMPLETED_LATE"]), TLEvent.overdue_minutes),
                else_=None,
            )).label("od_sum"),
            func.count(case(
                (TLEvent.status.in_(["OVERDUE", "COMPLETED_LATE"]), TLEvent.overdue_minutes),
                else_=None,
            )).label("od_cnt"),
        )
        .group_by(TLEvent.responsible_doctor_id, TLEvent.dept_code)
        .all()
    )
    doc_lock_rows = (
        approval_q.with_entities(
            TLApproval.apply_user_id,
            TLApproval.dept_code,
            func.count(TLApproval.id).label("locked"),
            func.sum(case(
                ((TLApproval.flag == "2") & (TLApproval.penalty_exempt != True),
                 func.coalesce(TLApproval.penalty_amount, 200)), else_=0,
            )).label("penalty"),
        )
        .group_by(TLApproval.apply_user_id, TLApproval.dept_code)
        .all()
    )

    doc_map: dict[tuple[str, str], dict[str, Any]] = {}
    for r in doc_event_rows:
        doctor = str(r.responsible_doctor_id or "")
        code = str(r.dept_code or "")
        bucket = doc_map.setdefault((doctor, code), {
            "doctor_code": doctor, "dept_code": code,
            "locked_count": 0, "overdue_count": int(r.overdue or 0),
            "total_events": int(r.total or 0),
            "on_time": int(r.on_time or 0), "late": int(r.late or 0),
            "od_minutes": int(r.od_sum or 0), "od_cnt": int(r.od_cnt or 0),
            "penalty_amount_total": 0,
        })
    for r in doc_lock_rows:
        doctor = str(r.apply_user_id or "")
        code = str(r.dept_code or "")
        bucket = doc_map.setdefault((doctor, code), {
            "doctor_code": doctor, "dept_code": code,
            "locked_count": 0, "overdue_count": 0, "total_events": 0,
            "on_time": 0, "late": 0, "od_minutes": 0, "od_cnt": 0,
            "penalty_amount_total": 0,
        })
        bucket["locked_count"] = int(r.locked or 0)
        bucket["penalty_amount_total"] = int(r.penalty or 0)

    doctor_ranking = []
    for (doctor, code), bucket in doc_map.items():
        done = bucket["on_time"] + bucket["late"]
        doctor_ranking.append({
            "doctor_code": doctor,
            "doctor_name": doctor,
            "dept_code": code,
            "dept_name": dept_names_map.get(code, code or "未知"),
            "locked_count": bucket["locked_count"],
            "overdue_count": bucket["overdue_count"],
            "total_events": bucket["total_events"],
            "on_time_rate": round(bucket["on_time"] * 100.0 / done, 1) if done else 0.0,
            "avg_overdue_hours": round((bucket["od_minutes"] / bucket["od_cnt"]) / 60.0, 1)
            if bucket["od_cnt"] else 0.0,
            "penalty_amount_total": bucket["penalty_amount_total"],
        })
    doctor_ranking.sort(key=lambda r: (-r["locked_count"], -r["overdue_count"]))
    doctor_ranking = doctor_ranking[:100]

    # 医生姓名复用 _display_maps["staff"]（每次请求最多 1 次）
    display = _display_maps(db)
    for row in doctor_ranking:
        row["doctor_name"] = (display["staff"] or {}).get(row["doctor_code"], "") or row["doctor_code"]

    # ---- 规则分布 ----
    rule_rows = (
        event_q.with_entities(
            TLEvent.rule_code,
            func.count(TLEvent.id).label("total"),
            func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
            func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
        )
        .group_by(TLEvent.rule_code)
        .all()
    )
    rule_names = {
        r.rule_code: (r.rule_name or "")
        for r in db.query(TLRule.rule_code, TLRule.rule_name).all()
    }
    rule_breakdown = [
        {
            "rule_code": str(r.rule_code or ""),
            "rule_name": rule_names.get(str(r.rule_code or ""), str(r.rule_code or "")),
            "overdue_count": int(r.overdue or 0),
            "late_completed_count": int(r.late or 0),
            "total_events": int(r.total or 0),
        }
        for r in rule_rows
    ]

    # ---- 每日趋势（缺失日期补 0） ----
    trend_by_day = {str(r.day)[:10]: r for r in trend_rows}
    lock_by_day = {str(r.day)[:10]: int(r.locked or 0) for r in lock_trend_rows}
    daily_trend = []
    cursor = date_from
    while cursor <= date_to:
        key = cursor.strftime("%Y-%m-%d")
        tr = trend_by_day.get(key)
        total = int(tr.total or 0) if tr else 0
        on_time = int(tr.on_time or 0) if tr else 0
        late = int(tr.late or 0) if tr else 0
        done = on_time + late
        daily_trend.append({
            "date": key,
            "total": total,
            "overdue": int(tr.overdue or 0) if tr else 0,
            "locked": lock_by_day.get(key, 0),
            "on_time_rate": round(on_time * 100.0 / done, 1) if done else 0.0,
        })
        cursor += timedelta(days=1)

    return {
        "date_from": date_from.strftime("%Y-%m-%d"),
        "date_to": date_to.strftime("%Y-%m-%d"),
        "scope_label": _scope_label(db, current_user),
        "summary": {
            "total_events": total_events,
            "on_time_count": on_time_count,
            "late_completed_count": late_completed_count,
            "overdue_count": overdue_count,
            "warning_count": warning_count,
            "on_time_rate": on_time_rate,
            "locked_count": locked_count,
            "locked_pending": locked_pending,
            "unlocked_count": unlocked_count,
            "exempt_count": exempt_count,
            "penalty_amount_total": penalty_amount_total,
            "avg_overdue_hours": avg_overdue_hours,
        },
        "dept_ranking": dept_ranking,
        "doctor_ranking": doctor_ranking,
        "rule_breakdown": rule_breakdown,
        "daily_trend": daily_trend,
    }


def _scope_label(db: Session, current_user: User) -> str:
    from app.services.data_scope import resolve_user_data_scope

    scope = resolve_user_data_scope(db, current_user)
    return scope.label
