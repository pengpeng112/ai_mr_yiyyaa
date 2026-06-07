"""Standalone regression checks for review fixes."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


ROOT = Path(__file__).parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_skip_reason_is_scoped_by_audit_type_code():
    executor_source = _read("app/services/push_executor.py")
    skip_source = _read("app/services/push_skip_policy.py")

    assert "def _apply_audit_type_scope" in executor_source
    assert "PushLog.audit_type_code == code" in skip_source
    assert "_apply_audit_type_scope_impl" in executor_source
    assert "push_config.audit_type_code" in executor_source


def test_bulk_executor_passes_audit_type_to_skip_reason():
    source = _read("app/services/bulk_push_executor.py")

    assert "base_executor._get_skip_reason" in source
    assert "push_config.audit_type_code" in source
    assert "get_bundle_source_key" in source
    assert "source_record_key" in source
    assert "push_config.audit_run_mode" in source


def test_only_builtin_legacy_type_uses_global_legacy_path():
    source = _read("app/routers/push.py")

    assert 'def _is_legacy_single_type(audit_types: list) -> bool:' in source
    assert '!= "progress_vs_nursing"' in source
    assert '== "legacy_progress_nursing"' in source


if __name__ == "__main__":
    tests = [
        test_skip_reason_is_scoped_by_audit_type_code,
        test_bulk_executor_passes_audit_type_to_skip_reason,
        test_only_builtin_legacy_type_uses_global_legacy_path,
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
