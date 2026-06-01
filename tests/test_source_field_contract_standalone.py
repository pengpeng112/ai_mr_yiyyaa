"""Standalone tests for source field contract/date normalize (Task 2)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.source_field_contract import (
    normalize_date_to_ymd,
    normalize_source_record,
    should_attach_followup_progress,
)


def test_normalize_date_formats():
    assert normalize_date_to_ymd("2026-04-26") == "2026-04-26"
    assert normalize_date_to_ymd("2026/04/26 09:30:00") == "2026-04-26"
    assert normalize_date_to_ymd("20260426") == "2026-04-26"
    assert normalize_date_to_ymd("2026年04月26日") == "2026-04-26"


def test_normalize_lab_record_with_mapping():
    record = {
        "患者ID": "p001",
        "次数": "1",
        "结果时间": "2026-04-26 10:11:12",
        "项目名称": "白细胞",
        "结果值": "12.3",
        "异常标记": "H",
    }
    mapping = {
        "patient_id": "患者ID",
        "visit_number": "次数",
        "result_time": "结果时间",
        "item_name": "项目名称",
        "result": "结果值",
        "abnormal_indicator": "异常标记",
    }
    canonical, errors = normalize_source_record("lab", record, mapping, "2026-04-26")
    assert errors == []
    assert canonical["patient_id"] == "p001"
    assert canonical["visit_number"] == "1"
    assert canonical["item_name"] == "白细胞"
    assert canonical["result"] == "12.3"
    assert canonical["audit_date"] == "2026-04-26"


def test_missing_group_fields_has_reason():
    record = {"结果时间": "2026-04-26 10:11:12"}
    mapping = {"result_time": "结果时间"}
    _, errors = normalize_source_record("lab", record, mapping, "2026-04-26")
    assert any(item.startswith("missing_group_fields:") for item in errors)


def test_data_source_loader_contains_contract_hook():
    loader_path = Path(__file__).parent.parent / "app" / "services" / "data_source_loader.py"
    source = loader_path.read_text(encoding="utf-8")
    assert "normalize_source_record(" in source
    assert "should_attach_followup_progress(" in source
    assert "missing_required" in source and "reason=" in source


def test_followup_window_logic():
    assert should_attach_followup_progress("2026-04-27", "2026-04-26", 1) is True
    assert should_attach_followup_progress("2026-04-28", "2026-04-26", 1) is False
    assert should_attach_followup_progress("2026-04-26", "2026-04-26", 1) is False


if __name__ == "__main__":
    tests = [
        test_normalize_date_formats,
        test_normalize_lab_record_with_mapping,
        test_missing_group_fields_has_reason,
        test_data_source_loader_contains_contract_hook,
        test_followup_window_logic,
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
