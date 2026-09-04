"""census 非 Oracle 数据源 → 400 契约测试（037 RP-E / P-005）。

能力不支持是客户端可纠正的 400，不再是 500；
真正的查询失败（RuntimeError）仍 500。
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace

import pytest


class _DummyDb:
    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return SimpleNamespace(name="admin")


def test_t1_service_raises_value_error_for_fixture(monkeypatch):
    from app.services.patient_census_service import load_patient_census

    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    with pytest.raises(ValueError, match="Oracle"):
        load_patient_census({"data_source": {"type": "fixture"}}, "discharged", None, [], 10, masking_enabled=True)


def _make_client(monkeypatch, tmp_path, data_source_type: str):
    from app.routers import patients as patients_router
    from app import auth as auth_module
    from app import permissions as permissions_module
    from app import database as database_module

    cfg = {"data_source": {"type": data_source_type}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(patients_router, "load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))

    app = FastAPI()
    app.include_router(patients_router.router, prefix="/api/patients")

    class _FakeUser:
        id = 1
        role_id = 1

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[database_module.get_db] = lambda: _DummyDb()
    monkeypatch.setattr(permissions_module, "require_permission", lambda _perm: lambda: _FakeUser())
    return TestClient(app)


def test_t2_census_fixture_returns_400(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    client = _make_client(monkeypatch, tmp_path, "fixture")
    r = client.get("/api/patients/census")
    assert r.status_code == 400, r.text


def test_t3_summary_and_metadata_fixture_return_400(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    client = _make_client(monkeypatch, tmp_path, "fixture")
    assert client.get("/api/patients/census/summary").status_code == 400
    assert client.get("/api/patients/census/metadata").status_code == 400


def test_t4_oracle_runtime_error_still_500(monkeypatch, tmp_path):
    """真查询故障不得被误改为 400。"""
    from app.routers import patients as patients_router

    client = _make_client(monkeypatch, tmp_path, "oracle")
    with monkeypatch.context() as m:
        m.setattr(
            patients_router, "load_patient_census",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ORA-12170 connection timeout")),
        )
        r = client.get("/api/patients/census")
        assert r.status_code == 500
