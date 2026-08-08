from app.routers.health import live_health, overall_health
from app.schemas import AuditTypeConfig


def test_live_health_does_not_require_dependencies():
    result = live_health()
    assert result["status"] == "alive"
    assert "timestamp" in result


def test_anonymous_overall_health_cannot_force_refresh(monkeypatch):
    seen = []

    def fake_cached(*, force_refresh=False):
        seen.append(force_refresh)
        return {"status": "healthy", "timestamp": "2026-07-15", "components": {}}

    monkeypatch.setattr("app.routers.health._get_cached_overall_health", fake_cached)
    overall_health(force_refresh=True)
    assert seen == [False]


def test_builder_capability_rejects_missing_sources():
    raw = {
        "code": "frontpage_surgery_diagnosis_vs_first_progress",
        "name": "custom",
        "sources": {"progress": {"name": "progress", "query_sql": "select 1"}},
        "payload": {"builder": "frontpage_surgery_first_progress"},
    }
    try:
        AuditTypeConfig.model_validate(raw)
    except ValueError as exc:
        assert "missing sources" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("builder/source mismatch must be rejected")
