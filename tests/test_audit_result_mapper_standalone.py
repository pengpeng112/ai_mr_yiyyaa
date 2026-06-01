"""Standalone tests for Task 10 audit result mapping."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.audit_result_mapper import map_conclusion_row, map_dimension_row


def test_new_audit_type_dimension_evidence_goes_to_extra_json():
    dim = {
        "dimension_code": "lab_consistency",
        "dimension": "检验一致性",
        "medical_evidence": [{"text": "legacy-med"}],
        "nursing_evidence": [{"text": "legacy-nurse"}],
        "extra": {"evidence_lab": [{"test_no": "L001"}]},
    }
    row, extra_json = map_dimension_row(dim, "lab_exam_vs_progress_nursing")
    assert row["medical_evidence_json"] == "[]"
    assert row["nursing_evidence_json"] == "[]"
    extra = json.loads(extra_json)
    assert "evidence_lab" in extra
    assert "medical_evidence_legacy" in extra
    assert "nursing_evidence_legacy" in extra


def test_legacy_audit_type_keeps_evidence_columns():
    dim = {
        "dimension_code": "diag_consistency",
        "dimension": "诊断一致性",
        "medical_evidence": [{"text": "病程证据"}],
        "nursing_evidence": [{"text": "护理证据"}],
    }
    row, extra_json = map_dimension_row(dim, "progress_vs_nursing")
    assert row["medical_evidence_json"] != "[]"
    assert row["nursing_evidence_json"] != "[]"
    assert extra_json == "{}"


def test_dimension_name_is_used_when_dimension_missing():
    dim = {
        "dimension_code": "diagnosis_consistency",
        "dimension_name": "诊断一致性",
        "status": "unknown",
    }
    row, _ = map_dimension_row(dim, "lab_exam_vs_progress_nursing")
    assert row["dimension"] == "诊断一致性"


def test_dimension_falls_back_to_code_for_oracle_not_null():
    dim = {
        "dimension_code": "timeline_consistency",
        "status": "unknown",
    }
    row, _ = map_dimension_row(dim, "lab_exam_vs_progress_nursing")
    assert row["dimension"] == "timeline_consistency"


def test_conclusion_extra_json_merges_parse_warning_and_aggregation_stats():
    parsed = {
        "inconsistency": True,
        "severity": "high",
        "risk_score": 88,
        "overall_conclusion": "存在不一致",
        "focus_items": ["白细胞升高"],
        "extra": {"trace_id": "abc-1"},
        "parse_warning": "response_path_no_match",
        "aggregation_stats": {"lab_omitted": 5, "exam_omitted": 2},
    }
    row, extra_json = map_conclusion_row(parsed)
    assert row["has_inconsistency"] == 1
    assert row["risk_score"] == 88
    extra = json.loads(extra_json)
    assert extra["trace_id"] == "abc-1"
    assert extra["parse_warning"] == "response_path_no_match"
    assert extra["aggregation_stats"]["lab_omitted"] == 5


if __name__ == "__main__":
    tests = [
        test_new_audit_type_dimension_evidence_goes_to_extra_json,
        test_legacy_audit_type_keeps_evidence_columns,
        test_dimension_name_is_used_when_dimension_missing,
        test_dimension_falls_back_to_code_for_oracle_not_null,
        test_conclusion_extra_json_merges_parse_warning_and_aggregation_stats,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR: {test.__name__}: {exc}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed > 0:
        raise SystemExit(1)
