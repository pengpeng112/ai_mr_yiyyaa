"""Standalone wiring checks for Task 12 dify priority and observability."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_push_router_manual_targets_endpoint_only_merge():
    content = _read("app/routers/push.py")
    assert "override_fields=base_url,api_key" in content
    assert "workflow_input_variable/workflow_output_key/response_paths 保持 audit_type.dify 与 audit_type.response" in content
    assert "merged_target[\"base_url\"] = base_url" in content
    assert "merged_target[\"api_key\"] = api_key" in content


def test_push_router_v2_bulk_passes_dify_targets():
    content = _read("app/routers/push.py")
    assert "dify_targets=_build_manual_dify_targets(body, dify_override, config)" in content


def test_bulk_executor_passes_audit_type_code_and_logs_audit_dify():
    content = _read("app/services/bulk_push_executor.py")
    assert "_save_audit_results(db, log.id, dify_result, str(push_config.audit_type_code or \"\"))" in content
    assert "[audit.dify] bulk_start" in content
    assert "[audit.dify] target_picked" in content
    assert "[audit.dify] bulk_done" in content


if __name__ == "__main__":
    tests = [
        test_push_router_manual_targets_endpoint_only_merge,
        test_push_router_v2_bulk_passes_dify_targets,
        test_bulk_executor_passes_audit_type_code_and_logs_audit_dify,
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
        sys.exit(1)
