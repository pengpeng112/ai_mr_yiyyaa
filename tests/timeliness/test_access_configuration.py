import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import database
from app.auth import WECOM_SETUP_PASSWORD_PREFIX, create_access_token, verify_password
from app.models import DIRECTORY_SYNC_PASSWORD_MARKER, Permission, Role, RolePermission
from app.routers import menu, mobile_timeliness, roles, timeliness, users
from app.timeliness import his_oracle_reader
from app.timeliness.models import TLApproval, TLEvent
from tests.timeliness.test_mobile_oauth_direct_issue_20261117 import _patch_relay_userid
from tests.timeliness.test_mobile_timeliness_20261116 import env  # noqa: F401


@pytest.fixture(autouse=True)
def offline_names(monkeypatch):
    monkeypatch.setattr(timeliness, "_patient_name_map", lambda pairs: {})
    monkeypatch.setattr(his_oracle_reader, "get_staff_name_map", lambda: {})


def add_pc_routes(app):
    app.include_router(timeliness.router, prefix="/api/timeliness")
    app.include_router(users.router, prefix="/api/users")
    app.include_router(roles.router, prefix="/api/roles")


def login(app, username, password):
    client = TestClient(app)
    response = client.post("/api/users/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return client


def test_pc_and_wecom_share_role_and_personal_settings(env, monkeypatch):
    db, accounts, app = env
    add_pc_routes(app)
    admin = login(app, "mob_admin", "admin-pass")
    scoped = accounts["scoped"]
    view = login(app, "mob_scoped", "scoped-pass")
    role_url = f"/api/roles/{scoped.role_id}/timeliness-access"
    user_url = f"/api/users/{scoped.id}"
    all_scope = {"timeliness_access": {"scope": "all", "default_view": "all"}}

    assert view.put(user_url, json=all_scope).status_code == 403
    assert view.put(role_url, json=all_scope).status_code == 403
    assert admin.put(role_url, json=all_scope).status_code == 200
    assert admin.put(user_url, json={"timeliness_access": {"scope": "all"}}).status_code == 200

    _patch_relay_userid(monkeypatch, scoped.username)
    mobile = TestClient(app)
    callback = mobile.get("/mobile/qc/timeliness/oauth/wecom/callback?code=valid", follow_redirects=False)
    assert callback.status_code == 302
    assert callback.cookies.get("med_audit_token")

    cross_event = db.query(TLEvent).filter_by(dept_code="030442").one()
    cross_approval = db.query(TLApproval).filter_by(dept_code="030442", flag="1").one()
    for client, prefix in ((view, "/api/timeliness"), (mobile, "/api/mobile/timeliness")):
        data = client.get(f"{prefix}/dicts").json()
        assert data["all_hospital"] is True
        assert data["default_dept"] == "040112"
        assert {dept["code"] for dept in data["departments"]} == {"040112", "030442"}
        assert {item["dept_code"] for item in client.get(f"{prefix}/approvals").json()["items"]} == {"040112", "030442"}
        assert client.get(f"{prefix}/events/{cross_event.id}").status_code == 200
        assert client.post(f"{prefix}/approvals/{cross_approval.id}/approve", json={"dry_run": True}).status_code == 403
        assert client.post(f"{prefix}/approvals/sync").status_code == 403

    params = {"month": "2026-11", "dept": "040112"}
    desktop = view.get("/api/timeliness/stats/monthly", params=params).json()["totals"]
    phone = mobile.get("/api/mobile/timeliness/stats", params=params).json()
    assert desktop["total"] == phone["summary"]["total"] == 3
    assert desktop["approval_count"] == phone["summary"]["approval_count"] == 3
    assert sum(row["total"] for row in phone["rule_breakdown"]) == 3
    assert view.get("/api/timeliness/export/monthly", params=params).status_code == 403

    # 撤销角色与个人授权后，两端原会话下次查询都只可见本科室。
    assert admin.put(user_url, json={"timeliness_access": None}).status_code == 200
    assert view.get("/api/timeliness/dicts").json()["default_dept"] == ""
    assert admin.put(role_url, json={"timeliness_access": None}).status_code == 200
    for client, prefix in ((view, "/api/timeliness"), (mobile, "/api/mobile/timeliness")):
        assert client.get(f"{prefix}/events/{cross_event.id}").status_code == 404
        assert client.get(f"{prefix}/approvals", params={"dept": "030442"}).json()["total"] == 0
        assert {item["dept_code"] for item in client.get(f"{prefix}/approvals").json()["items"]} == {"040112"}
    assert mobile.post("/api/mobile/timeliness/logout").status_code == 204
    assert mobile.get("/api/mobile/timeliness/me").status_code == 403


def test_selected_scope_replaces_home_and_requires_verified_auth(env, monkeypatch):
    _, accounts, app = env
    add_pc_routes(app)
    monkeypatch.delenv("MOBILE_TIMELINESS_EMPNO_LOGIN", raising=False)
    path = "/api/mobile/timeliness/login/empno"
    old = TestClient(app)
    assert old.post(path, json={"empno": "mob_scoped"}).status_code == 403
    monkeypatch.setenv("MOBILE_TIMELINESS_EMPNO_LOGIN", "true")
    assert old.post(path, json={"empno": "mob_admin"}).status_code == 401
    assert old.post(path, json={"empno": "mob_scoped"}).status_code == 200

    admin = login(app, "mob_admin", "admin-pass")
    user_path = f"/api/users/{accounts['scoped'].id}"
    access = {"timeliness_access": {"scope": "selected", "department_codes": ["missing"]}}
    assert admin.put(user_path, json=access).status_code == 422
    access["timeliness_access"]["department_codes"] = ["030442"]
    assert admin.put(user_path, json=access).status_code == 200
    assert old.get("/api/mobile/timeliness/dicts").status_code == 401
    assert old.post(path, json={"empno": "mob_scoped"}).status_code == 401

    view = login(app, "mob_scoped", "scoped-pass")
    data = view.get("/api/timeliness/dicts").json()
    assert data["default_dept"] == ""
    assert not data["all_hospital"]
    assert [item["code"] for item in data["departments"]] == ["030442"]
    assert view.get("/api/timeliness/events", params={"dept": "040112"}).json()["total"] == 0


def test_disabled_app_account_does_not_fall_back_to_his(env, monkeypatch):
    db, accounts, app = env
    accounts["scoped"].is_active = False
    db.commit()
    _patch_relay_userid(monkeypatch, accounts["scoped"].username)
    monkeypatch.setattr(mobile_timeliness, "_his_employee_lookup", lambda empno: {
        "empno": empno, "name": "测试职工", "dept_code": "040112", "dept_name": "测试科室",
    })
    client = TestClient(app)
    response = client.get("/mobile/qc/timeliness/oauth/wecom/callback?code=valid", follow_redirects=False)
    assert not response.cookies.get("med_audit_token")


def test_synced_user_keeps_wecom_his_access_until_role_activation(env, monkeypatch):
    db, accounts, app = env
    add_pc_routes(app)
    user = accounts["scoped"]
    role_id = user.role_id
    username = user.username
    user.is_active = False
    user.role_id = None
    user.email = None
    user.directory_pending = True
    db.commit()
    _patch_relay_userid(monkeypatch, username)
    monkeypatch.setattr(mobile_timeliness, "_his_employee_lookup", lambda empno: {
        "empno": empno, "name": "同步员工", "dept_code": "040112", "dept_name": "测试科室",
    })
    monkeypatch.setenv("MOBILE_TIMELINESS_EMPNO_LOGIN", "true")

    path = "/mobile/qc/timeliness/oauth/wecom/callback?code=valid"
    me_path = "/api/mobile/timeliness/me"
    pc = TestClient(app)
    assert pc.post("/api/users/login", json={"username": username, "password": "scoped-pass"}).status_code == 403
    assert pc.post("/api/mobile/timeliness/login/empno", json={"empno": username}).status_code == 401
    pending = TestClient(app)
    assert pending.get(path, follow_redirects=False).cookies.get("med_audit_token")
    me = pending.get(me_path).json()
    assert me["user"]["role"] == "his_employee"
    assert not me["capabilities"]["can_approve"]
    assert pending.get("/api/mobile/timeliness/events", params={"dept": "030442"}).json()["total"] == 0

    admin = login(app, "mob_admin", "admin-pass")
    found = admin.get("/api/users", params={"q": username}).json()
    assert found["total"] == 1 and found["items"][0]["directory_pending"] is True
    assert found["items"][0]["email"] == ""
    assert admin.get("/api/users", params={"q": "%"}).json()["total"] == 0
    assert admin.get("/api/users", params={"q": user.full_name}).json()["total"] == 1
    user_path = f"/api/users/{user.id}"
    assert admin.put(user_path, json={"is_active": True}).status_code == 422
    assert admin.put(user_path, json={"role_id": role_id, "is_active": False}).json()["directory_pending"]
    assert admin.put(user_path, json={"is_active": True}).json()["directory_pending"] is False

    active = TestClient(app)
    assert active.get(path, follow_redirects=False).cookies.get("med_audit_token")
    assert active.get(me_path).json()["user"]["role"] == "mob_scoped"
    assert admin.delete(user_path).status_code == 200
    assert active.get(me_path).status_code == 401
    assert pending.get(me_path).status_code == 401
    assert not TestClient(app).get(path, follow_redirects=False).cookies.get("med_audit_token")


def test_existing_sqlite_user_and_role_rows_migrate(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(database, "engine", engine)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE roles (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO roles (id) VALUES (1)"))
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, password_hash TEXT, is_active INTEGER, "
                          "role_id INTEGER, created_at TEXT, updated_at TEXT)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'ordinary', 0, NULL, 'same', 'same'), "
                          "(2, :marker, 0, NULL, 'same', 'same'), (3, :marker, 0, NULL, 'old', 'new')"),
                     {"marker": DIRECTORY_SYNC_PASSWORD_MARKER})
    for _ in range(2):
        database._migrate_timeliness_access_columns()
    with engine.connect() as conn:
        for table in ("users", "roles"):
            assert any(col["name"] == "timeliness_access_json" for col in inspect(conn).get_columns(table))
            assert conn.execute(text(f"SELECT timeliness_access_json FROM {table} WHERE id = 1")).one() == (None,)
        assert conn.execute(text("SELECT directory_pending FROM users WHERE id = 1")).one() == (0,)
        assert conn.execute(text("SELECT directory_pending, password_hash FROM users WHERE id = 2")).one() == (1, "!directory-password-unset")
        assert conn.execute(text("SELECT directory_pending FROM users WHERE id = 3")).one() == (0,)
        assert conn.execute(text("SELECT password_setup_required FROM users WHERE id = 2")).one() == (0,)


def test_initial_password_requires_verified_employee_and_changes_once(env, monkeypatch):
    db, accounts, app = env
    add_pc_routes(app)
    user = accounts["scoped"]
    user.password_setup_required = True
    user.password_hash = WECOM_SETUP_PASSWORD_PREFIX + user.password_hash
    db.commit()
    assert not verify_password("scoped-pass", user.password_hash)
    username = user.username
    pc_login = "/api/users/login"
    me = "/api/mobile/timeliness/me"
    params = {"initial_password": "scoped-pass", "new_password": "personal-secret-203"}
    anonymous = TestClient(app)
    blocked = anonymous.post(pc_login, json={"username": username, "password": "scoped-pass"})
    assert blocked.status_code == 403 and "access_token" not in blocked.json()
    assert not blocked.cookies.get("med_audit_token")
    assert anonymous.post(me, json=params).status_code == 403
    stale = create_access_token(user.id, username, auth_method="password")
    assert anonymous.post(me, json=params, headers={"Authorization": f"Bearer {stale}"}).status_code == 401

    _patch_relay_userid(monkeypatch, username)
    mobile = TestClient(app)
    assert mobile.get("/mobile/qc/timeliness/oauth/wecom/callback?code=valid", follow_redirects=False).cookies.get("med_audit_token")
    assert mobile.get(me).json()["capabilities"]["password_setup_required"] is True
    assert mobile.get("/api/mobile/timeliness/events", params={"dept": "030442"}).json()["total"] == 0
    assert mobile.post(me, json={**params, "initial_password": "wrong"}).status_code == 400
    assert mobile.post(me, json=params).status_code == 200
    assert mobile.get(me).json()["capabilities"]["password_setup_required"] is False
    assert mobile.post(me, json=params).status_code == 409
    assert anonymous.post(pc_login, json={"username": username, "password": "scoped-pass"}).status_code == 401

    authenticated = login(app, username, params["new_password"])
    assert authenticated.get("/api/timeliness/approvals", params={"dept": "030442"}).json()["total"] == 0
    assert authenticated.get("/api/timeliness/approvals").json()["total"] == 3


def test_seed_read_only_roles_and_pc_menus(env, monkeypatch):
    db, _, app = env
    add_pc_routes(app)
    app.include_router(menu.router, prefix="/api")
    session_factory = database.sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    for _ in range(2):
        database._ensure_default_rbac_permissions()
    admin = login(app, "mob_admin", "admin-pass")

    for name in ("timeliness_reader", "medical_affairs"):
        role = db.query(Role).filter_by(name=name).one()
        permissions = db.query(Permission.name).join(RolePermission).filter_by(role_id=role.id).all()
        assert permissions == [("timeliness_view",)]
        response = admin.post("/api/users", json={
            "username": name, "password": "viewer-pass", "full_name": "时效查看测试", "role_id": role.id,
        })
        assert response.status_code == 200
        reader = login(app, name, "viewer-pass")
        assert reader.get("/api/timeliness/dicts").json()["all_hospital"] is False
        menu_body = reader.get("/api/menu").json()
        assert {item["id"] for item in menu_body["menu"]} == {
            "timeliness-stats", "timeliness-events", "timeliness-approvals", "timeliness-monthly",
        }
