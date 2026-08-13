from app.routers.health import live_health, overall_health
from app.schemas import AuditTypeConfig


def test_live_health_does_not_require_dependencies():
    result = live_health()
    assert result["status"] == "alive"
    assert "timestamp" in result


def test_anonymous_overall_health_does_not_run_deep_checks(monkeypatch):
    def fail_if_called(*, force_refresh=False):
        raise AssertionError("anonymous health must not run dependency checks")

    monkeypatch.setattr("app.routers.health._get_cached_overall_health", fail_if_called)
    result = overall_health(force_refresh=True)
    assert result.status == "alive"


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
