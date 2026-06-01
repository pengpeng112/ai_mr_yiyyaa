"""Standalone tests for frontpage surgery payload builder (Task 16)."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas import AuditTypeConfig
from app.services.payload_composer import compose


def _build_audit_type() -> AuditTypeConfig:
    raw = {
        "code": "frontpage_surgery_diagnosis_vs_first_progress",
        "name": "病案首页手术诊断 vs 首次病程",
        "enabled": True,
        "sources": {
            "frontpage": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"}},
            "first_progress": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "患者ID", "visit_number": "次数"}},
        },
        "group_key": ["patient_id", "visit_number"],
        "payload": {
            "builder": "frontpage_surgery_first_progress",
            "record_name_include": ["术后首次病程记录"],
            "time_window_days": 3,
        },
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


def _build_bundle() -> SimpleNamespace:
    return SimpleNamespace(
        bundle_id="P_DEMO_020::1",
        group_values={"patient_id": "P_DEMO_020", "visit_number": "1"},
        sources={
            "frontpage": [
                {
                    "patient_id": "P_DEMO_020",
                    "visit_number": "1",
                    "patient_name": "患者乙",
                    "admission_no": "ZY20260020",
                    "admission_date": "2026-03-01",
                    "discharge_date": "2026-03-06",
                    "admission_diagnosis": "胆总管结石",
                    "discharge_diagnosis": "胆总管结石并感染",
                    "surgery": "手术名称:ERCP取石术,手术编码:51.8400,手术日期:2026-03-02,麻醉方式:全麻,手术级别:3级",
                }
            ],
            "first_progress": [
                {
                    "mrid": "MR-2001",
                    "record_name": "术后首次病程记录",
                    "title_time": "2026-03-02 14:20:00",
                    "record_date": "2026-03-02",
                    "rn": 1,
                    "content": "今日行ERCP取石术，术后生命体征平稳，已交代术后观察要点。",
                }
            ],
        },
        source_field_mappings={"frontpage": {}, "first_progress": {}},
        primary_source="frontpage",
        query_date="2026-03-06",
    )


def test_frontpage_builder_compose_sections_and_payload_fields():
    audit_type = _build_audit_type()
    bundle = _build_bundle()
    payload, mr_text = compose(audit_type, bundle, "2026-03-06")

    assert payload.get("audit_type_code") == "frontpage_surgery_diagnosis_vs_first_progress"
    assert isinstance(payload.get("surgeries"), list)
    assert payload.get("selected_first_progress")
    assert isinstance(payload.get("check_rules"), list)
    assert payload.get("mr_text") == mr_text
    assert "[首页手术与诊断]" in mr_text
    assert "[首次病程记录]" in mr_text


def test_frontpage_builder_fallback_warning_when_no_postop_name():
    audit_type = _build_audit_type()
    bundle = _build_bundle()
    bundle.sources["first_progress"][0]["record_name"] = "首次病程记录"
    payload, _ = compose(audit_type, bundle, "2026-03-06")
    warnings = payload.get("warnings") or []
    assert "no_post_op_first_progress" in warnings


def test_frontpage_builder_parses_english_month_surgery_date():
    audit_type = _build_audit_type()
    bundle = _build_bundle()
    bundle.sources["frontpage"][0]["surgery"] = "手术名称:ERCP取石术,手术编码:51.8400,手术日期:05-FEB-26,麻醉方式:全麻,手术级别:3级"
    bundle.sources["first_progress"][0]["title_time"] = "2026-02-05 14:20:00"
    bundle.sources["first_progress"][0]["record_date"] = "2026-02-05"

    payload, _ = compose(audit_type, bundle, "2026-02-06")

    assert payload["surgeries"][0]["operation_date"] == "2026-02-05"
    assert "date_unparseable" not in payload.get("warnings", [])
    assert payload.get("selected_first_progress")


def test_frontpage_builder_parses_four_digit_english_month_surgery_date():
    audit_type = _build_audit_type()
    bundle = _build_bundle()
    bundle.sources["frontpage"][0]["surgery"] = "手术名称:ERCP取石术,手术编码:51.8400,手术日期:05-FEB-2026,麻醉方式:全麻,手术级别:3级"
    bundle.sources["first_progress"][0]["title_time"] = "2026-02-05 14:20:00"
    bundle.sources["first_progress"][0]["record_date"] = "2026-02-05"

    payload, _ = compose(audit_type, bundle, "2026-02-06")

    assert payload["surgeries"][0]["operation_date"] == "2026-02-05"
    assert "date_unparseable" not in payload.get("warnings", [])
    assert payload.get("selected_first_progress")


if __name__ == "__main__":
    tests = [
        test_frontpage_builder_compose_sections_and_payload_fields,
        test_frontpage_builder_fallback_warning_when_no_postop_name,
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
