"""Standalone tests for Dify response path contract (Task 3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.response_path_utils import apply_response_paths


def test_apply_response_paths_success():
    sample = {
        "overall_conclusion": "发现不一致",
        "severity": "high",
        "risk_score": 88,
        "inconsistency": True,
        "dimensions": [{"dimension_code": "diagnosis_consistency", "issue_summary": "..."}],
    }
    paths = {
        "dimension_path": "$.dimensions",
        "conclusion_path": "$.overall_conclusion",
        "severity_path": "$.severity",
        "risk_score_path": "$.risk_score",
        "inconsistency_path": "$.inconsistency",
    }
    parsed = apply_response_paths(sample, paths)
    assert isinstance(parsed.get("dimensions"), list)
    assert parsed.get("severity") == "high"
    assert parsed.get("risk_score") == 88
    assert "parse_warning" not in parsed


def test_apply_response_paths_no_match_warning():
    sample = {"foo": "bar"}
    paths = {
        "dimension_path": "$.does.not.exist",
        "conclusion_path": "$.also.not.exist",
    }
    parsed = apply_response_paths(sample, paths)
    assert parsed.get("parse_warning") == "response_path_no_match"


if __name__ == "__main__":
    tests = [test_apply_response_paths_success, test_apply_response_paths_no_match_warning]
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
