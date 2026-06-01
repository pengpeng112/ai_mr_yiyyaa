"""frontpage_surgery_diagnosis_vs_first_progress payload builder（Task 16）。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas import AuditTypeConfig
from app.services.first_progress_matcher import select_first_progress_record
from app.services.frontpage_surgery_parser import parse_frontpage_record

if TYPE_CHECKING:
    from app.services.data_source_loader import PatientBundle
else:
    PatientBundle = Any


def _build_rules() -> list[dict[str, str]]:
    return [
        {"code": "operation_name_consistency", "desc": "首页手术名称在首次病程中是否有对应描述或同义描述"},
        {"code": "operation_date_consistency", "desc": "首页手术日期与首次病程标题时间/病历日期是否一致或在窗口内"},
        {"code": "anesthesia_consistency", "desc": "麻醉方式在首页与首次病程中是否一致"},
        {"code": "diagnosis_consistency", "desc": "首页主要/重要诊断是否在首次病程体现"},
        {"code": "postoperative_plan_completeness", "desc": "首次病程是否记录术后处理/医嘱/告知与生命体征"},
        {"code": "multi_operation_omission", "desc": "首页多台手术时首次病程是否遗漏关键手术"},
    ]


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _pick(record: dict[str, Any], *keys: str | None) -> str:
    for key in keys:
        if not key:
            continue
        text = _as_text(record.get(key))
        if text:
            return text
    return ""


def _join_surgeries(surgeries: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in surgeries:
        if not isinstance(item, dict):
            continue
        text = _pick(item, "raw_text")
        if not text:
            text = _pick(item, "operation_name")
        if text and text not in parts:
            parts.append(text)
    return "；".join(parts)


def _build_mr_text(
    query_date: str,
    patient_info: dict[str, str],
    parsed_frontpage: dict[str, Any],
    matched_progress: dict[str, Any],
    warnings: list[str],
) -> str:
    lines: list[str] = [
        f"审核日期: {query_date}",
        f"患者ID: {patient_info.get('patient_id', '')}",
        f"住院次数: {patient_info.get('visit_number', '')}",
        f"住院号: {patient_info.get('admission_no', '')}",
        f"患者姓名: {patient_info.get('patient_name', '')}",
        "",
        "[首页手术与诊断]",
    ]

    diagnoses = parsed_frontpage.get("diagnoses") or {}
    lines.append(f"- 入院诊断: {diagnoses.get('admission_diagnosis', '')}")
    lines.append(f"- 出院主诊断: {diagnoses.get('discharge_primary_diagnosis', '')}")
    other = diagnoses.get("discharge_other_diagnoses") or []
    if other:
        lines.append("- 出院其他诊断: " + "；".join(str(item.get("value") or "") for item in other if str(item.get("value") or "").strip()))

    surgeries = parsed_frontpage.get("surgeries") or []
    if not surgeries:
        lines.append("- 未解析到首页手术")
    else:
        for idx, item in enumerate(surgeries, start=1):
            lines.append(
                f"- 手术{idx}: {item.get('operation_name', '')} | 日期:{item.get('operation_date', '')} "
                f"| 麻醉:{item.get('anesthesia_method', '')} | 级别:{item.get('operation_level', '')} | 编码:{item.get('operation_code', '')}"
            )
            if item.get("warnings"):
                lines.append(f"  warnings: {','.join(item.get('warnings') or [])}")

    lines.extend(["", "[首次病程记录]"])
    selected = matched_progress.get("selected_progress")
    if not selected:
        lines.append("- 未匹配到首次病程记录")
    else:
        lines.append(f"- MRID: {selected.get('mrid', '')}")
        lines.append(f"- 记录名称: {selected.get('record_name', '')}")
        lines.append(f"- 标题时间: {selected.get('title_time', selected.get('event_time', ''))}")
        lines.append(f"- 内容: {selected.get('content', '')}")

    lines.extend(["", "[核查规则]"])
    for rule in _build_rules():
        lines.append(f"- {rule['code']}: {rule['desc']}")

    if warnings:
        lines.extend(["", "[注意事项]", "- " + "；".join(warnings)])
    return "\n".join(lines).strip()


def build_frontpage_surgery_first_progress_payload(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> tuple[dict[str, Any], str]:
    """构建病案首页手术诊断 vs 首次病程 payload。"""
    payload_cfg = audit_type.payload or {}
    frontpage_records = bundle.sources.get("frontpage", []) or []
    progress_records = bundle.sources.get("first_progress", []) or []

    frontpage_record = frontpage_records[0] if frontpage_records else {}
    parsed_frontpage = parse_frontpage_record(
        frontpage_record,
        {
            "surgery_fields": payload_cfg.get("surgery_fields", []),
            "diagnosis_fields": payload_cfg.get("diagnosis_fields", {}),
        },
    )
    matched = select_first_progress_record(
        parsed_frontpage.get("surgeries") or [],
        progress_records,
        {
            "record_name_include": payload_cfg.get("record_name_include") or ["术后首次病程记录"],
            "record_type_include": payload_cfg.get("record_type_include") or [],
            "rn_priority": payload_cfg.get("rn_priority") or [1],
            "time_window_days": payload_cfg.get("time_window_days", 3),
        },
    )

    diagnoses = parsed_frontpage.get("diagnoses") or {}
    admission_discharge_info = parsed_frontpage.get("admission_discharge_info") or {}
    surgeries = parsed_frontpage.get("surgeries") or []
    dept = _pick(
        frontpage_record,
        "dept",
        "department",
        "所在科室名称",
        "科室",
        "病区",
        "入院科室名称",
        "出院科室名称",
    )
    patient_info = {
        "patient_id": parsed_frontpage.get("patient_id") or bundle.group_values.get("patient_id", ""),
        "visit_number": parsed_frontpage.get("visit_number") or bundle.group_values.get("visit_number", ""),
        "patient_name": parsed_frontpage.get("patient_name", ""),
        "admission_no": parsed_frontpage.get("admission_no", ""),
        "dept": dept,
        "department": dept,
        "admission_date": _pick(admission_discharge_info, "admission_date") or _pick(frontpage_record, "admission_date", "入院日期"),
        "discharge_date": _pick(admission_discharge_info, "discharge_date") or _pick(frontpage_record, "discharge_date", "出院日期"),
        "admission_diagnosis": _pick(diagnoses, "admission_diagnosis") or _pick(frontpage_record, "admission_diagnosis", "入院诊断"),
        "discharge_main_diagnosis": _pick(diagnoses, "discharge_primary_diagnosis") or _pick(frontpage_record, "discharge_main_diagnosis", "discharge_primary_diagnosis", "出院主诊断", "出院诊断"),
        "surgery": _join_surgeries(surgeries) or _pick(frontpage_record, "surgery", "手术", "手术名称"),
        "is_discharged": _pick(frontpage_record, "is_discharged", "是否出院"),
        "admission_dept_name": _pick(frontpage_record, "admission_dept_name", "入院科室名称"),
        "discharge_dept_name": _pick(frontpage_record, "discharge_dept_name", "出院科室名称"),
        "id_card": _pick(frontpage_record, "id_card", "idcard", "身份证号", "身份证"),
        "address": _pick(frontpage_record, "address", "住址", "家庭住址"),
        "phone": _pick(frontpage_record, "phone", "联系电话", "手机号", "手机"),
    }
    warnings = list(parsed_frontpage.get("warnings") or [])
    warnings.extend(parsed_frontpage.get("missing_fields") or [])
    warnings.extend(matched.get("match_warnings") or [])

    payload = {
        "request_id": f"{audit_type.code}:{bundle.bundle_id}:{query_date}",
        "audit_date": query_date,
        "audit_type_code": audit_type.code,
        "audit_type_name": audit_type.name,
        "patient_info": patient_info,
        "admission_discharge_info": parsed_frontpage.get("admission_discharge_info") or {},
        "diagnoses": parsed_frontpage.get("diagnoses") or {},
        "surgeries": parsed_frontpage.get("surgeries") or [],
        "selected_first_progress": matched.get("selected_progress"),
        "first_progress_candidate_count": matched.get("candidate_count", 0),
        "check_rules": _build_rules(),
        "warnings": warnings,
    }
    mr_text = _build_mr_text(query_date, patient_info, parsed_frontpage, matched, warnings)
    payload["mr_text"] = mr_text
    return payload, mr_text
