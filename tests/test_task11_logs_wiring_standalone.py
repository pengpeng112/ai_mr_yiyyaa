"""Task 11 wiring checks for logs detail/export enhancements."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_logs_router_contains_stored_audit_snapshot_logic():
    content = (ROOT / "app" / "routers" / "logs.py").read_text(encoding="utf-8")
    assert "def _build_stored_audit_snapshot" in content
    assert "def _build_audit_result_payload" in content
    assert "def _build_raw_debug_payload" in content
    assert "stored_audit" in content
    assert "audit_result" in content
    assert "raw_debug" in content
    assert "AuditDimensionResult" in content and "AuditConclusion" in content


def test_logs_csv_export_contains_audit_type_code_column():
    content = (ROOT / "app" / "routers" / "logs.py").read_text(encoding="utf-8")
    assert "核查类型编码" in content
    assert "audit_type_code" in content


def test_push_log_detail_schema_contains_stored_audit_field():
    content = (ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    assert "stored_audit" in content
    assert "audit_result" in content
    assert "raw_debug" in content


if __name__ == "__main__":
    tests = [
        test_logs_router_contains_stored_audit_snapshot_logic,
        test_logs_csv_export_contains_audit_type_code_column,
        test_push_log_detail_schema_contains_stored_audit_field,
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
