"""配置写端点部分更新契约测试（037 RP-B / P-002）。

核心断言：
- 空 JSON `{}` → 422，磁盘配置不变（不再被模型默认值整段覆盖）；
- 部分字段保存 → 未提交字段保留现有值；
- 完整表单保存 → 行为与旧全量语义一致；
- relay-alert 只提交 alert_dept_filter 的部分保存红线不回退。
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from types import SimpleNamespace


class _DummyDb:
    def query(self, _model):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return SimpleNamespace(name="admin")


def _make_client(monkeypatch, tmp_path, initial: dict) -> TestClient:
    from app.routers import config as config_router_module
    from app import database as database_module
    from app import auth as auth_module

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(initial, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load() -> dict:
        return json.loads(cfg_file.read_text(encoding="utf-8"))

    def _update(section: str, data: dict) -> dict:
        cfg = _load()
        cfg[section] = data
        cfg_file.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        return cfg[section]

    monkeypatch.setattr(config_router_module, "load_config", _load)
    monkeypatch.setattr(config_router_module, "update_section", _update)
    monkeypatch.setattr(config_router_module, "reset_oracle_pool", lambda: None)
    monkeypatch.setattr(
        config_router_module, "update_scheduler",
        lambda enabled, cron, run_mode, job_id=None: {"applied": True, "message": "ok"},
    )

    app = FastAPI()
    app.include_router(config_router_module.router, prefix="/api/config")

    class _FakeUser:
        id = 1
        role_id = 1
        username = "admin"

    app.dependency_overrides[auth_module.get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[database_module.get_db] = lambda: _DummyDb()
    return TestClient(app), _load


def test_t1_privacy_empty_body_rejected_and_unchanged(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "privacy_masking": {"enabled": True, "mask_name": True, "mask_id_card": True, "mask_address": True, "mask_phone": True},
    })
    r = client.post("/api/config/privacy-masking", json={})
    assert r.status_code == 422
    assert load()["privacy_masking"]["enabled"] is True


def test_t2_privacy_partial_merge(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "privacy_masking": {"enabled": True, "mask_name": True, "mask_id_card": True, "mask_address": True, "mask_phone": True},
    })
    r = client.post("/api/config/privacy-masking", json={"mask_phone": False})
    assert r.status_code == 200
    cfg = load()["privacy_masking"]
    assert cfg["enabled"] is True
    assert cfg["mask_phone"] is False
    assert cfg["mask_name"] is True


def test_t3_scheduler_empty_body_rejected_enabled_kept(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "scheduler": {"enabled": False, "cron": "0 6 * * *", "schedule_mode": "daily", "daily_time": "06:00",
                      "interval_value": 10, "interval_unit": "minutes", "audit_run_mode": "daily_increment",
                      "audit_type_codes": [], "dept_filter": None},
    })
    r = client.post("/api/config/scheduler", json={})
    assert r.status_code == 422
    assert load()["scheduler"]["enabled"] is False


def test_t3b_scheduler_partial_keeps_cron_and_enabled(monkeypatch, tmp_path):
    """只改 audit_type_codes：排程字段未出现时不得用模型默认 06:00 重算 cron。"""
    client, load = _make_client(monkeypatch, tmp_path, {
        "scheduler": {"enabled": False, "cron": "30 9 * * *", "schedule_mode": "daily", "daily_time": "09:30",
                      "interval_value": 10, "interval_unit": "minutes", "audit_run_mode": "daily_increment",
                      "audit_type_codes": [], "dept_filter": None},
    })
    r = client.post("/api/config/scheduler", json={"audit_type_codes": []})
    assert r.status_code == 200
    cfg = load()["scheduler"]
    assert cfg["cron"] == "30 9 * * *"
    assert cfg["enabled"] is False


def test_t4_oracle_empty_body_rejected_host_kept(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "oracle": {"host": "127.0.0.1", "port": 1521, "service_name": "orcl", "username": "u", "password_enc": "enc-1"},
    })
    r = client.post("/api/config/oracle", json={})
    assert r.status_code == 422
    assert load()["oracle"]["host"] == "127.0.0.1"


def test_t5_oracle_partial_port_only(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "oracle": {"host": "127.0.0.1", "port": 1521, "service_name": "orcl", "username": "u", "password_enc": "enc-1"},
    })
    r = client.post("/api/config/oracle", json={"port": 1522})
    assert r.status_code == 200
    cfg = load()["oracle"]
    assert cfg["host"] == "127.0.0.1"
    assert cfg["port"] == 1522
    assert cfg["password_enc"] == "enc-1"


def test_t6_push_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "push": {"interval_ms": 800, "max_retry": 3, "batch_size": 50, "parallel_workers": 4},
    })
    r = client.post("/api/config/push", json={})
    assert r.status_code == 422
    assert load()["push"]["interval_ms"] == 800


def test_t7_full_privacy_body_still_overwrites(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "privacy_masking": {"enabled": True, "mask_name": True, "mask_id_card": True, "mask_address": True, "mask_phone": True},
    })
    body = {"enabled": False, "mask_name": False, "mask_id_card": True, "mask_address": False, "mask_phone": True}
    r = client.post("/api/config/privacy-masking", json=body)
    assert r.status_code == 200
    assert load()["privacy_masking"] == body


def test_t8_relay_dept_filter_only_partial_save(monkeypatch, tmp_path):
    """AGENTS 红线：relay 只提交 alert_dept_filter 不得清空其余配置。"""
    relay_cfg = {
        "enabled": True,
        "base_url": "http://relay.internal:3000",
        "endpoint": "/qc-record-alert",
        "secret_key_enc": "enc-secret",
        "severity_levels": ["high"],
        "nurse_heads": {"科一": "13800000000"},
        "alert_dept_filter": [],
    }
    client, load = _make_client(monkeypatch, tmp_path, {"relay_alert": dict(relay_cfg)})
    r = client.post("/api/config/relay-alert", json={"alert_dept_filter": ["听觉植入科"]})
    assert r.status_code == 200
    cfg = load()["relay_alert"]
    assert cfg["alert_dept_filter"] == ["听觉植入科"]
    assert cfg["enabled"] is True
    assert cfg["base_url"] == "http://relay.internal:3000"
    assert cfg["secret_key_enc"] == "enc-secret"
    assert cfg["nurse_heads"] == {"科一": "13800000000"}


def test_t8b_relay_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "relay_alert": {"enabled": True, "base_url": "http://relay.internal:3000"},
    })
    r = client.post("/api/config/relay-alert", json={})
    assert r.status_code == 422
    assert load()["relay_alert"]["enabled"] is True


def test_dify_partial_keeps_targets_and_key(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "dify": {
            "base_url": "http://dify.internal/v1",
            "api_key_enc": "enc-key",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "user_identifier": "med-audit-system",
            "timeout_seconds": 90,
            "targets": [{"name": "n1", "base_url": "http://dify.internal/v1", "api_key_enc": "enc-key", "enabled": True}],
            "target_strategy": "round_robin",
        },
    })
    r = client.post("/api/config/dify", json={"timeout_seconds": 120})
    assert r.status_code == 200
    cfg = load()["dify"]
    assert cfg["timeout_seconds"] == 120
    assert cfg["base_url"] == "http://dify.internal/v1"
    assert cfg["api_key_enc"] == "enc-key"
    assert len(cfg["targets"]) == 1
    assert cfg["target_strategy"] == "round_robin"


def test_dify_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "dify": {"base_url": "http://dify.internal/v1", "api_key_enc": "enc-key"},
    })
    r = client.post("/api/config/dify", json={})
    assert r.status_code == 422
    assert load()["dify"]["base_url"] == "http://dify.internal/v1"


def test_data_source_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {"data_source": {"type": "postgresql"}})
    r = client.post("/api/config/data-source", json={})
    assert r.status_code == 422
    assert load()["data_source"]["type"] == "postgresql"


def test_emr_vastbase_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "emr_vastbase": {"enabled": True, "host": "10.10.8.177", "port": 5432, "database": "jhemr",
                          "username": "aizk_user", "password_enc": "enc-1", "schema": "jhemr"},
    })
    r = client.post("/api/config/emr-vastbase", json={})
    assert r.status_code == 422
    cfg = load()["emr_vastbase"]
    assert cfg["host"] == "10.10.8.177"
    assert cfg["password_enc"] == "enc-1"


def test_departments_and_notify_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "departments": {"mode": "include", "list": ["内科"]},
        "notify": {"channels": [{"type": "webhook", "enabled": True, "config": {"url": "http://x"}}]},
    })
    assert client.post("/api/config/departments", json={}).status_code == 422
    assert client.post("/api/config/notify", json={}).status_code == 422
    assert load()["departments"] == {"mode": "include", "list": ["内科"]}
    assert len(load()["notify"]["channels"]) == 1


def test_postgresql_empty_body_rejected(monkeypatch, tmp_path):
    client, load = _make_client(monkeypatch, tmp_path, {
        "postgresql": {"host": "127.0.0.1", "port": 5432, "database": "db", "username": "u", "password_enc": "enc-1"},
    })
    r = client.post("/api/config/postgresql", json={})
    assert r.status_code == 422
    assert load()["postgresql"]["host"] == "127.0.0.1"
