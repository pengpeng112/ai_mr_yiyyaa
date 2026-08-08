"""003 工作包 F/B/C/D/E 关键回归（不含生产写）。"""

from __future__ import annotations

import time
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, PushLog
from app.services.high_risk_semantic_shadow import (
    apply_semantic_shadow,
    evaluate_semantic_high_risk_dim,
    semantic_enforce_enabled,
)
from app.services.push_log_supersede import mark_daily_logs_superseded
from app.services.dify_json_parser import _load_json_with_tolerance
from app.emr_vastbase_client import (
    VastbaseQueryError,
    _classify_vastbase_error,
    _is_transient_db_error,
)
from app.routers import health as health_router


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_live_health_has_no_external_side_effects(monkeypatch):
    called = {"db": 0}

    def boom():
        called["db"] += 1
        raise AssertionError("live must not call db")

    monkeypatch.setattr(health_router, "test_app_db_connection", boom)
    result = health_router.live_health()
    assert result["status"] == "alive"
    assert called["db"] == 0


def test_deep_health_cache_ttl(monkeypatch):
    calls = {"n": 0}

    def fake_compute():
        calls["n"] += 1
        from app.schemas import HealthResponse
        return HealthResponse(
            status="healthy",
            timestamp=datetime.now(),
            components={"app_db": {"status": "up"}},
        )

    monkeypatch.setattr(health_router, "_compute_overall_health", fake_compute)
    health_router._deep_health_cache = None
    health_router._deep_health_cache_at = 0.0
    a = health_router._get_cached_overall_health(force_refresh=True)
    b = health_router._get_cached_overall_health(force_refresh=False)
    assert calls["n"] == 1
    assert a.status == "healthy"
    assert b.components.get("deep_check_cache", {}).get("status") in {"hit", "miss"}


def test_supersede_blocks_parse_failed_and_fallback(db_session):
    daily = PushLog(
        push_time=datetime.now(),
        trigger_type="auto",
        query_date="2026-07-14",
        patient_id="p1",
        visit_number="1",
        audit_type_code="admission_vs_first_progress",
        audit_run_mode="daily_increment",
        status="success",
        parse_status="success",
        inconsistency=0,
        risk_score=0,
        elapsed_ms=1,
        retry_count=0,
    )
    discharge_bad = PushLog(
        push_time=datetime.now(),
        trigger_type="auto",
        query_date="2026-07-14",
        patient_id="p1",
        visit_number="1",
        audit_type_code="admission_vs_first_progress",
        audit_run_mode="discharge_final",
        status="success",
        parse_status="failed",
        inconsistency=0,
        risk_score=0,
        elapsed_ms=1,
        retry_count=0,
    )
    db_session.add_all([daily, discharge_bad])
    db_session.commit()
    assert mark_daily_logs_superseded(db_session, discharge_bad) == 0
    db_session.refresh(daily)
    assert daily.superseded_by is None

    discharge_ok = PushLog(
        push_time=datetime.now(),
        trigger_type="auto",
        query_date="2026-07-14",
        patient_id="p1",
        visit_number="1",
        audit_type_code="admission_vs_first_progress",
        audit_run_mode="discharge_final",
        status="success",
        parse_status="success",
        inconsistency=0,
        risk_score=0,
        elapsed_ms=1,
        retry_count=0,
    )
    db_session.add(discharge_ok)
    db_session.commit()
    n = mark_daily_logs_superseded(db_session, discharge_ok)
    assert n == 1
    db_session.refresh(daily)
    assert daily.superseded_by == discharge_ok.id


def test_json_tolerance_trailing_comma_and_markdown():
    raw = '```json\n{"dimensions": [], "conclusion": {"overall": "ok"},}\n```'
    parsed = _load_json_with_tolerance(raw)
    assert isinstance(parsed, dict)
    assert "dimensions" in parsed


def test_semantic_shadow_identical_evidence_default_not_enforced(monkeypatch):
    monkeypatch.delenv("HIGH_RISK_SEMANTIC_ENFORCE", raising=False)
    dim = {
        "dimension_code": "other",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["左侧鼓膜穿孔"],
        "nursing_evidence": ["左侧鼓膜穿孔"],
        "extra": {"issues": [{"evidence_a": "左", "evidence_b": "右"}]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert report["should_demote"] is True
    assert "identical_evidence" in report["reasons"] or "other_dimension_forbid_high" in report["reasons"]
    result = apply_semantic_shadow(dim)
    assert result["applied"] is False  # shadow only
    assert dim["severity"] == "high"
    assert semantic_enforce_enabled() is False


def test_semantic_enforce_env_cannot_demote_before_clinical_approval(monkeypatch):
    monkeypatch.setenv("HIGH_RISK_SEMANTIC_ENFORCE", "true")
    dim = {
        "dimension_code": "other",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["aaa"],
        "nursing_evidence": ["aaa"],
        "extra": {},
    }
    result = apply_semantic_shadow(dim)
    assert semantic_enforce_enabled() is False
    assert result["applied"] is False
    assert dim["severity"] == "high"


def test_physical_examination_uses_contract_safety_categories():
    dim = {
        "dimension_code": "physical_examination",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["左侧"],
        "nursing_evidence": ["右侧"],
        "extra": {"issues": [{
            "evidence_a": "左侧手术",
            "evidence_b": "右侧手术",
            "safety_category": "wrong_site_or_side",
            "attribute": "手术侧别",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "physical_examination_lacks_direct_safety_category" not in report["reasons"]


def test_vastbase_error_classification():
    class QueryCanceled(Exception):
        pass

    exc = QueryCanceled("canceling statement due to statement timeout")
    assert _is_transient_db_error(exc) is True
    assert _classify_vastbase_error(exc) == "VASTBASE_STATEMENT_TIMEOUT"
    err = VastbaseQueryError("VASTBASE_STATEMENT_TIMEOUT", "x", batch_index=2)
    assert err.error_code == "VASTBASE_STATEMENT_TIMEOUT"
    assert err.batch_index == 2


def test_directed_retry_stub_requires_dry_run():
    from app.routers.scheduler import directed_retry_stub
    from fastapi import HTTPException

    ok = directed_retry_stub(
        query_date="2026-07-14",
        audit_run_mode="discharge_final",
        audit_type_code="jyjc_vs_bcnursing",
        dry_run=True,
        _user=None,
    )
    assert ok["executed"] is False
    with pytest.raises(HTTPException) as ei:
        directed_retry_stub(
            query_date="2026-07-14",
            audit_run_mode="discharge_final",
            audit_type_code="jyjc_vs_bcnursing",
            dry_run=False,
            _user=None,
        )
    assert ei.value.status_code == 403
