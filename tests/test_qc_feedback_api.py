from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers import qc_feedback


def test_mark_feedback_viewed_increments_count_and_sets_flags():
    feedback = SimpleNamespace(is_viewed=False, view_count=0, viewed_at=None, updated_at=None)
    qc_feedback._mark_feedback_viewed(feedback)
    assert feedback.is_viewed is True
    assert feedback.view_count == 1
    assert feedback.viewed_at is not None


def test_check_feedback_permission_admin_pass(monkeypatch):
    monkeypatch.setattr(qc_feedback, "get_user_role", lambda _uid, _db: "admin")
    feedback = SimpleNamespace(dept_id=2)
    user = SimpleNamespace(id=1, dept_id=1)
    assert qc_feedback._check_feedback_permission(feedback, user, db=object()) == "admin"


def test_check_feedback_permission_non_admin_denied(monkeypatch):
    monkeypatch.setattr(qc_feedback, "get_user_role", lambda _uid, _db: "doctor")
    feedback = SimpleNamespace(dept_id=2)
    user = SimpleNamespace(id=1, dept_id=1)
    with pytest.raises(HTTPException) as exc:
        qc_feedback._check_feedback_permission(feedback, user, db=object())
    assert exc.value.status_code == 403


def test_build_case_item_uses_conclusion_severity_and_focus_items():
    log = SimpleNamespace(
        id=100,
        patient_id="P001",
        patient_name="张三",
        admission_no="ZY001",
        query_date="2026-04-05",
        push_time="2026-04-05 08:00:00",
        severity="low",
        alert_level="blue",
        risk_score=15,
    )
    conclusion = SimpleNamespace(
        severity="high",
        alert_level="red",
        overall_conclusion="存在不一致",
        overall_qc_summary="护理记录时间缺失",
        focus_items='["诊断一致性", "用药一致性"]',
        risk_score=80,
    )
    feedback = SimpleNamespace(
        id=200,
        status="acknowledged",
        feedback_text="请科室复核",
        created_by=9,
        updated_at="2026-04-05 09:00:00",
    )

    item = qc_feedback._build_case_item(
        log=log,
        conclusion=conclusion,
        feedback=feedback,
        dept_name="心内科",
        dept_id=3,
        issue_count=2,
    )

    assert item.severity == "high"
    assert item.alert_level == "red"
    assert item.overall_conclusion == "存在不一致"
    assert item.overall_qc_summary == "护理记录时间缺失"
    assert item.focus_items == ["诊断一致性", "用药一致性"]
    assert item.feedback_status == "acknowledged"


def test_build_dimension_items_keeps_medical_and_nursing_content():
    dimension = SimpleNamespace(
        dimension="护理记录一致性",
        dimension_code="NURSE_CONSISTENCY",
        status="fail",
        severity="medium",
        confidence=0.86,
        medical_content="病程记录：患者夜间胸痛",
        nursing_content="护理记录：夜间无胸痛主诉",
        explanation="病程与护理主诉冲突",
        issue_summary="主诉不一致",
        recommendation="建议复核夜间病程",
        alert_level="yellow",
        closure_hours=24,
        push_strategy="immediate",
        outcome_bucket="primary",
    )

    items = qc_feedback._build_dimension_items([dimension])
    assert len(items) == 1
    assert items[0].medical_content == "病程记录：患者夜间胸痛"
    assert items[0].nursing_content == "护理记录：夜间无胸痛主诉"
    assert items[0].explanation == "主诉不一致"


def test_build_dimension_items_fallback_to_empty_text():
    dimension = SimpleNamespace(
        dimension="用药一致性",
        dimension_code="",
        status="warn",
        severity="",
        confidence=0,
        medical_content=None,
        nursing_content=None,
        explanation=None,
        issue_summary=None,
        recommendation=None,
        alert_level=None,
        closure_hours=None,
        push_strategy=None,
        outcome_bucket=None,
    )

    items = qc_feedback._build_dimension_items([dimension])
    assert items[0].medical_content == ""
    assert items[0].nursing_content == ""
    assert items[0].explanation == ""


def test_resolve_confirm_dept_id_non_admin_requires_matching_department():
    dept_ref = SimpleNamespace(id=2)
    dept_id = qc_feedback._resolve_confirm_dept_id("doctor", 2, dept_ref)
    assert dept_id == 2


def test_resolve_confirm_dept_id_non_admin_denied_when_missing_department_mapping():
    with pytest.raises(HTTPException) as exc:
        qc_feedback._resolve_confirm_dept_id("doctor", 2, None)
    assert exc.value.status_code == 403


def test_resolve_confirm_dept_id_admin_denied_when_missing_department_mapping():
    with pytest.raises(HTTPException) as exc:
        qc_feedback._resolve_confirm_dept_id("admin", 1, None)
    assert exc.value.status_code == 400


def test_resolve_confirm_dept_id_admin_accepts_mapped_department():
    dept_ref = SimpleNamespace(id=8)
    dept_id = qc_feedback._resolve_confirm_dept_id("admin", None, dept_ref)
    assert dept_id == 8
