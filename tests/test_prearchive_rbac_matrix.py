"""041 T4：四角色（seed 实名 admin/auditor/dept_manager/clinician）× 六权限代表端点矩阵。

- 角色权限来自 app.demo_support.seed._seed_rbac 真实落库（auditor 仅追加 view）；
- 远端 mock：只验证 BFF 侧 200/403，不依赖 sidecar；
- clinician / dept_manager 的 GET settings = 403 是 041 T3 读端点收紧后的契约。
"""
import pytest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.prearchive_admin_client as client_mod
from app import auth as auth_module
from app.database import Base, get_db
from app.models import Role, User
from app.auth import hash_password
from app.demo_support.seed import _seed_rbac
from app.routers import prearchive_admin as bff

SEED_ROLES = ("admin", "auditor", "dept_manager", "clinician")


class _OkResp:
    status_code = 200

    def json(self):
        return {"items": [], "mode": "file"}


@pytest.fixture()
def matrix_env(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    _seed_rbac(db)   # 与 demo seed 完全同源的角色/权限落库

    users = {}
    for index, role_name in enumerate(SEED_ROLES):
        role = db.query(Role).filter(Role.name == role_name).first()
        assert role is not None, role_name
        user = User(username=f"mx_{role_name}", password_hash=hash_password("x"),
                    full_name=role_name, role_id=role.id)
        db.add(user)
        users[role_name] = user
    db.commit()

    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    monkeypatch.setenv(client_mod.ENV_BASE_URL, "http://prearchive")
    monkeypatch.setenv(client_mod.ENV_ADMIN_TOKEN, "t")
    monkeypatch.setenv(client_mod.ENV_SECRET, "s")

    app = FastAPI()
    app.include_router(bff.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    yield db, users, app
    db.close()


def _client_as(app, user):
    app.dependency_overrides[auth_module.get_current_user] = lambda: user
    return TestClient(app)


# (名称, 请求构造, 期望 200 的角色集合)——矩阵锁死：admin 全能、auditor 仅 view、其余全无
MATRIX_CASES = [
    ("settings GET(view)", lambda c: c.get("/api/prearchive-admin/settings"), {"admin", "auditor"}),
    ("rules GET(view)", lambda c: c.get("/api/prearchive-admin/rules"), {"admin", "auditor"}),
    ("dry-run POST(view)", lambda c: c.post("/api/prearchive-admin/rules/rk-1/dry-run", json={}), {"admin", "auditor"}),
    ("draft PUT(edit)", lambda c: c.put("/api/prearchive-admin/rules/rk-1/draft", json={}), {"admin"}),
    ("approve POST(approve)", lambda c: c.post("/api/prearchive-admin/rules/rk-1/approve", json={}), {"admin"}),
    ("publish POST(publish)", lambda c: c.post("/api/prearchive-admin/rules/rk-1/publish", json={}), {"admin"}),
    ("destinations POST(integration)", lambda c: c.post("/api/prearchive-admin/destinations", json={"code": "mock"}), {"admin"}),
    ("outbox retry POST(retry)", lambda c: c.post("/api/prearchive-admin/outbox/1/retry"), {"admin"}),
]


def test_role_endpoint_matrix(matrix_env):
    db, users, app = matrix_env
    with mock.patch.object(client_mod.requests, "request", return_value=_OkResp()):
        for label, send, allowed in MATRIX_CASES:
            for role_name in SEED_ROLES:
                client = _client_as(app, users[role_name])
                response = send(client)
                expected = 200 if role_name in allowed else 403
                assert response.status_code == expected, (
                    f"{label} as {role_name}: {response.status_code} != {expected}")


def test_seed_roles_are_exactly_four_named(matrix_env):
    db, _, _ = matrix_env
    names = {r.name for r in db.query(Role).all()}
    assert set(SEED_ROLES) <= names          # 四实名角色齐
    # auditor 权限精确 = 原 6 项 + view（无 edit/approve/publish/integration/retry）
    from app.permissions import get_user_permissions
    auditor_perms = set(get_user_permissions(
        db.query(User).filter(User.username == "mx_auditor").first().id, db))
    assert "prearchive_rule_view" in auditor_perms
    assert not (auditor_perms & {"prearchive_rule_edit", "prearchive_rule_approve",
                                 "prearchive_rule_publish",
                                 "prearchive_integration_manage",
                                 "prearchive_delivery_retry"})


def test_dept_manager_and_clinician_get_settings_403(matrix_env):
    """T3 收紧后的显式契约：无 view 的登录用户连 settings 都不可读。"""
    db, users, app = matrix_env
    for role_name in ("dept_manager", "clinician"):
        client = _client_as(app, users[role_name])
        response = client.get("/api/prearchive-admin/settings")
        assert response.status_code == 403, role_name
