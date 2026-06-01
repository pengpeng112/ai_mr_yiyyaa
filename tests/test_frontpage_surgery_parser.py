"""Standalone tests for frontpage surgery parser (Task 14)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.frontpage_surgery_parser import parse_frontpage_record


def test_parse_multiple_surgeries_keep_raw():
    record = {
        "patient_id": "P_DEMO_002",
        "visit_number": "2",
        "入院诊断": "胆总管结石",
        "出院主诊断": "胆总管结石并梗阻",
        "出院其他诊断1": "高血压",
        "手术": "手术名称:ERCP取石术,手术编码:51.8400,手术日期:2026-03-02,麻醉方式:静吸复合全麻,手术级别:3级",
        "手术1": "手术名称:胆道支架置入术,手术编码:51.8701,手术日期:2026-03-03,麻醉方式:全麻,手术级别:3级",
    }
    parsed = parse_frontpage_record(record, {})
    assert len(parsed["surgeries"]) == 2
    assert parsed["surgeries"][0]["operation_name"]
    assert parsed["surgeries"][0]["raw_text"]
    assert parsed["diagnoses"]["admission_diagnosis"] == "胆总管结石"


def test_parse_weird_operation_date_with_warning_or_normalized():
    record = {
        "patient_id": "P_DEMO_003",
        "visit_number": "1",
        "手术": "手术名称:完壁式乳突改良根治术,手术日期:11-2月 -26,麻醉方式:全麻",
    }
    parsed = parse_frontpage_record(record, {})
    surgery = parsed["surgeries"][0]
    assert surgery.get("raw_text")
    assert surgery.get("operation_date") in {"2026-02-11", ""}
    if not surgery.get("operation_date"):
        assert "date_unparseable" in (surgery.get("warnings") or [])


if __name__ == "__main__":
    tests = [
        test_parse_multiple_surgeries_keep_raw,
        test_parse_weird_operation_date_with_warning_or_normalized,
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
