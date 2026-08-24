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
    monkeypatch.setattr("app.config.load_config", lambda: {})
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


def test_semantic_enforce_env_enables_authorized_demotion(monkeypatch):
    """20260817 起运营方已授权：env/config 可开启语义降级，降级留审计标记。"""
    monkeypatch.setenv("HIGH_RISK_SEMANTIC_ENFORCE", "true")
    dim = {
        "dimension_code": "physical_examination",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["aaa"],
        "nursing_evidence": ["aaa"],
        "extra": {},
    }
    result = apply_semantic_shadow(dim)
    assert semantic_enforce_enabled() is True
    assert result["applied"] is True
    assert dim["severity"] == "medium"
    assert dim["alert_level"] == "yellow"
    assert dim["extra"].get("semantic_enforced_demote")


def test_semantic_enforce_config_flag_enables(monkeypatch):
    monkeypatch.delenv("HIGH_RISK_SEMANTIC_ENFORCE", raising=False)
    monkeypatch.setattr("app.config.load_config", lambda: {"high_risk_semantic_enforce": True})
    assert semantic_enforce_enabled() is True
    monkeypatch.setattr("app.config.load_config", lambda: {})
    assert semantic_enforce_enabled() is False


def test_text_quality_dimension_never_high_eligible():
    """YML 契约后端强制：text_quality 维度不得进入高危门槛（20260817）。"""
    from app.services.dify_schema_parser import (
        _qualified_high_risk_issue,
        _high_risk_rejection_reasons,
    )

    dim = {
        "dimension_code": "text_quality",
        "status": "fail",
        "severity": "high",
        "confidence": 0.95,
        "medical_evidence": ["入院记录 BMI 22.72"],
        "nursing_evidence": ["首次病程 BMI 0"],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "BMI 22.72", "evidence_b": "BMI 0", "confidence": 0.95,
            "safety_category": "critical_diagnosis_basis",
        }]},
    }
    assert _qualified_high_risk_issue(dim, "admission_vs_first_progress") is None
    assert "dimension_code_text_quality_not_high_eligible" in _high_risk_rejection_reasons(
        dim, "admission_vs_first_progress")


def test_text_quality_rule_in_semantic_shadow():
    dim = {
        "dimension_code": "text_quality",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["x" * 20],
        "nursing_evidence": ["y" * 20],
        "extra": {},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "text_quality_forbid_high" in report["reasons"]
    assert report["should_demote"] is True


def test_diagnosis_superset_demoted():
    """新增诊断（一侧是另一侧严格超集）不得判红（高庆贵/王剑辉模式）。"""
    dim = {
        "dimension_code": "diagnosis_consistency",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["初步诊断: 1.腰椎椎管狭窄 2.腰椎间盘突出 3.2型糖尿病"],
        "nursing_evidence": ["初步诊断：1、腰椎椎管狭窄 2、腰椎间盘突出 3、2型糖尿病 4、颈椎椎管狭窄 5、神经根型颈椎病"],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "x" * 20, "evidence_b": "y" * 20, "confidence": 0.95,
            "safety_category": "critical_diagnosis_basis",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "diagnosis_superset_not_contradiction" in report["reasons"]
    assert report["should_demote"] is True


def test_diagnosis_real_conflict_not_superset():
    """诊断项存在差异（非超集）时不得触发该规则（真矛盾保护）。"""
    dim = {
        "dimension_code": "diagnosis_consistency",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["初步诊断: 1.腰椎压缩性骨折 2.冠心病"],
        "nursing_evidence": ["初步诊断：1、右踝关节骨折 2、冠心病"],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "x" * 20, "evidence_b": "y" * 20, "confidence": 0.95,
            "safety_category": "critical_diagnosis_basis",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "diagnosis_superset_not_contradiction" not in report["reasons"]


def test_non_diagnosis_evidence_not_superset_checked():
    """非诊断类证据（如查体侧别冲突）不参与超集判断（王金强模式保护）。"""
    dim = {
        "dimension_code": "physical_examination",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["左侧鼓膜紧张部穿孔" + "x" * 20],
        "nursing_evidence": ["双侧鼓膜完整" + "y" * 20],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "x" * 20, "evidence_b": "y" * 20, "confidence": 0.95,
            "safety_category": "wrong_site_or_side",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "diagnosis_superset_not_contradiction" not in report["reasons"]


def test_impossible_vital_value_demoted():
    """BMI=0/体重0/身高0 属数据质量，不得作为临床矛盾判红（张定宇模式）。"""
    dim = {
        "dimension_code": "physical_examination",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["查体：T 39℃;P 110次/分;H 178cm;W 72kg;BMI 22.72kg/m2"],
        "nursing_evidence": ["查体：T 39℃;P 110次/分;H 178cm;W 72kg;BMI 0kg/m2"],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "x" * 20, "evidence_b": "y" * 20, "confidence": 0.95,
            "safety_category": "critical_diagnosis_basis",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "impossible_vital_value_data_quality" in report["reasons"]
    assert report["should_demote"] is True


def test_normal_vitals_not_flagged_impossible():
    dim = {
        "dimension_code": "physical_examination",
        "severity": "high",
        "alert_level": "red",
        "medical_evidence": ["体温37℃，脉搏80次/分" + "x" * 20],
        "nursing_evidence": ["体温39℃，脉搏110次/分" + "y" * 20],
        "extra": {"issues": [{
            "level": "severe", "high_eligible": True, "issue_mode": "contradiction",
            "source_a": "admission_record", "source_b": "first_progress_record",
            "evidence_a": "x" * 20, "evidence_b": "y" * 20, "confidence": 0.95,
            "safety_category": "current_vital_or_life_support",
        }]},
    }
    report = evaluate_semantic_high_risk_dim(dim)
    assert "impossible_vital_value_data_quality" not in report["reasons"]


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
