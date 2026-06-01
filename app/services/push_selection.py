"""推送选择与 bundle 匹配工具函数。"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.services.record_identity import get_bundle_source_key, get_record_mrid, get_record_source_key

logger = logging.getLogger(__name__)

KEY_PATIENT_ID = "患者ID"
KEY_VISIT_NO = "次数"
KEY_MR_FINISH_TIME = "病历文书_完成时间"
SOURCE_RECORD_KEY_FIELD = "source_record_key"


def legacy_medical_record_source_key(record: dict, field_mapping: dict | None = None) -> str:
    """Build one stable key per medical document for legacy progress/nursing SQL rows."""
    mapping = field_mapping or {}
    patient_id = str(record.get(mapping.get("patient_id", KEY_PATIENT_ID)) or record.get(KEY_PATIENT_ID) or "").strip()
    visit_number = str(record.get(mapping.get("visit_number", KEY_VISIT_NO)) or record.get(KEY_VISIT_NO) or "").strip()
    document_values = [
        str(record.get(KEY_MR_FINISH_TIME) or record.get("病历文书_完成时间") or "").strip(),
        str(record.get("病历文书_名称") or record.get("病历名称") or "").strip(),
        str(record.get("病历文书_签名医师") or record.get("病历创建人") or record.get("创建人") or "").strip(),
        str(record.get("病历文书_内容") or record.get("病历内容") or "").strip(),
    ]
    if any(document_values):
        identity_text = "\x1f".join([patient_id, visit_number, *document_values])
        digest = hashlib.sha1(identity_text.encode("utf-8", errors="ignore")).hexdigest()[:24]
        return f"legacy-mr::{patient_id or 'unknown'}::{visit_number or 'unknown'}::{digest}"
    return get_record_source_key(record)


def filter_grouped_records(grouped: dict, selected_record_keys: list[str] | None) -> dict:
    """按选中的记录 key 过滤分组记录。"""
    if not selected_record_keys:
        return grouped
    selected = {str(item or "").strip() for item in selected_record_keys if str(item or "").strip()}
    return {
        key: value
        for key, value in grouped.items()
        if key in selected or f"progress_vs_nursing::{key}" in selected
    }


def audit_type_code(audit_type: Any) -> str:
    """提取审计类型 code。"""
    if isinstance(audit_type, dict):
        return str(audit_type.get("code") or "").strip()
    return str(getattr(audit_type, "code", "") or "").strip()


def audit_type_group_key(audit_type: Any) -> list[str]:
    """提取审计类型 group_key。"""
    if isinstance(audit_type, dict):
        group_key = audit_type.get("group_key") or []
    else:
        group_key = getattr(audit_type, "group_key", []) or []
    return [str(item or "").strip() for item in group_key if str(item or "").strip()] or ["patient_id", "visit_number"]


def add_selection_key(keys: set[str], value: Any) -> None:
    """向 keys 集合添加非空字符串值。"""
    text = str(value or "").strip()
    if text:
        keys.add(text)


def bundle_selection_keys(bundle: Any, audit_type: Any) -> set[str]:
    """Build compatible keys for matching manual-preview selected rows to audit bundles."""
    keys: set[str] = set()
    code = audit_type_code(audit_type)
    bundle_id = str(getattr(bundle, "bundle_id", "") or "").strip()
    add_selection_key(keys, bundle_id)
    if code and bundle_id:
        add_selection_key(keys, f"{code}::{bundle_id}")
    try:
        add_selection_key(keys, get_bundle_source_key(bundle, audit_type))
    except Exception:
        logger.debug("failed to build bundle source key for selected-record matching", exc_info=True)

    group_values = getattr(bundle, "group_values", {}) or {}
    if isinstance(group_values, dict):
        group_key = audit_type_group_key(audit_type)
        ordered_values = [str(group_values.get(key, "") or "").strip() for key in group_key]
        min_prefix_len = min(2, len(ordered_values))
        for size in range(min_prefix_len, len(ordered_values) + 1):
            current = ordered_values[:size]
            if all(current):
                group_identity = "::".join(current)
                add_selection_key(keys, group_identity)
                if code:
                    add_selection_key(keys, f"{code}::{group_identity}")
        patient_id = str(group_values.get("patient_id", "") or "").strip()
        visit_number = str(group_values.get("visit_number", "") or "").strip()
        if patient_id and visit_number:
            group_identity = f"{patient_id}::{visit_number}"
            add_selection_key(keys, group_identity)
            if code:
                add_selection_key(keys, f"{code}::{group_identity}")

    sources = getattr(bundle, "sources", {}) or {}
    if isinstance(sources, dict):
        for records in sources.values():
            if isinstance(records, dict):
                iterable_records = [records]
            else:
                iterable_records = records or []
            for record in iterable_records:
                if not isinstance(record, dict):
                    continue
                add_selection_key(keys, get_record_source_key(record))
                mrid = get_record_mrid(record)
                if mrid:
                    add_selection_key(keys, f"mrid::{mrid}")
                patient_id = str(record.get("patient_id") or record.get(KEY_PATIENT_ID) or "").strip()
                visit_number = str(record.get("visit_number") or record.get(KEY_VISIT_NO) or "").strip()
                if patient_id and visit_number:
                    add_selection_key(keys, f"{patient_id}::{visit_number}")
                    audit_date = str(record.get("audit_date") or record.get("query_date") or "").strip()
                    if audit_date:
                        add_selection_key(keys, f"{patient_id}::{visit_number}::{audit_date}")
    return keys


def selection_key_matches(bundle_keys: set[str], selected_keys: set[str]) -> bool:
    """判断 bundle keys 与 selected keys 是否匹配。"""
    if bundle_keys & selected_keys:
        return True
    for selected in selected_keys:
        for candidate in bundle_keys:
            if candidate.startswith(f"{selected}::") or selected.startswith(f"{candidate}::"):
                return True
    return False


def filter_bundles_by_selected_record_keys(grouped: dict, selected_record_keys: list[str] | None, audit_type: Any) -> dict:
    """按选中的记录 key 过滤 bundle。"""
    if not selected_record_keys:
        return grouped
    selected = {str(item or "").strip() for item in selected_record_keys if str(item or "").strip()}
    if not selected:
        return grouped

    filtered = {}
    for key, bundle in grouped.items():
        b_keys = bundle_selection_keys(bundle, audit_type)
        add_selection_key(b_keys, key)
        if selection_key_matches(b_keys, selected):
            filtered[key] = bundle

    logger.info(
        "[selected_record_filter] audit_type=%s selected_keys=%s grouped_before=%s grouped_after=%s",
        audit_type_code(audit_type) or "unknown",
        len(selected),
        len(grouped),
        len(filtered),
    )
    return filtered


def selected_audit_type_codes_from_keys(selected_record_keys: list[str] | None, audit_types: list) -> set[str]:
    """Extract explicit audit-type prefixes from selected keys."""
    if not selected_record_keys:
        return set()
    available_codes = {audit_type_code(item) for item in audit_types if audit_type_code(item)}
    selected_codes: set[str] = set()
    for raw_key in selected_record_keys:
        key = str(raw_key or "").strip()
        if not key:
            continue
        for code in available_codes:
            if key.startswith(f"{code}::"):
                selected_codes.add(code)
    return selected_codes


def scope_audit_types_by_selected_record_keys(audit_types: list, selected_record_keys: list[str] | None) -> list:
    """按选中的记录 key 限定审计类型范围。"""
    selected_codes = selected_audit_type_codes_from_keys(selected_record_keys, audit_types)
    if not selected_codes:
        return audit_types
    scoped = [item for item in audit_types if audit_type_code(item) in selected_codes]
    return scoped or audit_types
