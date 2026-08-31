"""Cookie 认证 + CSRF + CSP 安全契约测试（023 P1-03 / 031 T1-5）。

覆盖：登录下发 HttpOnly Cookie、Cookie/Bearer 双轨认证、Cookie 写操作 CSRF 头
正反用例、Bearer 免 CSRF、登出清 Cookie、过期 Token、CSP 响应头。
"""
import pytest
from datetime import timedelta
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import AUTH_COOKIE_NAME, create_access_token, hash_password
from app.database import Base, get_db
from app.models import User
from app.routers import users as users_router
from app.security_middleware import CSP_POLICY, register_security_middleware


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(User(
        username="admin", password_hash=hash_password("admin-pass"),
        full_name="管理员", email="", is_active=True,
    ))
    db.commit()

    # 权限聚合走轻量桩：本文件只验证认证/CSRF/CSP 语义，不测 RBAC 内容
    monkeypatch.setattr(users_router, "get_user_permissions_list", lambda uid, d: [])
    monkeypatch.setattr(users_router, "get_user_role", lambda uid, d: "admin")

    app = FastAPI()
    register_security_middleware(app)
    app.include_router(users_router.router, prefix="/api/users")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    db.close()


def _login(client, username="admin", password="admin-pass"):
    return client.post("/api/users/login", json={"username": username, "password": password})


def test_login_sets_httponly_strict_samesite_cookie(client):
    r = _login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]  # Bearer 兼容：响应体仍返回 token
    set_cookie = r.headers["set-cookie"]
    assert AUTH_COOKIE_NAME in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=strict" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


def test_cookie_only_authentication(client):
    _login(client)
    r = client.get("/api/users/me")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"


def test_bearer_still_works_during_compatibility_window(client):
    token = _login(client).json()["access_token"]
    fresh = TestClient(client.app)
    r = fresh.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_cookie_write_without_csrf_header_rejected(client):
    _login(client)
    r = client.post("/api/users/logout")
    assert r.status_code == 403
    assert "CSRF" in r.json()["message"]


def test_cookie_write_with_csrf_header_allowed_and_clears_cookie(client):
    _login(client)
    r = client.post("/api/users/logout", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert AUTH_COOKIE_NAME in set_cookie
    assert ('max-age=0' in set_cookie.lower()) or ('="";' in set_cookie) or ('expires=Thu, 01 Jan 1970' in set_cookie)


def test_stale_cookie_login_not_csrf_blocked(client):
    """带旧 Cookie 的登录不得被 CSRF 门拦截（2026-08-30 生产缺陷：
    旧会话 Cookie + 旧缓存 JS 无 X-Requested-With → 登录被 403 锁死）。"""
    client.cookies.set(AUTH_COOKIE_NAME, "stale-or-expired-token")
    r = client.post(
        "/api/users/login",
        json={"username": "admin", "password": "admin-pass"},
    )
    assert r.status_code == 200, f"stale cookie must not block login, got {r.status_code}"
    assert AUTH_COOKIE_NAME in r.headers.get("set-cookie", "")  # 滚动下发新 Cookie


def test_stale_cookie_login_wrong_password_still_401(client):
    client.cookies.set(AUTH_COOKIE_NAME, "stale-or-expired-token")
    r = client.post(
        "/api/users/login",
        json={"username": "admin", "password": "wrong-pass"},
    )
    assert r.status_code == 401
    assert "CSRF" not in str(r.json())


def test_bearer_write_exempt_from_csrf(client):
    token = _login(client).json()["access_token"]
    fresh = TestClient(client.app)
    r = fresh.post("/api/users/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_anonymous_login_post_not_csrf_blocked(client):
    """登录本身无 Cookie，CSRF 门不得拦截匿名写请求。"""
    r = client.post(
        "/api/users/login",
        json={"username": "admin", "password": "wrong-pass"},
    )
    assert r.status_code == 401
    body_text = str(r.json())
    assert "CSRF" not in body_text


def test_expired_token_cookie_rejected(client):
    from app.models import User as _User
    db_user = client.app.dependency_overrides[get_db]().query(_User).filter_by(username="admin").one()
    expired = create_access_token(db_user.id, db_user.username, expires_delta=timedelta(seconds=-10))
    fresh = TestClient(client.app)
    fresh.cookies.set(AUTH_COOKIE_NAME, expired)
    r = fresh.get("/api/users/me")
    assert r.status_code == 401


def test_csp_header_present_on_responses(client):
    r = client.get("/api/users/me")
    assert r.headers.get("Content-Security-Policy") == CSP_POLICY
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
