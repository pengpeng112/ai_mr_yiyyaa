"""Tests for runtime-summary HTTP router — Phase 2.5 hardening.

Tests the GET /api/config/runtime-summary endpoint via FastAPI TestClient
with mocked config and auth overrides. No real config.json, database,
or network access.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _base_config() -> dict:
    return {
        "data_source": {"type": "oracle"},
        "scheduler_daily": {
            "enabled": True,
            "cron": "0 10 * * *",
            "schedule_mode": "daily",
            "daily_time": "10:00",
            "audit_run_mode": "daily_increment",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": ["020103"],
        },
        "scheduler_discharge": {
            "enabled": True,
            "cron": "13 14 * * *",
            "schedule_mode": "daily",
            "daily_time": "14:13",
            "audit_run_mode": "discharge_final",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": ["020103"],
        },
        "dify": {
            "base_url": "http://example.com/v1",
            "api_key_enc": "enc",
            "workflow_input_variable": "mr_txt",
        },
        "audit_types": [
            {
                "code": "progress_vs_nursing",
                "name": "病程 vs 护理",
                "enabled": True,
                "default_for_schedule": True,
                "sources": {"primary": {"type": "sql", "required": True, "query_sql": "SELECT 1 FROM dual"}},
                "payload": {"builder": "generic_multi_source"},
                "dify": {"base_url": "http://dify/v1", "api_key_enc": "k", "workflow_input_variable": "mr_txt"},
            },
        ],
    }


class _DummyDb:
    def __init__(self, role_name: str = "admin"):
        self.role_name = role_name

    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return SimpleNamespace(name=self.role_name)


def _make_client(monkeypatch, role_name: str = "admin", config: dict | None = None) -> TestClient:
    cfg = config or _base_config()
    monkeypatch.setattr("app.routers.config.load_config", lambda: cfg)

    from app.routers import config as config_router_module
    from app import database as database_module
    from app import auth as auth_module

    app = FastAPI()
    app.include_router(config_router_module.router, prefix="/api/config")

    class _FakeUser:
        id = 1
        role_id = 1

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[database_module.get_db] = lambda: _DummyDb(role_name=role_name)

    return TestClient(app)


# ---- basic structure ---------------------------------------------------------


def test_runtime_summary_returns_200(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    assert response.status_code == 200


def test_runtime_summary_has_top_level_keys(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    for key in ("run_modes", "schedulers", "dept_scopes", "audit_types", "warnings", "meta"):
        assert key in data, f"Missing top-level key: {key}"


def test_runtime_summary_no_query_sql(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    def _has_key(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return True
            for v in obj.values():
                if _has_key(v, key):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if _has_key(item, key):
                    return True
        return False
    assert not _has_key(data, "query_sql"), "query_sql key found in response"


def test_runtime_summary_no_secrets(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    def _has_key(obj, key):
        if isinstance(obj, dict):
            if key in obj:
                return True
            for v in obj.values():
                if _has_key(v, key):
                    return True
        elif isinstance(obj, list):
            for item in obj:
                if _has_key(item, key):
                    return True
        return False
    for secret_field in ("api_key", "api_key_enc", "password", "password_enc", "secret_key", "secret_key_enc"):
        assert not _has_key(data, secret_field), f"Secret field leaked: {secret_field}"


# ---- run_modes ---------------------------------------------------------------


def test_runtime_summary_run_modes_structure(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    modes = data["run_modes"]
    for mode in ("daily_increment", "discharge_final", "manual", "precheck"):
        assert mode in modes
        assert "calls_dify" in modes[mode]
        assert "writes_push_log" in modes[mode]


# ---- schedulers --------------------------------------------------------------


def test_runtime_summary_schedulers_structure(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    for key in ("scheduler_daily", "scheduler_discharge"):
        assert key in data["schedulers"]
        sched = data["schedulers"][key]
        assert "enabled" in sched
        assert "audit_type_codes" in sched
        assert "dept_filter" in sched


# ---- audit_types -------------------------------------------------------------


def test_runtime_summary_audit_types_structure(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    ats = data["audit_types"]
    assert len(ats) >= 1
    at = ats[0]
    assert "code" in at
    assert "sources" in at
    assert isinstance(at["sources"], list)
    assert "dify_target" in at
    assert "flags" in at


# ---- warnings ----------------------------------------------------------------


def test_runtime_summary_warnings_are_list(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    assert isinstance(data["warnings"], list)


# ---- meta --------------------------------------------------------------------


def test_runtime_summary_meta_fields(monkeypatch):
    client = _make_client(monkeypatch)
    response = client.get("/api/config/runtime-summary")
    data = response.json()
    meta = data["meta"]
    assert meta["readonly"] is True
    assert meta["sql_included"] is False


# ---- config with secrets -----------------------------------------------------


def test_runtime_summary_strips_injected_secrets(monkeypatch):
    cfg = _base_config()
    cfg["dify"]["api_key"] = "secret-in-config"
    cfg["oracle"] = {"password_enc": "secret-pwd"}
    client = _make_client(monkeypatch, config=cfg)
    response = client.get("/api/config/runtime-summary")
    text = response.text
    assert "secret-in-config" not in text
    assert "secret-pwd" not in text
