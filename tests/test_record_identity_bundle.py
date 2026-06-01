"""Standalone tests for ADR-3 bundle source key compatibility."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas import AuditTypeConfig
from app.services.record_identity import get_bundle_source_key


def _build_audit_type(code: str, builder: str, group_key: list[str]) -> AuditTypeConfig:
    raw = {
        "code": code,
        "name": code,
        "enabled": True,
        "sources": {"primary": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {}}},
        "group_key": group_key,
        "payload": {"builder": builder},
        "dify": {
            "base_url": "http://example.local/v1",
            "api_key": "k",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "user_identifier": "u",
            "timeout_seconds": 60,
        },
        "response": {},
        "display": {},
    }
    return AuditTypeConfig.model_validate(raw)


def _build_bundle(patient_id: str, visit: str, audit_date: str | None = None) -> SimpleNamespace:
    group_values = {"patient_id": patient_id, "visit_number": visit}
    if audit_date is not None:
        group_values["audit_date"] = audit_date
    return SimpleNamespace(
        primary_source="primary",
        group_values=group_values,
        sources={"primary": [{"患者ID": patient_id, "次数": visit, "audit_date": audit_date or ""}]},
    )


def test_legacy_bundle_key_compatible_without_audit_type_prefix():
    legacy = _build_audit_type("progress_vs_nursing", "legacy_progress_nursing", ["patient_id", "visit_number"])
    bundle = _build_bundle("P001", "1")
    key = get_bundle_source_key(bundle, legacy)
    assert key.startswith("legacy::")
    assert "progress_vs_nursing::" not in key


def test_new_bundle_key_contains_audit_type_prefix_and_date():
    new_type = _build_audit_type(
        "lab_exam_test",
        "lab_exam_progress_nursing",
        ["patient_id", "visit_number", "audit_date"],
    )
    bundle = _build_bundle("P001", "1", "2026-04-26")
    key = get_bundle_source_key(bundle, new_type)
    assert key == "lab_exam_test::P001::1::2026-04-26"


def test_new_bundle_key_changes_for_cross_day_push():
    new_type = _build_audit_type(
        "lab_exam_test",
        "lab_exam_progress_nursing",
        ["patient_id", "visit_number", "audit_date"],
    )
    key_d1 = get_bundle_source_key(_build_bundle("P001", "1", "2026-04-26"), new_type)
    key_d2 = get_bundle_source_key(_build_bundle("P001", "1", "2026-04-27"), new_type)
    assert key_d1 != key_d2


if __name__ == "__main__":
    tests = [
        test_legacy_bundle_key_compatible_without_audit_type_prefix,
        test_new_bundle_key_contains_audit_type_prefix_and_date,
        test_new_bundle_key_changes_for_cross_day_push,
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
