"""历史重跑业务身份与候选哈希（ACTIVE/007 §4.2）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional


def normalize_identity_parts(
    source_record_key: str,
    audit_type_code: str,
    audit_run_mode: str,
    patient_id: str = "",
    visit_number: str = "",
) -> Dict[str, str]:
    return {
        "source_record_key": str(source_record_key or "").strip(),
        "audit_type_code": str(audit_type_code or "").strip(),
        "audit_run_mode": str(audit_run_mode or "daily_increment").strip() or "daily_increment",
        "patient_id": str(patient_id or "").strip(),
        "visit_number": str(visit_number or "").strip(),
    }


def make_business_identity_hash(
    source_record_key: str,
    audit_type_code: str,
    audit_run_mode: str,
    patient_id: str = "",
    visit_number: str = "",
) -> str:
    """业务身份哈希；不含姓名与病历正文。"""
    parts = normalize_identity_parts(
        source_record_key, audit_type_code, audit_run_mode, patient_id, visit_number
    )
    # 首版身份优先：source_record_key + audit_type_code + audit_run_mode
    raw = "|".join(
        [
            parts["source_record_key"],
            parts["audit_type_code"],
            parts["audit_run_mode"],
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_identity_ambiguous(source_record_key: str) -> bool:
    """空 source_record_key 无法证明稳定来源身份，禁止自动替代。"""
    return not str(source_record_key or "").strip()


def make_candidate_hash(items: Iterable[Dict[str, Any]]) -> str:
    """对候选集规范化后生成 SHA-256；字段不得含姓名/正文。"""
    normalized: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "business_identity_hash": str(item.get("business_identity_hash") or "").strip(),
                "source_record_key": str(item.get("source_record_key") or "").strip(),
                "audit_type_code": str(item.get("audit_type_code") or "").strip(),
                "audit_run_mode": str(item.get("audit_run_mode") or "daily_increment").strip(),
                "patient_id": str(item.get("patient_id") or "").strip(),
                "visit_number": str(item.get("visit_number") or "").strip(),
                "query_date": str(item.get("query_date") or "").strip(),
                "previous_current_push_log_id": str(item.get("previous_current_push_log_id") or "").strip(),
                "category": str(item.get("category") or "").strip(),
            }
        )
    normalized.sort(
        key=lambda x: (
            x["query_date"],
            x["audit_type_code"],
            x["business_identity_hash"],
            x["patient_id"],
            x["visit_number"],
        )
    )
    payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_config_snapshot_hash(
    *,
    date_from: str,
    date_to: str,
    date_dimension: str,
    audit_type_codes: Optional[List[str]],
    dept_filter: Optional[List[str]],
    alert_policy: str,
    existing_result_policy: str,
) -> str:
    snapshot = {
        "date_from": str(date_from or "").strip(),
        "date_to": str(date_to or "").strip(),
        "date_dimension": str(date_dimension or "").strip(),
        "audit_type_codes": sorted(str(c).strip() for c in (audit_type_codes or []) if str(c).strip()),
        "dept_filter": sorted(str(d).strip() for d in (dept_filter or []) if str(d).strip()),
        "alert_policy": str(alert_policy or "suppress").strip(),
        "existing_result_policy": str(existing_result_policy or "replace_current").strip(),
    }
    raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
