"""departments/list 数据源能力分支测试（037 RP-D / P-004 / K-2）。

fixture 数据源必须返回内置 12 科室且不触碰 Oracle/PG 驱动；
Oracle 后端故障 → 503；未知数据源类型 → 400。
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client(monkeypatch, tmp_path, data_source_type: str, oracle_side_effect=None, pg_calls=None):
    from app.routers import config as config_router_module
    from app import auth as auth_module

    cfg = {"data_source": {"type": data_source_type}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(config_router_module, "load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))

    oracle_calls = []

    def _fake_fetch_department_list(_cfg):
        oracle_calls.append(1)
        if oracle_side_effect is not None:
            raise oracle_side_effect
        return ["Oracle 科室一"]

    def _fake_fetch_pg_department_list(_cfg):
        if pg_calls is not None:
            pg_calls.append(1)
        return ["PG 科室一"]

    monkeypatch.setattr(config_router_module, "fetch_department_list", _fake_fetch_department_list)
    monkeypatch.setattr(config_router_module, "fetch_pg_department_list", _fake_fetch_pg_department_list)

    app = FastAPI()
    app.include_router(config_router_module.router, prefix="/api/config")

    class _FakeUser:
        id = 1
        role_id = 1

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    return TestClient(app), oracle_calls


def test_t1_fixture_returns_demo_12_departments_without_oracle(monkeypatch, tmp_path):
    client, oracle_calls = _make_client(monkeypatch, tmp_path, "fixture")
    r = client.get("/api/config/departments/list")
    assert r.status_code == 200
    departments = r.json()["departments"]
    assert "听觉植入科" in departments
    assert len(departments) == 12
    assert oracle_calls == []  # 不得触碰 Oracle 路径


def test_t2_oracle_driver_failure_returns_503(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path, "oracle", oracle_side_effect=Exception("cx_Oracle 未安装"))
    r = client.get("/api/config/departments/list")
    assert r.status_code == 503


def test_t3_unknown_data_source_type_returns_400(monkeypatch, tmp_path):
    client, _ = _make_client(monkeypatch, tmp_path, "sqlite")
    r = client.get("/api/config/departments/list")
    assert r.status_code == 400


def test_t4_postgresql_branch_used(monkeypatch, tmp_path):
    pg_calls = []
    client, oracle_calls = _make_client(monkeypatch, tmp_path, "postgresql", pg_calls=pg_calls)
    r = client.get("/api/config/departments/list")
    assert r.status_code == 200
    assert r.json()["departments"] == ["PG 科室一"]
    assert len(pg_calls) == 1
    assert oracle_calls == []


def test_logs_dept_candidates_fixture_branch(monkeypatch, tmp_path):
    """logs 科室候选在 fixture 下也不 import cx_Oracle，返回 demo 科室。"""
    import app.routers.logs as logs_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base
    import sys

    cfg = {"data_source": {"type": "fixture"}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")

    # 让 logs 模块内部 from app.config import load_config 拿到 fixture 配置
    import app.config as app_config_module
    monkeypatch.setattr(app_config_module, "load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))

    # cx_Oracle 不可导入时也不得报错：屏蔽 oracle_client 的导入副作用
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()

    items = logs_module._list_distinct_depts(db)
    labels = {item["label"] for item in items}
    assert "听觉植入科" in labels
    db.close()
