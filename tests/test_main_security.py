from app import main


def test_api_docs_disabled_by_default_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    assert main._api_docs_enabled() is False


def test_api_docs_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    assert main._api_docs_enabled() is True


def test_cors_uses_app_env_alias_and_rejects_wildcard_in_production(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    assert main._get_cors_origins() == []


def test_cors_environment_alias_conflict_fails_closed(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")

    import pytest

    with pytest.raises(RuntimeError, match="冲突"):
        main._get_cors_origins()


def test_anonymous_health_is_safe_summary():
    from app.routers import health

    payload = health.overall_health().model_dump()

    assert payload["status"] == "alive"
    assert set(payload) == {"status", "timestamp"}
    assert "/ready" in {route.path for route in health.router.routes}
