"""四类数据源字段契约与日期归一工具（Task 2）。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any


REQUIRED_GROUP_KEYS = ("patient_id", "visit_number")

SOURCE_CANONICAL_FIELDS: dict[str, list[str]] = {
    "lab": [
        "test_no",
        "test_name",
        "result_time",
        "specimen",
        "item_name",
        "report_item_name",
        "report_item_code",
        "result",
        "units",
        "abnormal_indicator",
        "reference_range",
        "print_context",
    ],
    "exam": [
        "exam_no",
        "exam_time",
        "report_time",
        "exam_class",
        "exam_name",
        "description",
        "impression",
        "recommendation",
        "is_abnormal",
    ],
    "progress": ["event_time", "record_id", "record_name", "content"],
    "nursing": ["event_time", "record_id", "record_name", "content"],
    "frontpage": [
        "record_id",
        "record_name",
        "content",
        "admission_diagnosis",
        "discharge_diagnosis",
        "surgery_1",
        "surgery_2",
        "surgery_3",
        "surgery_4",
        "surgery_5",
    ],
    "first_progress": ["event_time", "record_id", "record_name", "content"],
}

TIME_KEY_CANDIDATES: dict[str, list[str]] = {
    "lab": ["result_time", "event_time"],
    "exam": ["report_time", "exam_time", "event_time"],
    "progress": ["event_time"],
    "nursing": ["event_time"],
    "frontpage": ["event_time", "discharge_date", "admission_date"],
    "first_progress": ["event_time"],
}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _pick(record: dict[str, Any], field_mapping: dict[str, str], canonical_key: str) -> str:
    candidates = [field_mapping.get(canonical_key), canonical_key]
    for key in candidates:
        if not key:
            continue
        value = record.get(str(key))
        text = _as_text(value)
        if text:
            return text
    return ""


def normalize_date_to_ymd(raw_value: Any) -> str:
    """将常见时间格式归一到 YYYY-MM-DD；失败返回空串。"""
    if raw_value is None:
        return ""
    if isinstance(raw_value, datetime):
        return raw_value.strftime("%Y-%m-%d")
    if isinstance(raw_value, date):
        return raw_value.strftime("%Y-%m-%d")

    text = _as_text(raw_value)
    if not text:
        return ""

    normalized = text.replace("年", "-").replace("月", "-").replace("日", "")
    normalized = normalized.replace("/", "-").replace(".", "-")
    normalized = " ".join(normalized.split())

    patterns = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d",
        "%Y%m%d%H%M%S",
    )
    for pattern in patterns:
        try:
            parsed = datetime.strptime(normalized, pattern)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue

    if len(normalized) >= 10 and normalized[4] == "-" and normalized[7] == "-":
        candidate = normalized[:10]
        try:
            datetime.strptime(candidate, "%Y-%m-%d")
            return candidate
        except ValueError:
            return ""
    return ""


def _resolve_audit_date(source_name: str, canonical: dict[str, str], query_date: str) -> str:
    for key in TIME_KEY_CANDIDATES.get(source_name, ["event_time"]):
        resolved = normalize_date_to_ymd(canonical.get(key, ""))
        if resolved:
            return resolved
    return normalize_date_to_ymd(query_date)


def should_attach_followup_progress(record_audit_date: str, base_audit_date: str, followup_days: int) -> bool:
    """progress follow-up window 判定：支持同日 + T+n。"""
    if followup_days <= 0:
        return False

    record_day = normalize_date_to_ymd(record_audit_date)
    base_day = normalize_date_to_ymd(base_audit_date)
    if not record_day or not base_day:
        return False

    record_dt = datetime.strptime(record_day, "%Y-%m-%d")
    base_dt = datetime.strptime(base_day, "%Y-%m-%d")
    delta_days = (record_dt - base_dt).days
    return 1 <= delta_days <= followup_days


def normalize_source_record(
    source_name: str,
    record: dict[str, Any],
    field_mapping: dict[str, str],
    query_date: str,
) -> tuple[dict[str, str], list[str]]:
    """按 source 契约提取 canonical 字段，并生成可诊断 skipped reason。"""
    canonical: dict[str, str] = {
        "patient_id": _pick(record, field_mapping, "patient_id"),
        "visit_number": _pick(record, field_mapping, "visit_number"),
        "record_id": _pick(record, field_mapping, "record_id"),
        "record_name": _pick(record, field_mapping, "record_name"),
        "content": _pick(record, field_mapping, "content"),
        "event_time": _pick(record, field_mapping, "event_time"),
    }

    for key in SOURCE_CANONICAL_FIELDS.get(source_name, []):
        if key not in canonical:
            canonical[key] = _pick(record, field_mapping, key)

    audit_date = _resolve_audit_date(source_name, canonical, query_date)
    canonical["audit_date"] = audit_date

    errors: list[str] = []
    missing_group = [key for key in REQUIRED_GROUP_KEYS if not canonical.get(key, "")]
    if missing_group:
        errors.append(f"missing_group_fields:{','.join(missing_group)}")
    if not audit_date:
        errors.append("invalid_audit_date")

    return canonical, errors
