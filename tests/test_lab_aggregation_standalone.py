"""Standalone tests for Task 6 lab aggregation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.lab_aggregation import aggregate_lab_records


def test_lab_dedup_keep_latest_result_time():
    records = [
        {
            "test_no": "LAB-001",
            "report_item_code": "WBC",
            "item_name": "白细胞",
            "result": "11.0",
            "abnormal_indicator": "H",
            "result_time": "2026-04-26 08:10:00",
        },
        {
            "test_no": "LAB-001",
            "report_item_code": "WBC",
            "item_name": "白细胞",
            "result": "12.3",
            "abnormal_indicator": "H",
            "result_time": "2026-04-26 10:10:00",
        },
        {
            "test_no": "LAB-001",
            "report_item_code": "NEUT",
            "item_name": "中性粒细胞比例",
            "result": "85%",
            "abnormal_indicator": "H",
            "result_time": "2026-04-26 08:15:00",
        },
    ]
    aggregated = aggregate_lab_records(records, {"max_lab_items": 30})
    assert aggregated["total_deduped"] == 2
    assert aggregated["selected_count"] == 2
    item_by_code = {item["report_item_code"]: item for item in aggregated["items"]}
    assert item_by_code["WBC"]["result"] == "12.3"


def test_lab_risk_sorting_high_priority_first():
    records = [
        {
            "test_no": "LAB-001",
            "item_name": "白细胞",
            "result": "12.3",
            "abnormal_indicator": "H",
            "result_time": "2026-04-26 08:10:00",
        },
        {
            "test_no": "LAB-002",
            "item_name": "血糖",
            "result": "危急值 25.6",
            "abnormal_indicator": "HH",
            "result_time": "2026-04-26 09:10:00",
        },
    ]
    aggregated = aggregate_lab_records(records, {"max_lab_items": 30})
    assert aggregated["selected_count"] == 2
    assert aggregated["items"][0]["item_name"] == "血糖"
    assert aggregated["items"][0]["risk_level"] == "high"


def test_lab_limit_with_omitted_count():
    records = []
    for idx in range(50):
        records.append(
            {
                "test_no": f"LAB-{idx:03d}",
                "report_item_code": f"ITEM-{idx:03d}",
                "item_name": f"异常项{idx}",
                "result": "异常",
                "abnormal_indicator": "H",
                "result_time": "2026-04-26 08:10:00",
            }
        )
    aggregated = aggregate_lab_records(records, {"max_lab_items": 30})
    assert aggregated["selected_count"] == 30
    assert aggregated["omitted_count"] == 20


if __name__ == "__main__":
    tests = [
        test_lab_dedup_keep_latest_result_time,
        test_lab_risk_sorting_high_priority_first,
        test_lab_limit_with_omitted_count,
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
