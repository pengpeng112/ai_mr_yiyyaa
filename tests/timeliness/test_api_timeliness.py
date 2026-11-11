"""T5：/api/timeliness 后端 API 测试（权限/可见性/版本不覆盖/dry-run/导出审计/D8）。

覆盖（主设计文档 §15 T5 + 用户任务书）：
- 权限拒绝 403（无权限访问规则列表/编辑/导出/扫描记录）；
- 科室可见性：普通用户只见本院区科室事件，越权详情 404，admin 全院；
- 保存新版本不覆盖旧版本（旧版本行原样保留，当前版本切换）；
- dry-run 不写库（事件/历史/扫描批次/版本表行数全部不变）；
- 导出写 ExportAuditLog（export_type=timeliness_monthly）；
- D8 防呆：ADM_REC / CHIEF_FIRST_ROUND 设 LOCK_EMR 一律 400（即使 admin +
  jhemr_write.enabled=true）；FIRST_COURSE 的 LOCK_EMR 需 admin 权限与写开关双闸门。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth as auth_module
from app.database import Base, get_db
from app.models import Department, ExportAuditLog, Permission, Role, RolePermission, User
from app.routers import timeliness as timeliness_router
from app.timeliness.models import TLEvent, TLEventHistory, TLRule, TLRuleVersion, TLScanRun
from app.timeliness.rules_seed import seed_rules

NOW = datetime(2026, 11, 10, 12, 0, 0)


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    permissions = {}
    for name in ("timeliness_view", "timeliness_rule_edit", "timeliness_export", "timeliness_admin"):
        perm = Permission(name=name, description=name, module="timeliness")
        db.add(perm)
        permissions[name] = perm

    admin_role = Role(name="admin", description="管理员")
    db.add(admin_role)
    db.flush()

    def make_user(username: str, role: Role | None, dept_id=None) -> User:
        user = User(username=username, password_hash="x", full_name=username,
                    role_id=role.id if role else None, dept_id=dept_id)
        db.add(user)
        return user

    def make_role(name: str, perms: list[str]) -> Role:
        role = Role(name=name, description=name)
        db.add(role)
        db.flush()
        for perm_name in perms:
            db.add(RolePermission(role_id=role.id, permission_id=permissions[perm_name].id))
        return role

    admin = make_user("tl_admin", admin_role)
    viewer = make_user("tl_viewer", make_role("tl_viewer", ["timeliness_view"]))
    editor = make_user("tl_editor", make_role("tl_editor", ["timeliness_view", "timeliness_rule_edit"]))
    # 可锁定口径的编辑者：rule_edit + timeliness_admin（但仍受 jhemr_write 闸门）
    editor_admin = make_user(
        "tl_editor_admin",
        make_role("tl_editor_admin", ["timeliness_view", "timeliness_rule_edit", "timeliness_admin"]),
    )

    dept_ear = Department(name="耳科", code="0201")
    dept_nose = Department(name="鼻科", code="0202")
    db.add_all([dept_ear, dept_nose])
    db.flush()
    scoped = make_user("tl_scoped", make_role("tl_scoped", ["timeliness_view"]), dept_id=dept_ear.id)

    # 两条不同科室的事件（挂在 FIRST_COURSE 当前版本下）
    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )
    for pid, dept_code in (("T0001", "0201"), ("T0002", "0202")):
        db.add(TLEvent(
            event_uid=f"FIRST_COURSE:{pid}:1:1", rule_code="FIRST_COURSE",
            rule_version_id=version.id, patient_id=pid, visit_id="1",
            dept_code=dept_code, t0=NOW, status="OVERDUE", overdue_minutes=60,
            last_scan_at=NOW, created_at=NOW, updated_at=NOW,
        ))
    db.commit()

    app = FastAPI()
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.dependency_overrides[get_db] = lambda: db
    yield db, {"admin": admin, "viewer": viewer, "editor": editor,
               "editor_admin": editor_admin, "scoped": scoped}, app
    db.close()


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


def _enable_write(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        timeliness_router, "load_config",
        lambda: {"timeliness": {"enabled": True, "jhemr_write": {"enabled": enabled}}},
    )


# ---- 字典 ----


def test_dicts_endpoint_returns_dictionaries(env):
    db, users, app = env
    resp = client_as(app, users["viewer"]).get("/api/timeliness/dicts")
    assert resp.status_code == 200
    body = resp.json()
    codes = {item["code"] for item in body["trigger_types"]}
    assert {"ADMISSION", "OPERATION_END", "CONSULT_APPLY"} <= codes
    mr = {item["code"] for item in body["mr_class"]}
    assert {"EMR09.00.01", "EMR10.00.01", "EMR12.00"} <= mr
    items = {item["code"]: item for item in body["monitor_items"]["items"]}
    assert items["JH04.02.002"]["jhemr_generated"] is True   # 实证 R2：4 类自动生成
    assert items["JH04.02.001"]["jhemr_generated"] is True
    assert items["JH04.02.008"]["jhemr_generated"] is True
    assert set(body["d8_no_lock_rule_codes"]) == {"ADM_REC", "CHIEF_FIRST_ROUND"}


# ---- 权限矩阵 ----


@pytest.mark.parametrize("user_key,path,expected", [
    ("viewer", "/api/timeliness/rules", 200),
    ("admin", "/api/timeliness/rules", 200),
    ("editor", "/api/timeliness/rules", 200),
    ("scoped", "/api/timeliness/rules", 200),
])
def test_rules_list_requires_view(env, user_key, path, expected):
    db, users, app = env
    resp = client_as(app, users[user_key]).get(path)
    assert resp.status_code == expected
    if expected == 200:
        body = resp.json()
        assert body["total"] == 18
        sample = next(r for r in body["items"] if r["rule_code"] == "FIRST_COURSE")
        assert sample["current_version"]["limit_minutes"] == 480


def test_permission_denials_403(env):
    db, users, app = env
    # viewer 无编辑权限：保存版本 403
    resp = client_as(app, users["viewer"]).post(
        "/api/timeliness/rules/FIRST_COURSE/versions", json={"limit_minutes": 600})
    assert resp.status_code == 403
    # viewer 无导出权限：403
    resp = client_as(app, users["viewer"]).get("/api/timeliness/export/monthly?month=2026-11")
    assert resp.status_code == 403
    # viewer 无 admin 权限：扫描记录 403
    resp = client_as(app, users["viewer"]).get("/api/timeliness/scan-runs")
    assert resp.status_code == 403
    # editor 无导出权限：403（编辑权限不能导出）
    resp = client_as(app, users["editor"]).get("/api/timeliness/export/monthly?month=2026-11")
    assert resp.status_code == 403
    # admin 可以读扫描记录
    resp = client_as(app, users["admin"]).get("/api/timeliness/scan-runs")
    assert resp.status_code == 200


# ---- 科室可见性 ----


def test_events_visibility_scoped_user_sees_only_own_dept(env):
    db, users, app = env
    scoped = client_as(app, users["scoped"])
    body = scoped.get("/api/timeliness/events").json()
    assert body["total"] == 1
    assert body["items"][0]["dept_code"] == "0201"
    # 按名称过滤也受可见性约束
    body = scoped.get("/api/timeliness/events", params={"dept": "鼻科"}).json()
    assert body["total"] == 0

    admin = client_as(app, users["admin"])
    body = admin.get("/api/timeliness/events").json()
    assert body["total"] == 2


def test_event_detail_hidden_for_out_of_scope_user(env):
    db, users, app = env
    ear_event = db.query(TLEvent).filter(TLEvent.dept_code == "0201").one()
    nose_event = db.query(TLEvent).filter(TLEvent.dept_code == "0202").one()
    scoped = client_as(app, users["scoped"])
    assert scoped.get(f"/api/timeliness/events/{ear_event.id}").status_code == 200
    assert scoped.get(f"/api/timeliness/events/{nose_event.id}").status_code == 404
    detail = scoped.get(f"/api/timeliness/events/{ear_event.id}").json()
    assert detail["event_uid"].startswith("FIRST_COURSE:")
    assert isinstance(detail["history"], list)


def test_events_date_filter_inclusive_and_invalid_returns_400(env):
    """修订回归（2026-11-11）：date_to 传纯日期含当日全天；非法日期 400 而非 500。

    fixture 事件 t0=2026-11-10 12:00——修订前 date_to=2026-11-10 解析为零点，
    两条事件被静默排除；非法日期此前抛未捕获 ValueError → 500。
    """
    db, users, app = env
    admin = client_as(app, users["admin"])
    body = admin.get("/api/timeliness/events", params={"date_to": "2026-11-10"}).json()
    assert body["total"] == 2                       # 含当日（23:59:59.999999 截止）
    body = admin.get("/api/timeliness/events", params={"date_to": "2026-11-09"}).json()
    assert body["total"] == 0                       # 当日之前为空
    body = admin.get("/api/timeliness/events", params={"date_from": "2026-11-10"}).json()
    assert body["total"] == 2
    body = admin.get("/api/timeliness/events",
                     params={"date_from": "2026-11-10", "date_to": "2026-11-10"}).json()
    assert body["total"] == 2
    resp = admin.get("/api/timeliness/events", params={"date_from": "not-a-date"})
    assert resp.status_code == 400
    resp = admin.get("/api/timeliness/events", params={"date_to": "2026-13-40"})
    assert resp.status_code == 400


# ---- 版本管理（不覆盖旧版本） ----


def test_save_new_version_keeps_old_version(env):
    db, users, app = env
    client = client_as(app, users["editor"])
    resp = client.post("/api/timeliness/rules/FIRST_COURSE/versions",
                       json={"limit_minutes": 600, "warn_before_minutes": 60})
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"]["version_no"] == 2
    assert body["version"]["limit_minutes"] == 600

    versions = client.get("/api/timeliness/rules/FIRST_COURSE/versions").json()
    assert versions["total"] == 2
    v1 = next(v for v in versions["items"] if v["version_no"] == 1)
    assert v1["limit_minutes"] == 480            # 旧版本原样保留
    rule_row = db.query(TLRule).filter(TLRule.rule_code == "FIRST_COURSE").one()
    assert rule_row.current_version_id == body["version"]["id"]

    # 不存在规则 404；非法字段 400
    assert client.post("/api/timeliness/rules/NO_SUCH/versions",
                       json={"limit_minutes": 1}).status_code == 404
    resp = client.post("/api/timeliness/rules/FIRST_COURSE/versions",
                       json={"limit_minutes": -5})
    assert resp.status_code == 400


def test_toggle_rule(env):
    db, users, app = env
    client = client_as(app, users["editor"])
    resp = client.post("/api/timeliness/rules/ADM_REC/toggle", json={"enabled": True})
    assert resp.status_code == 200
    assert db.query(TLRule).filter(TLRule.rule_code == "ADM_REC").one().enabled is True
    assert client.post("/api/timeliness/rules/ADM_REC/toggle",
                       json={"enabled": False}).status_code == 200


# ---- dry-run（不写库） ----


def test_dry_run_writes_nothing(env):
    db, users, app = env
    before = (
        db.query(TLEvent).count(),
        db.query(TLEventHistory).count(),
        db.query(TLScanRun).count(),
        db.query(TLRuleVersion).count(),
        db.query(TLRule).count(),
    )
    client = client_as(app, users["viewer"])
    resp = client.post("/api/timeliness/rules/FIRST_COURSE/dry-run",
                       json={"limit_minutes": 600})
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["data_source"] == "unavailable"      # 本地无 JHEMR 只读配置
    assert "stats" in body and "samples" in body
    after = (
        db.query(TLEvent).count(),
        db.query(TLEventHistory).count(),
        db.query(TLScanRun).count(),
        db.query(TLRuleVersion).count(),
        db.query(TLRule).count(),
    )
    assert after == before                            # 绝不写库


def test_dry_run_rejects_d8_lock(env):
    db, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/timeliness/rules/ADM_REC/dry-run",
                       json={"action_mode": "LOCK_EMR"})
    assert resp.status_code == 400
    assert "D8" in resp.json()["detail"]


# ---- D8 防呆（§18.1/§18.6） ----


def test_d8_blocks_lock_emr_even_for_admin_with_write_enabled(env, monkeypatch):
    db, users, app = env
    _enable_write(monkeypatch, True)                  # 写开关打开也必须拒绝
    client = client_as(app, users["admin"])
    for rule_code in ("ADM_REC", "CHIEF_FIRST_ROUND"):
        resp = client.post(f"/api/timeliness/rules/{rule_code}/versions",
                           json={"action_mode": "LOCK_EMR"})
        assert resp.status_code == 400, rule_code
        assert "D8" in resp.json()["detail"]
        assert "JH04.02.002" in resp.json()["detail"]  # 提示仅 FIRST_COURSE/002 可开锁定
        # 版本表无新增（写入被拒绝）
        versions = client.get(f"/api/timeliness/rules/{rule_code}/versions").json()
        assert versions["total"] == 1


def test_lock_emr_requires_admin_perm_and_write_switch(env, monkeypatch):
    db, users, app = env
    # FIRST_COURSE：D8 允许，但需 timeliness_admin + jhemr_write.enabled
    resp = client_as(app, users["editor"]).post(
        "/api/timeliness/rules/FIRST_COURSE/versions", json={"action_mode": "LOCK_EMR"})
    assert resp.status_code == 400
    assert "timeliness_admin" in resp.json()["detail"]

    _enable_write(monkeypatch, False)
    resp = client_as(app, users["editor_admin"]).post(
        "/api/timeliness/rules/FIRST_COURSE/versions", json={"action_mode": "LOCK_EMR"})
    assert resp.status_code == 400
    assert "jhemr_write" in resp.json()["detail"]

    _enable_write(monkeypatch, True)
    resp = client_as(app, users["editor_admin"]).post(
        "/api/timeliness/rules/FIRST_COURSE/versions", json={"action_mode": "LOCK_EMR"})
    assert resp.status_code == 200
    assert resp.json()["version"]["action_mode"] == "LOCK_EMR"


# ---- 导出（写 ExportAuditLog） ----


def test_export_monthly_writes_audit_log(env):
    db, users, app = env
    client = client_as(app, users["admin"])
    resp = client.get("/api/timeliness/export/monthly?month=2026-11")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "T0001" not in resp.text                    # 月度统计为聚合口径，不含患者号

    audit = db.query(ExportAuditLog).order_by(ExportAuditLog.id.desc()).first()
    assert audit is not None
    assert audit.export_type == "timeliness_monthly"
    assert audit.export_format == "csv"
    assert audit.record_count >= 1
    assert "2026-11" in (audit.filter_criteria or "")


def test_stats_monthly_aggregates_by_dept_and_doctor(env):
    db, users, app = env
    body = client_as(app, users["admin"]).get(
        "/api/timeliness/stats/monthly?month=2026-11").json()
    assert body["month"] == "2026-11"
    assert body["totals"]["total"] == 2 and body["totals"]["overdue"] == 2
    assert {row["dept_code"] for row in body["rows"]} == {"0201", "0202"}
    # 非法月份 400
    resp = client_as(app, users["admin"]).get("/api/timeliness/stats/monthly?month=2026-13")
    assert resp.status_code == 400
