"""
Standalone tests for ADR-2 dimension sub-field mapping protocol
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_push_executor_has_unknown_field_warning():
    """Verify _save_audit_results logs warning for unknown dimension fields"""
    executor_path = Path(__file__).parent.parent / "app" / "services" / "push_executor.py"
    source = executor_path.read_text(encoding="utf-8")

    save_start = source.find("def _save_audit_results")
    assert save_start != -1

    # Check unknown_keys detection exists
    unknown_keys = source.find("unknown_keys = set(dim.keys()) - known_dim_keys", save_start)
    assert unknown_keys != -1, "Unknown keys detection not found"

    # Check warning log exists
    warning_log = source.find("logger.warning(", unknown_keys)
    assert warning_log != -1, "Warning log for unknown fields not found"


def test_push_executor_has_known_dim_keys_set():
    """Verify known_dim_keys set includes all expected fields"""
    executor_path = Path(__file__).parent.parent / "app" / "services" / "push_executor.py"
    source = executor_path.read_text(encoding="utf-8")

    save_start = source.find("def _save_audit_results")
    assert save_start != -1

    # Check known_dim_keys definition
    known_keys_start = source.find("known_dim_keys = {", save_start)
    assert known_keys_start != -1, "known_dim_keys set not found"

    known_keys_section = source[known_keys_start:known_keys_start + 800]
    expected_keys = [
        "dimension_code", "dimension", "status", "severity", "confidence",
        "medical_content", "nursing_content", "explanation", "issue_summary",
        "recommendation", "medical_evidence", "nursing_evidence", "alert_level",
        "closure_hours", "push_strategy", "outcome_bucket", "extra",
    ]
    for key in expected_keys:
        assert f'"{key}"' in known_keys_section, f"Missing key: {key}"


def test_audit_dimension_schema_doc_exists():
    """Verify docs/audit_dimension_schema.md exists and has required sections"""
    doc_path = Path(__file__).parent.parent / "docs" / "audit_dimension_schema.md"
    assert doc_path.exists(), "audit_dimension_schema.md not found"

    content = doc_path.read_text(encoding="utf-8")
    assert "# ADR-2" in content
    assert "progress_vs_nursing" in content
    assert "lab_exam_vs_progress_nursing" in content
    assert "frontpage_surgery_diagnosis_vs_first_progress" in content
    assert "向后兼容性" in content


def test_audit_type_registry_has_adr2_docstring():
    """Verify audit_type_registry.py has ADR-2 protocol documentation"""
    registry_path = Path(__file__).parent.parent / "app" / "services" / "audit_type_registry.py"
    source = registry_path.read_text(encoding="utf-8")

    assert "ADR-2" in source
    assert "dimension_code / dimension / severity" in source
    assert "extra" in source


if __name__ == "__main__":
    tests = [
        test_push_executor_has_unknown_field_warning,
        test_push_executor_has_known_dim_keys_set,
        test_audit_dimension_schema_doc_exists,
        test_audit_type_registry_has_adr2_docstring,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"ERROR: {test.__name__}: {e}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed > 0:
        sys.exit(1)
