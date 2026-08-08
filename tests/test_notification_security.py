import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import main
from app.routers import notify as notify_router
from app.notifier import test_notify_channel as run_test_notify_channel
from app.security_utils import public_error_message, validate_test_notification_target


def test_notification_target_rejects_private_ip_and_credentials():
    with pytest.raises(ValueError, match="禁止访问"):
        validate_test_notification_target("webhook", {"url": "http://127.0.0.1:8080/hook"})
    with pytest.raises(ValueError, match="用户凭据"):
        validate_test_notification_target("webhook", {"url": "https://user:pass@example.com/hook"})


def test_notification_target_resolves_all_addresses(monkeypatch):
    monkeypatch.setattr(
        "app.security_utils._resolved_addresses",
        lambda host, port: {__import__("ipaddress").ip_address("8.8.8.8")},
    )
    validate_test_notification_target("webhook", {"url": "https://example.test/hook"})

    monkeypatch.setattr(
        "app.security_utils._resolved_addresses",
        lambda host, port: {__import__("ipaddress").ip_address("10.0.0.5")},
    )
    with pytest.raises(ValueError, match="禁止访问"):
        validate_test_notification_target("webhook", {"url": "https://example.test/hook"})


def test_allowlisted_internal_host_is_allowed(monkeypatch):
    monkeypatch.setenv("NOTIFY_TEST_ALLOWED_HOSTS", "relay.internal")
    validate_test_notification_target("webhook", {"url": "http://relay.internal/qc"})


def test_notifier_validates_before_sender(monkeypatch):
    sender = SimpleNamespace(send=lambda *args: pytest.fail("private target must not send"))
    monkeypatch.setitem(__import__("app.notifier", fromlist=["CHANNEL_REGISTRY"]).CHANNEL_REGISTRY, "webhook", sender)
    result = run_test_notify_channel({"type": "webhook", "config": {"url": "http://192.168.1.10/hook"}})
    assert result["success"] is False
    assert "禁止访问" in result["message"]


def test_public_error_message_filters_internal_details():
    assert public_error_message(RuntimeError("ORA-00942 table secret_users"), "fallback") == "fallback"
    assert public_error_message(RuntimeError("数据库暂时不可用"), "fallback") == "数据库暂时不可用"
    assert public_error_message(RuntimeError("x" * 241), "fallback") == "fallback"


def test_http_exception_handler_filters_sensitive_string_detail():
    response = asyncio.run(
        main.http_exception_handler(
            None,
            HTTPException(status_code=500, detail="ORA-00942: SELECT * FROM secret_users"),
        )
    )
    assert response.status_code == 500
    assert response.body.decode("utf-8") == '{"code":"HTTP_500","message":"请求处理失败"}'


def test_notify_test_is_disabled_by_default_in_production(monkeypatch):
    monkeypatch.delenv("NOTIFY_TEST_ENABLED", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert notify_router._notify_test_enabled() is False
    monkeypatch.setenv("NOTIFY_TEST_ENABLED", "true")
    assert notify_router._notify_test_enabled() is True
