"""Standalone checks for multi-source audit type template (Task 1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db_client_base import validate_configurable_sql
from app.schemas import AuditTypeConfig


ROOT = Path(__file__).parent.parent
TEMPLATE_PATH = ROOT / "config" / "config.json.template"


def _load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _find_audit_type(config_data: dict, code: str) -> dict:
    for item in config_data.get("audit_types", []) or []:
        if str(item.get("code") or "").strip() == code:
            return item
    raise AssertionError(f"audit_type not found: {code}")


def test_template_json_parseable():
    cfg = _load_template()
    assert isinstance(cfg, dict)


def test_new_audit_types_exist_and_schema_valid():
    cfg = _load_template()
    for code in [
        "lab_exam_vs_progress_nursing",
        "frontpage_surgery_diagnosis_vs_first_progress",
        "orders_vs_progress",
    ]:
        raw = _find_audit_type(cfg, code)
        parsed = AuditTypeConfig.model_validate(raw)
        assert parsed.code == code


def test_lab_exam_template_contract():
    cfg = _load_template()
    raw = _find_audit_type(cfg, "lab_exam_vs_progress_nursing")
    assert raw.get("group_key") == ["patient_id", "visit_number", "audit_date"]
    payload = raw.get("payload", {}) or {}
    assert payload.get("builder") == "lab_exam_structured_progress_nursing"
    assert payload.get("date_window_days") == 0
    assert payload.get("progress_followup_days") == 1
    assert payload.get("max_lab_items") == 30
    assert payload.get("max_exam_reports") == 10
    assert payload.get("include_normal_summary") is False
    assert set((raw.get("sources") or {}).keys()) >= {"lab", "exam", "progress", "nursing"}
    lab_mapping = raw["sources"]["lab"].get("field_mapping", {}) or {}
    assert {"test_name", "report_item_name", "reference_range"}.issubset(set(lab_mapping.keys()))
    exam_mapping = raw["sources"]["exam"].get("field_mapping", {}) or {}
    assert {"exam_name", "report_time"}.issubset(set(exam_mapping.keys()))


def test_frontpage_template_contract():
    cfg = _load_template()
    raw = _find_audit_type(cfg, "frontpage_surgery_diagnosis_vs_first_progress")
    assert raw.get("group_key") == ["patient_id", "visit_number"]
    payload = raw.get("payload", {}) or {}
    assert payload.get("builder") == "frontpage_surgery_first_progress"
    assert set((raw.get("sources") or {}).keys()) >= {"frontpage", "first_progress"}


def test_orders_stub_not_default_schedule():
    cfg = _load_template()
    raw = _find_audit_type(cfg, "orders_vs_progress")
    assert raw.get("enabled") is False
    assert raw.get("default_for_schedule") is False


def test_placeholder_sql_contains_required_tokens_and_select_only():
    cfg = _load_template()
    source_matrix = {
        "lab_exam_vs_progress_nursing": ["lab", "exam", "progress", "nursing"],
        "frontpage_surgery_diagnosis_vs_first_progress": ["frontpage", "first_progress"],
    }
    for code, source_names in source_matrix.items():
        raw = _find_audit_type(cfg, code)
        sources = raw.get("sources", {}) or {}
        for source_name in source_names:
            source_cfg = sources.get(source_name) or {}
            sql_text = str(source_cfg.get("query_sql") or "")
            validate_configurable_sql(sql_text, f"{code}.{source_name}.query_sql")
            assert ":query_date" in sql_text
            assert "{dept_filter}" in sql_text


if __name__ == "__main__":
    tests = [
        test_template_json_parseable,
        test_new_audit_types_exist_and_schema_valid,
        test_lab_exam_template_contract,
        test_frontpage_template_contract,
        test_orders_stub_not_default_schedule,
        test_placeholder_sql_contains_required_tokens_and_select_only,
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
