"""Standalone tests for first progress matcher (Task 14)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.first_progress_matcher import select_first_progress_record


def test_select_first_progress_by_rn_priority():
    surgeries = [{"operation_date": "2026-03-02"}]
    progress_records = [
        {
            "mrid": "MR-002",
            "record_name": "术后首次病程记录",
            "rn": 2,
            "title_time": "2026-03-02 10:00:00",
            "content": "记录2",
        },
        {
            "mrid": "MR-001",
            "record_name": "术后首次病程记录",
            "rn": 1,
            "title_time": "2026-03-02 11:00:00",
            "content": "记录1",
        },
    ]
    matched = select_first_progress_record(surgeries, progress_records, {"rn_priority": [1], "time_window_days": 1})
    assert matched["selected_progress"]["mrid"] == "MR-001"
    assert matched["candidate_count"] == 2


def test_fallback_when_no_post_op_record_name():
    surgeries = [{"operation_date": "2026-03-02"}]
    progress_records = [
        {
            "mrid": "MR-010",
            "record_name": "首次病程记录",
            "rn": 1,
            "title_time": "2026-03-02 09:00:00",
            "content": "兜底候选",
        }
    ]
    matched = select_first_progress_record(surgeries, progress_records, {"record_name_include": ["术后首次病程记录"]})
    assert matched["selected_progress"]["mrid"] == "MR-010"
    assert "no_post_op_first_progress" in (matched["match_warnings"] or [])


def test_pre_op_record_excluded_from_post_op_window():
    surgeries = [{"operation_date": "2026-03-02"}]
    progress_records = [
        {
            "mrid": "MR-PRE",
            "record_name": "术后首次病程记录",
            "rn": 1,
            "title_time": "2026-03-01 09:00:00",
            "content": "术前记录，不应命中术后窗口",
        },
        {
            "mrid": "MR-POST",
            "record_name": "术后首次病程记录",
            "rn": 1,
            "title_time": "2026-03-03 09:00:00",
            "content": "术后记录",
        },
    ]
    matched = select_first_progress_record(surgeries, progress_records, {"time_window_days": 3})
    assert matched["selected_progress"]["mrid"] == "MR-POST"


if __name__ == "__main__":
    tests = [
        test_select_first_progress_by_rn_priority,
        test_fallback_when_no_post_op_record_name,
        test_pre_op_record_excluded_from_post_op_window,
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
