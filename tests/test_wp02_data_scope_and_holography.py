"""WP02（064 D5/D1）统一数据范围 + 360 全息视图后端测试（2026-11-19）。

覆盖任务书 §五 10+ 用例：admin=all / home 科室隔离 / selected 多科精准 /
用户覆盖优先 / 无科室安全空集 / batch-update 护栏 / access-bundle 原子保存 /
holography 默认值与 user_code 规则 / relay-alert 放宽与隔离 / departments paged /
users 旧参数兼容。
"""
from __future__ import annotations

import json

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.models import (
    Department, Permission, PushLog, QCFeedback, QCRecordAlertLog,
    Role, RoleDepartment, RoleMenu, RolePermission, User,
)
from app.services.data_scope import resolve_user_data_scope
from app.timeliness.models import TLEvent, TLApproval, TLRule, TLRuleVersion, TLScanRun
from app.timeliness.rules_seed import seed_rules

NOW = datetime(2026, 11, 19, 12, 0, 0)


@pytest.fixture()
def env():
    import app.timeliness.models  # noqa: F401 — 注册 timeliness 表
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    perms = {}
    for name in ("view_reports", "timeliness_view", "timeliness_admin", "timeliness_approve"):
        perm = Permission(name=name, description=name, module="qc_reports" if name == "view_reports" else "timeliness")
        db.add(perm)
        perms[name] = perm

    admin_role = Role(name="admin", description="管理员")
    home_role = Role(name="dept_manager", description="科室管理员")
    sel_role = Role(name="auditor", description="质控审核员")
    viewer_role = Role(name="timeliness_reader", description="只读")
    nomad_role = Role(name="clinician", description="临床（无科室）")
    db.add_all([admin_role, home_role, sel_role, viewer_role, nomad_role])
    db.flush()
    # 角色权限：admin 角色名即放行；其余挂 view_reports/timeliness_view
    for role_obj in (home_role, sel_role, viewer_role, nomad_role):
        for pname in ("view_reports", "timeliness_view"):
            db.add(RolePermission(role_id=role_obj.id, permission_id=perms[pname].id))

    admin = User(username="admin", password_hash="x", full_name="管理员", role_id=admin_role.id)
    home_user = User(username="home_mgr", password_hash="x", full_name="本科室经理", role_id=home_role.id)
    sel_user = User(username="auditor1", password_hash="x", full_name="审核员", role_id=sel_role.id)
    nomad = User(username="nomad1", password_hash="x", full_name="无科室用户", role_id=nomad_role.id)
    emp = User(username="003966", password_hash="x", full_name="工号员工", role_id=viewer_role.id)
    db.add_all([admin, home_user, sel_user, nomad, emp])

    dept_a = Department(name="耳鼻喉一科", code="040112")
    dept_b = Department(name="耳鼻喉二科", code="030442")
    dept_c = Department(name="PCCM", code="030326")
    db.add_all([dept_a, dept_b, dept_c])
    db.flush()

    home_user.dept_id = dept_a.id
    # selected：auditor1 角色默认（timeliness_access_json）
    import json as _json
    sel_role.timeliness_access_json = _json.dumps({
        "scope": "selected", "department_codes": ["040112", "030442"], "default_view": "home",
    })
    # legacy RoleDepartment：viewer 角色绑 PCCM
    db.add(RoleDepartment(role_id=viewer_role.id, dept_id=dept_c.id))
    db.add_all([RoleDepartment(role_id=admin_role.id, dept_id=dept_a.id)])
    db.commit()
    admin_role_row = db.query(Role).filter(Role.name == "admin").one()
    db.query(RoleDepartment).filter(RoleDepartment.role_id == admin_role_row.id).delete()

    # 业务数据：两科室各 1 条事件/告警/日志/反馈/审批
    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )
    db.add(TLEvent(
        event_uid="FC:A:1:1", rule_code="FIRST_COURSE", rule_version_id=version.id,
        patient_id="PA", visit_id="1", dept_code="040112", t0=NOW, status="OVERDUE",
        last_scan_at=NOW, created_at=NOW, updated_at=NOW,
    ))
    db.add(TLEvent(
        event_uid="FC:B:1:1", rule_code="FIRST_COURSE", rule_version_id=version.id,
        patient_id="PB", visit_id="1", dept_code="030442", t0=NOW, status="WARNING",
        last_scan_at=NOW, created_at=NOW, updated_at=NOW,
    ))
    db.add(TLApproval(
        patient_id="PA", visit_id="1", monitor_code="JH04.02.002", apply_date_time=NOW,
        type="1", flag="1", hospital_no="PA", dept_code="040112", penalty_amount=200, synced_at=NOW,
    ))
    db.add(PushLog(
        push_time=NOW, trigger_type="auto", query_date="2026-11-19",
        patient_id="PA", visit_number="1", audit_type_code="progress_vs_nursing",
        dept="耳鼻喉一科", discharge_dept="耳鼻喉一科", status="success",
        severity="high", inconsistency=1, mr_text="L" * 3000,
    ))
    db.flush()
    db.add(PushLog(
        push_time=NOW, trigger_type="auto", query_date="2026-11-19",
        patient_id="PB", visit_number="1", audit_type_code="progress_vs_nursing",
        dept="耳鼻喉二科", status="success", severity="medium",
    ))
    push_row = db.query(PushLog).filter(PushLog.patient_id == "PA").first()
    db.add(QCRecordAlertLog(
        push_log_id=push_row.id, dimension_code="FOLLOW_UP",
        patient_id="PA", dept="耳鼻喉一科", status="failed", viewed_flag=0, created_at=NOW,
    ))
    db.add(QCFeedback(push_log_id=1, dept_id=dept_a.id, severity="high", created_by=1))
    db.commit()

    app = FastAPI()
    from app.routers import users as users_router
    from app.routers import roles as roles_router
    from app.routers import departments as departments_router
    from app.routers import patient_qc as patient_qc_router
    from app.routers import stats as stats_router
    from app.routers import logs as logs_router
    from app.routers import timeliness as timeliness_router
    from app.routers import config as config_router
    app.include_router(users_router.router, prefix="/api/users")
    app.include_router(roles_router.router, prefix="/api/roles")
    app.include_router(departments_router.router, prefix="/api/departments")
    app.include_router(patient_qc_router.router, prefix="/api/patient-qc")
    app.include_router(stats_router.router, prefix="/api/stats")
    app.include_router(logs_router.router, prefix="/api/logs")
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.include_router(config_router.router, prefix="/api/config")
    app.dependency_overrides[get_db] = lambda: db

    def as_user(user):
        app.dependency_overrides[auth_module.get_current_user] = lambda: user
        return TestClient(app)

    yield db, {"admin": admin, "home": home_user, "sel": sel_user, "nomad": nomad,
               "emp": emp}, app, as_user
    db.close()


# ---- 1. admin → all ----


def test_admin_resolves_to_all(env):
    db, users, app, as_user = env
    scope = resolve_user_data_scope(db, users["admin"])
    assert scope.scope == "all" and scope.source == "admin" and scope.label == "全院"


# ---- 2. home 隔离（stats/logs/patient-qc/relay-alert/timeliness） ----


def test_home_role_sees_only_home_dept_across_modules(env):
    db, users, app, as_user = env
    client = as_user(users["home"])

    logs = client.get("/api/logs").json()
    assert logs["total"] >= 1 and all(i["dept"] == "耳鼻喉一科" for i in logs["items"])

    events = client.get("/api/timeliness/events?limit=50").json()
    assert events["total"] >= 1 and all(i["dept_code"] == "040112" for i in events["items"])

    relay = client.get("/api/patient-qc/relay-alert/summary").json()
    assert relay["total"] == 1  # 仅 040112 告警

    monthly = client.get("/api/timeliness/stats/monthly").json()
    assert all(r["dept_code"] == "040112" for r in monthly["rows"])


# ---- 3. selected 多科室精准匹配 ----


def test_selected_role_matches_exact_depts(env):
    db, users, app, as_user = env
    scope = resolve_user_data_scope(db, users["sel"])
    assert scope.scope == "selected" and scope.source == "role"
    assert set(scope.dept_codes) == {"040112", "030442"}

    client = as_user(users["sel"])
    events = client.get("/api/timeliness/events?limit=50").json()
    assert {i["dept_code"] for i in events["items"]} <= {"040112", "030442"}


# ---- 4. 用户个人覆盖优先于角色默认 ----


def test_user_override_beats_role_default(env):
    db, users, app, as_user = env
    import json as _json
    sel_user = users["sel"]
    # 角色默认 selected(040112,030442)；个人覆盖 home
    sel_user.timeliness_access_json = _json.dumps({
        "scope": "home", "department_codes": [], "default_view": "home",
    })
    db.commit()
    scope = resolve_user_data_scope(db, sel_user)
    assert scope.scope == "home" and scope.source == "user"
    # sel_user 无 dept_id → home 空集（安全默认，绝不放大成角色 selected 的两科）
    assert scope.dept_codes == ()


# ---- 5. 无科室普通用户安全空集 ----


def test_nomad_user_safely_empty_not_all(env):
    db, users, app, as_user = env
    scope = resolve_user_data_scope(db, users["nomad"])
    assert scope.scope == "home" and scope.source == "default"
    assert scope.dept_codes == () and scope.dept_names == ()
    assert scope.is_all is False

    client = as_user(users["nomad"])
    assert client.get("/api/logs").json()["total"] == 0
    assert client.get("/api/timeliness/events").json()["total"] == 0


# ---- 6. batch-update ----


def test_batch_update_success_and_guards(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    sel_role = db.query(Role).filter(Role.name == "auditor").one()

    resp = client.post("/api/users/batch-update", json={
        "user_ids": [users["nomad"].id],
        "role_id": sel_role.id,
        "is_active": True,
        "data_scope": {"mode": "selected", "department_codes": ["040112"]},
    })
    assert resp.status_code == 200
    db.refresh(users["nomad"])
    assert users["nomad"].role_id == sel_role.id
    user_cfg = json.loads(users["nomad"].timeliness_access_json or "{}")
    assert user_cfg["scope"] == "selected" and user_cfg["department_codes"] == ["040112"]
    scope = resolve_user_data_scope(db, users["nomad"])
    assert scope.dept_codes == ("040112",)

    # 禁禁用自己
    self_resp = client.post("/api/users/batch-update", json={
        "user_ids": [users["admin"].id], "is_active": False,
    })
    assert self_resp.status_code == 400

    # 禁禁用最后一个活跃 admin
    last_resp = client.post("/api/users/batch-update", json={
        "user_ids": [users["admin"].id, users["home"].id], "is_active": True,
    })
    assert last_resp.status_code == 200
    disable_resp = client.post("/api/users/batch-update", json={
        "user_ids": [users["admin"].id], "is_active": False,
    })
    assert disable_resp.status_code == 400

    # 批量 >200 拒绝
    big = client.post("/api/users/batch-update", json={
        "user_ids": list(range(1, 202)), "is_active": True,
    })
    assert big.status_code == 400


def test_batch_update_requires_admin(env):
    _, users, app, as_user = env
    client = as_user(users["home"])
    resp = client.post("/api/users/batch-update", json={"user_ids": [1], "is_active": True})
    assert resp.status_code == 403


# ---- 7. access-bundle 原子保存 ----


def test_role_access_bundle_atomic_save(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    sel_role = db.query(Role).filter(Role.name == "auditor").one()

    resp = client.put(f"/api/roles/{sel_role.id}/access-bundle", json={
        "menu_ids": ["workbench", "timeliness-stats", "timeliness-events"],
        "permission_ids": [p.id for p in db.query(Permission).all()[:2]],
        "data_scope": {"scope": "selected", "department_codes": ["040112", "030326"], "default_view": "home"},
    })
    print("DEBUG_BUNDLE:", resp.status_code, repr(resp.text[:300]))
    assert resp.status_code == 200
    body = resp.json()
    menu_ids = {m["id"] if isinstance(m, dict) else m for m in body["menus"]}
    assert "timeliness-stats" in menu_ids

    # RoleMenu/RolePermission/timeliness_access_json/RoleDepartment 全部同步
    menus = {m.menu_id for m in db.query(RoleMenu).filter(RoleMenu.role_id == sel_role.id).all()}
    assert menus == {"workbench", "timeliness-stats", "timeliness-events"}
    role_cfg = json.loads(sel_role.timeliness_access_json or "{}")
    assert role_cfg["scope"] == "selected" and set(role_cfg["department_codes"]) == {"040112", "030326"}
    bound = {d.code for d in db.query(Department).join(
        RoleDepartment, RoleDepartment.dept_id == Department.id
    ).filter(RoleDepartment.role_id == sel_role.id).all()}
    assert bound == {"040112", "030326"}

    # 无效菜单 ID 拒绝
    bad = client.put(f"/api/roles/{sel_role.id}/access-bundle", json={
        "menu_ids": ["no-such-menu"], "permission_ids": [],
    })
    assert bad.status_code == 400

    # 非 admin 403
    denied = as_user(users["home"])
    assert denied.put(f"/api/roles/{sel_role.id}/access-bundle", json={
        "menu_ids": [], "permission_ids": [],
    }).status_code == 403


# ---- 8. holography 配置与 user_code ----


def test_holography_defaults_and_user_code(env):
    db, users, app, as_user = env
    # 工号员工
    client = as_user(users["emp"])
    body = client.get("/api/config/holography").json()
    assert body["sys_code"] == "S28"
    assert body["fallback_user_code"] == "wfy"
    assert body["enabled"] is True
    assert body["user_code"] == "003966"

    # admin → wfy
    admin_client = as_user(users["admin"])
    assert admin_client.get("/api/config/holography").json()["user_code"] == "wfy"

    # 更新校验：非法正则 400
    bad = admin_client.post("/api/config/holography", json={
        "enabled": True, "base_url": "http://x/y", "sys_code": "S28",
        "employee_code_pattern": "([bad",
    })
    assert bad.status_code == 400

    # 合法更新 + base_url 校验
    ok = admin_client.post("/api/config/holography", json={
        "enabled": True, "base_url": "http://10.10.8.231:8281/h", "sys_code": "S28",
        "fallback_user_code": "wfy",
    })
    assert ok.status_code == 200
    bad_url = admin_client.post("/api/config/holography", json={
        "enabled": True, "base_url": "ftp://nope", "sys_code": "S28",
    })
    assert bad_url.status_code == 400

    # 保存后 GET 反映新值（只写本节）
    assert admin_client.get("/api/config/holography").json()["base_url"] == "http://10.10.8.231:8281/h"

    # 未登录/非 admin 写 403
    assert as_user(users["home"]).post("/api/config/holography", json={
        "enabled": True, "base_url": "http://x", "sys_code": "S",
    }).status_code == 403


# ---- 9. relay-alert：home 隔离 + retry 仍 admin ----


def test_relay_alert_home_scope_and_retry_admin_only(env):
    db, users, app, as_user = env
    home_client = as_user(users["home"])
    summary = home_client.get("/api/patient-qc/relay-alert/summary").json()
    assert summary["total"] == 1  # 仅本科室

    logs = home_client.get("/api/patient-qc/relay-alert/logs").json()
    assert all("耳鼻喉一科" in (i.get("dept") or "") for i in logs["items"])

    retry = home_client.post("/api/patient-qc/relay-alert/retry/1")
    assert retry.status_code == 403  # 写操作仍 admin

    report = home_client.get("/api/patient-qc/alert-status-report")
    assert report.status_code == 403  # 全院账实报告保持 admin


# ---- 10. departments 结构兼容 + paged + users 旧参数 ----


def test_departments_list_unchanged_and_paged(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    lst = client.get("/api/departments")
    assert lst.status_code == 200
    assert isinstance(lst.json(), list)  # 结构不变（仍是列表）

    paged = client.get("/api/departments/paged", params={"keyword": "耳鼻喉", "page": 1, "limit": 1})
    assert paged.status_code == 200
    body = paged.json()
    assert body["total"] >= 2
    assert len(body["items"]) == 1
    assert body["items"][0]["user_count"] >= 1  # GROUP BY 聚合

    # /paged 不被 /{dept_id} 捕获（上面 200 已证）


def test_users_list_old_params_unchanged_and_new_filters(env):
    db, users, app, as_user = env
    client = as_user(users["admin"])
    # 旧参数
    resp = client.get("/api/users", params={"page": 1, "limit": 5, "q": "home"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1 and body["limit"] == 5
    assert body["items"][0]["username"] == "home_mgr"
    # effective_scope 只读字段已下发
    assert body["items"][0]["effective_scope"]["scope"] == "home"

    # 新筛选：unassigned_role / dept_id / is_active
    no_role = client.get("/api/users", params={"unassigned_role": True})
    assert no_role.status_code == 200 and no_role.json()["total"] == 0
    by_dept = client.get("/api/users", params={"dept_id": users["home"].dept_id})
    assert by_dept.json()["total"] == 1

    # scope=selected 过滤（角色默认 selected 的 auditor1 命中）
    by_scope = client.get("/api/users", params={"scope": "selected"})
    assert by_scope.status_code == 200
    usernames = {i["username"] for i in by_scope.json()["items"]}
    assert "auditor1" in usernames


# ---- 11. 走查回归保护：数字 ID 顺序 / holography get_db / admin access-bundle ----


def test_resolve_selected_triplet_numeric_ids_and_order(env):
    """回归保护（P1-1）：_resolve_selected_triplet 兼容数字科室 ID 并保持调用顺序。"""
    from app.services.data_scope import _resolve_selected_triplet

    db, _, _, _ = env
    d1 = db.query(Department).filter(Department.code == "040112").one()
    d2 = db.query(Department).filter(Department.code == "030326").one()

    codes_by_id, _, ids_by_id = _resolve_selected_triplet(db, [str(d2.id), str(d1.id)])
    assert codes_by_id == ("030326", "040112")
    assert ids_by_id == (d2.id, d1.id)

    codes_by_code, _, _ = _resolve_selected_triplet(db, ["030326", "040112"])
    assert codes_by_code == ("030326", "040112")


def test_holography_save_uses_injected_db_not_sessionlocal(env, monkeypatch):
    """回归保护（P1-2）：POST /api/config/holography 必须走 Depends(get_db)，不得自建 SessionLocal。"""
    import app.database as db_module

    _, users, _, as_user = env

    def _boom():
        raise AssertionError("save_holography_config 不得绕过 Depends(get_db) 直接创建 SessionLocal")

    monkeypatch.setattr(db_module, "SessionLocal", _boom)
    assert as_user(users["home"]).post("/api/config/holography", json={
        "enabled": True, "base_url": "http://10.10.8.231:8281/h", "sys_code": "S28",
    }).status_code == 403
    assert as_user(users["admin"]).post("/api/config/holography", json={
        "enabled": True, "base_url": "http://10.10.8.231:8281/h", "sys_code": "S28",
    }).status_code == 200


def test_role_access_bundle_protects_admin_role(env):
    """回归保护（P1-3）：access-bundle 禁止降级 admin 数据范围或移除 access 菜单。"""
    db, users, _, as_user = env
    client = as_user(users["admin"])
    admin_role = db.query(Role).filter(Role.name == "admin").one()

    # 试图将 admin 降级为 home 范围 → 400
    bad_scope = client.put(f"/api/roles/{admin_role.id}/access-bundle", json={
        "menu_ids": ["dashboard", "access"],
        "permission_ids": [],
        "data_scope": {"scope": "home", "department_codes": [], "default_view": "home"},
    })
    assert bad_scope.status_code == 400

    # 试图移除 admin 的 access 菜单 → 400
    bad_menu = client.put(f"/api/roles/{admin_role.id}/access-bundle", json={
        "menu_ids": ["dashboard"],
        "permission_ids": [],
        "data_scope": {"scope": "all", "department_codes": [], "default_view": "all"},
    })
    assert bad_menu.status_code == 400

    # 保留 all 范围与 access 菜单 → 200
    ok = client.put(f"/api/roles/{admin_role.id}/access-bundle", json={
        "menu_ids": ["dashboard", "access"],
        "permission_ids": [],
        "data_scope": {"scope": "all", "department_codes": [], "default_view": "all"},
    })
    assert ok.status_code == 200
