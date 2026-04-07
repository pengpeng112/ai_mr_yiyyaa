"""Patient snapshot extraction and privacy masking helpers."""

from __future__ import annotations

import json
from typing import Any, Dict


DEFAULT_PRIVACY_MASKING = {
    "enabled": False,
    "mask_name": True,
    "mask_id_card": True,
    "mask_address": True,
    "mask_phone": True,
}


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _as_text(value)
        if text:
            return text
    return ""


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _join_non_empty(parts: list[str], sep: str = " | ") -> str:
    return sep.join([part for part in parts if part])


def _format_medical_documents(payload: dict) -> str:
    documents = payload.get("medical_documents", [])
    if not isinstance(documents, list):
        return ""

    lines: list[str] = []
    for index, item in enumerate(documents, start=1):
        if not isinstance(item, dict):
            continue
        header = _join_non_empty(
            [
                f"时间：{_as_text(item.get('document_time'))}",
                f"文书：{_as_text(item.get('document_name'))}",
                f"医师：{_as_text(item.get('signed_doctor'))}",
            ]
        )
        content = _as_text(item.get("content"))
        if not header and not content:
            continue
        lines.append(f"{index}. {header}" if header else f"{index}.")
        if content:
            lines.append(content)
    return "\n\n".join(lines)


def _format_nursing_records(payload: dict) -> str:
    records = payload.get("nursing_records", [])
    if not isinstance(records, list):
        return ""

    lines: list[str] = []
    for index, item in enumerate(records, start=1):
        if not isinstance(item, dict):
            continue
        header = _join_non_empty(
            [
                f"时间：{_as_text(item.get('record_time'))}",
                f"类型：{_as_text(item.get('record_type'))}",
                f"记录人：{_as_text(item.get('recorder'))}",
            ]
        )
        content = _as_text(item.get("content"))
        vitals = item.get("vitals", {}) if isinstance(item.get("vitals"), dict) else {}
        assessment = item.get("assessment", {}) if isinstance(item.get("assessment"), dict) else {}
        supportive = item.get("supportive_care", {}) if isinstance(item.get("supportive_care"), dict) else {}

        vital_line = _join_non_empty(
            [
                f"体温：{_as_text(vitals.get('temperature'))}",
                f"脉搏/心率：{_as_text(vitals.get('heart_rate_pulse'))}",
                f"呼吸：{_as_text(vitals.get('respiratory_rate'))}",
                f"血压：{_as_text(vitals.get('blood_pressure'))}",
                f"血氧：{_as_text(vitals.get('oxygen_saturation'))}",
                f"血糖：{_as_text(vitals.get('blood_glucose'))}",
            ]
        )
        assessment_line = _join_non_empty(
            [
                f"意识：{_as_text(assessment.get('consciousness'))}",
                f"皮肤：{_as_text(assessment.get('skin_condition'))}",
                f"刀口：{_as_text(assessment.get('wound_condition'))}",
                f"管道：{_as_text(assessment.get('tube_care'))}",
                f"高危风险：{_as_text(assessment.get('high_risk'))}",
            ]
        )
        supportive_line = _join_non_empty(
            [
                f"入量：{_as_text(supportive.get('intake'))}",
                f"出量：{_as_text(supportive.get('output'))}",
                f"尿量：{_as_text(supportive.get('urine_volume'))}",
                f"鼻导管氧疗：{_as_text(supportive.get('oxygen_nasal_cannula'))}",
                f"面罩氧疗：{_as_text(supportive.get('oxygen_mask'))}",
            ]
        )

        if not any([header, content, vital_line, assessment_line, supportive_line]):
            continue
        lines.append(f"{index}. {header}" if header else f"{index}.")
        if content:
            lines.append(content)
        if vital_line:
            lines.append(f"生命体征：{vital_line}")
        if assessment_line:
            lines.append(f"护理评估：{assessment_line}")
        if supportive_line:
            lines.append(f"支持治疗：{supportive_line}")
    return "\n\n".join(lines)


def extract_patient_snapshot(push_log: Any) -> Dict[str, str]:
    """Extract patient context from push log/request_json payload."""
    payload = _parse_json(getattr(push_log, "request_json", "") or "")
    patient_info = payload.get("patient_info", {}) if isinstance(payload.get("patient_info"), dict) else {}

    dept_name = _first_non_empty(
        patient_info.get("department"),
        patient_info.get("dept"),
        getattr(push_log, "dept", ""),
        payload.get("所在科室名称"),
        payload.get("科室"),
    )

    return {
        "patient_name": _first_non_empty(
            patient_info.get("patient_name"),
            payload.get("patient_name"),
            payload.get("患者姓名"),
            getattr(push_log, "patient_name", ""),
        ),
        "patient_id": _first_non_empty(
            patient_info.get("patient_id"),
            payload.get("patient_id"),
            payload.get("患者ID"),
            getattr(push_log, "patient_id", ""),
        ),
        "admission_no": _first_non_empty(
            patient_info.get("admission_no"),
            payload.get("admission_no"),
            payload.get("住院号"),
            getattr(push_log, "admission_no", ""),
        ),
        "dept_name": dept_name,
        "admission_date": _first_non_empty(
            patient_info.get("admission_date"),
            payload.get("admission_date"),
            payload.get("入院日期"),
        ),
        "discharge_date": _first_non_empty(
            patient_info.get("discharge_date"),
            payload.get("discharge_date"),
            payload.get("出院日期"),
        ),
        "admission_diagnosis": _first_non_empty(
            patient_info.get("admission_diagnosis"),
            payload.get("admission_diagnosis"),
            payload.get("入院诊断"),
        ),
        "is_discharged": _first_non_empty(
            patient_info.get("is_discharged"),
            payload.get("is_discharged"),
            payload.get("是否出院"),
        ),
        "admission_dept_name": _first_non_empty(
            patient_info.get("admission_dept_name"),
            payload.get("admission_dept_name"),
            payload.get("入院科室名称"),
        ),
        "discharge_dept_name": _first_non_empty(
            patient_info.get("discharge_dept_name"),
            payload.get("discharge_dept_name"),
            payload.get("出院科室名称"),
        ),
        "discharge_main_diagnosis": _first_non_empty(
            patient_info.get("discharge_main_diagnosis"),
            payload.get("discharge_main_diagnosis"),
            payload.get("出院主诊断"),
        ),
        "surgery": _first_non_empty(
            patient_info.get("surgery"),
            payload.get("surgery"),
            payload.get("手术"),
        ),
        "id_card": _first_non_empty(
            patient_info.get("id_card"),
            patient_info.get("idcard"),
            payload.get("id_card"),
            payload.get("idcard"),
            payload.get("身份证号"),
            payload.get("身份证"),
        ),
        "address": _first_non_empty(
            patient_info.get("address"),
            payload.get("address"),
            payload.get("住址"),
            payload.get("家庭住址"),
        ),
        "phone": _first_non_empty(
            patient_info.get("phone"),
            payload.get("phone"),
            payload.get("联系电话"),
            payload.get("手机号"),
            payload.get("手机"),
        ),
    }


def extract_raw_record_sections(push_log: Any) -> Dict[str, str]:
    payload = _parse_json(getattr(push_log, "request_json", "") or "")
    if not payload:
        return {
            "medical_documents_text": "",
            "nursing_records_text": "",
        }

    return {
        "medical_documents_text": _format_medical_documents(payload),
        "nursing_records_text": _format_nursing_records(payload),
    }


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def normalize_privacy_masking_config(raw_cfg: Dict[str, Any] | None) -> Dict[str, bool]:
    cfg = dict(DEFAULT_PRIVACY_MASKING)
    raw = raw_cfg or {}
    for key, default in DEFAULT_PRIVACY_MASKING.items():
        cfg[key] = _to_bool(raw.get(key), default)
    return cfg


def _mask_name(value: str) -> str:
    text = _as_text(value)
    if not text:
        return ""
    if len(text) <= 1:
        return "*"
    if len(text) == 2:
        return text[0] + "*"
    return text[0] + "*" * (len(text) - 2) + text[-1]


def _mask_id_card(value: str) -> str:
    text = _as_text(value)
    if not text:
        return ""
    if len(text) <= 2:
        return "*" * len(text)
    if len(text) <= 6:
        return text[:1] + "*" * max(1, len(text) - 2) + text[-1:]
    if len(text) <= 10:
        return text[:3] + "*" * max(1, len(text) - 5) + text[-2:]
    return text[:6] + "*" * max(1, len(text) - 10) + text[-4:]


def _mask_address(value: str) -> str:
    text = _as_text(value)
    if len(text) <= 6:
        return "*" * len(text) if text else ""
    return text[:6] + "*" * max(4, len(text) - 6)


def _mask_phone(value: str) -> str:
    text = _as_text(value)
    if len(text) <= 7:
        return "*" * len(text) if text else ""
    return text[:3] + "*" * (len(text) - 7) + text[-4:]


def apply_privacy_masking(snapshot: Dict[str, str], mask_cfg: Dict[str, Any] | None) -> Dict[str, str]:
    cfg = normalize_privacy_masking_config(mask_cfg)
    data = dict(snapshot or {})
    if not cfg.get("enabled", False):
        return data
    if cfg.get("mask_name", True):
        data["patient_name"] = _mask_name(data.get("patient_name", ""))
    if cfg.get("mask_id_card", True):
        data["id_card"] = _mask_id_card(data.get("id_card", ""))
    if cfg.get("mask_address", True):
        data["address"] = _mask_address(data.get("address", ""))
    if cfg.get("mask_phone", True):
        data["phone"] = _mask_phone(data.get("phone", ""))
    return data
