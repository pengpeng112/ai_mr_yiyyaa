"""12 科室脱敏合成测试环境的硬隔离门禁。"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


TRUTHY = {"1", "true", "yes", "on"}
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


class IsolatedModeError(RuntimeError):
    """隔离环境配置违反硬门禁。"""


def isolated_mode_enabled() -> bool:
    return str(os.getenv("TEST_ISOLATED_MODE", "")).strip().lower() in TRUTHY


def demo_mode_enabled() -> bool:
    return str(os.getenv("DEMO_MODE", "")).strip().lower() in TRUTHY


def assert_demo_runtime_allowed() -> None:
    """DEMO_MODE 只能运行在显式隔离、非生产的合成环境。"""
    if not demo_mode_enabled():
        return
    environment = str(os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or "development").strip().lower()
    if environment in {"production", "prod"}:
        raise IsolatedModeError("DEMO_MODE is forbidden in production")
    if not isolated_mode_enabled():
        raise IsolatedModeError("DEMO_MODE requires TEST_ISOLATED_MODE")


def _resolved(path: str) -> Path:
    return Path(path).expanduser().resolve()


def assert_isolated_runtime_paths(data_dir: str, config_dir: str, log_dir: str) -> None:
    if not isolated_mode_enabled():
        return
    run_id = str(os.getenv("DEMO_RUN_ID", "")).strip()
    workspace = str(os.getenv("DEMO_WORKSPACE_ROOT", "")).strip()
    if not run_id or not workspace:
        raise IsolatedModeError("TEST_ISOLATED_MODE requires DEMO_RUN_ID and DEMO_WORKSPACE_ROOT")
    expected = {
        "DATA_DIR": _resolved(str(Path(workspace) / "data" / "demo" / run_id)),
        "CONFIG_DIR": _resolved(str(Path(workspace) / "config" / "demo" / run_id)),
        "LOG_DIR": _resolved(str(Path(workspace) / "logs" / "demo" / run_id)),
    }
    actual = {
        "DATA_DIR": _resolved(data_dir),
        "CONFIG_DIR": _resolved(config_dir),
        "LOG_DIR": _resolved(log_dir),
    }
    for key, expected_path in expected.items():
        if actual[key] != expected_path:
            raise IsolatedModeError(f"{key} must be isolated under demo/{run_id}: {actual[key]}")


def assert_loopback_url(value: str, label: str) -> None:
    if not isolated_mode_enabled() or not str(value or "").strip():
        return
    parsed = urlparse(str(value).strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in LOOPBACK_HOSTS:
        raise IsolatedModeError(f"{label} must use an isolated loopback/demo host, got: {value}")


def assert_loopback_host(value: str, label: str) -> None:
    if not isolated_mode_enabled() or not str(value or "").strip():
        return
    if str(value).strip().lower() not in LOOPBACK_HOSTS:
        raise IsolatedModeError(f"{label} must be empty or loopback in isolated mode")


def assert_fixture_source_allowed() -> None:
    if not isolated_mode_enabled():
        raise IsolatedModeError("fixture data source is only available in TEST_ISOLATED_MODE")


def validate_isolated_config(config: dict) -> None:
    """Fail closed before any Oracle/Vastbase/Dify/Relay/notify connection is attempted."""
    if not isolated_mode_enabled():
        return
    if str((config.get("data_source") or {}).get("type") or "").strip() != "fixture":
        raise IsolatedModeError("isolated mode requires data_source.type=fixture")
    if str(os.getenv("ENABLE_SCHEDULER", "true")).lower() not in {"false", "0", "no", "off"}:
        raise IsolatedModeError("isolated mode requires ENABLE_SCHEDULER=false")

    for section in ("oracle", "postgresql", "emr_vastbase"):
        assert_loopback_host((config.get(section) or {}).get("host", ""), f"{section}.host")

    dify = config.get("dify") or {}
    assert_loopback_url(dify.get("base_url", ""), "dify.base_url")
    for target in dify.get("targets", []) or []:
        assert_loopback_url(target.get("base_url", ""), "dify.targets[].base_url")
    for item in config.get("audit_types", []) or []:
        audit_dify = item.get("dify") or {}
        assert_loopback_url(audit_dify.get("base_url", ""), f"audit_types.{item.get('code')}.dify.base_url")
        for target in audit_dify.get("targets", []) or []:
            assert_loopback_url(target.get("base_url", ""), "audit_type.dify.targets[].base_url")

    relay = config.get("relay_alert") or {}
    assert_loopback_url(relay.get("base_url", ""), "relay_alert.base_url")
    assert_loopback_url((relay.get("detail_page") or {}).get("external_base_url", ""), "relay_alert.detail_page.external_base_url")

    notify = config.get("notify") or {}
    if bool(notify.get("enabled")):
        raise IsolatedModeError("notify.enabled must be false in isolated mode")
    for key in ("webhook_url", "url", "base_url"):
        assert_loopback_url(notify.get(key, ""), f"notify.{key}")
