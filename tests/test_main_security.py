from app import main


def test_api_docs_disabled_by_default_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("ENABLE_API_DOCS", raising=False)
    assert main._api_docs_enabled() is False


def test_api_docs_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ENABLE_API_DOCS", "true")
    assert main._api_docs_enabled() is True

