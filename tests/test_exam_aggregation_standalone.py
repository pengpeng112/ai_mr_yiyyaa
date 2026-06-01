"""Standalone tests for Task 7 exam aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.exam_aggregation import aggregate_exam_reports


def test_exam_group_by_exam_no_keep_single_summary():
    records = [
        {
            "exam_no": "EXAM-001",
            "exam_class": "CT",
            "description": "胸部CT",
            "impression": "",
            "recommendation": "",
            "is_abnormal": "N",
            "exam_time": "2026-04-26 09:20:00",
        },
        {
            "exam_no": "EXAM-001",
            "exam_class": "CT",
            "description": "胸部CT",
            "impression": "双肺感染影",
            "recommendation": "建议复查",
            "is_abnormal": "Y",
            "exam_time": "2026-04-26 09:30:00",
        },
    ]
    aggregated = aggregate_exam_reports(records, {"max_exam_reports": 10})
    assert aggregated["total_grouped"] == 1
    assert aggregated["selected_count"] == 1
    assert aggregated["reports"][0]["exam_no"] == "EXAM-001"
    assert aggregated["reports"][0]["is_abnormal"] is True


def test_exam_normal_summary_excluded_when_disabled():
    records = [
        {
            "exam_no": "EXAM-001",
            "exam_class": "CT",
            "description": "胸部CT",
            "impression": "双肺感染影",
            "recommendation": "建议复查",
            "is_abnormal": "Y",
            "exam_time": "2026-04-26 09:30:00",
        },
        {
            "exam_no": "EXAM-002",
            "exam_class": "X线",
            "description": "胸片未见明显异常",
            "impression": "",
            "recommendation": "",
            "is_abnormal": "N",
            "exam_time": "2026-04-26 10:30:00",
        },
    ]
    aggregated = aggregate_exam_reports(records, {"max_exam_reports": 10, "include_normal_summary": False})
    assert aggregated["selected_count"] == 1
    assert aggregated["reports"][0]["exam_no"] == "EXAM-001"


def test_exam_limit_with_omitted_count():
    records = []
    for idx in range(12):
        records.append(
            {
                "exam_no": f"EXAM-{idx:03d}",
                "exam_class": "CT",
                "description": f"检查{idx}",
                "impression": "异常影",
                "recommendation": "建议随访",
                "is_abnormal": "Y",
                "exam_time": f"2026-04-26 09:{idx:02d}:00",
            }
        )
    aggregated = aggregate_exam_reports(records, {"max_exam_reports": 10})
    assert aggregated["selected_count"] == 10
    assert aggregated["omitted_count"] == 2


if __name__ == "__main__":
    tests = [
        test_exam_group_by_exam_no_keep_single_summary,
        test_exam_normal_summary_excluded_when_disabled,
        test_exam_limit_with_omitted_count,
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
