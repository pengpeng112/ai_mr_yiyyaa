import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.demo_support.dataset import AUDIT_TYPES, build_demo_config
from app.demo_support.mock_server import create_dify_app, create_relay_app
from app.schemas import AuditTypeConfig, DataSourceConfig
from app.services.isolated_mode import (
    IsolatedModeError,
    assert_isolated_runtime_paths,
    assert_loopback_url,
    assert_demo_runtime_allowed,
    validate_isolated_config,
)


def _enable_isolated(monkeypatch, tmp_path, run_id="unit-demo"):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    monkeypatch.setenv("DEMO_RUN_ID", run_id)
    monkeypatch.setenv("DEMO_WORKSPACE_ROOT", str(tmp_path))
    paths = (
        tmp_path / "data" / "demo" / run_id,
        tmp_path / "config" / "demo" / run_id,
        tmp_path / "logs" / "demo" / run_id,
    )
    monkeypatch.setenv("DATA_DIR", str(paths[0]))
    monkeypatch.setenv("CONFIG_DIR", str(paths[1]))
    monkeypatch.setenv("CONFIG_TEMPLATE_PATH", str(paths[1] / "config.json.template"))
    monkeypatch.setenv("LOG_DIR", str(paths[2]))
    return paths


def test_isolated_paths_and_external_url_fail_closed(monkeypatch, tmp_path):
    data_dir, config_dir, log_dir = _enable_isolated(monkeypatch, tmp_path)
    assert_isolated_runtime_paths(str(data_dir), str(config_dir), str(log_dir))
    assert_loopback_url("http://127.0.0.1:18081/v1", "dify")
    with pytest.raises(IsolatedModeError):
        assert_loopback_url("http://10.10.8.84:8000", "production")
    with pytest.raises(IsolatedModeError):
        assert_loopback_url("http://host.docker.internal:18081", "host gateway")
    with pytest.raises(IsolatedModeError):
        assert_isolated_runtime_paths(str(tmp_path / "data"), str(config_dir), str(log_dir))


def test_demo_mode_requires_isolation_and_is_forbidden_in_production(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("TEST_ISOLATED_MODE", raising=False)
    with pytest.raises(IsolatedModeError):
        assert_demo_runtime_allowed()

    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(IsolatedModeError):
        assert_demo_runtime_allowed()

    monkeypatch.setenv("ENVIRONMENT", "development")
    assert_demo_runtime_allowed()


def test_demo_config_has_six_valid_audit_types_and_no_external_target(monkeypatch, tmp_path):
    _enable_isolated(monkeypatch, tmp_path)
    config = build_demo_config()
    validate_isolated_config(config)
    assert DataSourceConfig.model_validate(config["data_source"]).type == "fixture"
    parsed = [AuditTypeConfig.model_validate(item) for item in config["audit_types"]]
    assert [item.code for item in parsed] == [item["code"] for item in AUDIT_TYPES]
    assert len(parsed) == 6


def test_mock_dify_contract_and_failure_scenarios(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    client = TestClient(create_dify_app())
    body = {"inputs": {"mr_txt": "SYNTHETIC TEST DATA", "mr_type": "progress_vs_nursing"}, "response_mode": "blocking", "user": "test"}
    success = client.post("/v1/workflows/run", json=body, headers={"X-Demo-Audit-Type": "progress_vs_nursing"})
    assert success.status_code == 200
    parsed = json.loads(success.json()["data"]["outputs"]["aa"])
    assert len(parsed["dimensions"]) == 6
    assert parsed["audit_summary"]["overall_conclusion"].startswith("SYNTHETIC TEST DATA")
    empty = client.post("/v1/workflows/run", json=body, headers={"X-Demo-Scenario": "empty_outputs"})
    assert empty.json()["data"]["outputs"] == {}
    failed = client.post("/v1/workflows/run", json=body, headers={"X-Demo-Scenario": "http_500"})
    assert failed.status_code == 500


def test_mock_relay_checks_hmac_and_closes_h5_route(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("DEMO_RELAY_SECRET", "test-secret")
    monkeypatch.setenv("DEMO_APP_BASE_URL", "http://127.0.0.1:18080")
    client = TestClient(create_relay_app(), follow_redirects=False)
    payload = {"alert_id": 42, "detail_url": "http://127.0.0.1:18082/qc-detail/42?token=t"}
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = "1786540000"
    signature = hmac.new(b"test-secret", timestamp.encode("utf-8") + b"." + raw, hashlib.sha256).hexdigest()
    response = client.post(
        "/qc-record-alert",
        content=raw,
        headers={"Content-Type": "application/json", "X-Relay-Timestamp": timestamp, "X-Relay-Signature": signature},
    )
    assert response.status_code == 200
    assert response.json()["synthetic"] is True
    assert client.post("/qc-record-alert", content=raw).status_code == 401
    redirect = client.get("/qc-detail/42?token=t")
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "http://127.0.0.1:18080/mobile/qc/42?token=t"


def test_isolated_dify_and_relay_disable_redirects(monkeypatch, tmp_path):
    _enable_isolated(monkeypatch, tmp_path)
    dify_kwargs = {}

    def dify_post(*_args, **kwargs):
        dify_kwargs.update(kwargs)
        return SimpleNamespace(status_code=302)

    monkeypatch.setattr("app.dify_pusher.requests.post", dify_post)
    from app.dify_pusher import test_dify_connection as check_dify_connection

    result = check_dify_connection({
        "base_url": "http://127.0.0.1:18081/v1",
        "api_key": "demo",
        "workflow_input_variable": "mr_txt",
    })
    assert result["status"] == "down"
    assert dify_kwargs["allow_redirects"] is False

    relay_kwargs = {}

    def relay_post(*_args, **kwargs):
        relay_kwargs.update(kwargs)
        return SimpleNamespace(status_code=302, content=b"")

    monkeypatch.setattr("app.services.relay_alert_service.requests.post", relay_post)
    from app.services.relay_alert_service import RelayAlertService

    alert = MagicMock()
    alert.payload_json = "{}"
    alert.retry_count = 0
    service = RelayAlertService(MagicMock(), {"relay_alert": {
        "enabled": True,
        "base_url": "http://127.0.0.1:18082",
        "endpoint": "/qc-record-alert",
        "secret_key": "demo-secret",
    }})
    assert service.send_one(alert) is False
    assert relay_kwargs["allow_redirects"] is False
