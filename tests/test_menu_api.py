"""菜单目录、角色默认矩阵与环境过滤测试（017 WP1）。"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import menu as menu_module
from app.routers.menu import (
    MENU_CATALOG,
    MENU_CONFIG,
    MENU_GROUPS,
    MENU_MAP,
    ROLE_DEFAULT_HOME,
    build_menu_response,
    filter_menu_items_for_navigation,
)


def test_menu_ids_are_unique():
    ids = [item["id"] for item in MENU_CATALOG]
    assert len(ids) == len(set(ids))
    assert len(ids) == 17


def test_menu_groups_unique_and_within_limit():
    group_ids = [g["id"] for g in MENU_GROUPS]
    assert len(group_ids) == len(set(group_ids))
    assert len(group_ids) <= 6


def test_every_catalog_item_has_valid_group_and_route_name():
    group_ids = {g["id"] for g in MENU_GROUPS}
    for item in MENU_CATALOG:
        assert item["group"] in group_ids, item["id"]
        assert item.get("route_name"), item["id"]
        assert item.get("path"), item["id"]
        assert "target" in item and "activeMenu" in item["target"]


def test_role_menu_ids_exist_in_catalog():
    for role, menu_ids in MENU_CONFIG.items():
        for mid in menu_ids:
            assert mid in MENU_MAP, f"{role} references unknown menu {mid}"


def test_role_default_homes_exist():
    for role, home in ROLE_DEFAULT_HOME.items():
        assert home in MENU_MAP
        assert role in MENU_CONFIG
        assert home in MENU_CONFIG[role] or home in MENU_MAP


def test_placeholder_menus_are_hidden():
    for mid in ("oracle-status", "system-logs"):
        assert MENU_MAP[mid]["hidden"] is True


def test_debug_is_dev_only():
    assert MENU_MAP["debug"]["dev_only"] is True


def test_filter_hides_placeholders_and_prod_dev_only():
    raw = list(MENU_CATALOG)
    nav_dev = filter_menu_items_for_navigation(raw, production=False)
    nav_prod = filter_menu_items_for_navigation(raw, production=True)

    nav_dev_ids = {i["id"] for i in nav_dev}
    nav_prod_ids = {i["id"] for i in nav_prod}

    assert "oracle-status" not in nav_dev_ids
    assert "system-logs" not in nav_dev_ids
    assert "debug" in nav_dev_ids
    assert "debug" not in nav_prod_ids
    assert "dashboard" in nav_prod_ids


def test_build_menu_response_schema_and_groups():
    resp = build_menu_response(MENU_CONFIG["auditor"], "auditor", production=True)
    assert resp["schema_version"] == 2
    assert resp["role"] == "auditor"
    assert all(not item.get("hidden") for item in resp["menu"])
    used_groups = {item["group"] for item in resp["menu"]}
    assert {g["id"] for g in resp["groups"]} == used_groups
    assert "oracle-status" not in {m["id"] for m in resp["menu"]}


def test_legacy_role_matrix_ids_preserved():
    """确保 RoleMenu 兼容：角色默认 ID 集合不因文案改动而丢失核心项。"""
    assert set(MENU_CONFIG["clinician"]) == {"dashboard", "audit", "feedback"}
    assert set(MENU_CONFIG["auditor"]) == {
        "dashboard",
        "patient-qc",
        "audit",
        "feedback",
        "health",
    }
    assert set(MENU_CONFIG["dept_manager"]) == {
        "dashboard",
        "patient-qc",
        "audit",
        "feedback",
        "scheduler",
        "health",
    }
    assert "admin" in MENU_CONFIG
    assert set(MENU_CONFIG["admin"]) == {item["id"] for item in MENU_CATALOG}


class _QueryChain:
    def __init__(self, rows=None, role=None):
        self._rows = rows or []
        self._role = role

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._role


class _DummyDb:
    def __init__(self, role_name="admin", role_menus=None):
        self.role_name = role_name
        self.role_menus = role_menus or []
        self.role = SimpleNamespace(id=1, name=role_name)

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        if name == "RoleMenu":
            return _QueryChain(rows=self.role_menus)
        if name == "Role":
            return _QueryChain(role=self.role)
        return _QueryChain()


def _make_menu_client(monkeypatch, role_name="admin", role_menus=None):
    from app import auth as auth_module
    from app import database as database_module
    from app.permissions import get_user_role

    app = FastAPI()
    app.include_router(menu_module.router, prefix="/api")

    class _FakeUser:
        id = 1
        role_id = 1

    monkeypatch.setattr(
        "app.routers.menu.get_user_role",
        lambda user_id, db: role_name,
    )

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[database_module.get_db] = lambda: _DummyDb(
        role_name=role_name, role_menus=role_menus
    )
    return TestClient(app)


def test_get_menu_returns_filtered_for_auditor(monkeypatch):
    client = _make_menu_client(monkeypatch, role_name="auditor")
    r = client.get("/api/menu")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 2
    assert data["role"] == "auditor"
    ids = [m["id"] for m in data["menu"]]
    assert "dashboard" in ids
    assert "patient-qc" in ids
    assert "config" not in ids
    assert "oracle-status" not in ids
    assert "system-logs" not in ids


def test_get_menu_production_filters_debug(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    client = _make_menu_client(monkeypatch, role_name="admin")
    r = client.get("/api/menu")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["menu"]]
    assert "debug" not in ids
    assert "dashboard" in ids
    assert "oracle-status" not in ids


def test_get_menu_development_includes_debug_for_admin(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    client = _make_menu_client(monkeypatch, role_name="admin")
    r = client.get("/api/menu")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["menu"]]
    assert "debug" in ids
    assert "oracle-status" not in ids


def test_menu_all_requires_admin(monkeypatch):
    client = _make_menu_client(monkeypatch, role_name="auditor")
    r = client.get("/api/menu/all")
    assert r.status_code == 403


def test_menu_all_admin_ok(monkeypatch):
    client = _make_menu_client(monkeypatch, role_name="admin")
    r = client.get("/api/menu/all")
    assert r.status_code == 200
    data = r.json()
    assert data["schema_version"] == 2
    assert len(data["catalog"]) == 17
    assert "menus" in data


def test_menu_service_is_deprecated_stub():
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from app.services import menu_service

        assert menu_service.MENU_CONFIG == {}
        assert menu_service.get_menu_for_role("admin") == []
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)
