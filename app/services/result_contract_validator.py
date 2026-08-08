"""P1-4: 结果契约校验 — 在 parser 解析后、writer/mapper 前执行。

校验并归一化 status/severity/alert_level 组合；按 audit_type_code 校验预期维度集合。
不修改 Dify 原始 response_json。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

VALID_STATUS = {"pass", "warn", "fail", "unknown"}
VALID_SEVERITY = {"low", "medium", "high"}
VALID_ALERT_LEVEL = {"blue", "yellow", "red", "gray"}

VALID_COMBOS = {
    ("pass", "low", "blue"),
    ("warn", "medium", "yellow"),
    ("warn", "low", "blue"),
    ("fail", "high", "red"),
    ("unknown", "low", "gray"),
}

CONFIDENCE_THRESHOLD = 0.6

EXPECTED_DIMENSIONS: Dict[str, List[str]] = {
    "progress_vs_nursing": [
        "diagnosis_consistency",
        "nursing_level_consistency",
        "vital_sign_consistency",
        "condition_consistency",
        "treatment_measure_consistency",
        "timeline_consistency",
    ],
    "jyjc_vs_bcnursing": [
        "lab_abnormal_followup",
        "exam_abnormal_followup",
        "progress_result_consistency",
        "nursing_recorded_consistency",
        "high_risk_response_consistency",
        "timeline_consistency",
    ],
    "surgery_chain": [
        "patient_info_consistency",
        "timeline_consistency",
        "preoperative_template_validity",
        "diagnosis_consistency",
        "operation_consistency",
        "anesthesia_material_step_consistency",
        "intraoperative_to_postoperative_consistency",
        "postoperative_record_completeness",
        "consent_subject_validity",
        "text_quality",
    ],
    "discharge_vs_frontpage": [
        "patient_info_consistency",
        "chief_complaint_consistency",
        "admission_diagnosis_consistency",
        "diagnosis_backfill_validity",
        "new_discharge_diagnosis_evidence",
        "treatment_course_completeness",
        "discharge_advice_consistency",
        "discharge_condition_consistency",
        "text_quality",
    ],
    "syssvsscbc": [
        "diagnosis_consistency",
        "operation_consistency",
        "diagnosis_operation_match",
        "timeline_consistency",
    ],
}

STATUS_TO_SEVERITY = {"pass": "low", "warn": "medium", "fail": "high", "unknown": "low"}
SEVERITY_TO_ALERT = {"low": "blue", "medium": "yellow", "high": "red"}


def normalize_dimension_combo(dim: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """归一化单个维度的 status/severity/alert_level 组合。返回 (dim, errors)。"""
    errors: List[str] = []
    status = str(dim.get("status") or "unknown").strip().lower()
    severity = str(dim.get("severity") or "").strip().lower()
    alert_level = str(dim.get("alert_level") or "").strip().lower()
    confidence = float(dim.get("confidence") or 0)

    if status not in VALID_STATUS:
        errors.append(f"invalid_status:{status}")
        status = "unknown"

    if confidence < CONFIDENCE_THRESHOLD:
        status = "unknown"
        severity = "low"
        alert_level = "gray"
        dim["status"] = status
        dim["severity"] = severity
        dim["alert_level"] = alert_level
        dim["_contract_normalized"] = "low_confidence"
        return dim, errors

    if not severity:
        severity = STATUS_TO_SEVERITY.get(status, "low")
    if severity not in VALID_SEVERITY:
        errors.append(f"invalid_severity:{severity}")
        severity = STATUS_TO_SEVERITY.get(status, "low")

    if not alert_level:
        alert_level = SEVERITY_TO_ALERT.get(severity, "gray")
    if alert_level not in VALID_ALERT_LEVEL:
        errors.append(f"invalid_alert_level:{alert_level}")
        alert_level = SEVERITY_TO_ALERT.get(severity, "gray")

    combo = (status, severity, alert_level)
    if combo not in VALID_COMBOS:
        errors.append(f"invalid_combo:{status}|{severity}|{alert_level}")
        severity = STATUS_TO_SEVERITY.get(status, "low")
        alert_level = SEVERITY_TO_ALERT.get(severity, "gray")
        if status == "unknown":
            severity = "low"
            alert_level = "gray"

    dim["status"] = status
    dim["severity"] = severity
    dim["alert_level"] = alert_level
    return dim, errors


def validate_result_contract(
    result: Dict[str, Any],
    audit_type_code: str = "",
    expected_dimensions_override: Optional[List[str]] = None,
) -> Tuple[bool, List[str]]:
    """校验完整结果的契约。返回 (contract_valid, contract_errors)。

    不修改 Dify 原始 response_json；仅校验解析后的 result dict。
    admission_vs_first_progress 的维度来自运行时配置快照（expected_dimensions_override），
    不得硬编码；缺少配置即 fail-closed。
    """
    errors: List[str] = []
    dimensions = result.get("dimensions") or []

    if not dimensions:
        errors.append("no_dimensions")
        return False, errors

    seen_codes: Set[str] = set()
    for dim in dimensions:
        code = str(dim.get("dimension_code") or "").strip()
        if not code:
            errors.append("missing_dimension_code")
            continue
        if code in seen_codes:
            errors.append(f"duplicate_dimension_code:{code}")
        seen_codes.add(code)

        _, dim_errors = normalize_dimension_combo(dim)
        errors.extend(dim_errors)

    code_key = str(audit_type_code or "").strip()
    if expected_dimensions_override is not None:
        expected = expected_dimensions_override
    else:
        expected = EXPECTED_DIMENSIONS.get(code_key)

    if code_key == "admission_vs_first_progress" and expected is None:
        errors.append("admission_dimensions_not_configured")
        return False, errors

    if expected:
        missing = set(expected) - seen_codes
        if missing:
            errors.append(f"missing_dimensions:{','.join(sorted(missing))}")
        unknown_codes = seen_codes - set(expected)
        if unknown_codes:
            errors.append(f"unknown_dimension_codes:{','.join(sorted(unknown_codes))}")

    contract_valid = len(errors) == 0
    if not contract_valid:
        logger.info(
            "contract validation failed audit_type=%s errors=%s",
            audit_type_code,
            errors[:5],
        )
    return contract_valid, errors
