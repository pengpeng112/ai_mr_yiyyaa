"""2026-11-15 P0-2/P0-3：事件人工豁免端点 + 台账患者姓名填充测试。

覆盖（用户任务书四、1）：
- POST /events/{id}/exempt 正常豁免：EXEMPT 终态 + TLEventHistory + TLActionLog(EVENT_EXEMPT/EXECUTED)；
- 幂等重入：已豁免事件再次豁免 200 且不重复写痕；
- 完成/取消终态拒绝：COMPLETED_ON_TIME / CANCELLED → 400；
- 无 timeliness_admin → 403；跨科室不可见 → 404；
- _patient_name_map：空 pairs 零连接返回 {}、查询异常静默降级 {}、正常映射；
- 姓名填充：list_events / get_event / list_approvals 把 V_QYBR 姓名塞进 patient_name。
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
from app.models import Department, Permission, Role, RolePermission, User
from app.routers import timeliness as timeliness_router
from app.timeliness.models import TLEvent, TLEventHistory, TLActionLog, TLRule, TLRuleVersion
from app.timeliness.rules_seed import seed_rules

NOW = datetime(2026, 11, 15, 10, 0, 0)


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    permissions = {}
    for name in ("timeliness_view", "timeliness_admin"):
        perm = Permission(name=name, description=name, module="timeliness")
        db.add(perm)
        permissions[name] = perm

    admin_role = Role(name="admin", description="管理员")
    db.add(admin_role)
    db.flush()
    admin = User(username="tl_admin", password_hash="x", full_name="tl_admin", role_id=admin_role.id)
    db.add(admin)

    viewer_role = Role(name="tl_viewer", description="tl_viewer")
    db.add(viewer_role)
    db.flush()
    db.add(RolePermission(role_id=viewer_role.id, permission_id=permissions["timeliness_view"].id))
    viewer = User(username="tl_viewer", password_hash="x", full_name="tl_viewer", role_id=viewer_role.id)
    db.add(viewer)

    dept_ear = Department(name="耳科", code="0201")
    dept_nose = Department(name="鼻科", code="0202")
    db.add_all([dept_ear, dept_nose])
    db.flush()
    scoped_role = Role(name="tl_scoped", description="tl_scoped")
    db.add(scoped_role)
    db.flush()
    # scoped 具备 timeliness_admin（可过权限检查）但仅可见耳科——用于验证跨科室 404
    # （若仅给 view 权限会在 require_permission 处先 403，覆盖不到可见性分支）。
    db.add(RolePermission(role_id=scoped_role.id, permission_id=permissions["timeliness_view"].id))
    db.add(RolePermission(role_id=scoped_role.id, permission_id=permissions["timeliness_admin"].id))
    scoped = User(username="tl_scoped", password_hash="x", full_name="tl_scoped", role_id=scoped_role.id,
                  dept_id=dept_ear.id)

    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )

    def add_event(pid, status, dept_code):
        event = TLEvent(
            event_uid=f"FIRST_COURSE:{pid}:1:1", rule_code="FIRST_COURSE",
            rule_version_id=version.id, patient_id=pid, visit_id="1",
            dept_code=dept_code, t0=NOW, status=status, overdue_minutes=30,
            last_scan_at=NOW, created_at=NOW, updated_at=NOW,
        )
        db.add(event)
        return event

    add_event("T0001", "OVERDUE", "0201")            # 主用例：可豁免
    add_event("T0002", "COMPLETED_ON_TIME", "0201")  # 完成终态：400
    add_event("T0003", "CANCELLED", "0201")          # 取消终态：400
    add_event("T0004", "EXEMPT", "0201")             # 已豁免：幂等
    add_event("T0005", "WARNING", "0202")            # 跨科室：scoped 404
    db.commit()

    app = FastAPI()
    app.include_router(timeliness_router.router, prefix="/api/timeliness")
    app.dependency_overrides[get_db] = lambda: db
    yield db, {"admin": admin, "viewer": viewer, "scoped": scoped}, app
    db.close()


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


def _event_by_pid(db, pid: str) -> TLEvent:
    return db.query(TLEvent).filter(TLEvent.patient_id == pid).one()


# ---- 事件豁免端点 ----


def test_exempt_overdue_event_writes_history_and_action_log(env):
    db, users, app = env
    event = _event_by_pid(db, "T0001")
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/events/{event.id}/exempt",
        json={"exempt_reason": "患者术中会诊顺延，医务部核实豁免"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "EXEMPT"

    db.refresh(event)
    assert event.status == "EXEMPT"
    history = db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id).all()
    assert len(history) == 1
    assert history[0].from_status == "OVERDUE"
    assert history[0].to_status == "EXEMPT"
    assert history[0].reason.startswith("manual_exempt:")
    assert history[0].scan_run_id is None
    action = (
        db.query(TLActionLog)
        .filter(TLActionLog.event_id == event.id, TLActionLog.action_type == "EVENT_EXEMPT")
        .one()
    )
    assert action.mode == "EXECUTED"
    assert action.target == f"tl_event:{event.id}"
    assert action.operator == "tl_admin"


def test_exempt_event_is_idempotent_when_already_exempt(env):
    db, users, app = env
    event = _event_by_pid(db, "T0004")
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/events/{event.id}/exempt", json={"exempt_reason": "重复豁免"},
    )
    assert resp.status_code == 200
    assert resp.json()["message"] == "event already exempted"
    assert db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id).count() == 0


@pytest.mark.parametrize("pid", ["T0002", "T0003"])
def test_exempt_rejects_terminal_completed_cancelled(env, pid):
    db, users, app = env
    event = _event_by_pid(db, pid)
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/events/{event.id}/exempt", json={"exempt_reason": "不应成功"},
    )
    assert resp.status_code == 400
    assert "cannot exempt terminal event" in resp.json()["detail"]


def test_exempt_requires_admin_permission(env):
    db, users, app = env
    event = _event_by_pid(db, "T0001")
    resp = client_as(app, users["viewer"]).post(
        f"/api/timeliness/events/{event.id}/exempt", json={"exempt_reason": "无权限"},
    )
    assert resp.status_code == 403


def test_exempt_cross_dept_event_returns_404(env):
    db, users, app = env
    event = _event_by_pid(db, "T0005")  # 鼻科事件，scoped 仅可见耳科
    resp = client_as(app, users["scoped"]).post(
        f"/api/timeliness/events/{event.id}/exempt", json={"exempt_reason": "越权"},
    )
    assert resp.status_code == 404


def test_exempt_reason_required(env):
    db, users, app = env
    event = _event_by_pid(db, "T0001")
    resp = client_as(app, users["admin"]).post(
        f"/api/timeliness/events/{event.id}/exempt", json={"exempt_reason": "  "},
    )
    assert resp.status_code == 400


# ---- _patient_name_map 容错与姓名填充 ----


def test_patient_name_map_empty_pairs_no_connection():
    # 空 pairs：不触发任何 import/连接，直接 {}
    assert timeliness_router._patient_name_map([]) == {}


def test_patient_name_map_degrades_silently_on_error(monkeypatch):
    from app.timeliness import his_oracle_reader

    def _boom(*_a, **_k):
        raise RuntimeError("oracle offline")

    monkeypatch.setattr(his_oracle_reader, "fetch_patient_visit_meta", _boom)
    assert timeliness_router._patient_name_map([("T0001", "1")]) == {("T0001", "1"): ""}


def test_patient_name_map_normal_mapping(monkeypatch):
    from app.timeliness import his_oracle_reader

    monkeypatch.setattr(
        his_oracle_reader, "fetch_patient_visit_meta",
        lambda pairs: {pair: {"patient_name": f"姓名{pair[0]}"} for pair in pairs},
    )
    result = timeliness_router._patient_name_map([("T0001", "1"), ("T0001", "1"), ("", "1")])
    assert result == {("T0001", "1"): "姓名T0001"}


def test_list_events_fills_patient_name(monkeypatch, env):
    db, users, app = env
    monkeypatch.setattr(
        timeliness_router, "_patient_name_map",
        lambda pairs: {pair: f"患者{pair[0]}" for pair in pairs},
    )
    resp = client_as(app, users["admin"]).get("/api/timeliness/events?page=1&limit=10")
    assert resp.status_code == 200
    by_pid = {item["patient_id"]: item for item in resp.json()["items"]}
    assert by_pid["T0001"]["patient_name"] == "患者T0001"


def test_get_event_fills_patient_name(monkeypatch, env):
    db, users, app = env
    monkeypatch.setattr(
        timeliness_router, "_patient_name_map",
        lambda pairs: {pair: f"患者{pair[0]}" for pair in pairs},
    )
    event = _event_by_pid(db, "T0001")
    resp = client_as(app, users["admin"]).get(f"/api/timeliness/events/{event.id}")
    assert resp.status_code == 200
    assert resp.json()["patient_name"] == "患者T0001"


def test_list_approvals_fills_patient_name(monkeypatch, env):
    db, users, app = env
    from app.timeliness.models import TLApproval

    db.add(TLApproval(
        patient_id="A0001", visit_id="2", monitor_code="JH04.02.001",
        apply_date_time=NOW, type="KK", hospital_no="A0001",
        synced_at=NOW,
    ))
    db.commit()
    monkeypatch.setattr(
        timeliness_router, "_patient_name_map",
        lambda pairs: {pair: f"患者{pair[0]}" for pair in pairs},
    )
    resp = client_as(app, users["admin"]).get("/api/timeliness/approvals?page=1&limit=10")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["patient_name"] == "患者A0001"
