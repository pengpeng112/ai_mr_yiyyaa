"""企微手机端「病历超时解锁查询与时效统计」H5 后端测试（2026-11-16）。

覆盖（任务书 §五 Step1 十项断言）：
1. 路由优先级防 422（/mobile/qc/timeliness 与别名 200 HTML + no-store；原 /mobile/qc/1 400 HTML 不破）；
2. CSP 零违规静态扫描（无内联 script、无 on*= 事件属性）；
3. Vue 静态桥接 200 且 >100000 字节；
4. 登录 + CSRF 豁免（残留 Cookie 无 X-Requested-With 登录 200）；
5. Overview/Stats 聚合准确性（按时率/排行/规则分布/医师应扣×200 排除豁免）；
6. 科室可见性隔离（scoped 用户 100% 只见本科室数据）；
7. keyword 模糊搜索（患者编号/申请原因/科室名称）；
8. 手动同步 15 秒冷却节流；
9. 写闸关闭手机解锁 409 + BLOCKED 审计（零外部连接）；
10. 豁免与取消豁免闭环（审计留存 + effective_penalty 更新）。
"""
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
from app.routers import mobile_qc, mobile_timeliness
from app.timeliness.models import TLApproval, TLEvent, TLRule, TLRuleVersion
from app.timeliness.rules_seed import seed_rules

NOW = datetime(2026, 11, 16, 10, 0, 0)


@pytest.fixture(autouse=True)
def _offline_patient_names(monkeypatch):
    """离线单测零连库：姓名补齐层直接降级为空 map（patient_id 回退展示不影响聚合断言）。"""
    monkeypatch.setattr(mobile_timeliness.timeliness, "_patient_name_map", lambda pairs: {})


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, autoflush=False)()
    seed_rules(db)

    permissions = {}
    for name in ("timeliness_view", "timeliness_admin", "timeliness_approve"):
        perm = Permission(name=name, description=name, module="timeliness")
        db.add(perm)
        permissions[name] = perm

    admin_role = Role(name="admin", description="管理员")
    db.add(admin_role)
    db.flush()
    admin = User(username="mob_admin", password_hash=auth_module.hash_password("admin-pass"),
                 full_name="系统管理员", role_id=admin_role.id)
    db.add(admin)

    approver_role = Role(name="mob_approver", description="审批员")
    db.add(approver_role)
    db.flush()
    db.add(RolePermission(role_id=approver_role.id, permission_id=permissions["timeliness_view"].id))
    db.add(RolePermission(role_id=approver_role.id, permission_id=permissions["timeliness_approve"].id))
    approver = User(username="mob_approver", password_hash=auth_module.hash_password("approve-pass"),
                    full_name="质控审核员", role_id=approver_role.id, dept_id=None)
    db.add(approver)

    viewer_role = Role(name="mob_viewer", description="查看者")
    db.add(viewer_role)
    db.flush()
    db.add(RolePermission(role_id=viewer_role.id, permission_id=permissions["timeliness_view"].id))
    viewer = User(username="mob_viewer", password_hash=auth_module.hash_password("viewer-pass"),
                  full_name="查看者", role_id=viewer_role.id)
    db.add(viewer)

    dept_a = Department(name="耳鼻喉一科", code="040112")
    dept_b = Department(name="耳鼻喉二科", code="030442")
    db.add_all([dept_a, dept_b])
    db.flush()
    # 审批员绑定耳鼻喉一科（可见性内执行 409 用例）
    approver.dept_id = dept_a.id
    scoped_role = Role(name="mob_scoped", description="科室管理员")
    db.add(scoped_role)
    db.flush()
    db.add(RolePermission(role_id=scoped_role.id, permission_id=permissions["timeliness_view"].id))
    scoped = User(username="mob_scoped", password_hash=auth_module.hash_password("scoped-pass"),
                  full_name="王主任", role_id=scoped_role.id, dept_id=dept_a.id)
    db.add(scoped)

    version = (
        db.query(TLRuleVersion)
        .join(TLRule, TLRule.id == TLRuleVersion.rule_id)
        .filter(TLRule.rule_code == "FIRST_COURSE", TLRuleVersion.version_no == 1)
        .one()
    )

    def add_event(pid, dept_code, status, deadline=None, rule_code="FIRST_COURSE"):
        event = TLEvent(
            event_uid=f"{rule_code}:{pid}:1:1", rule_code=rule_code,
            rule_version_id=version.id, patient_id=pid, visit_id="1",
            dept_code=dept_code, t0=NOW, status=status,
            deadline=deadline or (NOW + timedelta(hours=4)),
            last_scan_at=NOW, created_at=NOW, updated_at=NOW,
        )
        db.add(event)
        return event

    add_event("T0001", "040112", "OVERDUE", deadline=NOW - timedelta(hours=4))
    add_event("T0002", "040112", "WARNING")
    add_event("T0003", "030442", "OVERDUE", deadline=NOW - timedelta(hours=1))
    add_event("T0004", "040112", "COMPLETED_ON_TIME", rule_code="DISCHARGE_REC")

    def add_approval(pid, dept_code, flag, *, exempt=False, amount=None, reason="急诊连台手术延误补写", applier="001234"):
        row = TLApproval(
            patient_id=pid, visit_id="1", monitor_code="JH04.02.002",
            apply_date_time=NOW, type="1", flag=flag,
            apply_user_id=applier, approve_user_id="admin" if flag == "2" else None,
            approve_date_time=NOW if flag == "2" else None,
            hospital_no=pid, dept_code=dept_code,
            penalty_amount=amount, penalty_exempt=exempt,
            exempt_reason="系统故障" if exempt else None,
            synced_at=NOW, apply_reason=reason,
        )
        db.add(row)
        return row

    add_approval("A0001", "040112", "1")
    add_approval("A0002", "040112", "2", amount=200)
    add_approval("A0003", "040112", "2", exempt=True, amount=200)
    add_approval("A0004", "030442", "1", reason="转科交接特殊情况")
    add_approval("A0005", "030442", "2", amount=300)
    db.commit()

    app = FastAPI()
    # 路由顺序契约：mobile_timeliness 必须先于 mobile_qc（防 /mobile/qc/{alert_id:int} 捕获）
    app.include_router(mobile_timeliness.router)
    app.include_router(mobile_qc.router)
    app.dependency_overrides[get_db] = lambda: db
    yield db, {"admin": admin, "approver": approver, "viewer": viewer, "scoped": scoped}, app
    db.close()


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


def login_token(client, username, password):
    resp = client.post("/api/mobile/timeliness/login",
                       json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def bearer(client, token):
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


# ---- 1. 路由优先级防 422 ----

def test_page_routes_registered_before_mobile_qc_alert_pattern(env):
    _, _, app = env
    client = TestClient(app)
    for path in ("/mobile/qc/timeliness", "/mobile/timeliness"):
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        assert "text/html" in resp.headers["content-type"]
        assert "no-store" in resp.headers.get("cache-control", "")
        assert "timeliness_h5.js" in resp.text
    # 原 alert 详情路由未被破坏：无 token 仍返回 400 HTML（而非 404/422）
    legacy = client.get("/mobile/qc/1")
    assert legacy.status_code == 400
    assert "text/html" in legacy.headers["content-type"]


# ---- 2. CSP 零违规静态扫描 ----

def test_h5_html_has_no_inline_script_or_event_attributes():
    import re
    import pathlib

    html_path = pathlib.Path(__file__).resolve().parents[2] / "static" / "templates" / "mobile" / "timeliness_h5.html"
    html = html_path.read_text("utf-8")
    inline_blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S | re.I)
    assert not [b for b in inline_blocks if b.strip()], "禁止内联 script 代码块"
    on_attrs = re.findall(r"\bon[a-z]+\s*=", html, re.I)
    assert not on_attrs, f"禁止内联事件属性: {on_attrs}"
    for src in re.findall(r'<script[^>]*src="([^"]+)"', html):
        assert src.startswith("/scripts/mobile/"), src


# ---- 3. Vue 静态桥接 ----

def test_vue_bridge_returns_full_bundle(env):
    _, _, app = env
    client = TestClient(app)
    resp = client.get("/scripts/mobile/vue.global.prod.js")
    assert resp.status_code == 200
    assert len(resp.content) > 100_000


# ---- 4. 登录 + CSRF 豁免 ----

def test_login_with_stale_cookie_and_no_csrf_header_succeeds(env):
    _, _, app = env
    client = TestClient(app)
    # 模拟手机浏览器残留旧 Cookie 且不带 X-Requested-With 的 POST 登录
    client.cookies.set("med_audit_token", "stale-or-expired-token")
    resp = client.post("/api/mobile/timeliness/login",
                       json={"username": "mob_admin", "password": "admin-pass"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("access_token")
    assert body["user"]["role"] == "admin"


# ---- 5. Overview / Stats 聚合准确性 ----

def test_overview_counts_match_seed_data(env):
    db, users, app = env
    client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    data = client.get("/api/mobile/timeliness/overview").json()
    # 全院口径：pending = A0001 + A0004；approved = A0002 + A0005；exempt = A0003
    assert data["pending_approvals"] == 2
    assert data["month_approvals_total"] == 5
    # flag='2' 共 3 条（A0002/A0003/A0005）——豁免项 A0003 也属已审批解锁
    assert data["month_approved"] == 3
    assert data["month_exempt"] == 1
    # 应扣 = 已解锁且未豁免：A0002=200 + A0005=300（排除豁免 A0003）
    assert data["month_penalty_amount"] == 500
    assert data["in_hosp_overdue"] == 2
    assert data["in_hosp_warning"] == 1
    assert data["jhemr_write_enabled"] is False


def test_stats_aggregates_ranking_rule_breakdown_and_penalties(env):
    db, users, app = env
    client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    data = client.get("/api/mobile/timeliness/stats?month=2026-11").json()
    summary = data["summary"]
    assert summary["month"] == "2026-11"
    assert summary["total"] == 4
    assert summary["completed_on_time"] == 1
    assert summary["overdue"] == 2
    assert summary["on_time_rate"] == 25.0

    ranking = {r["dept_code"]: r for r in data["dept_ranking"]}
    assert set(ranking) == {"040112", "030442"}
    # 040112 当月 3 节点（OVERDUE+WARNING+按时完成）→ 1/3 = 33.3%
    assert ranking["040112"]["on_time_rate"] == 33.3
    assert ranking["040112"]["penalty_amount_total"] == 200
    assert ranking["030442"]["on_time_rate"] == 0.0
    assert ranking["030442"]["penalty_amount_total"] == 300

    rules = {r["rule_code"]: r for r in data["rule_breakdown"]}
    assert rules["FIRST_COURSE"]["total"] == 3
    assert rules["DISCHARGE_REC"]["completed_on_time"] == 1

    # 医师扣罚榜按（科室, 医师）行：扣罚挂在申请医师 001234 名下
    penalties = {(d["dept_code"], d["doctor_id"]): d for d in data["doctor_penalties"]}
    # 应扣：040112=200（A0002，豁免 A0003 排除）、030442=300（A0005）
    assert penalties[("040112", "001234")]["penalty_amount_total"] == 200
    assert penalties[("030442", "001234")]["penalty_amount_total"] == 300
    assert penalties[("040112", "")]["overdue"] == 1


# ---- 6. 科室可见性隔离（关键安全测试） ----

def test_scoped_user_never_sees_other_dept_data(env):
    db, users, app = env
    token = login_token(client_as(app, users["scoped"]), "mob_scoped", "scoped-pass")
    client = bearer(client_as(app, users["scoped"]), token)

    approvals = client.get("/api/mobile/timeliness/approvals?status_tab=all").json()
    assert approvals["total"] >= 1
    assert {i["dept_code"] for i in approvals["items"]} == {"040112"}

    events = client.get("/api/mobile/timeliness/events?status=ACTIVE_RISK").json()
    assert events["total"] >= 1
    assert {i["dept_code"] for i in events["items"]} == {"040112"}

    overview = client.get("/api/mobile/timeliness/overview").json()
    assert overview["pending_approvals"] == 1
    # 040112 的 flag=2 共 2 条（A0002 已解锁 + A0003 已解锁且豁免）
    assert overview["month_approved"] == 2
    assert overview["in_hosp_overdue"] == 1

    stats = client.get("/api/mobile/timeliness/stats?month=2026-11").json()
    assert {r["dept_code"] for r in stats["dept_ranking"]} == {"040112"}

    # 管理员可见两科全量
    admin_client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    admin_approvals = admin_client.get("/api/mobile/timeliness/approvals?status_tab=all").json()
    assert admin_approvals["total"] == 5
    assert {i["dept_code"] for i in admin_approvals["items"]} == {"040112", "030442"}


# ---- 7. keyword 模糊搜索 ----

def test_keyword_search_matches_reason_dept_and_patient(env):
    _, users, app = env
    client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    # 按申请原因片段
    by_reason = client.get("/api/mobile/timeliness/approvals", params={"keyword": "转科交接"}).json()
    assert by_reason["total"] == 1
    assert by_reason["items"][0]["patient_id"] == "A0004"
    # 按科室名称
    by_dept = client.get("/api/mobile/timeliness/approvals", params={"keyword": "耳鼻喉二科"}).json()
    assert by_dept["total"] == 2
    assert all(i["dept_code"] == "030442" for i in by_dept["items"])
    # 按患者编号
    by_pid = client.get("/api/mobile/timeliness/approvals", params={"keyword": "A0003"}).json()
    assert by_pid["total"] == 1


# ---- 8. 手动同步 15 秒冷却节流 ----

def test_manual_sync_throttled_within_cooldown(monkeypatch, env):
    from app.routers import mobile_timeliness as mt

    mt.reset_mobile_sync_throttle()

    def fake_sync(db, config, since=None):
        return {"approvals_inserted": 3, "approvals_updated": 1}

    monkeypatch.setattr(mt.timeliness, "sync_approvals", fake_sync)
    _, users, app = env
    client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))

    first = client.post("/api/mobile/timeliness/approvals/sync")
    assert first.status_code == 200
    assert first.json()["throttled"] is False
    assert first.json()["data"]["approvals_inserted"] == 3

    second = client.post("/api/mobile/timeliness/approvals/sync")
    assert second.status_code == 200
    body = second.json()
    assert body["throttled"] is True
    assert body["message"] == "刚完成同步，请稍后再试"
    assert body["data"]["approvals_inserted"] == 3

    mt.reset_mobile_sync_throttle()


# ---- 9. 写闸关闭时手机解锁 409 友好拦截 ----

def test_mobile_approve_blocked_409_with_audit_when_write_gate_closed(monkeypatch, env):
    from app.routers import mobile_timeliness as mt

    monkeypatch.setattr(mt.timeliness, "load_config",
                        lambda: {"timeliness": {"jhemr_write": {"enabled": False}}})
    db, users, app = env
    client = bearer(client_as(app, users["approver"]), login_token(client_as(app, users["approver"]), "mob_approver", "approve-pass"))

    pending = client.get("/api/mobile/timeliness/approvals?status_tab=pending").json()
    target = next(i for i in pending["items"] if i["patient_id"] == "A0001")

    before = db.query(mobile_timeliness.TLApproval).count()
    resp = client.post(f"/api/mobile/timeliness/approvals/{target['id']}/approve", json={"dry_run": False})
    assert resp.status_code == 409
    from app.timeliness.models import TLActionLog
    blocked = db.query(TLActionLog).filter(TLActionLog.mode == "BLOCKED",
                                           TLActionLog.action_type == "JHEMR_APPROVE").all()
    assert len(blocked) == 1
    assert db.query(mobile_timeliness.TLApproval).count() == before

    # 无 approve/admin 权限的 viewer 403
    viewer_client = bearer(client_as(app, users["viewer"]), login_token(client_as(app, users["viewer"]), "mob_viewer", "viewer-pass"))
    assert viewer_client.post(f"/api/mobile/timeliness/approvals/{target['id']}/approve",
                              json={"dry_run": False}).status_code == 403


# ---- 10. 豁免与取消豁免闭环 ----

def test_mobile_exempt_and_cancel_full_loop(env):
    db, users, app = env
    client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))

    approved = client.get("/api/mobile/timeliness/approvals?status_tab=approved").json()
    target = next(i for i in approved["items"] if i["patient_id"] == "A0002" and not i["penalty_exempt"])
    assert target["effective_penalty"] == 200

    set_resp = client.post(f"/api/mobile/timeliness/approvals/{target['id']}/exempt",
                           json={"exempt_reason": "急危重症抢救"})
    assert set_resp.status_code == 200
    after = client.get("/api/mobile/timeliness/approvals?status_tab=exempt").json()
    row = next(i for i in after["items"] if i["patient_id"] == "A0002")
    assert row["penalty_exempt"] is True
    assert row["effective_penalty"] == 0

    from app.timeliness.models import TLActionLog
    exempt_logs = db.query(TLActionLog).filter(TLActionLog.action_type == "APPROVAL_EXEMPT").count()
    assert exempt_logs >= 1

    cancel_resp = client.post(f"/api/mobile/timeliness/approvals/{target['id']}/exempt",
                              json={"exempt_reason": "口径勘误恢复扣罚", "cancel": True})
    assert cancel_resp.status_code == 200
    again = client.get("/api/mobile/timeliness/approvals?status_tab=approved").json()
    row2 = next(i for i in again["items"] if i["patient_id"] == "A0002")
    assert row2["penalty_exempt"] is False
    assert row2["effective_penalty"] == 200


# ---- 补充：me 能力字段 + 事件详情中文标签 ----

def test_me_capabilities_and_event_detail_labels(env):
    _, users, app = env
    admin_client = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    me = admin_client.get("/api/mobile/timeliness/me").json()
    assert me["user"]["role_label"] == "系统管理员"
    assert me["capabilities"]["can_approve"] is True
    assert me["capabilities"]["can_exempt"] is True
    assert me["capabilities"]["jhemr_write_enabled"] is False

    events = admin_client.get("/api/mobile/timeliness/events?status=OVERDUE").json()
    target = events["items"][0]
    assert target["status_label"] in ("已超时未签", "临期预警", "申请解锁中")
    assert "已超时" in target["remain_text"]
    detail = admin_client.get(f"/api/mobile/timeliness/events/{target['id']}").json()
    assert "history" in detail and "action_logs" in detail
    # 列表字段：monitor_label / type_label / flag_label 手机端专属
    approvals = admin_client.get("/api/mobile/timeliness/approvals?status_tab=pending").json()
    item = approvals["items"][0]
    assert item["monitor_label"] == "首次病程记录"
    assert item["type_label"] == "草稿审签拦截"
    assert item["flag_label"] == "待审批锁定"


def test_ping_and_dicts(env):
    _, users, app = env
    client = TestClient(app)
    ping = client.get("/api/mobile/timeliness/ping")
    assert ping.status_code == 200
    assert ping.json() == {"ok": True, "service": "mobile-timeliness"}

    authed = bearer(client_as(app, users["admin"]), login_token(client_as(app, users["admin"]), "mob_admin", "admin-pass"))
    dicts = authed.get("/api/mobile/timeliness/dicts").json()
    pinned = [m for m in dicts["monitor_items"] if m.get("pinned")]
    assert [m["code"] for m in pinned] == ["JH04.02.001", "JH04.02.002", "JH04.02.011"]
    assert dicts["departments"] and {d["code"] for d in dicts["departments"]} == {"040112", "030442"}
    # 种子规则默认 enabled=False（SHADOW 影子期），手机端只列启用规则 → 空列表是正确行为
    assert isinstance(dicts["rules"], list)
    assert all(r.get("rule_code") for r in dicts["rules"])
