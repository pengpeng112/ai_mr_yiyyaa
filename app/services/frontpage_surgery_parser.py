"""病案首页手术/诊断解析工具（Task 14/16）。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.source_field_contract import normalize_date_to_ymd


_SURGERY_DEFAULT_FIELDS = [
    "surgery",
    "surgery_1",
    "surgery_2",
    "surgery_3",
    "surgery_4",
    "surgery_5",
    "手术",
    "手术1",
    "手术2",
    "手术3",
    "手术4",
    "手术5",
]
_DISCHARGE_OTHER_DIAG_FIELDS = [
    "discharge_other_diagnosis_1",
    "discharge_other_diagnosis_2",
    "discharge_other_diagnosis_3",
    "discharge_other_diagnosis_4",
    "discharge_other_diagnosis_5",
    "出院其他诊断1",
    "出院其他诊断2",
    "出院其他诊断3",
    "出院其他诊断4",
    "出院其他诊断5",
]
_EN_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}


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


def _parse_english_month_date(text: str) -> str | None:
    matched = re.search(r"^(\d{1,2})-([A-Z]{3})-(\d{2,4})$", text.upper().strip())
    if not matched:
        return None
    day = int(matched.group(1))
    month = _EN_MONTHS.get(matched.group(2))
    year = int(matched.group(3))
    if not month:
        return None
    if year < 100:
        year += 2000
    try:
        return datetime(year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _normalize_operation_date(raw_date: str) -> tuple[str, str | None]:
    text = _as_text(raw_date)
    if not text:
        return "", None

    direct = normalize_date_to_ymd(text)
    if direct:
        return direct, None

    compact = re.sub(r"\s+", "", text)
    upper_compact = compact.upper()
    parsed_english_month = _parse_english_month_date(upper_compact)
    if parsed_english_month:
        return parsed_english_month, None

    matched = re.search(r"^(\d{1,2})-(\d{1,2})月-(\d{2,4})$", compact)
    if not matched:
        matched = re.search(r"^(\d{1,2})-(\d{1,2})-(\d{2,4})$", compact)
    if matched:
        day = int(matched.group(1))
        month = int(matched.group(2))
        year = int(matched.group(3))
        if year < 100:
            year += 2000
        try:
            resolved = datetime(year, month, day).strftime("%Y-%m-%d")
            return resolved, None
        except ValueError:
            return "", "date_unparseable"

    return "", "date_unparseable"


def parse_surgery_text(raw_text: str) -> dict[str, Any]:
    """解析首页手术半结构化文本，保留 raw_text 与 warnings。"""
    text = _as_text(raw_text)
    parsed = {
        "operation_name": "",
        "operation_code": "",
        "wound_healing_grade": "",
        "incision_grade": "",
        "operation_date": "",
        "anesthesia_method": "",
        "operation_level": "",
        "raw_text": text,
        "warnings": [],
    }
    if not text:
        parsed["warnings"].append("empty_surgery_text")
        return parsed

    mapping = {
        "手术名称": "operation_name",
        "手术编码": "operation_code",
        "切口愈合等级": "wound_healing_grade",
        "切口等级": "incision_grade",
        "手术日期": "operation_date",
        "麻醉方式": "anesthesia_method",
        "手术级别": "operation_level",
    }
    tokens = re.split(r"[,，]\s*", text)
    for token in tokens:
        parts = re.split(r"[:：]", token, maxsplit=1)
        if len(parts) != 2:
            continue
        key = _as_text(parts[0])
        value = _as_text(parts[1])
        target = mapping.get(key)
        if not target:
            continue
        parsed[target] = value

    parsed_date, date_warning = _normalize_operation_date(parsed.get("operation_date", ""))
    if parsed.get("operation_date") and parsed_date:
        parsed["operation_date"] = parsed_date
    elif parsed.get("operation_date") and date_warning:
        parsed["warnings"].append(date_warning)

    if not parsed.get("operation_name"):
        parsed["warnings"].append("missing_operation_name")
    return parsed


def parse_frontpage_record(record: dict[str, Any], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """解析首页记录为结构化诊断与手术数组。"""
    cfg = options or {}
    surgery_fields = cfg.get("surgery_fields") or _SURGERY_DEFAULT_FIELDS
    diagnosis_fields = cfg.get("diagnosis_fields") or {
        "admission": ["admission_diagnosis", "入院诊断"],
        "discharge_primary": ["discharge_primary_diagnosis", "discharge_diagnosis", "出院主诊断", "出院诊断"],
        "discharge_other": _DISCHARGE_OTHER_DIAG_FIELDS,
    }

    surgeries: list[dict[str, Any]] = []
    warnings: list[str] = []
    missing_fields: list[str] = []
    for field in surgery_fields:
        raw = _as_text(record.get(field))
        if not raw:
            continue
        surgery = parse_surgery_text(raw)
        surgery["source_field"] = str(field)
        surgeries.append(surgery)
    if not surgeries:
        warnings.append("no_surgery_found")

    admission_diag = _pick(record, *(diagnosis_fields.get("admission") or []))
    discharge_primary = _pick(record, *(diagnosis_fields.get("discharge_primary") or []))

    discharge_other: list[dict[str, str]] = []
    seen_other: set[str] = set()
    for field in diagnosis_fields.get("discharge_other") or []:
        value = _as_text(record.get(field))
        if not value:
            continue
        if value in seen_other:
            continue
        seen_other.add(value)
        discharge_other.append({"value": value, "source_field": str(field)})

    if not admission_diag:
        missing_fields.append("admission_diagnosis")
    if not discharge_primary:
        missing_fields.append("discharge_primary_diagnosis")

    admission_date = _pick(record, "admission_date", "入院日期")
    discharge_date = _pick(record, "discharge_date", "出院日期")

    return {
        "patient_id": _pick(record, "patient_id", "患者ID"),
        "visit_number": _pick(record, "visit_number", "次数"),
        "patient_name": _pick(record, "patient_name", "患者姓名"),
        "admission_no": _pick(record, "admission_no", "住院号"),
        "admission_discharge_info": {
            "admission_date": admission_date,
            "discharge_date": discharge_date,
        },
        "diagnoses": {
            "admission_diagnosis": admission_diag,
            "discharge_primary_diagnosis": discharge_primary,
            "discharge_other_diagnoses": discharge_other,
        },
        "surgeries": surgeries,
        "warnings": warnings,
        "missing_fields": missing_fields,
    }
