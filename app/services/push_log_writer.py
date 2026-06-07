"""推送日志写入服务 —— 创建 PushLog 记录。"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from app.models import PushLog
from app.services.data_source_loader import PatientBundle
from app.services.push_types import PushConfig, normalize_query_date_for_log as _normalize_query_date_for_log, safe_json_dumps as _safe_json_dumps
from app.services.record_identity import get_bundle_source_key, get_record_source_key

logger = logging.getLogger(__name__)


def _resolve_visit_number(
    bundle: PatientBundle,
    first_record: Dict[str, Any],
    fm: Dict[str, str],
    payload: Dict[str, Any] | None = None,
) -> str:
    """统一获取 visit_number：优先 bundle.group_values → patient_info → first_record。"""
    payload = payload or {}
    patient_info = payload.get("patient_info", {}) if isinstance(payload.get("patient_info"), dict) else {}
    return str(
        bundle.group_values.get("visit_number")
        or bundle.group_values.get("次数")
        or patient_info.get("visit_number")
        or patient_info.get("次数")
        or first_record.get(fm.get("visit_number", "次数"), "")
        or ""
    )


def create_skipped_push_log(
    bundle: PatientBundle,
    bundle_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str],
    push_config: PushConfig,
    skip_reason: str,
    skip_message: str,
    patient_id: str,
) -> PushLog:
    """创建跳过的推送日志记录。"""
    first_record = bundle_records[0]
    fm = bundle.source_field_mappings.get(bundle.primary_source, field_mapping)
    real_patient_id = str(bundle.group_values.get("patient_id") or (patient_id.split("_")[0] if "_" in patient_id else patient_id) or "")
    audit_type = push_config.audit_type
    source_record_key = get_bundle_source_key(bundle, audit_type, push_config.audit_run_mode) if audit_type else get_record_source_key(first_record)
    return PushLog(
        push_time=datetime.now(),
        trigger_type=push_config.trigger_type,
        query_date=_normalize_query_date_for_log(push_config.query_date),
        patient_id=real_patient_id,
        patient_name=first_record.get(fm.get("patient_name", "患者姓名"), ""),
        admission_no=str(first_record.get(fm.get("admission_no", "住院号"), "")),
        visit_number=_resolve_visit_number(bundle, first_record, fm),
        audit_type_code=str(push_config.audit_type_code or "progress_vs_nursing"),
        source_record_key=source_record_key,
        dept=first_record.get(fm.get("dept", "所在科室名称"), ""),
        status="skipped",
        pushed_flag=0,
        reviewed_flag=0,
        manual_override=0,
        skip_reason=skip_reason,
        error_msg=skip_message,
        elapsed_ms=0,
        mr_text="",
        request_json="",
        response_json="",
        parse_status="skipped",
        parse_error="",
        risk_score=0,
        ai_version="1.0",
    )


def create_push_log(
    bundle: PatientBundle,
    bundle_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str],
    dify_result: Dict[str, Any],
    payload: Dict[str, Any],
    mr_text: str,
    push_config: PushConfig,
    patient_id: str,
) -> PushLog:
    """创建推送日志记录。"""
    first_record = bundle_records[0]
    fm = bundle.source_field_mappings.get(bundle.primary_source, field_mapping)

    real_patient_id = str(bundle.group_values.get("patient_id") or (patient_id.split("_")[0] if "_" in patient_id else patient_id) or "")
    audit_type = push_config.audit_type
    source_record_key = get_bundle_source_key(bundle, audit_type, push_config.audit_run_mode) if audit_type else get_record_source_key(first_record)

    patient_info = payload.get("patient_info", {}) if isinstance(payload.get("patient_info"), dict) else {}
    parsed_output = dify_result.get("parsed_output", {}) or {}
    if parsed_output.get("parse_success"):
        parse_status = "success"
    elif parsed_output.get("fallback_inference"):
        parse_status = "fallback"
    else:
        parse_status = "failed"

    return PushLog(
        push_time=datetime.now(),
        trigger_type=push_config.trigger_type,
        query_date=_normalize_query_date_for_log(push_config.query_date),
        patient_id=real_patient_id,
        patient_name=patient_info.get("patient_name") or first_record.get(fm.get("patient_name", "患者姓名"), ""),
        admission_no=str(patient_info.get("admission_no") or first_record.get(fm.get("admission_no", "住院号"), "")),
        visit_number=_resolve_visit_number(bundle, first_record, fm, payload),
        audit_type_code=str(push_config.audit_type_code or "progress_vs_nursing"),
        source_record_key=source_record_key,
        dept=patient_info.get("department") or patient_info.get("dept") or first_record.get(fm.get("dept", "所在科室名称"), ""),
        workflow_run_id=dify_result.get("workflow_run_id", ""),
        task_id=dify_result.get("task_id", ""),
        status=dify_result.get("status", "failed"),
        pushed_flag=1 if dify_result.get("status") == "success" else 0,
        reviewed_flag=0,
        manual_override=0,
        skip_reason="",
        ai_result=_safe_json_dumps(dify_result.get("result", {})),
        inconsistency=1 if dify_result.get("inconsistency") else 0,
        severity=dify_result.get("severity", ""),
        error_msg=dify_result.get("error", ""),
        elapsed_ms=dify_result.get("elapsed_ms", 0),
        mr_text=mr_text,
        request_json=_safe_json_dumps(payload),
        response_json=_safe_json_dumps(dify_result.get("result", {})),
        parse_status=parse_status,
        parse_error=dify_result.get("parse_error", ""),
        risk_score=dify_result.get("risk_score", 0),
        ai_version=parsed_output.get("version", "1.0"),
        alert_level=parsed_output.get("alert_level", ""),
    )
