"""Builder registry tests (Task 15a/15b)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.builder_registry import get_builder, has_builder, list_builders, register_builder, unregister_builder


def _dummy_builder(audit_type, bundle, query_date):
    return {"mr_text": "dummy"}, "dummy"


def test_registry_register_and_unregister():
    name = "unit_test_dummy"
    unregister_builder(name)
    assert has_builder(name) is False
    register_builder(name, _dummy_builder)
    assert has_builder(name) is True
    assert name in list_builders()
    payload, mr_text = get_builder(name)(None, None, "")
    assert payload.get("mr_text") == "dummy"
    assert mr_text == "dummy"
    unregister_builder(name)
    assert has_builder(name) is False


def test_registry_unknown_builder_raises():
    name = "missing_builder_case"
    unregister_builder(name)
    try:
        get_builder(name)
    except ValueError as exc:
        assert "unknown payload builder" in str(exc)
        return
    raise AssertionError("expected ValueError for unknown builder")


if __name__ == "__main__":
    tests = [
        test_registry_register_and_unregister,
        test_registry_unknown_builder_raises,
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
