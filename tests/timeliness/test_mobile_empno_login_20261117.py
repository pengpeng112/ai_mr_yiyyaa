"""工号免登（企业微信嵌入传参 ?empno=工号）后端测试（2026-11-17）。

覆盖：开关关闭 403 / 工号不存在 401 / 成功签发（JWT+Cookie+/me 可用）/
限流防刷 / CSRF 豁免（残留 Cookie 无 X-Requested-With 放行）/ H5 JS 免登链路源码断言。
"""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from app import auth as auth_module
from tests.timeliness.test_mobile_timeliness_20261116 import env  # noqa: F401


def client_as(app, user) -> TestClient:
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


# ---- 开关 ----


def test_empno_login_disabled_by_env_returns_403(monkeypatch, env):
    _, users, app = env
    monkeypatch.setenv("MOBILE_TIMELINESS_EMPNO_LOGIN", "false")
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "mob_admin"})
    assert resp.status_code == 403
    assert "disabled" in resp.json()["detail"]


# ---- 工号不存在 ----


def test_empno_login_unknown_empno_returns_401(env):
    _, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "ghost99999"})
    assert resp.status_code == 401
    assert "not bound" in resp.json()["detail"]


def test_empno_login_inactive_user_returns_401(env):
    db, users, app = env
    from app.models import User

    ghost = db.query(User).filter(User.username == "mob_viewer").one()
    ghost.is_active = False
    db.commit()
    try:
        client = client_as(app, users["admin"])
        resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "mob_viewer"})
        assert resp.status_code == 401
    finally:
        ghost.is_active = True
        db.commit()


# ---- 成功签发 ----


def test_empno_login_success_issues_token_cookie_and_me(env):
    _, users, app = env
    client = client_as(app, users["admin"])
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "mob_admin"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["token_type"] == "bearer"
    assert body["user"]["username"] == "mob_admin"
    assert "med_audit_token" in resp.headers.get("set-cookie", "")

    # 签发的 JWT 可直接访问鉴权接口
    me = client.get("/api/mobile/timeliness/me")
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "mob_admin"
    assert me.json()["capabilities"]["can_approve"] is True


def test_empno_login_token_carries_bearer_access(env):
    """签发 token 以 Bearer 方式访问（iframe 嵌入场景 Cookie 受限时的主通道）。"""
    _, users, app = env
    client = client_as(app, users["admin"])
    token = client.post("/api/mobile/timeliness/login/empno",
                        json={"empno": "mob_admin"}).json()["access_token"]
    fresh = client_as(app, users["admin"])
    fresh.headers.update({"Authorization": f"Bearer {token}"})
    resp = fresh.get("/api/mobile/timeliness/overview")
    assert resp.status_code == 200
    assert resp.json()["jhemr_write_enabled"] is False


# ---- 限流防刷 ----


def test_empno_login_rate_limited_after_five_failures(env):
    from app.routers import users as users_router

    users_router._login_attempts.pop("empno:ghost777", None)
    try:
        _, users, app = env
        client = client_as(app, users["admin"])
        codes = []
        for _ in range(6):
            resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "ghost777"})
            codes.append(resp.status_code)
        assert codes[:5] == [401, 401, 401, 401, 401]
        assert codes[5] == 429  # 第 6 次触发限流（5 次/5 分钟窗口）
    finally:
        users_router._login_attempts.pop("empno:ghost777", None)


# ---- CSRF 豁免 ----


def test_empno_login_exempt_from_csrf_with_stale_cookie(env):
    _, users, app = env
    client = client_as(app, users["admin"])
    client.cookies.set("med_audit_token", "stale-or-expired-token")
    # 不带 X-Requested-With 头：若 CSRF 门未豁免本路径将 403
    resp = client.post("/api/mobile/timeliness/login/empno", json={"empno": "mob_admin"})
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "mob_admin"


# ---- H5 JS 免登链路源码断言 ----


def test_h5_js_contains_empno_auto_login_flow():
    js_path = pathlib.Path(__file__).resolve().parents[2] / "static" / "scripts" / "mobile" / "timeliness_h5.js"
    js = js_path.read_text("utf-8")
    assert "URLSearchParams" in js
    assert "empno" in js
    assert "/login/empno" in js
    # 免登失败必须落回手动登录（不裸奔白屏）
    assert "请改用手动登录" in js
    # 仍然统一携带 CSRF 头
    assert "'X-Requested-With'" in js


def test_csrf_exempt_path_registered():
    from app.security_middleware import _CSRF_EXEMPT_PATHS

    assert "/api/mobile/timeliness/login/empno" in _CSRF_EXEMPT_PATHS
