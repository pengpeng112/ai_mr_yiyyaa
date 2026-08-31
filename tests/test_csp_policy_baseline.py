"""CSP 现状基线固化（035/RP4，F1）。

用途：防止未来误删 'unsafe-eval'（删=legacy 页面 EvalError 崩）或误放
'unsafe-inline'/外源（放=削弱注入防护）。本文件固化 2026-09-01 现状策略，
不改任何行为（零生产变更）。

**unsafe-eval 解除条件（登记）**：
1. legacy 前端三个运行时模板编译页面（index.html / log_detail.html /
   移动端 qc_detail.html）全部迁移为预编译渲染（vue.runtime + 构建期模板编译），
   或 legacy 前端整体下线（ui-next 全量切换完成，WP6 canary 转 GA）；
2. 且全仓前端静态资产无 new Function/eval 依赖（构建产物 grep 复核）。
两项同时满足后方可从 CSP_POLICY 移除 'unsafe-eval' 并删除本文件的
test_script_src_baseline 断言中的对应检查。
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.auth import hash_password
from app.models import User
from app.routers import users as users_router
from app.security_middleware import CSP_POLICY, register_security_middleware

import pytest


@pytest.fixture()
def client(monkeypatch):
    """最小认证应用（与 test_cookie_csrf_security.client 同构，仅验证响应头）。"""
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
    monkeypatch.setattr(users_router, "get_user_permissions_list", lambda uid, d: [])
    monkeypatch.setattr(users_router, "get_user_role", lambda uid, d: "admin")
    app = FastAPI()
    register_security_middleware(app)
    app.include_router(users_router.router, prefix="/api/users")
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    db.close()


def _directive(name: str) -> str:
    for part in CSP_POLICY.split(";"):
        tokens = part.split()
        if tokens and tokens[0] == name:
            return part.strip()
    return ""


def test_script_src_baseline():
    """script-src 必须同时含 'self' 与 'unsafe-eval'（vue.global 运行时模板编译必需）。"""
    script_src = _directive("script-src")
    assert "'self'" in script_src
    assert "'unsafe-eval'" in script_src


def test_script_src_stays_strict_elsewhere():
    """除 self/unsafe-eval 外不得放宽：无 unsafe-inline、无外源主机、无通配 https。"""
    script_src = _directive("script-src")
    assert "unsafe-inline" not in script_src
    assert "*" not in script_src
    assert "http://" not in script_src
    assert "https://" not in script_src


def test_other_directives_baseline():
    """其余指令现状：default-src self、object-src none、style 允许内联、无 frame 限制。"""
    assert _directive("default-src") == "default-src 'self'"
    assert _directive("object-src") == "object-src 'none'"
    assert "'unsafe-inline'" in _directive("style-src")  # Element Plus/内联 style 依赖
    assert "frame-ancestors" not in CSP_POLICY  # Relay 反代移动端 H5 依赖（勿加）
    assert "X-Frame-Options" not in CSP_POLICY
    assert _directive("connect-src") == "connect-src 'self'"
    assert _directive("base-uri") == "base-uri 'self'"
    assert _directive("form-action") == "form-action 'self'"


def test_security_headers_via_middleware(client):
    """中间件在真实响应上设置 CSP/nosniff/Referrer-Policy 三头（现状固化）。"""
    r = client.get("/api/users/me")
    assert r.headers.get("Content-Security-Policy") == CSP_POLICY
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("Referrer-Policy") in ("no-referrer", "same-origin", "strict-origin-when-cross-origin")
