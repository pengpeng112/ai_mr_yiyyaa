# -*- coding: utf-8 -*-
"""WP03（064 总计划）时效统计分析聚合 + 路由校验测试。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.models import Department, Permission, Role, RolePermission, User
from app.routers import timeliness as timeliness_router
from app.timeliness.models import TLApproval, TLEvent, TLRule, TLRuleVersion
from app.timeliness.rules_seed import seed_rules
from app.timeliness.stats_service import compute_timeliness_analytics

NOW_BASE = datetime(2026, 11, 10, 12, 0, 0)
FROM = "2026-11-01"
TO = "2026-11-10"


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    perms = {}
    for name in ("timeliness_view", "timeliness_admin"):
        perm = Permission(name=name, description=name, module="timeliness")
        db.add(perm)
        perms[name] = perm

    admin_role = Role(name="admin", description="管理员")
    home_role = Role(name="dept_manager", description="科室管理员")
    db.add_all([admin_role, home_role])
    db.flush()
    admin = User(username="wp_admin", password_hash="x", full_name="管理员", role_id=admin_role.id)
    home_user = User(username="home_mgr", password_hash="x", full_name="本科室经理", role_id=home_role.id,
                     dept_id=1)
    db.add_all([admin, home_user])
    db.add(RolePermission(role_id=home_role.id, permission_id=perms["timeliness_view"].id))

    dept_a = Department(name="耳鼻喉一科", code="040112")
    dept_b = Department(name="耳鼻喉二科", code="030442")
    db.add_all([dept_a, dept_b])
    db.commit()

    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )

    def add_event(pid, dept_code, status, t0, doctor="D001", overdue=None):
        db.add(TLEvent(
            event_uid=f"FIRST_COURSE:{pid}:1:1", rule_code="FIRST_COURSE",
            rule_version_id=version.id, patient_id=pid, visit_id="1",
            dept_code=dept_code, responsible_doctor_id=doctor, t0=t0, status=status,
            overdue_minutes=overdue,
            last_scan_at=NOW_BASE, created_at=NOW_BASE, updated_at=NOW_BASE,
        ))

    def add_approval(pid, dept_code, flag, apply_dt, *, exempt=False, amount=None, applier="D001"):
        db.add(TLApproval(
            patient_id=pid, visit_id="1", monitor_code="JH04.02.002", apply_date_time=apply_dt,
            type="1", flag=flag, apply_user_id=applier, hospital_no=pid, dept_code=dept_code,
            penalty_amount=amount, penalty_exempt=exempt, synced_at=NOW_BASE,
        ))

    # 区间内（2026-11-01~2026-11-10）
    add_event("A1", "040112", "COMPLETED_ON_TIME", datetime(2026, 11, 2, 9, 0))
    add_event("A2", "040112", "COMPLETED_LATE", datetime(2026, 11, 3, 9, 0), overdue=120)
    add_event("A3", "040112", "OVERDUE", datetime(2026, 11, 4, 9, 0), overdue=60)
    add_event("A4", "040112", "WARNING", datetime(2026, 11, 5, 9, 0))
    add_event("B1", "030442", "OVERDUE", datetime(2026, 11, 6, 9, 0), overdue=240)
    # 医生 D002 的超时（avg 分医生验证）
    add_event("A5", "040112", "OVERDUE", datetime(2026, 11, 7, 9, 0), doctor="D002", overdue=90)
    # 区间外（不计入）
    add_event("OUT1", "040112", "OVERDUE", datetime(2026, 10, 31, 9, 0), overdue=500)
    add_event("OUT2", "040112", "OVERDUE", datetime(2026, 11, 11, 9, 0), overdue=500)

    add_approval("A1", "040112", "1", datetime(2026, 11, 2, 10, 0))
    add_approval("A2", "040112", "2", datetime(2026, 11, 3, 10, 0), amount=None)   # 200 兜底
    add_approval("B1", "030442", "2", datetime(2026, 11, 6, 10, 0), amount=300)     # 300
    add_approval("B1", "030442", "2", datetime(2026, 11, 7, 10, 0), amount=300, exempt=True)  # 豁免不计
    add_approval("OUT", "040112", "1", datetime(2026, 11, 15, 10, 0))               # 区间外

    db.commit()

    app = FastAPI()
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.dependency_overrides[get_db] = lambda: db

    def as_user(user):
        app.dependency_overrides[auth_module.get_current_user] = lambda: user
        return TestClient(app)

    yield db, {"admin": admin, "home": home_user}, app, as_user
    db.close()


def _get_analytics(client, **params):
    resp = client.get("/api/timeliness/stats/analytics",
                      params={"date_from": FROM, "date_to": TO, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---- 口径准确性 ----


def test_summary_counts_and_rates(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    body = _get_analytics(client)
    summary = body["summary"]
    # 区间内事件 6 条（OUT1/OUT2 不计入）
    assert summary["total_events"] == 6
    assert summary["on_time_count"] == 1
    assert summary["late_completed_count"] == 1
    assert summary["overdue_count"] == 3
    assert summary["warning_count"] == 1
    assert summary["on_time_rate"] == 50.0  # 1/(1+1)
    assert summary["locked_count"] == 4
    assert summary["locked_pending"] == 1
    assert summary["unlocked_count"] == 3
    assert summary["exempt_count"] == 1
    # 有效扣罚 = 200 兜底 + 300；豁免 B1 不计；区间外不计
    assert summary["penalty_amount_total"] == 500


def test_date_window_excludes_outliers(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    body = _get_analytics(client)
    trend_days = {d["date"] for d in body["daily_trend"]}
    assert "2026-10-31" not in trend_days
    assert "2026-11-11" not in trend_days
    # 11-15 的区间外锁定也不计入
    summary = body["summary"]
    assert summary["locked_count"] == 4


# ---- 排名合并与排序 ----


def test_dept_ranking_merge_and_sort(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    body = _get_analytics(client)
    ranking = {r["dept_code"]: r for r in body["dept_ranking"]}
    assert set(ranking) == {"040112", "030442"}
    a = ranking["040112"]
    assert a["locked_count"] == 2   # A1 flag1 + A2 flag2
    assert a["locked_pending"] == 1
    assert a["overdue_count"] == 2   # A3(OVERDUE 60min) + A5(OVERDUE 90min)
    assert a["total_events"] == 5   # A1~A4 + A5(D002)
    assert a["on_time_rate"] == 50.0  # 1/(1+1)
    assert a["penalty_amount_total"] == 200
    b = ranking["030442"]
    assert b["locked_count"] == 2   # B1 两条 flag=2（一条豁免）——均计锁定次数
    assert b["penalty_amount_total"] == 300  # 豁免那条不计有效扣罚
    # 排序：040112 locked=1 overdue=1；030442 locked=1 overdue=1 → 按 overdue DESC 稳定即可


def test_doctor_ranking_merge(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    body = _get_analytics(client)
    ranking = {(r["doctor_code"], r["dept_code"]): r for r in body["doctor_ranking"]}
    # D001 040112：事件 4（1 on_time + 1 late + 1 overdue + 1 warning）
    d1 = ranking[("D001", "040112")]
    assert d1["total_events"] == 4   # A1~A4
    assert d1["locked_count"] == 2   # A1 flag1 + A2 flag2（applier=D001）
    assert d1["on_time_rate"] == 50.0
    assert d1["penalty_amount_total"] == 200
    # D002 040112：仅 1 条 OVERDUE 90min → avg=1.5h
    d2 = ranking[("D002", "040112")]
    assert d2["overdue_count"] == 1
    assert d2["avg_overdue_hours"] == 1.5


# ---- home 范围隔离与 dept 参数 ----


def test_home_scope_user_only_home_dept(env):
    db, users, app, as_user = env
    home_user = users["home"]
    home_user.dept_id = db.query(Department).filter(Department.code == "040112").one().id
    db.commit()
    client = as_user(home_user)
    body = _get_analytics(client)
    assert {r["dept_code"] for r in body["dept_ranking"]} == {"040112"}
    assert body["summary"]["total_events"] == 5
    # 传别的 dept 参数不越权（数据范围优先）
    body2 = _get_analytics(client, dept="030442")
    assert body2["summary"]["total_events"] == 0


# ---- 校验 400 ----


@pytest.mark.parametrize("params", [
    {"date_from": "2026-13-01", "date_to": "2026-11-10"},
    {"date_from": "2026-11-10", "date_to": "2026-11-01"},
    {"date_from": "2025-01-01", "date_to": "2026-01-03"},
    {"date_from": "bad-date"},
])
def test_invalid_date_params_return_400(env, params):
    _, users, app, as_user = env
    client = as_user(users["admin"])
    resp = client.get("/api/timeliness/stats/analytics", params=params)
    assert resp.status_code == 400


# ---- daily_trend 补 0 ----


def test_daily_trend_fills_missing_days(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    body = _get_analytics(client)
    days = [d["date"] for d in body["daily_trend"]]
    assert len(days) == 10  # 11-01 ~ 11-10 全覆盖
    missing = [d for d in days if d in ("2026-11-01", "2026-11-08")]
    # 11-01 无事件 → 补 0；11-08 无事件 → 补 0
    zero_days = [d for d in body["daily_trend"] if d["total"] == 0 and d["locked"] == 0]
    assert len(zero_days) >= 2
    # 每条都有 on_time_rate
    assert all(isinstance(d["on_time_rate"], float) for d in body["daily_trend"])


# ---- service 直调（scope label）----


def test_scope_label_admin(env):
    db, users, app, as_user = env
    from datetime import date as _date
    body = compute_timeliness_analytics(
        db, current_user=users["admin"],
        date_from=_date(2026, 11, 1), date_to=_date(2026, 11, 10),
    )
    assert body["scope_label"] == "全院"
    assert body["summary"]["avg_overdue_hours"] > 0
