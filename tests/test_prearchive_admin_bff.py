"""预检规则中心 BFF 测试（039 T6 / §12.1 BFF、Security）。

覆盖：disabled 默认 503 feature-disabled、白名单外目标拒绝、
远端不可用/超时/坏 JSON → 502（fail-open 不拖垮主服务）、
六权限 RBAC 后端强校验、主应用注册不影响启动、
既有 /api/audit-types/prearchive 只读接口不受影响。
"""
import pytest
from types import SimpleNamespace
from unittest import mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.routers.prearchive_admin as bff
from app import database as database_module
from app.database import Base, get_db
from app.models import Permission, Role, RolePermission, User
from app.auth import hash_password
from app.services import prearchive_admin_client as client_mod
from app.services.prearchive_admin_client import (
    PrearchiveAdminClient,
    PrearchiveAdminDisabled,
    PrearchiveAdminUnavailable,
    render_path,
)


def _make_user(db, username, role_name, permissions):
    role = db.query(Role).filter(Role.name == role_name).first()
    if role is None:
        role = Role(name=role_name, description="")
        db.add(role)
        db.flush()
    for perm_name in permissions:
        perm = db.query(Permission).filter(Permission.name == perm_name).first()
        if perm is None:
            perm = Permission(name=perm_name, description="", module="prearchive")
            db.add(perm)
            db.flush()
        if not db.query(RolePermission).filter(
                RolePermission.role_id == role.id,
                RolePermission.permission_id == perm.id).first():
            db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    user = User(username=username, password_hash=hash_password("x"),
                full_name=username, role_id=role.id)
    db.add(user)
    db.commit()
    return user


def _make_app(db):
    app = FastAPI()
    app.include_router(bff.router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return app


def _override_current_user(app, user):
    from app import auth as auth_module
    app.dependency_overrides[auth_module.get_current_user] = lambda: user


ALL_SIX = ["prearchive_rule_view", "prearchive_rule_edit",
           "prearchive_rule_approve", "prearchive_rule_publish",
           "prearchive_integration_manage", "prearchive_delivery_retry"]


@pytest.fixture()
def env():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    admin = _make_user(db, "admin", "admin", ALL_SIX)
    viewer = _make_user(db, "viewer", "viewer", ["prearchive_rule_view"])
    yield db, admin, viewer
    db.close()


def test_disabled_by_default_returns_503_feature_disabled(env):
    db, admin, _ = env
    app = _make_app(db)
    _override_current_user(app, admin)
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"]
    # 写端点同样 503，且不触网
    r2 = client.post("/api/prearchive-admin/rules", json={"rule_id": "X"})
    assert r2.status_code == 503


def test_enabled_unreachable_returns_502(env, monkeypatch):
    db, admin, _ = env
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    monkeypatch.setenv(client_mod.ENV_BASE_URL, "http://127.0.0.1:59999")
    monkeypatch.setenv(client_mod.ENV_ADMIN_TOKEN, "t")
    monkeypatch.setenv(client_mod.ENV_SECRET, "s")
    app = _make_app(db)
    _override_current_user(app, admin)
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 502


def test_enabled_bad_json_and_timeout_fail_open(env, monkeypatch):
    db, admin, _ = env
    app = _make_app(db)
    _override_current_user(app, admin)

    fake = PrearchiveAdminClient(enabled=True, base_url="http://prearchive",
                                 admin_token="t", signing_secret="s")
    with mock.patch.object(bff, "_get_client", lambda: fake):
        with mock.patch.object(client_mod.requests, "request",
                               side_effect=client_mod.requests.Timeout("t")):
            client = TestClient(app)
            r = client.get("/api/prearchive-admin/settings")
            assert r.status_code == 502
            assert "timeout" in r.json()["detail"]

        class _BadResp:
            status_code = 200

            def json(self):
                raise ValueError("not json")

        with mock.patch.object(client_mod.requests, "request", return_value=_BadResp()):
            client2 = TestClient(app)
            r2 = client2.get("/api/prearchive-admin/settings")
            assert r2.status_code == 200
            assert r2.json() == {"message": "invalid remote response"}


def test_allowlist_blocks_unknown_targets():
    client = PrearchiveAdminClient(enabled=True, base_url="http://x",
                                   admin_token="t", signing_secret="s")
    with pytest.raises(ValueError, match="allowlist"):
        client.call("GET", "/api/admin/whatever-else", SimpleNamespace())
    with pytest.raises(ValueError, match="allowlist"):
        client.call("DELETE", "/api/admin/rules", SimpleNamespace())


def test_render_path_encodes_params():
    assert render_path("/api/admin/rules/{rule_key}/diff",
                       {"rule_key": "R 1/2"}) == "/api/admin/rules/R%201%2F2/diff"


def test_permission_enforced_backend_side(env, monkeypatch):
    db, admin, viewer = env
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    monkeypatch.setenv(client_mod.ENV_BASE_URL, "http://prearchive")
    monkeypatch.setenv(client_mod.ENV_ADMIN_TOKEN, "t")
    monkeypatch.setenv(client_mod.ENV_SECRET, "s")
    app = _make_app(db)
    _override_current_user(app, viewer)
    client = TestClient(app)

    # viewer 可以读列表（读端点走 view 权限）
    fake = PrearchiveAdminClient(enabled=True, base_url="http://x",
                                 admin_token="t", signing_secret="s")
    ok_response = {"status": 200, "json": {"items": []}, "request_id": "r"}
    with mock.patch.object(bff, "_get_client", lambda: fake), \
            mock.patch.object(fake, "call", return_value=ok_response):
        assert client.get("/api/prearchive-admin/rules").status_code == 200
        # viewer 不能建草稿（require_permission 在依赖层拒绝）
        r = client.post("/api/prearchive-admin/rules", json={})
        assert r.status_code == 403


def test_main_app_registers_bff_router_without_breaking_startup():
    from app.main import app as main_app
    paths = {route.path for route in main_app.routes}
    assert "/api/prearchive-admin/settings" in paths
    # 既有只读预检接口保持原响应路径
    assert "/api/audit-types/prearchive" in paths


def test_six_permissions_seeded_to_admin_only():
    from app.database import _ensure_default_rbac_permissions
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    with mock.patch.object(database_module, "SessionLocal", session_factory):
        _ensure_default_rbac_permissions()
    db = session_factory()
    admin_role = db.query(Role).filter(Role.name == "admin").first()
    admin_perms = {p.name for p in db.query(Permission).join(RolePermission).filter(
        RolePermission.role_id == admin_role.id).all()}
    for perm in ALL_SIX:
        assert perm in admin_perms
    dept_role = db.query(Role).filter(Role.name == "dept_manager").first()
    dept_perms = {p.name for p in db.query(Permission).join(RolePermission).filter(
        RolePermission.role_id == dept_role.id).all()}
    assert not (set(ALL_SIX) & dept_perms)   # 现有角色权限不变
    db.close()


def test_actor_signature_matches_prearchive_expectation():
    """签名向量：主服务 client 与预检 admin_api 的 HMAC 口径必须一致。"""
    import hashlib
    import hmac as _hmac
    import sys
    from pathlib import Path
    prearchive_root = Path(__file__).resolve().parents[1] / "prearchive_service"
    sys.path.insert(0, str(prearchive_root))
    try:
        from prearchive.admin_api import actor_signature as pa_signature
    finally:
        sys.path.remove(str(prearchive_root))

    actor = SimpleNamespace(id="u-1", username="管理员",
                            permissions=["prearchive_rule_view"])
    fake_client = PrearchiveAdminClient(enabled=True, base_url="http://x",
                                        admin_token="t", signing_secret="shared-secret")
    headers = fake_client._headers(actor, "req-9", "/api/admin/settings")
    # 服务端按线上原始（encoded）值验签
    expected_server = pa_signature("shared-secret", "u-1", headers["X-Actor-Name"],
                                   headers["X-Actor-Permissions"], "req-9")
    assert headers["X-Actor-Signature"] == expected_server


# ---- 041 T3 权限双修：读端点收紧 + 签名权限装载 ----

READ_ENDPOINTS = [
    ("get", "/api/prearchive-admin/settings"),
    ("get", "/api/prearchive-admin/rules"),
    ("get", "/api/prearchive-admin/rules/rk-1/versions"),
    ("post", "/api/prearchive-admin/rules/rk-1/dry-run"),
    ("get", "/api/prearchive-admin/rules/rk-1/diff?version_a=1&version_b=2"),
    ("get", "/api/prearchive-admin/outbox"),
    ("get", "/api/prearchive-admin/fields"),
    ("get", "/api/prearchive-admin/audit"),
    ("get", "/api/prearchive-admin/delivery-logs"),
]


def _editor_without_view(db):
    return _make_user(db, "editor-no-view", "editor", ["prearchive_rule_edit"])


def test_read_endpoints_403_without_view_and_never_reach_sidecar(env, monkeypatch):
    """无 prearchive_rule_view 的登录用户：9 个读端点全部 403，且零次触达远端。"""
    db, _, _ = env
    editor = _editor_without_view(db)
    app = _make_app(db)
    _override_current_user(app, editor)
    client = TestClient(app)

    calls = []
    with mock.patch.object(client_mod.requests, "request",
                           side_effect=lambda *a, **k: calls.append(a)):
        for method, path in READ_ENDPOINTS:
            if method == "post":
                r = client.post(path, json={})
            else:
                r = client.get(path)
            assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
    assert calls == []   # 依赖层已拦，根本没打到 sidecar


def test_viewer_can_read_but_cannot_publish(env, monkeypatch):
    """仅有 view：GET settings 200（mock）；POST publish 403。"""
    db, _, viewer = env
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    monkeypatch.setenv(client_mod.ENV_BASE_URL, "http://prearchive")
    monkeypatch.setenv(client_mod.ENV_ADMIN_TOKEN, "t")
    monkeypatch.setenv(client_mod.ENV_SECRET, "s")
    app = _make_app(db)
    _override_current_user(app, viewer)
    client = TestClient(app)
    with mock.patch.object(client_mod.requests, "request", return_value=_OkResp()):
        assert client.get("/api/prearchive-admin/settings").status_code == 200
    r = client.post("/api/prearchive-admin/rules/rk-1/publish", json={})
    assert r.status_code == 403


def test_admin_request_headers_carry_permissions(env, monkeypatch):
    """admin 请求的 X-Actor-Permissions 必须非空且含 view（签名权限来自查库）。"""
    db, admin, _ = env
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    monkeypatch.setenv(client_mod.ENV_BASE_URL, "http://prearchive")
    monkeypatch.setenv(client_mod.ENV_ADMIN_TOKEN, "t")
    monkeypatch.setenv(client_mod.ENV_SECRET, "s")
    app = _make_app(db)
    _override_current_user(app, admin)
    client = TestClient(app)

    captured = {}

    def _capture(method, url, **kwargs):
        captured.update(kwargs.get("headers") or {})
        return _OkResp()

    with mock.patch.object(client_mod.requests, "request", side_effect=_capture):
        assert client.get("/api/prearchive-admin/settings").status_code == 200
    assert "prearchive_rule_view" in captured["X-Actor-Permissions"]
    assert "prearchive_rule_publish" in captured["X-Actor-Permissions"]


def test_proxy_double_guard_403_without_permission(env):
    """直接调 _proxy（不靠 Depends）：viewer 无发布权限 → 403。"""
    db, _, viewer = env
    with mock.patch.object(bff, "_get_client") as get_client:
        with pytest.raises(HTTPException) as exc_info:
            bff._proxy("POST", "/api/admin/rules/{rule_key}/publish", viewer,
                       bff.PERM_PUBLISH, db, params={"rule_key": "rk-1"},
                       json_body={})
        assert exc_info.value.status_code == 403
        get_client.assert_not_called()   # 无权限时不构造远端调用


def test_admin_role_bypasses_permission_even_without_seeded_perms(env, monkeypatch):
    """admin 短路径：即使 DB 未 seed 六权限，双保险与签名仍给全集（与 require_permission 一致）。"""
    db, _, _ = env
    bare_admin = _make_user(db, "bare-admin", "admin", [])
    app = _make_app(db)
    _override_current_user(app, bare_admin)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "false")   # BFF 关闭：仍应 503 而非 403
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503
    assert bff.current_user_has_permission(bare_admin, bff.PERM_RETRY, db) is True
    assert bff.PERM_RETRY in bff.effective_actor_permissions(bare_admin, db)


class _OkResp:
    status_code = 200

    def json(self):
        return {"mode": "file", "items": []}


def test_read_endpoints_still_503_when_bff_disabled_after_tightening(env):
    """回归：BFF 关闭时读端点仍 503，不因 041 收紧变成 403。"""
    db, _, viewer = env
    app = _make_app(db)
    _override_current_user(app, viewer)
    client = TestClient(app)
    r = client.get("/api/prearchive-admin/settings")
    assert r.status_code == 503
    assert "disabled" in r.json()["detail"]


def test_allowlist_locked_at_exactly_20_targets():
    """041 历史锚：原 20 目标集合必须原样保留（046 只允许显式新增，不得删除）。"""
    from app.services.prearchive_admin_client import ALLOWED_TARGETS
    original_20 = {
        ("GET", "/api/admin/settings"),
        ("GET", "/api/admin/rules"),
        ("POST", "/api/admin/rules"),
        ("GET", "/api/admin/rules/{rule_key}/versions"),
        ("PUT", "/api/admin/rules/{rule_key}/draft"),
        ("POST", "/api/admin/rules/{rule_key}/validate"),
        ("POST", "/api/admin/rules/{rule_key}/dry-run"),
        ("POST", "/api/admin/rules/{rule_key}/approve"),
        ("POST", "/api/admin/rules/{rule_key}/publish"),
        ("POST", "/api/admin/rules/{rule_key}/rollback"),
        ("POST", "/api/admin/rules/{rule_key}/retire"),
        ("GET", "/api/admin/rules/{rule_key}/diff"),
        ("GET", "/api/admin/destinations"),
        ("POST", "/api/admin/destinations"),
        ("POST", "/api/admin/destinations/{code}/contract-test"),
        ("GET", "/api/admin/outbox"),
        ("POST", "/api/admin/outbox/{outbox_id}/retry"),
        ("GET", "/api/admin/fields"),
        ("GET", "/api/admin/audit"),
        ("GET", "/api/admin/delivery-logs"),
    }
    assert original_20 <= ALLOWED_TARGETS, "041 原 20 目标不得删除（046 §T7.1）"


def test_allowlist_exact_granted_set_and_permission_matrix():
    """046 T7.1：白名单=完整获准 (method,path) 集合的精确比较 + 逐条权限矩阵。

    集合精确断言（不是 len>=20 下限）；每个目标都有权限映射且 ∈ 合法枚举；
    未知路径/方法/路径穿越仍拒绝。白名单任何变更必须同步本测试。
    """
    from app.services.prearchive_admin_client import (
        ALLOWED_TARGETS,
        TARGET_PERMISSIONS,
        _match_target,
        permission_for_target,
    )
    expected = {
        # 041 原 20
        ("GET", "/api/admin/settings"),
        ("GET", "/api/admin/rules"),
        ("POST", "/api/admin/rules"),
        ("GET", "/api/admin/rules/{rule_key}/versions"),
        ("PUT", "/api/admin/rules/{rule_key}/draft"),
        ("POST", "/api/admin/rules/{rule_key}/validate"),
        ("POST", "/api/admin/rules/{rule_key}/dry-run"),
        ("POST", "/api/admin/rules/{rule_key}/approve"),
        ("POST", "/api/admin/rules/{rule_key}/publish"),
        ("POST", "/api/admin/rules/{rule_key}/rollback"),
        ("POST", "/api/admin/rules/{rule_key}/retire"),
        ("GET", "/api/admin/rules/{rule_key}/diff"),
        ("GET", "/api/admin/destinations"),
        ("POST", "/api/admin/destinations"),
        ("POST", "/api/admin/destinations/{code}/contract-test"),
        ("GET", "/api/admin/outbox"),
        ("POST", "/api/admin/outbox/{outbox_id}/retry"),
        ("GET", "/api/admin/fields"),
        ("GET", "/api/admin/audit"),
        ("GET", "/api/admin/delivery-logs"),
        # 046 T1a 新增：覆盖账本 / AI 匹配 / trial
        ("GET", "/api/admin/coverage"),
        ("POST", "/api/admin/coverage/import-snapshot"),
        ("POST", "/api/admin/coverage/{fid}/confirm"),
        ("GET", "/api/admin/coverage/export"),
        ("POST", "/api/admin/coverage/generate-file"),
        ("POST", "/api/admin/match/tasks"),
        ("POST", "/api/admin/match/tasks/{task_id}/run"),
        ("GET", "/api/admin/match/tasks/{task_id}"),
        ("POST", "/api/admin/match/tasks/{task_id}/cancel"),
        ("POST", "/api/admin/match/candidates/{candidate_id}/decision"),
        ("POST", "/api/admin/trial/runs"),
        ("GET", "/api/admin/trial/runs"),
        # 046 T5 新增：核查工作台
        ("GET", "/api/admin/checks"),
        ("GET", "/api/admin/checks/{run_id}"),
        ("GET", "/api/admin/issues"),
        ("GET", "/api/admin/issues/{issue_id}"),
        ("POST", "/api/admin/issues/{issue_id}/actions"),
        ("POST", "/api/admin/trial/runs/{trial_run_id}/execute"),
        ("GET", "/api/admin/trial/runs/{trial_run_id}/observations"),
        ("POST", "/api/admin/trial/runs/{trial_run_id}/feedback"),
        # 046 T7 新增：JHEMR 集成内部目标（外部=主服务签名路由 /api/integrations/jhemr/*）
        ("POST", "/api/integration/jhemr/submission-checks"),
        ("GET", "/api/integration/jhemr/submission-checks/{check_id}"),
        ("POST", "/api/integration/jhemr/view-tickets"),
        ("POST", "/api/integration/jhemr/view-tickets/{nonce}/redeem"),
        ("POST", "/api/integration/jhemr/issues/{issue_id}/feedback"),
        ("POST", "/api/integration/jhemr/rechecks"),
    }
    assert ALLOWED_TARGETS == expected, (
        "白名单漂移：新增/删除需按 046 §T7.1 同步本测试。"
        f"差集={ALLOWED_TARGETS ^ expected}")

    legal_perms = {
        "prearchive_rule_view", "prearchive_rule_edit",
        "prearchive_rule_approve", "prearchive_rule_publish",
        "prearchive_integration_manage", "prearchive_delivery_retry",
        "prearchive_match_run", "prearchive_trial_manage",
        "prearchive_check_view", "prearchive_issue_review",
        "prearchive_issue_feedback",
    }
    assert set(TARGET_PERMISSIONS) == ALLOWED_TARGETS, "每个获准目标都必须有权限映射"
    for target, perm in TARGET_PERMISSIONS.items():
        assert perm in legal_perms, f"目标 {target} 映射到未知权限 {perm}"

    # 权限矩阵关键行：新增目标→新增权限；读类→view
    assert permission_for_target("POST", "/api/admin/match/tasks") == \
        "prearchive_match_run"
    assert permission_for_target("POST", "/api/admin/trial/runs") == \
        "prearchive_trial_manage"
    assert permission_for_target("GET", "/api/admin/coverage") == \
        "prearchive_rule_view"
    assert permission_for_target("GET", "/api/admin/trial/runs") == \
        "prearchive_rule_view"
    # 046 T7：集成目标=服务账号最小集（提交检查/复检/票据=check_view，反馈=feedback）
    assert permission_for_target(
        "POST", "/api/integration/jhemr/submission-checks") == \
        "prearchive_check_view"
    assert permission_for_target(
        "GET", "/api/integration/jhemr/submission-checks/{check_id}") == \
        "prearchive_check_view"
    assert permission_for_target(
        "POST", "/api/integration/jhemr/issues/{issue_id}/feedback") == \
        "prearchive_issue_feedback"
    assert permission_for_target(
        "POST", "/api/integration/jhemr/rechecks") == "prearchive_check_view"

    # 未知路径 / 方法 / 路径穿越拒绝
    assert not _match_target("GET", "/api/admin/unknown")
    assert not _match_target("DELETE", "/api/admin/rules")
    assert not _match_target("GET", "/api/admin/../../etc/passwd")
    assert not _match_target("DELETE", "/api/integration/jhemr/submission-checks")


def test_bff_router_routes_covered_by_allowlist():
    """主服务 BFF 路由实际注册的代理目标 ⊆ 白名单（路由不得先于白名单扩展）。"""
    from app.routers import prearchive_admin as router_mod
    from app.services.prearchive_admin_client import ALLOWED_TARGETS

    proxied = set()
    for route in router_mod.router.routes:
        handler = getattr(route, "endpoint", None)
        code = getattr(handler, "__code__", None)
        if code is None:
            continue
        path = next((c for c in code.co_consts
                     if isinstance(c, str) and c.startswith("/api/admin/")), None)
        method = next((c for c in code.co_consts
                       if isinstance(c, str) and c in ("GET", "POST", "PUT")), None)
        if path and method:
            proxied.add((method, path))
    assert proxied, "未能从路由提取代理目标（检查 _proxy 调用形态）"
    unknown = proxied - ALLOWED_TARGETS
    assert not unknown, f"路由代理了白名单外目标: {unknown}"


# ---------------------------------------------------------------- 046 T5：核查工作台 BFF


def _make_scoped_user(db, username, role_name, permissions, dept_name):
    from app.models import Department
    dept = db.query(Department).filter(Department.name == dept_name).first()
    if dept is None:
        dept = Department(name=dept_name, code=f"CODE-{dept_name}")
        db.add(dept)
        db.commit()
    user = _make_user(db, username, role_name, permissions)
    user.dept_id = dept.id
    db.commit()
    return user


def test_checks_bff_scopes_dept_for_clinician(env, monkeypatch):
    """clinician（仅 check_view，无 review）→ 强制本科室过滤参数。"""
    db, _admin, _viewer = env
    clinician = _make_scoped_user(
        db, "dr-li", "clinician",
        ["prearchive_check_view", "prearchive_issue_feedback"], "普外科")
    app = _make_app(db)
    _override_current_user(app, clinician)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    captured = {}

    class _CapturingClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            captured["path"] = path_template
            captured["query"] = kwargs.get("query")
            return {"status": 200, "json": {"items": []},
                    "request_id": "r-1"}

    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        r = client.get("/api/prearchive-admin/checks")
    assert r.status_code == 200
    assert captured["query"]["dept_code"] == "CODE-普外科", "非复核角色强制本科室"


def test_checks_bff_no_scope_for_reviewer(env, monkeypatch):
    db, _admin, _viewer = env
    qc = _make_user(db, "qc-audit", "auditor",
                    ["prearchive_check_view", "prearchive_issue_review"])
    app = _make_app(db)
    _override_current_user(app, qc)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    captured = {}

    class _CapturingClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            captured["query"] = kwargs.get("query")
            return {"status": 200, "json": {"items": []},
                    "request_id": "r-1"}

    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        r = client.get("/api/prearchive-admin/checks",
                       params={"dept_code": "D002"})
    assert r.status_code == 200
    assert captured["query"]["dept_code"] == "D002", "复核角色不强制过滤"


def test_issue_action_any_of_feedback_or_review(env, monkeypatch):
    db, _admin, _viewer = env
    doctor = _make_user(db, "dr-wang", "clinician", ["prearchive_issue_feedback"])
    app = _make_app(db)
    _override_current_user(app, doctor)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    class _OkClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            return {"status": 200, "json": {"status": "viewed"},
                    "request_id": "r-2"}

    with mock.patch.object(bff, "_get_client", lambda: _OkClient()):
        r = client.post("/api/prearchive-admin/issues/i-1/actions",
                        json={"action": "viewed"})
    assert r.status_code == 200

    # 完全无关权限 → 403
    stranger = _make_user(db, "stranger", "nobody", [])   # 独立角色：无任何预检权限
    _override_current_user(app, stranger)
    r = client.post("/api/prearchive-admin/issues/i-1/actions",
                    json={"action": "viewed"})
    assert r.status_code == 403


def test_checks_bff_denied_without_check_view(env, monkeypatch):
    db, _admin, viewer = env     # viewer 只有 prearchive_rule_view
    app = _make_app(db)
    _override_current_user(app, viewer)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")
    r = client.get("/api/prearchive-admin/checks")
    assert r.status_code == 403


# ---- 048 T2：checks 分页透传 + 详情/动作科室范围强制注入 ----


def test_checks_bff_passes_pagination_params(env, monkeypatch):
    """page/page_size 透传；未传的分页参数（0）不得发给预检侧。"""
    db, _admin, _viewer = env
    qc = _make_user(db, "qc-page", "auditor",
                    ["prearchive_check_view", "prearchive_issue_review"])
    app = _make_app(db)
    _override_current_user(app, qc)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    captured = {}

    class _CapturingClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            captured["query"] = kwargs.get("query")
            return {"status": 200, "json": {"items": [], "total": 0},
                    "request_id": "r-1"}

    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        r = client.get("/api/prearchive-admin/checks",
                       params={"page": 2, "page_size": 50})
    assert r.status_code == 200
    assert captured["query"]["page"] == 2
    assert captured["query"]["page_size"] == 50
    assert captured["query"].get("limit") is None, "limit=0 不透传"

    # 旧 limit 兼容透传
    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        client.get("/api/prearchive-admin/checks", params={"limit": 30})
    assert captured["query"]["limit"] == 30
    assert captured["query"].get("page_size") is None


def test_check_detail_bff_enforces_dept_for_clinician(env, monkeypatch):
    db, _admin, _viewer = env
    clinician = _make_scoped_user(
        db, "dr-detail", "clinician",
        ["prearchive_check_view", "prearchive_issue_feedback"], "普外科")
    app = _make_app(db)
    _override_current_user(app, clinician)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    captured = {}

    class _CapturingClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            captured["path"] = path_template
            captured["query"] = kwargs.get("query")
            return {"status": 200, "json": {"dept_code": "CODE-普外科"},
                    "request_id": "r-1"}

    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        r = client.get("/api/prearchive-admin/checks/run-x")
    assert r.status_code == 200
    assert captured["query"]["enforce_dept_code"] == "CODE-普外科"

    # 缺陷详情同样强制
    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        client.get("/api/prearchive-admin/issues/iss-x")
    assert captured["path"] == "/api/admin/issues/{issue_id}"
    assert captured["query"]["enforce_dept_code"] == "CODE-普外科"

    # 复核角色（auditor）不注入
    qc = _make_user(db, "qc-detail", "auditor",
                    ["prearchive_check_view", "prearchive_issue_review"])
    _override_current_user(app, qc)
    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        client.get("/api/prearchive-admin/checks/run-x")
    assert captured["query"] is None, "复核角色不限制科室"


def test_issue_action_bff_injects_enforce_dept_for_clinician(env, monkeypatch):
    db, _admin, _viewer = env
    clinician = _make_scoped_user(
        db, "dr-act", "clinician",
        ["prearchive_check_view", "prearchive_issue_feedback"], "普外科")
    app = _make_app(db)
    _override_current_user(app, clinician)
    client = TestClient(app)
    monkeypatch.setenv(client_mod.ENV_ENABLED, "true")

    captured = {}

    class _CapturingClient:
        enabled = True
        base_url = "http://sidecar"
        admin_token = "t"
        signing_secret = "s"

        def call(self, method, path_template, actor, **kwargs):
            captured["body"] = kwargs.get("json_body")
            return {"status": 200, "json": {"status": "viewed"},
                    "request_id": "r-1"}

    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        r = client.post("/api/prearchive-admin/issues/i-9/actions",
                        json={"action": "viewed"})
    assert r.status_code == 200
    assert captured["body"]["enforce_dept_code"] == "CODE-普外科"
    assert captured["body"]["action"] == "viewed"

    # 复核角色不注入（body 原样）
    qc = _make_user(db, "qc-act", "auditor",
                    ["prearchive_check_view", "prearchive_issue_review"])
    _override_current_user(app, qc)
    with mock.patch.object(bff, "_get_client", lambda: _CapturingClient()):
        client.post("/api/prearchive-admin/issues/i-9/actions",
                    json={"action": "recheck_passed"})
    assert "enforce_dept_code" not in captured["body"]
