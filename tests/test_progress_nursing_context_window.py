"""Tests for progress/nursing context selector (Task 8)."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app.services.progress_nursing_context_window import select_progress_nursing_context
from fixtures.audit_source_samples import scenario_cross_day_progress, scenario_same_day_complete


def test_followup_progress_included_within_window():
    sample = scenario_cross_day_progress()
    result = select_progress_nursing_context(
        progress_records=sample["progress"],
        nursing_records=sample["nursing"],
        query_date=sample["audit_date"],
        options={"progress_followup_days": 1},
    )
    progress_ctx = result["progress_context"]
    assert progress_ctx["total_selected"] == 2
    assert progress_ctx["followup_count"] == 1


def test_nursing_only_same_day():
    sample = scenario_same_day_complete()
    sample["nursing"].append(
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-27",
            "record_id": "NU-002",
            "record_name": "护理记录",
            "content": "次日护理",
            "event_time": "2026-04-27 09:00:00",
        }
    )
    result = select_progress_nursing_context(
        progress_records=sample["progress"],
        nursing_records=sample["nursing"],
        query_date=sample["audit_date"],
        options={"progress_followup_days": 1},
    )
    nursing_ctx = result["nursing_context"]
    assert nursing_ctx["total_selected"] == 1
    assert all(item.get("context_date") == "2026-04-26" for item in nursing_ctx["records"])


def test_nursing_content_truncated_when_exceeds_max_chars():
    sample = scenario_same_day_complete()
    sample = copy.deepcopy(sample)
    sample["nursing"][0]["content"] = "A" * 500

    result = select_progress_nursing_context(
        progress_records=sample["progress"],
        nursing_records=sample["nursing"],
        query_date=sample["audit_date"],
        options={"max_nursing_chars": 120},
    )
    nursing_ctx = result["nursing_context"]
    assert nursing_ctx["truncated"] is True
    assert len(nursing_ctx["records"][0].get("content", "")) == 120
    assert nursing_ctx["records"][0].get("content_truncated") is True


if __name__ == "__main__":
    tests = [
        test_followup_progress_included_within_window,
        test_nursing_only_same_day,
        test_nursing_content_truncated_when_exceeds_max_chars,
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
