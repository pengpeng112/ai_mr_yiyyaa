"""041 T2：仅 DEMO_MODE 注入预检规则中心 BFF env（显式 env 键优先）。

| 用例 | 期望 |
|---|---|
| 默认 env、非 DEMO_MODE | settings → 503，detail 含 disabled |
| DEMO_MODE + sidecar 未起 | settings 鉴权后 502，health 摘要 200 |
| DEMO_MODE + sidecar mock（签名带权限） | 200 |
| os.environ 已有 PREARCHIVE_ADMIN_ENABLED=false 即使 DEMO_MODE | 仍 503 |
| 仅 TEST_ISOLATED_MODE=true、无 DEMO_MODE | 不注入，503 |
"""
import socket
from unittest import mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.prearchive_admin_client as client_mod
from app import database as database_module
from app.database import Base, get_db
from app.models import Permission, Role, RolePermission, User
from app.auth import hash_password
from app.routers import health as health_router
from app.routers import prearchive_admin as bff
from app.services.isolated_mode import (
    DEMO_PREARCHIVE_BFF_ENV,
    inject_prearchive_admin_bff_env,
)

ENV_KEYS = ("PREARCHIVE_ADMIN_ENABLED", "PREARCHIVE_ADMIN_BASE_URL",
            "PREARCHIVE_ADMIN_TOKEN", "PREARCHIVE_ADMIN_SECRET",
            "DEMO_MODE", "TEST_ISOLATED_MODE")


@pytest.fixture()
def env_snapshot(monkeypatch):
    """清空本组相关 env 键；teardown 显式回收注入函数直接写入 os.environ 的键。

    monkeypatch 只回收自己 setenv/delenv 的键——被测函数用 os.environ.update
    新增的 PREARCHIVE_ADMIN_* 键必须在这里兜底删除，否则泄漏到后续测试
    （曾导致 test_prearchive_admin_bff 的默认 503 用例在全量跑时变 502）。
    """
    import os
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    for key in ENV_KEYS:
        os.environ.pop(key, None)


def _make_admin_app():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    role = Role(name="admin", description="")
    db.add(role)
    db.flush()
    for name in ("prearchive_rule_view", "prearchive_rule_edit",
                 "prearchive_rule_approve", "prearchive_rule_publish",
                 "prearchive_integration_manage", "prearchive_delivery_retry"):
        db.add(Permission(name=name, description="", module="prearchive"))
    db.flush()
    perms = {p.name: p for p in db.query(Permission).all()}
    for perm in perms.values():
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    db.add(User(username="admin", password_hash=hash_password("x"),
                full_name="admin", role_id=role.id))
    db.commit()

    from app import auth as auth_module
    users = db.query(User).all()
    app = FastAPI()
    app.include_router(bff.router, prefix="/api")
    app.include_router(health_router.router, prefix="/api/health")
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[auth_module.get_current_user] = lambda: users[0]
    return app, db


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"mode": "file", "items": []}


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


# ---- 注入函数本体 ----

def test_inject_sets_four_keys_only_in_demo_mode(env_snapshot, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    assert inject_prearchive_admin_bff_env() is True
    for key, value in DEMO_PREARCHIVE_BFF_ENV.items():
        import os
        assert os.environ[key] == value
    # 假值必须与 sidecar config.demo.json 一致（回归锚）
    assert DEMO_PREARCHIVE_BFF_ENV["PREARCHIVE_ADMIN_BASE_URL"] == "http://127.0.0.1:18600"
    assert DEMO_PREARCHIVE_BFF_ENV["PREARCHIVE_ADMIN_TOKEN"] == "demo-admin-token"


def test_inject_respects_explicit_env_key_presence(env_snapshot, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PREARCHIVE_ADMIN_ENABLED", "false")   # 键存在即显式意图
    assert inject_prearchive_admin_bff_env() is False
    import os
    for key in ("PREARCHIVE_ADMIN_BASE_URL", "PREARCHIVE_ADMIN_TOKEN", "PREARCHIVE_ADMIN_SECRET"):
        assert key not in os.environ


def test_inject_ignores_test_isolated_mode_alone(env_snapshot, monkeypatch):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    assert inject_prearchive_admin_bff_env() is False
    import os
    assert "PREARCHIVE_ADMIN_ENABLED" not in os.environ


def test_inject_off_by_default(env_snapshot):
    assert inject_prearchive_admin_bff_env() is False


# ---- HTTP 行为 ----

def test_default_env_non_demo_returns_503(env_snapshot):
    app, db = _make_admin_app()
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"]


def test_demo_mode_without_sidecar_returns_502_health_ok(env_snapshot, monkeypatch):
    if _port_open(18600):
        pytest.skip("18600 已有服务在跑（sidecar 被外部拉起），502 用例跳过")
    monkeypatch.setenv("DEMO_MODE", "true")
    assert inject_prearchive_admin_bff_env() is True
    app, db = _make_admin_app()
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 502
    health = client.get("/api/health")
    assert health.status_code == 200


def test_demo_mode_with_mocked_sidecar_200(env_snapshot, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    assert inject_prearchive_admin_bff_env() is True
    app, db = _make_admin_app()
    client = TestClient(app)
    captured = {}

    def _capture(method, url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers") or {}
        return _FakeResponse()

    with mock.patch.object(client_mod.requests, "request", side_effect=_capture):
        r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 200
    # 注入的假 token 确实被 BFF 用作 Admin-Token；签名权限来自查库（041 T3）
    assert captured["url"].startswith("http://127.0.0.1:18600/api/admin/settings")
    assert captured["headers"]["X-Admin-Token"] == "demo-admin-token"
    assert "prearchive_rule_view" in captured["headers"]["X-Actor-Permissions"]
    assert captured["headers"]["X-Actor-Signature"]


def test_demo_mode_respects_explicit_disabled_key(env_snapshot, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PREARCHIVE_ADMIN_ENABLED", "false")
    assert inject_prearchive_admin_bff_env() is False
    app, db = _make_admin_app()
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503


def test_isolated_mode_alone_still_503(env_snapshot, monkeypatch):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    assert inject_prearchive_admin_bff_env() is False
    app, db = _make_admin_app()
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503
