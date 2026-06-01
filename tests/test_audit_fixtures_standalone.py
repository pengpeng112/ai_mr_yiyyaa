"""Task 4 fixture smoke test (standalone)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.fixtures.audit_source_samples import (
    scenario_cross_day_progress,
    scenario_missing_sources,
    scenario_mixed_normal_abnormal,
    scenario_same_day_complete,
)


def test_fixture_counts():
    same_day = scenario_same_day_complete()
    assert len(same_day["lab"]) >= 2
    assert len(same_day["exam"]) >= 1
    assert len(same_day["progress"]) >= 1
    assert len(same_day["nursing"]) >= 1

    missing = scenario_missing_sources()
    assert len(missing["exam"]) == 0
    assert len(missing["nursing"]) == 0

    cross_day = scenario_cross_day_progress()
    audit_dates = {item["audit_date"] for item in cross_day["progress"]}
    assert "2026-04-26" in audit_dates and "2026-04-27" in audit_dates

    mixed = scenario_mixed_normal_abnormal()
    abnormal_flags = {item["abnormal_indicator"] for item in mixed["lab"]}
    assert "H" in abnormal_flags and "N" in abnormal_flags


if __name__ == "__main__":
    try:
        test_fixture_counts()
        print("PASS: test_fixture_counts")
        print("\nResults: 1 passed, 0 failed")
    except AssertionError as exc:
        print(f"FAIL: test_fixture_counts: {exc}")
        raise SystemExit(1)
