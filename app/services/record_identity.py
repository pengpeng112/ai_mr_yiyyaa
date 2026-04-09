"""Stable record identity helpers for manual push preview and logging."""

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
