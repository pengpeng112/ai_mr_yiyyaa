"""Stable record identity helpers for manual push preview and logging.

ADR-3: Bundle-Level source key with audit_type prefix for new audit types.
- Old audit_type (legacy_progress_nursing): keep get_record_source_key() behavior, no audit_type prefix
- New audit_type: f"{audit_type.code}::" + "::".join(group_values)
"""

from __future__ import annotations

from typing import Any, Dict

KEY_PATIENT_ID = "\u60a3\u8005ID"
KEY_VISIT_NO = "\u6b21\u6570"
KEY_DEPT = "\u6240\u5728\u79d1\u5ba4\u540d\u79f0"
KEY_MR_FINISH_TIME = "\u75c5\u5386\u6587\u4e66_\u5b8c\u6210\u65f6\u95f4"
KEY_MR_TITLE_TIME = "\u75c5\u5386\u6807\u9898\u65f6\u95f4"
KEY_NURSE_CREATE_TIME = "\u62a4\u7406\u8bb0\u5f55_\u521b\u5efa\u65f6\u95f4"
KEY_NURSE_TIME = "\u62a4\u7406\u8bb0\u5f55\u65f6\u95f4"
KEY_NURSE_FORM_TIME = "\u62a4\u7406\u8bb0\u5f55\u8868\u5355\u5355\u521b\u5efa\u65f6\u95f4"


def get_record_mrid(record: Dict[str, Any]) -> str:
    return str(record.get("MRID") or record.get("mrid") or "").strip()


def get_record_source_key(record: Dict[str, Any]) -> str:
    mrid = get_record_mrid(record)
    if mrid:
        return f"mrid::{mrid}"
    return "legacy::" + "|".join(
        [
            str(record.get(KEY_PATIENT_ID) or ""),
            str(record.get(KEY_VISIT_NO) or ""),
            str(record.get(KEY_DEPT) or ""),
            str(record.get(KEY_MR_FINISH_TIME) or record.get(KEY_MR_TITLE_TIME) or ""),
            str(record.get(KEY_NURSE_CREATE_TIME) or record.get(KEY_NURSE_TIME) or record.get(KEY_NURSE_FORM_TIME) or ""),
        ]
    )


def get_bundle_source_key(bundle, audit_type) -> str:
    """生成 bundle 级别的 source_record_key。

    Args:
        bundle: PatientBundle 实例
        audit_type: AuditTypeConfig 实例或 dict

    Returns:
        str: source_record_key
    """
    # 旧类型保持兼容：不带 audit_type 前缀
    builder = str(getattr(audit_type, "payload", {}).get("builder", "") if hasattr(audit_type, "payload") else audit_type.get("payload", {}).get("builder", ""))
    if builder == "legacy_progress_nursing":
        first_record = bundle.sources.get(bundle.primary_source, [{}])[0] if bundle.sources else {}
        return get_record_source_key(first_record)

    # 新类型：带 audit_type 前缀
    code = getattr(audit_type, "code", "") if hasattr(audit_type, "code") else audit_type.get("code", "")
    group_key = getattr(audit_type, "group_key", ["patient_id", "visit_number"]) if hasattr(audit_type, "group_key") else audit_type.get("group_key", ["patient_id", "visit_number"])
    values = [str(bundle.group_values.get(k, "")) for k in group_key]
    return f"{code}::" + "::".join(values)
