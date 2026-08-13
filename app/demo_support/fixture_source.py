"""手动推送页使用的脱敏合成临床数据源。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.demo_support.dataset import DEPARTMENTS, SYNTHETIC_LABEL
from app.services.isolated_mode import assert_fixture_source_allowed


IDENTITY_MAPPING = {
    "patient_id": "patient_id",
    "visit_number": "visit_number",
    "patient_name": "patient_name",
    "admission_no": "admission_no",
    "dept": "dept",
    "record_key": "record_key",
    "record_name": "record_name",
    "content": "content",
    "event_time": "event_time",
    "audit_date": "audit_date",
}


def _record(source: str, patient: dict[str, str], query_date: str, ordinal: int) -> dict[str, Any]:
    event_time = f"{query_date} {8 + ordinal:02d}:20:00"
    common: dict[str, Any] = {
        **patient,
        "record_key": f"{patient['patient_id']}::{patient['visit_number']}::{source}",
        "source_record_key": f"{patient['patient_id']}::{patient['visit_number']}::{source}",
        "record_id": f"REC-{patient['patient_id']}-{source}",
        "record_name": f"{source}脱敏测试文书",
        "record_type": source,
        "event_time": event_time,
        "create_date": event_time,
        "audit_date": query_date,
        "creator": "测试医生",
        "content": f"{SYNTHETIC_LABEL}。用于验证{source}质控链路；症状、诊断和处置均为虚构。",
        "admission_date": (datetime.fromisoformat(query_date) - timedelta(days=5)).strftime("%Y-%m-%d"),
        "discharge_date": query_date,
        "admission_diagnosis": "测试性眩晕待查",
        "discharge_main_diagnosis": "测试性眩晕",
        "admission_dept_name": patient["dept"],
        "discharge_dept_name": patient["dept"],
        "attending_doctor_userid": f"demo-doctor-{patient['dept_code'][-3:].lower()}",
        "attending_doctor_name": "测试医生",
        "nurse_head_userid": f"demo-manager-{patient['dept_code'][-3:].lower()}",
        "nurse_head_name": "测试护士长",
    }
    if source == "lab":
        common.update({"test_no": common["record_id"], "test_name": "血常规", "item_name": "白细胞", "result_value": "12.1", "reference_range": "3.5-9.5", "is_abnormal": True, "abnormal_flag": "H", "result_time": event_time})
    elif source == "exam":
        common.update({"exam_no": common["record_id"], "exam_name": "头颅CT", "exam_class": "影像", "finding": "脱敏测试异常影", "conclusion": "建议结合临床（测试）", "is_abnormal": True, "report_time": event_time})
    elif source == "frontpage":
        common.update({"surgery": "测试性内镜检查|2026-08-10|局部麻醉", "operation_name": "测试性内镜检查", "operation_date": query_date, "anesthesia_method": "局部麻醉"})
    elif source == "first_progress":
        common.update({"record_name": "术后首次病程记录", "rn": 1, "title_time": event_time, "mrid": common["record_id"]})
    elif source == "perioperative":
        common.update({"record_type": ["术前小结", "手术记录", "术后首次病程"][ordinal % 3], "record_name": ["术前小结", "手术记录", "术后首次病程"][ordinal % 3]})
    return common


def load_fixture_patient_bundles(
    audit_type,
    query_date: str,
    dept_filter: list[str] | None = None,
    return_diagnostics: bool = False,
    audit_run_mode: str = "",
):
    assert_fixture_source_allowed()
    from app.services.data_source_loader import PatientBundle

    selected = {str(value).strip() for value in (dept_filter or []) if str(value).strip()}
    specs = [(code, name) for code, name in DEPARTMENTS if not selected or code in selected or name in selected]
    source_names = list((audit_type.sources or {}).keys())
    bundles: list[PatientBundle] = []
    row_counts = {name: 0 for name in source_names}
    for dept_index, (dept_code, dept_name) in enumerate(specs, start=1):
        for ordinal in range(1, 3):
            patient = {
                "patient_id": f"SYNTH-FIX-{dept_index:02d}-{ordinal:02d}",
                "visit_number": "1",
                "patient_name": f"测试患者{dept_index:02d}{ordinal:02d}",
                "admission_no": f"SYNTH-ZY-{dept_index:02d}{ordinal:02d}",
                "dept": dept_name,
                "dept_code": dept_code,
            }
            sources: dict[str, list[dict[str, Any]]] = {}
            for source_index, source_name in enumerate(source_names):
                records = [_record(source_name, patient, query_date, source_index + ordinal)]
                if source_name == "perioperative":
                    records = [_record(source_name, patient, query_date, item) for item in range(3)]
                sources[source_name] = records
                row_counts[source_name] += len(records)
            group_values = {"patient_id": patient["patient_id"], "visit_number": patient["visit_number"]}
            if "audit_date" in list(getattr(audit_type, "group_key", []) or []):
                group_values["audit_date"] = query_date
            bundle_id = "::".join(str(group_values.get(key, "")) for key in (list(getattr(audit_type, "group_key", [])) or ["patient_id", "visit_number"]))
            bundles.append(
                PatientBundle(
                    bundle_id=bundle_id,
                    group_values=group_values,
                    sources=sources,
                    source_field_mappings={name: dict(IDENTITY_MAPPING) for name in source_names},
                    primary_source=source_names[0] if source_names else "primary",
                    query_date=query_date,
                    relation_metadata={"synthetic": True, "audit_run_mode": audit_run_mode or "daily_increment"},
                )
            )
    diagnostics = {"source_row_counts": row_counts, "skipped_records": 0, "synthetic": True}
    return (bundles, diagnostics) if return_diagnostics else bundles
