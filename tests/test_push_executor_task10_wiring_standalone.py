"""Source wiring checks for Task 10 push_executor integration."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).parent.parent
PUSH_EXECUTOR = ROOT / "app" / "services" / "push_executor.py"
AUDIT_RESULT_WRITER = ROOT / "app" / "services" / "audit_result_writer.py"


def test_push_executor_uses_audit_result_mapper_and_audit_type_code():
    executor_content = PUSH_EXECUTOR.read_text(encoding="utf-8")
    writer_content = AUDIT_RESULT_WRITER.read_text(encoding="utf-8")
    assert "from app.services.audit_result_mapper import map_conclusion_row, map_dimension_row" in writer_content
    assert "def save_audit_results(db: Session, push_log_id: int, dify_result: Dict[str, Any], audit_type_code: str = \"\")" in writer_content
    assert "map_dimension_row(dim, audit_type_code)" in writer_content
    assert "_save_audit_results_impl" in executor_content


if __name__ == "__main__":
    tests = [test_push_executor_uses_audit_result_mapper_and_audit_type_code]
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
