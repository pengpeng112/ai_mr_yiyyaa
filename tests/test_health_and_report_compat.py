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


def test_live_health_payload_contains_no_diagnostics():
    """匿名 /live 只含存活状态与时间戳，不得出现 ORA/IP/SQL/凭据类内容。"""
    result = live_health()
    assert set(result.keys()) == {"status", "timestamp"}
    blob = str(result).lower()
    for marker in ("ora-", "10.10.", "select ", "dsn=", "password", "host="):
        assert marker not in blob


def test_ready_health_enforces_permission_dependency():
    """深度就绪 /ready 必须挂 view_scheduler 权限依赖，不得匿名暴露诊断。"""
    import inspect

    from fastapi.params import Depends

    from app.routers import health

    dep = inspect.signature(health.ready_health).parameters["_user"].default
    assert isinstance(dep, Depends)
    closure = getattr(dep.dependency, "__closure__", None)
    assert closure is not None
    assert "view_scheduler" in [cell.cell_contents for cell in closure]
