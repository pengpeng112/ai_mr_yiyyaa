"""
Push routes: /api/push
Supports manual push by single date or date range with multiple date dimensions.
"""

import hashlib
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app.config import decrypt_value, load_config, normalize_dify_base_url
from app.database import SessionLocal, get_app_db_type, get_db
from app.oracle_client import build_mr_text_combined, fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.schemas import ManualPushRequest, PushProgress, RetryRequest
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.bulk_push_executor import BulkPushExecutor
from app.services.config_parser import ConfigParser
from app.services.data_source_loader import load_patient_bundles
from app.services.payload_builder import build_dify_payload
from app.services.payload_composer import compose
from app.services.push_executor import PushConfig, PushExecutor, PushResult
from app.services.push_async_executor import AsyncCallbackPushExecutor
from app.services.task_manager import get_task_manager
from app.services.record_identity import SOURCE_RECORD_KEY_FIELD, get_bundle_source_key, get_record_mrid, get_record_source_key
from app.services.push_date_utils import parse_date as _push_date_parse, coerce_to_date as _push_date_coerce, resolve_query_dates as _push_date_resolve, date_label as _push_date_label, record_date_in_range as _push_date_in_range
from app.services import push_date_utils as _push_date
from app.services import push_selection as _push_sel
from app.services import push_query_service as _push_query
from app.services.lab_exam_payload_builder import build_lab_exam_structured_input_for_diagnostics
from app.models import PushLog, QCFeedback
from app.permissions import require_role

router = APIRouter()
logger = logging.getLogger(__name__)


KEY_PATIENT_ID = "\u60a3\u8005ID"
KEY_VISIT_NO = "\u6b21\u6570"
KEY_PATIENT_NAME = "\u60a3\u8005\u59d3\u540d"
KEY_DEPT = "\u6240\u5728\u79d1\u5ba4\u540d\u79f0"
KEY_MR_FINISH_TIME = "\u75c5\u5386\u6587\u4e66_\u5b8c\u6210\u65f6\u95f4"
KEY_MR_TITLE_TIME = "\u75c5\u5386\u6807\u9898\u65f6\u95f4"
KEY_NURSE_CREATE_TIME = "\u62a4\u7406\u8bb0\u5f55_\u521b\u5efa\u65f6\u95f4"
KEY_NURSE_TIME = "\u62a4\u7406\u8bb0\u5f55\u65f6\u95f4"
KEY_NURSE_FORM_TIME = "\u62a4\u7406\u8bb0\u5f55\u8868\u5355\u5355\u521b\u5efa\u65f6\u95f4"
KEY_ADMISSION_DATE = "\u5165\u9662\u65e5\u671f"
KEY_DISCHARGE_DATE = "\u51fa\u9662\u65e5\u671f"
KEY_DISCHARGE_TIME = "\u51fa\u9662\u65f6\u95f4"
KEY_DISCHARGE_DATETIME = "\u51fa\u9662\u65e5\u671f\u65f6\u95f4"

DATE_DIMENSION_FIELDS = {
    "query_date": [],
    "record_create_date": [
        KEY_MR_FINISH_TIME,
        KEY_MR_TITLE_TIME,
        KEY_NURSE_CREATE_TIME,
        KEY_NURSE_TIME,
        KEY_NURSE_FORM_TIME,
    ],
    "admission_date": [KEY_ADMISSION_DATE],
    "discharge_date": [KEY_DISCHARGE_DATE, KEY_DISCHARGE_TIME, KEY_DISCHARGE_DATETIME],
}


def _log_push_funnel(
    trigger_type: str,
    query_date_label: str,
    raw_rows: int,
    filtered_rows: int,
    grouped_count: int,
    result: PushResult | None = None,
) -> None:
    skipped = 0
    success = 0
    failed = 0
    skip_reason_counts: dict[str, int] = {}
    if result:
        for item in result.results:
            status = str(item.get("status", ""))
            if status == "success":
                success += 1
            elif status == "skipped":
                skipped += 1
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
            else:
                failed += 1
    logger.info(
        "[push_funnel] trigger=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
        trigger_type,
        query_date_label,
        raw_rows,
        filtered_rows,
        grouped_count,
        success,
        failed,
        skipped,
    )
    if skip_reason_counts:
        logger.info(
            "[push_funnel] trigger=%s query_date=%s skip_reason_counts=%s",
            trigger_type,
            query_date_label,
            skip_reason_counts,
        )


def _parse_date(date_text: str):
    return _push_date.parse_date(date_text)


def _coerce_to_date(value) -> date | None:
    return _push_date.coerce_to_date(value)


def _resolve_query_dates(body: ManualPushRequest) -> list[str]:
    return _push_date.resolve_query_dates(body.date_from, body.date_to, body.query_date)


def _date_label(query_dates: list[str]) -> str:
    return _push_date.date_label(query_dates)


def _record_date_in_range(record: dict, field_candidates: list[str], date_from: str, date_to: str) -> bool:
    return _push_query.record_date_in_range(record, field_candidates, date_from, date_to)


def _auto_inject_date_filter(sql: str, date_dimension: str) -> tuple[str, str | None]:
    return _push_query.auto_inject_date_filter(sql, date_dimension)


def _collect_records(
    data_source: str,
    db_cfg: dict,
    dept_list: list[str],
    query_dates: list[str],
    date_dimension: str,
) -> tuple[list[dict], int]:
    return _push_query.collect_records(data_source, db_cfg, dept_list, query_dates, date_dimension)


def _build_query_diagnostics(
    body: ManualPushRequest,
    db_cfg: dict,
    raw_rows: int,
    pre_dept_rows: int | None = None,
    filtered_rows: int = 0,
    dept_config: dict | None = None,
) -> list[str]:
    return _push_query.build_query_diagnostics(
        date_dimension=body.date_dimension,
        date_from=body.date_from,
        date_to=body.date_to,
        query_date=body.query_date,
        db_cfg=db_cfg,
        raw_rows=raw_rows,
        pre_dept_rows=pre_dept_rows,
        filtered_rows=filtered_rows,
        dept_config=dept_config,
    )


def _legacy_medical_record_source_key(record: dict, field_mapping: dict | None = None) -> str:
    return _push_sel.legacy_medical_record_source_key(record, field_mapping)


def _flatten_to_single_records(grouped: dict, field_mapping: dict | None = None) -> dict:
    """Flatten patient groups into legacy push units, merging rows from the same medical document."""
    flattened: dict = {}
    for _, records in grouped.items():
        for record in records:
            unique_key = _legacy_medical_record_source_key(record, field_mapping)
            record[SOURCE_RECORD_KEY_FIELD] = unique_key
            flattened.setdefault(unique_key, []).append(record)
    return flattened


def _prepare_push_data(body: ManualPushRequest, config: dict, data_source: str, db_cfg: dict, field_mapping: dict):
    query_dates = _resolve_query_dates(body)
    query_date_label = _date_label(query_dates)
    # 手动推送页面：未选择科室时默认"全部科室"（不再回落全局 departments 配置）
    dept_list = body.dept_filter if body.dept_filter is not None else []

    records, raw_rows = _collect_records(
        data_source=data_source,
        db_cfg=db_cfg,
        dept_list=dept_list,
        query_dates=query_dates,
        date_dimension=body.date_dimension,
    )

    dept_config = {"mode": "include", "list": dept_list or []}
    dept_field = field_mapping.get("dept", KEY_DEPT)
    pre_dept_rows = len(records)
    records = ConfigParser.filter_departments(records, dept_config, dept_field)
    filtered_rows = len(records)
    grouped = group_by_patient(records, field_mapping)
    grouped = _flatten_to_single_records(grouped, field_mapping)
    return query_dates, query_date_label, dept_list, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config


def _filter_grouped_records(grouped: dict, selected_record_keys: list[str] | None) -> dict:
    return _push_sel.filter_grouped_records(grouped, selected_record_keys)


def _audit_type_code(audit_type) -> str:
    return _push_sel.audit_type_code(audit_type)


def _audit_type_group_key(audit_type) -> list[str]:
    return _push_sel.audit_type_group_key(audit_type)


def _add_selection_key(keys: set[str], value) -> None:
    _push_sel.add_selection_key(keys, value)


def _bundle_selection_keys(bundle, audit_type) -> set[str]:
    return _push_sel.bundle_selection_keys(bundle, audit_type)


def _selection_key_matches(bundle_keys: set[str], selected_keys: set[str]) -> bool:
    return _push_sel.selection_key_matches(bundle_keys, selected_keys)


def _filter_bundles_by_selected_record_keys(grouped: dict, selected_record_keys: list[str] | None, audit_type) -> dict:
    return _push_sel.filter_bundles_by_selected_record_keys(grouped, selected_record_keys, audit_type)


def _selected_audit_type_codes_from_keys(selected_record_keys: list[str] | None, audit_types: list) -> set[str]:
    return _push_sel.selected_audit_type_codes_from_keys(selected_record_keys, audit_types)


def _scope_audit_types_by_selected_record_keys(audit_types: list, selected_record_keys: list[str] | None) -> list:
    return _push_sel.scope_audit_types_by_selected_record_keys(audit_types, selected_record_keys)


def _filter_already_succeeded(
    db: Session,
    grouped: dict,
) -> tuple[dict, list[dict]]:
    """过滤掉 push_log 中已有成功记录的条目，用于断点续推。

    返回 (remaining_grouped, skipped_items)。
    """
    if not grouped:
        return grouped, []
    latest_push_map = _load_latest_push_map(db, list(grouped.keys()))
    remaining: dict = {}
    skipped_items: list[dict] = []
    for key, records in grouped.items():
        latest = latest_push_map.get(key)
        if latest and str(getattr(latest, "status", "") or "") == "success":
            patient_id = str(records[0].get(KEY_PATIENT_ID, key)) if records else key
            skipped_items.append(
                {
                    "patient_id": patient_id,
                    "status": "skipped",
                    "skip_reason": "already_succeeded",
                    "error": f"已成功推送（log_id={getattr(latest, 'id', '')}，时间={getattr(latest, 'push_time', '')}）",
                    "inconsistency": False,
                    "severity": "",
                    "workflow_run_id": str(getattr(latest, "workflow_run_id", "") or ""),
                    "elapsed_ms": 0,
                }
            )
        else:
            remaining[key] = records
    if skipped_items:
        logger.info(
            "[skip_already_succeeded] skipped=%s remaining=%s",
            len(skipped_items),
            len(remaining),
        )
    return remaining, skipped_items


def _load_latest_push_map(db: Session, source_record_keys: list[str]) -> dict[str, PushLog]:
    if not source_record_keys:
        return {}

    # ORA-01795: Oracle IN 列表最多 1000 项，保守按 900 分片。
    chunk_size = 900
    if len(source_record_keys) > chunk_size:
        logger.info(
            "[query_preview] loading latest push map with chunking: keys=%s chunk_size=%s chunks=%s",
            len(source_record_keys),
            chunk_size,
            (len(source_record_keys) + chunk_size - 1) // chunk_size,
        )
    rows: list[PushLog] = []
    for i in range(0, len(source_record_keys), chunk_size):
        chunk = source_record_keys[i:i + chunk_size]
        subq = (
            db.query(
                PushLog.source_record_key.label("source_record_key"),
                func.max(PushLog.id).label("max_id"),
            )
            .filter(PushLog.source_record_key.in_(chunk))
            .group_by(PushLog.source_record_key)
            .subquery()
        )
        chunk_rows = (
            db.query(PushLog)
            .join(subq, PushLog.id == subq.c.max_id)
            .all()
        )
        rows.extend(chunk_rows)

    latest: dict[str, PushLog] = {}
    for row in rows:
        key = str(getattr(row, "source_record_key", "") or "")
        if key and key not in latest:
            latest[key] = row
    return latest


def _build_query_preview_rows(
    grouped: dict,
    field_mapping: dict,
    dept_field: str,
    latest_push_map: dict[str, PushLog],
    preview_audit_type_code: str = "",
    preview_audit_type_name: str = "",
) -> list[dict]:
    name_field = field_mapping.get("patient_name", KEY_PATIENT_NAME)
    admission_no_field = field_mapping.get("admission_no", "住院号")
    visit_field = field_mapping.get("visit_number", KEY_VISIT_NO)
    rows: list[dict] = []
    for record_key, patient_records in grouped.items():
        record = patient_records[0] if patient_records else {}
        latest = latest_push_map.get(record_key)
        rows.append(
            {
                "record_key": record_key,
                "audit_type_code": preview_audit_type_code,
                "audit_type_name": preview_audit_type_name,
                "mrid": get_record_mrid(record),
                "patient_id": str(record.get(KEY_PATIENT_ID) or ""),
                "visit_number": str(record.get(visit_field) or ""),
                "patient_name": str(record.get(name_field) or ""),
                "admission_no": str(record.get(admission_no_field) or ""),
                "dept": str(record.get(dept_field) or ""),
                "medical_document_time": str(record.get(KEY_MR_FINISH_TIME) or record.get(KEY_MR_TITLE_TIME) or ""),
                "medical_document_name": str(record.get("病历文书_名称") or record.get("病历名称") or ""),
                "nursing_record_time": str(record.get(KEY_NURSE_CREATE_TIME) or record.get(KEY_NURSE_TIME) or record.get(KEY_NURSE_FORM_TIME) or ""),
                "nursing_record_type": str(record.get("护理记录_文书类型") or record.get("护理单类型") or ""),
                # 查询预览仅用于列表展示，避免为数万条记录拼接全文导致接口变慢。
                "mr_text_preview": "",
                "pushed_before": latest is not None,
                "latest_log_id": int(getattr(latest, "id", 0) or 0) if latest else None,
                "latest_push_status": str(getattr(latest, "status", "") or "") if latest else "",
                "latest_push_time": getattr(latest, "push_time", None) if latest else None,
                "latest_reviewed_flag": int(getattr(latest, "reviewed_flag", 0) or 0) if latest else 0,
            }
        )
    rows.sort(
        key=lambda item: (
            0 if not item["pushed_before"] else 1,
            str(item.get("patient_id") or ""),
            str(item.get("medical_document_time") or ""),
            str(item.get("nursing_record_time") or ""),
        )
    )
    return rows


def _first_bundle_record(bundle) -> dict:
    sources = getattr(bundle, "sources", {}) or {}
    if not isinstance(sources, dict):
        return {}
    for source_name in ["patient", getattr(bundle, "primary_source", ""), "lab", "exam", "progress", "nursing"]:
        records = sources.get(source_name)
        if isinstance(records, list) and records:
            return records[0] if isinstance(records[0], dict) else {}
        if isinstance(records, dict):
            return records
    for records in sources.values():
        if isinstance(records, list) and records:
            return records[0] if isinstance(records[0], dict) else {}
        if isinstance(records, dict):
            return records
    return {}


def _first_source_record(sources: dict, source_name: str) -> dict:
    records = sources.get(source_name) if isinstance(sources, dict) else None
    if isinstance(records, list) and records:
        return records[0] if isinstance(records[0], dict) else {}
    if isinstance(records, dict):
        return records
    return {}


def _first_record_value(records: list[dict], keys: list[str]) -> str:
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in keys:
            value = str(record.get(key) or "").strip()
            if value:
                return value
    return ""


def _audit_type_builder(audit_type) -> str:
    payload = getattr(audit_type, "payload", {}) if hasattr(audit_type, "payload") else audit_type.get("payload", {})
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump()
    return str((payload or {}).get("builder") or "").strip()


def _bundle_records_for_preview(bundle) -> list[dict]:
    sources = getattr(bundle, "sources", {}) or {}
    if not isinstance(sources, dict):
        return []
    ordered_sources = [getattr(bundle, "primary_source", ""), "lab", "exam", "frontpage", "first_progress", "progress", "nursing", "patient"]
    records: list[dict] = []
    seen_sources: set[str] = set()
    for source_name in ordered_sources + list(sources.keys()):
        if not source_name or source_name in seen_sources:
            continue
        seen_sources.add(source_name)
        source_records = sources.get(source_name)
        if isinstance(source_records, list):
            records.extend([record for record in source_records if isinstance(record, dict)])
        elif isinstance(source_records, dict):
            records.append(source_records)
    return records


def _bundle_preview_document(bundle, audit_type) -> tuple[str, str]:
    sources = getattr(bundle, "sources", {}) or {}
    builder = _audit_type_builder(audit_type)
    if builder in {"lab_exam_progress_nursing", "lab_exam_structured_progress_nursing"}:
        lab_records = sources.get("lab") if isinstance(sources, dict) else []
        exam_records = sources.get("exam") if isinstance(sources, dict) else []
        lab_records = lab_records if isinstance(lab_records, list) else []
        exam_records = exam_records if isinstance(exam_records, list) else []
        lab_time = _first_record_value(lab_records, ["result_time", "结果时间", "event_time", "audit_date"])
        exam_time = _first_record_value(exam_records, ["report_time", "报告时间", "exam_time", "event_time", "audit_date"])
        lab_name = _first_record_value(lab_records, ["test_name", "检验项目", "item_name", "report_item_name", "报告项目名称", "test_no", "检验单号"])
        exam_name = _first_record_value(exam_records, ["exam_name", "检查名称", "exam_class", "检查类别", "exam_no", "检查号"])
        parts: list[str] = []
        if lab_records:
            parts.append(f"检验{len(lab_records)}项" + (f"：{lab_name}" if lab_name else ""))
        if exam_records:
            parts.append(f"检查{len(exam_records)}项" + (f"：{exam_name}" if exam_name else ""))
        return lab_time or exam_time, " / ".join(parts)

    if builder == "frontpage_surgery_first_progress":
        frontpage_records = sources.get("frontpage") if isinstance(sources, dict) else []
        first_progress = _first_source_record(sources, "first_progress")
        frontpage_records = frontpage_records if isinstance(frontpage_records, list) else []
        surgery_name = _first_record_value(frontpage_records, ["surgery_1", "手术", "record_name", "content"])
        surgery_date = _first_record_value(frontpage_records, ["operation_date", "手术日期标准", "audit_date"])
        progress_name = str(first_progress.get("record_name") or first_progress.get("病历名称") or first_progress.get("病程名称") or "").strip()
        return str(first_progress.get("event_time") or surgery_date or ""), progress_name or surgery_name

    record = _first_bundle_record(bundle)
    return (
        str(record.get("progress_time") or record.get(KEY_MR_FINISH_TIME) or record.get(KEY_MR_TITLE_TIME) or record.get("event_time") or ""),
        str(record.get("progress_name") or record.get("record_name") or record.get("病程名称") or record.get("病历文书_名称") or record.get("病历名称") or ""),
    )


def _safe_preview_value(value, max_len: int = 120) -> str:
    text = str(value or "").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _source_sample_records(records: list[dict], max_records: int = 3) -> list[dict]:
    samples: list[dict] = []
    preferred_keys = [
        "patient_id", "visit_number", "audit_date", "record_id", "record_name", "event_time",
        "test_no", "test_name", "item_name", "result", "abnormal_indicator", "result_time",
        "exam_no", "exam_name", "exam_class", "report_time", "exam_time", "is_abnormal",
        KEY_PATIENT_ID, KEY_VISIT_NO, "住院号", "病程记录ID", "病程名称", "病程时间", "护理记录ID", "护理单类型", "护理时间",
    ]
    for record in (records or [])[:max_records]:
        if not isinstance(record, dict):
            continue
        item: dict[str, str] = {}
        for key in preferred_keys:
            if key in record and record.get(key) not in (None, ""):
                item[key] = _safe_preview_value(record.get(key))
        samples.append(item)
    return samples


def _parse_context_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y%m%d"):
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    return None


def _record_context_time(record: dict, source_name: str) -> tuple[str, datetime | None]:
    keys = ["event_time", "record_time", "title_time", "create_time", "sign_time"] if source_name == "progress" else ["event_time", "record_time", "nurse_time"]
    for key in keys:
        parsed = _parse_context_datetime(record.get(key))
        if parsed:
            return str(record.get(key) or ""), parsed
    return "", None


def _diagnose_context_records(records: list[dict], source_name: str, context_diagnostics: dict) -> list[dict]:
    event_sources = context_diagnostics.get("included_event_sources") or []
    events: list[dict] = []
    for item in event_sources:
        parsed = _parse_context_datetime(item.get("event_time"))
        if parsed:
            events.append({**item, "_parsed": parsed})

    matched_key = "matched_progress" if source_name == "progress" else "matched_nursing"
    matched_by_id = {
        str(item.get("record_id") or "").strip(): item
        for item in (context_diagnostics.get(matched_key) or [])
        if str(item.get("record_id") or "").strip()
    }
    rows: list[dict] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        record_id = str(record.get("record_id") or record.get("病程记录ID") or record.get("护理记录ID") or "").strip()
        event_time_text, record_dt = _record_context_time(record, source_name)
        matched = matched_by_id.get(record_id)
        same_day_events = []
        later_events = []
        if record_dt:
            record_day = record_dt.strftime("%Y-%m-%d")
            same_day_events = [item for item in events if item["_parsed"].strftime("%Y-%m-%d") == record_day]
            later_events = [item for item in same_day_events if record_dt > item["_parsed"]]
        if matched:
            status = "included"
            reason = "同患者/住院次、同日，且记录时间晚于匹配报告时间"
        elif not events:
            status = "excluded"
            reason = "没有可参与关联的异常检验/异常检查报告时间"
        elif not record_dt:
            status = "excluded"
            reason = "病程/护理时间无法解析"
        elif not same_day_events:
            status = "excluded"
            reason = "没有同一天的异常检验/异常检查报告"
        elif not later_events:
            status = "excluded"
            reason = "记录时间不晚于当天异常报告时间"
        else:
            status = "excluded"
            reason = "超过载荷数量或字符限制后未纳入"
        rows.append(
            {
                "status": status,
                "reason": reason,
                "record_id": record_id,
                "record_name": str(record.get("record_name") or record.get("病程名称") or record.get("护理单类型") or ""),
                "event_time": event_time_text,
                "matched_event_time": str((matched or {}).get("matched_event_time") or ""),
                "matched_event_source": (matched or {}).get("matched_event_source") or {},
                "matched_event_sources": (matched or {}).get("matched_event_sources") or [],
                "matched_event_source_labels": (matched or {}).get("matched_event_source_labels") or [],
                "matched_event_source_label": str((matched or {}).get("matched_event_source_label") or ""),
                "content_preview": _safe_preview_value(record.get("content") or record.get("病程内容") or record.get("护理内容"), 180),
            }
        )
    return rows


def _build_bundle_match_diagnostic(bundle, audit_type, query_date_label: str) -> dict:
    payload, _ = compose(audit_type, bundle, query_date_label)
    sources = getattr(bundle, "sources", {}) or {}
    source_counts = {
        key: len(value) if isinstance(value, list) else (1 if value else 0)
        for key, value in sources.items()
    }
    source_samples = {
        key: _source_sample_records(value if isinstance(value, list) else [value])
        for key, value in sources.items()
    }
    context_diagnostics = payload.get("context_match_diagnostics") or {}
    progress_records = sources.get("progress") if isinstance(sources, dict) else []
    nursing_records = sources.get("nursing") if isinstance(sources, dict) else []
    progress_records = progress_records if isinstance(progress_records, list) else []
    nursing_records = nursing_records if isinstance(nursing_records, list) else []
    group_values = getattr(bundle, "group_values", {}) or {}
    structured_input = {}
    if payload.get("abnormal_labs") is not None or payload.get("abnormal_exams") is not None:
        try:
            structured_input = build_lab_exam_structured_input_for_diagnostics(audit_type, bundle, query_date_label)
        except Exception:
            logger.warning("failed to build structured_input for diagnostics", exc_info=True)
    return {
        "record_key": get_bundle_source_key(bundle, audit_type),
        "bundle_id": getattr(bundle, "bundle_id", "") or "",
        "group_values": group_values,
        "patient_id": str(group_values.get("patient_id") or _first_record_value(_bundle_records_for_preview(bundle), ["patient_id", KEY_PATIENT_ID]) or ""),
        "visit_number": str(group_values.get("visit_number") or _first_record_value(_bundle_records_for_preview(bundle), ["visit_number", KEY_VISIT_NO]) or ""),
        "patient_name": _first_record_value(_bundle_records_for_preview(bundle), ["patient_name", KEY_PATIENT_NAME]),
        "source_counts": source_counts,
        "source_samples": source_samples,
        "context_match_diagnostics": context_diagnostics,
        "progress_candidates": _diagnose_context_records(progress_records, "progress", context_diagnostics),
        "nursing_candidates": _diagnose_context_records(nursing_records, "nursing", context_diagnostics),
        "payload_rules": payload.get("rules") or {},
        "structured_input": structured_input,
    }


def _build_bundle_query_preview_rows(
    grouped: dict,
    audit_type,
    latest_push_map: dict[str, PushLog],
) -> list[dict]:
    rows: list[dict] = []
    audit_type_code = _audit_type_code(audit_type)
    audit_type_name = str(getattr(audit_type, "name", "") or "")
    for _, bundle in grouped.items():
        record_key = get_bundle_source_key(bundle, audit_type)
        record = _first_bundle_record(bundle)
        preview_records = _bundle_records_for_preview(bundle)
        medical_document_time, medical_document_name = _bundle_preview_document(bundle, audit_type)
        group_values = getattr(bundle, "group_values", {}) or {}
        latest = latest_push_map.get(record_key)
        source_counts = {
            key: len(value) if isinstance(value, list) else (1 if value else 0)
            for key, value in (getattr(bundle, "sources", {}) or {}).items()
        }
        rows.append(
            {
                "record_key": record_key,
                "audit_type_code": audit_type_code,
                "audit_type_name": audit_type_name,
                "bundle_id": getattr(bundle, "bundle_id", "") or "",
                "source_counts": source_counts,
                "mrid": get_record_mrid(record),
                "patient_id": str(group_values.get("patient_id") or _first_record_value(preview_records, ["patient_id", KEY_PATIENT_ID]) or ""),
                "visit_number": str(group_values.get("visit_number") or _first_record_value(preview_records, ["visit_number", KEY_VISIT_NO]) or ""),
                "patient_name": _first_record_value(preview_records, ["patient_name", KEY_PATIENT_NAME]),
                "admission_no": _first_record_value(preview_records, ["admission_no", "住院号"]),
                "dept": _first_record_value(preview_records, ["dept", "department", KEY_DEPT, "所在科室", "科室"]),
                "medical_document_time": str(medical_document_time or ""),
                "medical_document_name": str(medical_document_name or ""),
                "nursing_record_time": str(record.get("nursing_time") or record.get(KEY_NURSE_CREATE_TIME) or record.get(KEY_NURSE_TIME) or record.get(KEY_NURSE_FORM_TIME) or ""),
                "nursing_record_type": str(record.get("nursing_type") or record.get("护理记录_文书类型") or record.get("护理单类型") or ""),
                "mr_text_preview": "",
                "pushed_before": latest is not None,
                "latest_log_id": int(getattr(latest, "id", 0) or 0) if latest else None,
                "latest_push_status": str(getattr(latest, "status", "") or "") if latest else "",
                "latest_push_time": getattr(latest, "push_time", None) if latest else None,
                "latest_reviewed_flag": int(getattr(latest, "reviewed_flag", 0) or 0) if latest else 0,
            }
        )
    rows.sort(
        key=lambda item: (
            0 if not item["pushed_before"] else 1,
            str(item.get("patient_id") or ""),
            str(item.get("visit_number") or ""),
            str(item.get("bundle_id") or ""),
        )
    )
    return rows


def _load_persisted_dify_targets(config: dict) -> list[dict]:
    """Load enabled persisted Dify targets from config.dify.targets."""
    dify_section = (config or {}).get("dify", {}) or {}
    raw_targets = dify_section.get("targets", []) or []
    persisted: list[dict] = []
    for idx, item in enumerate(raw_targets):
        t = dict(item or {})
        if not t or not bool(t.get("enabled", True)):
            continue
        api_key = ""
        try:
            api_key = decrypt_value(t.get("api_key_enc", "")) if t.get("api_key_enc") else ""
        except Exception:
            api_key = ""
        if not api_key:
            continue
        base_url = str(t.get("base_url") or "").strip()
        if not base_url:
            continue
        try:
            base_url = normalize_dify_base_url(base_url)
        except Exception:
            continue
        persisted.append(
            {
                "name": str(t.get("name") or f"target-{idx + 1}"),
                "base_url": base_url,
                "api_key": api_key,
                "timeout_seconds": int(t.get("timeout_seconds") or 90),
                "weight": int(t.get("weight") or 1),
                "enabled": True,
            }
        )
    return persisted


def _build_manual_dify_targets(
    body: ManualPushRequest,
    dify_cfg: dict,
    config: dict | None = None,
) -> list[dict] | None:
    targets = []
    if body.dify_targets:
        for item in body.dify_targets:
            if hasattr(item, "model_dump"):
                targets.append(item.model_dump())
            else:
                targets.append(dict(item))
    if not targets:
        targets = _load_persisted_dify_targets(config or {})
        if not targets:
            return None

    def _build_endpoint_target(base_cfg: dict, target_cfg: dict, idx: int) -> dict:
        base_url = normalize_dify_base_url(str(target_cfg.get("base_url") or "").strip())
        api_key = str(target_cfg.get("api_key") or "").strip()
        if not base_url or not api_key:
            raise HTTPException(status_code=422, detail=f"Dify target[{idx}] requires non-empty base_url and api_key")

        timeout_seconds = int(target_cfg.get("timeout_seconds") or base_cfg.get("timeout_seconds", 90))
        merged_target = dict(base_cfg)
        merged_target["base_url"] = base_url
        merged_target["api_key"] = api_key
        merged_target["name"] = str(target_cfg.get("name") or f"target-{idx + 1}")
        merged_target["weight"] = int(target_cfg.get("weight") or 1)
        merged_target["enabled"] = bool(target_cfg.get("enabled", True))
        merged_target["timeout_seconds"] = timeout_seconds
        return merged_target

    # 优先级约束：manual/persisted targets 仅覆盖 endpoint（base_url/api_key）与路由元信息。
    # workflow_input_variable/workflow_output_key/response_paths 保持 audit_type.dify 与 audit_type.response。
    merged = []
    for idx, t in enumerate(targets):
        cfg = _build_endpoint_target(dify_cfg, t, idx)
        if not cfg.get("enabled", True):
            continue
        merged.append(cfg)

    if not merged:
        raise HTTPException(status_code=422, detail="No enabled Dify target after endpoint merge")

    unique_identities = {
        (
            normalize_dify_base_url(str(item.get("base_url") or "").strip()),
            str(item.get("api_key") or "").strip(),
        )
        for item in merged
        if str(item.get("base_url") or "").strip()
    }
    if len(merged) >= 2 and len(unique_identities) <= 1:
        raise HTTPException(
            status_code=422,
            detail="要实现真实负载分流，多个已启用的 Dify 目标必须配置为不同的 base_url 或 api_key。",
        )
    logger.info(
        "[audit.dify] manual targets prepared count=%s override_fields=base_url,api_key workflow_input_variable=%s workflow_output_key=%s",
        len(merged),
        str(dify_cfg.get("workflow_input_variable") or "mr_txt"),
        str(dify_cfg.get("workflow_output_key") or "aa"),
    )
    return merged


def _paginate_query_preview_rows(rows: list[dict], page: int | None, page_size: int | None) -> tuple[list[dict], dict]:
    total_rows = len(rows)
    use_paging = page is not None and page_size is not None
    if not use_paging:
        return rows, {
            "paged": False,
            "page": 1,
            "page_size": total_rows,
            "total_rows": total_rows,
            "total_pages": 1 if total_rows > 0 else 0,
        }

    total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 0
    safe_page = page
    if total_pages > 0:
        safe_page = min(max(page, 1), total_pages)
    else:
        safe_page = 1
    start = (safe_page - 1) * page_size
    end = start + page_size
    return rows[start:end], {
        "paged": True,
        "page": safe_page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
    }


def _should_use_bulk_executor(body: ManualPushRequest) -> bool:
    if int(body.parallel_workers or 1) > 1:
        return True
    if int(body.empty_retry_max or 0) > 0:
        return True
    if body.dify_targets:
        return True
    return False


def _effective_parallel_workers(requested_workers: int) -> tuple[int, str]:
    workers = max(1, int(requested_workers or 1))
    db_type = str(get_app_db_type() or "").lower()
    if db_type == "sqlite":
        capped = min(workers, 4)
        if capped != workers:
            return capped, "sqlite mode: workers capped to 4 to reduce database lock contention"
    return workers, ""


def _effective_audit_type_workers(audit_type_count: int, parallel_enabled: bool) -> tuple[int, str]:
    if not parallel_enabled:
        return 1, ""
    workers = min(max(1, int(audit_type_count or 1)), 3)
    notes: list[str] = []
    if audit_type_count > workers:
        notes.append("audit type parallelism capped to 3")
    if str(get_app_db_type() or "").lower() == "sqlite" and workers > 1:
        notes.append("sqlite mode: parallel audit types may increase database write contention")
    return workers, "; ".join(notes)


def _resolve_manual_audit_types(config: dict, body: ManualPushRequest):
    registry = AuditTypeRegistry(config)
    if body.audit_type_codes:
        items = []
        for code in body.audit_type_codes:
            try:
                items.append(registry.get(code))
            except KeyError:
                raise HTTPException(status_code=404, detail=f"audit_type not found: {code}")
        return registry, items
    return registry, registry.list_default_schedule()


def _resolve_query_preview_audit_type(config: dict, body: ManualPushRequest) -> tuple[str, str]:
    """Return the audit type that SQL-preview selected rows should target.

    The SQL preview table is still the legacy single-record preview. When the
    form has multiple default audit types selected, prefer progress_vs_nursing
    so clicking "push selected" does not fan out into unrelated multi-source
    audit workflows.
    """
    try:
        _, audit_types = _resolve_manual_audit_types(config, body)
    except Exception:
        return "", ""
    if len(audit_types) == 1:
        item = audit_types[0]
        return _audit_type_code(item), str(getattr(item, "name", "") or "")
    for item in audit_types:
        if _audit_type_code(item) == "progress_vs_nursing":
            return "progress_vs_nursing", str(getattr(item, "name", "") or "")
    return "", ""


def _is_legacy_single_type(audit_types: list) -> bool:
    if len(audit_types) != 1:
        return False
    if str(getattr(audit_types[0], "code", "") or "") != "progress_vs_nursing":
        return False
    payload_cfg = audit_types[0].payload or {}
    return str(payload_cfg.get("builder") or "") == "legacy_progress_nursing"


def _resolve_legacy_audit_type(config: dict):
    try:
        return AuditTypeRegistry(config).get("progress_vs_nursing")
    except Exception:
        logger.debug("failed to resolve legacy progress_vs_nursing audit type", exc_info=True)
        return None


def _manual_push_for_configured_audit_types_v2(
    body: ManualPushRequest,
    config: dict,
    audit_types: list,
):
    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        task_manager = get_task_manager()
        task_manager.create_task(task_id)
        thread = threading.Thread(
            target=_async_push_for_configured_audit_types_v2,
            args=(task_id, body.model_dump(), config, [item.code for item in audit_types]),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "message": "async task submitted", "diagnostics": []}

    query_dates = _resolve_query_dates(body)
    if not query_dates:
        raise HTTPException(status_code=422, detail="multi audit type requires explicit query_date/date range")

    diagnostics: list[str] = []
    use_bulk_executor = _should_use_bulk_executor(body)
    field_mapping = ConfigParser.get_field_mapping(config, ConfigParser.get_data_source_type(config))
    push_settings = ConfigParser.get_push_settings(config)
    query_date_label = _date_label(query_dates)
    effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers) if use_bulk_executor else (1, "")
    audit_type_workers, audit_type_worker_note = _effective_audit_type_workers(len(audit_types), body.parallel_audit_types)

    def _run_single_audit_type(audit_type):
        audit_results: list[dict] = []
        preview_rows: list[dict] = []
        all_bundles = []
        for query_date in query_dates:
            bundles = load_patient_bundles(
                audit_type=audit_type,
                root_config=config,
                query_date=query_date,
                date_dimension=body.date_dimension,
                dept_filter=body.dept_filter or [],
            )
            all_bundles.extend(bundles)

        grouped = {bundle.bundle_id: bundle for bundle in all_bundles}
        grouped_before_selected = len(grouped)
        grouped = _filter_bundles_by_selected_record_keys(grouped, body.selected_record_keys, audit_type)
        run_result = {
            "audit_type_code": audit_type.code,
            "audit_type_name": audit_type.name,
            "total": len(grouped),
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "results": audit_results,
            "preview": preview_rows,
            "diagnostics": [],
            "target_metrics": {},
            "empty_retry_total": 0,
        }
        if body.selected_record_keys and grouped_before_selected and not grouped:
            run_result["diagnostics"].append(f"{audit_type.name}: selected records did not match any pushable bundle")
        if not grouped:
            run_result["diagnostics"].append(f"{audit_type.name}: no matched bundles")
            return run_result

        if body.dry_run:
            for bundle in grouped.values():
                preview_rows.append(
                    {
                        "audit_type_code": audit_type.code,
                        "audit_type_name": audit_type.name,
                        "bundle_id": bundle.bundle_id,
                        "patient_id": bundle.group_values.get("patient_id", ""),
                        "visit_number": bundle.group_values.get("visit_number", ""),
                        "source_counts": {key: len(value) for key, value in bundle.sources.items()},
                    }
                )
            return run_result

        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            audit_type_code=audit_type.code,
            audit_type=audit_type,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        dify_override = audit_type.dify.model_dump()
        if dify_override.get("api_key_enc") and not dify_override.get("api_key"):
            dify_override["api_key"] = ConfigParser.parse_dify_config({"dify": dify_override}).get("api_key", "")

        if use_bulk_executor:
            executor = BulkPushExecutor(
                dify_config=dify_override,
                notify_config=config.get("notify", {}),
                field_mapping=field_mapping,
                dify_targets=_build_manual_dify_targets(body, dify_override, config),
                max_workers=effective_workers,
                empty_retry_max=body.empty_retry_max,
                empty_retry_backoff_ms=body.empty_retry_backoff_ms,
                target_strategy=body.target_strategy,
            )
            result = executor.execute(grouped, push_config)
            run_result["target_metrics"] = executor.get_target_metrics()
            run_result["empty_retry_total"] = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
        else:
            executor = PushExecutor(dify_override, config.get("notify", {}), field_mapping)
            local_db = SessionLocal()
            try:
                result = executor.execute(local_db, grouped, push_config)
            finally:
                local_db.close()

        for item in result.results:
            item["audit_type_code"] = audit_type.code
            item["audit_type_name"] = audit_type.name
            audit_results.append(item)
        run_result["success"] = int(result.success)
        run_result["failed"] = int(result.failed)
        run_result["skipped"] = int(getattr(result, "skipped", 0) or len([item for item in audit_results if item.get("status") == "skipped"]))
        _log_push_funnel(f"manual:{audit_type.code}", query_date_label, len(grouped), len(grouped), len(grouped), result)
        return run_result

    run_results: dict[str, dict] = {}
    if audit_type_workers <= 1:
        for audit_type in audit_types:
            run_results[audit_type.code] = _run_single_audit_type(audit_type)
    else:
        with ThreadPoolExecutor(max_workers=audit_type_workers, thread_name_prefix="manual-audit-type") as pool:
            futures = {
                pool.submit(_run_single_audit_type, audit_type): audit_type.code
                for audit_type in audit_types
            }
            for future in as_completed(futures):
                run_results[futures[future]] = future.result()

    all_results: list[dict] = []
    target_metrics: dict[str, dict] = {}
    empty_retry_total = 0
    total_bundles = 0
    success_total = 0
    failed_total = 0
    skipped_total = 0
    preview_rows: list[dict] = []

    for audit_type in audit_types:
        current = run_results[audit_type.code]
        total_bundles += int(current.get("total", 0))
        success_total += int(current.get("success", 0))
        failed_total += int(current.get("failed", 0))
        skipped_total += int(current.get("skipped", 0))
        empty_retry_total += int(current.get("empty_retry_total", 0))
        diagnostics.extend(current.get("diagnostics", []))
        preview_rows.extend(current.get("preview", []))
        if current.get("target_metrics"):
            target_metrics[audit_type.code] = current["target_metrics"]
        all_results.extend(current.get("results", []))

    worker_notes = [note for note in [worker_note, audit_type_worker_note] if note]
    response = {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "total": total_bundles,
        "success": success_total,
        "failed": failed_total,
        "skipped": skipped_total,
        "raw_rows": total_bundles,
        "filtered_rows": total_bundles,
        "grouped": total_bundles,
        "used_bulk_executor": use_bulk_executor,
        "parallel_workers_effective": effective_workers if use_bulk_executor else 1,
        "parallel_audit_types_effective": audit_type_workers > 1,
        "parallel_audit_type_workers": audit_type_workers,
        "worker_note": "; ".join(worker_notes),
        "target_metrics": target_metrics,
        "empty_retry_total": empty_retry_total,
        "diagnostics": diagnostics,
        "results": all_results,
        "audit_type_codes": [item.code for item in audit_types],
    }
    if body.dry_run:
        response.update(
            {
                "dry_run": True,
                "total_patients": total_bundles,
                "total_records": total_bundles,
                "preview": preview_rows,
            }
        )
    return response


@router.post("/manual", summary="Manual push")
def manual_push(body: ManualPushRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    config = load_config()
    registry, audit_types = _resolve_manual_audit_types(config, body)
    audit_types = _scope_audit_types_by_selected_record_keys(audit_types, body.selected_record_keys)
    if not _is_legacy_single_type(audit_types):
        return _manual_push_for_configured_audit_types_v2(body, config, audit_types)
    audit_type = audit_types[0]

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = (
        ConfigParser.parse_postgresql_config(config)
        if data_source == "postgresql"
        else ConfigParser.parse_oracle_config(config)
    )
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    query_dates, query_date_label, dept_list, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config = _prepare_push_data(
        body, config, data_source, db_cfg, field_mapping
    )
    grouped_before_selected = len(grouped)
    grouped = _filter_grouped_records(grouped, body.selected_record_keys)
    grouped_after_selected = len(grouped)

    # 断点续推：过滤已成功的记录（不适用于 dry_run 和 query_preview）
    pre_skip_succeeded_items: list[dict] = []
    if body.skip_already_succeeded and not body.dry_run:
        grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)

    logger.info(
        "[manual_push] mode=%s date_dimension=%s query_dates=%s dept_count=%s dept_mode=%s dept_list_size=%s raw_rows=%s pre_dept_rows=%s filtered_rows=%s grouped_before_selected=%s grouped_after_selected=%s selected_record_keys=%s skip_already_succeeded=%s skipped_succeeded=%s dry_run=%s async_mode=%s",
        "range" if (body.date_from and body.date_to) else "single",
        body.date_dimension,
        query_dates,
        len(dept_list or []),
        str((dept_config or {}).get("mode") or "include"),
        len((dept_config or {}).get("list") or []),
        raw_rows,
        pre_dept_rows,
        filtered_rows,
        grouped_before_selected,
        grouped_after_selected,
        len(body.selected_record_keys or []),
        body.skip_already_succeeded,
        len(pre_skip_succeeded_items),
        body.dry_run,
        body.async_mode,
    )

    diagnostics = _build_query_diagnostics(body, db_cfg, raw_rows, pre_dept_rows, filtered_rows, dept_config)
    use_bulk_executor = _should_use_bulk_executor(body)

    if not grouped:
        empty_result = {
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total": len(pre_skip_succeeded_items),
            "success": 0,
            "failed": 0,
            "skipped": len(pre_skip_succeeded_items),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "grouped": 0,
            "used_bulk_executor": use_bulk_executor,
            "parallel_workers_effective": 0,
            "worker_note": "",
            "target_metrics": {},
            "empty_retry_total": 0,
            "results": pre_skip_succeeded_items,
            "diagnostics": diagnostics,
        }
        if body.dry_run:
            empty_result.update(
                {
                    "dry_run": True,
                    "total_patients": 0,
                    "total_records": 0,
                    "preview": [],
                }
            )
        return empty_result

    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        task_manager = get_task_manager()
        task_manager.create_task(task_id)
        thread_target = _async_push_bulk if use_bulk_executor else _async_push
        thread = threading.Thread(
            target=thread_target,
            args=(
                task_id,
                body.model_dump(),
                dept_list,
                data_source,
                db_cfg,
                dify_cfg,
                config,
                push_settings,
                field_mapping,
            ),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "message": "async task submitted", "diagnostics": diagnostics}

    if body.dry_run:
        name_field = field_mapping.get("patient_name", KEY_PATIENT_NAME)
        preview = []
        for pid, patient_records in grouped.items():
            payload = build_dify_payload(patient_records, field_mapping, query_date_label)
            preview.append(
                {
                    "patient_id": pid,
                    "patient_name": patient_records[0].get(name_field, ""),
                    "dept": patient_records[0].get(dept_field, ""),
                    "record_count": len(patient_records),
                    "mr_text_preview": build_mr_text_combined(patient_records, field_mapping)[:500] + "...",
                    "dify_payload": payload,
                }
            )
        return {
            "dry_run": True,
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total_patients": len(grouped),
            "total_records": len(records),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "diagnostics": diagnostics,
            "preview": preview,
        }

    push_config = PushConfig(
        trigger_type="manual",
        query_date=query_date_label,
        audit_type_code=audit_type.code,
        audit_type=audit_type,
        interval_ms=push_settings["interval_ms"],
        max_retry=push_settings["max_retry"],
        notify_enabled=True,
    )
    effective_workers = 1
    worker_note = ""
    target_metrics: dict = {}
    empty_retry_total = 0
    if use_bulk_executor:
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg, config),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(grouped, push_config)
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
    else:
        executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
    _log_push_funnel("manual", query_date_label, raw_rows, filtered_rows, len(grouped), result)

    all_results = pre_skip_succeeded_items + result.results
    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "total": result.total + len(pre_skip_succeeded_items),
        "success": result.success,
        "failed": result.failed,
        "skipped": len([r for r in all_results if r.get("status") == "skipped"]),
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "used_bulk_executor": use_bulk_executor,
        "parallel_workers_effective": effective_workers,
        "worker_note": worker_note,
        "target_metrics": target_metrics,
        "empty_retry_total": empty_retry_total,
        "diagnostics": diagnostics,
        "results": all_results,
    }


@router.post("/preview", summary="Manual dry-run preview")
def preview_push(body: ManualPushRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    body.dry_run = True
    return manual_push(body, db)


@router.post("/query-preview", summary="Manual query preview")
def query_preview(body: ManualPushRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    config = load_config()
    registry, audit_types = _resolve_manual_audit_types(config, body)
    if len(audit_types) == 1 and not _is_legacy_single_type(audit_types):
        audit_type = audit_types[0]
        query_dates = _resolve_query_dates(body)
        if not query_dates:
            raise HTTPException(status_code=422, detail="query_date is required")

        all_bundles = []
        for query_date in query_dates:
            all_bundles.extend(
                load_patient_bundles(
                    audit_type=audit_type,
                    root_config=config,
                    query_date=query_date,
                    date_dimension=body.date_dimension,
                    dept_filter=body.dept_filter or [],
                )
            )
        grouped = {bundle.bundle_id: bundle for bundle in all_bundles}
        grouped_before_selected = len(grouped)
        grouped = _filter_bundles_by_selected_record_keys(grouped, body.selected_record_keys, audit_type)
        grouped_after_selected = len(grouped)
        latest_push_map = _load_latest_push_map(db, [get_bundle_source_key(bundle, audit_type) for bundle in grouped.values()])
        all_rows = _build_bundle_query_preview_rows(grouped, audit_type, latest_push_map)
        rows, page_meta = _paginate_query_preview_rows(all_rows, body.page, body.page_size)
        raw_rows = sum(
            len(records) if isinstance(records, list) else (1 if records else 0)
            for bundle in all_bundles
            for records in (getattr(bundle, "sources", {}) or {}).values()
        )
        diagnostics = []
        if grouped_before_selected and body.selected_record_keys and not grouped:
            diagnostics.append("勾选记录未匹配到当前审计类型的可推送数据，请重新查询并勾选该审计类型候选记录。")
        if not grouped_before_selected:
            diagnostics.append(f"{getattr(audit_type, 'name', '') or audit_type.code}：未查询到可推送数据")

        logger.info(
            "[query_preview] mode=%s audit_type=%s date_dimension=%s query_dates=%s raw_rows=%s grouped_before_selected=%s grouped_after_selected=%s total_rows=%s page=%s page_size=%s selected_record_keys=%s diagnostics=%s",
            "range" if (body.date_from and body.date_to) else "single",
            audit_type.code,
            body.date_dimension,
            query_dates,
            raw_rows,
            grouped_before_selected,
            grouped_after_selected,
            len(all_rows),
            page_meta.get("page"),
            page_meta.get("page_size"),
            len(body.selected_record_keys or []),
            diagnostics,
        )

        return {
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "query_date_label": _date_label(query_dates),
            "preview_audit_type_code": audit_type.code,
            "preview_audit_type_name": getattr(audit_type, "name", "") or "",
            "raw_rows": raw_rows,
            "filtered_rows": raw_rows,
            "grouped": len(grouped),
            "selected_count": len(body.selected_record_keys or []),
            "pushed_count": len([row for row in all_rows if row.get("pushed_before")]),
            "unpushed_count": len([row for row in all_rows if not row.get("pushed_before")]),
            "paged": bool(page_meta["paged"]),
            "page": int(page_meta["page"]),
            "page_size": int(page_meta["page_size"]),
            "total_rows": int(page_meta["total_rows"]),
            "total_pages": int(page_meta["total_pages"]),
            "rows": rows,
            "diagnostics": diagnostics,
        }

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = (
        ConfigParser.parse_postgresql_config(config)
        if data_source == "postgresql"
        else ConfigParser.parse_oracle_config(config)
    )
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    query_dates, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config = _prepare_push_data(
        body, config, data_source, db_cfg, field_mapping
    )
    grouped_before_selected = len(grouped)
    grouped = _filter_grouped_records(grouped, body.selected_record_keys)
    grouped_after_selected = len(grouped)
    diagnostics = _build_query_diagnostics(body, db_cfg, raw_rows, pre_dept_rows, filtered_rows, dept_config)
    preview_audit_type_code, preview_audit_type_name = _resolve_query_preview_audit_type(config, body)
    latest_push_map = _load_latest_push_map(db, list(grouped.keys()))
    all_rows = _build_query_preview_rows(
        grouped,
        field_mapping,
        dept_field,
        latest_push_map,
        preview_audit_type_code=preview_audit_type_code,
        preview_audit_type_name=preview_audit_type_name,
    )
    rows, page_meta = _paginate_query_preview_rows(all_rows, body.page, body.page_size)

    logger.info(
        "[query_preview] mode=%s date_dimension=%s query_dates=%s dept_mode=%s dept_list_size=%s raw_rows=%s pre_dept_rows=%s filtered_rows=%s grouped_before_selected=%s grouped_after_selected=%s total_rows=%s page=%s page_size=%s selected_record_keys=%s diagnostics=%s",
        "range" if (body.date_from and body.date_to) else "single",
        body.date_dimension,
        query_dates,
        str((dept_config or {}).get("mode") or "include"),
        len((dept_config or {}).get("list") or []),
        raw_rows,
        pre_dept_rows,
        filtered_rows,
        grouped_before_selected,
        grouped_after_selected,
        len(all_rows),
        page_meta.get("page"),
        page_meta.get("page_size"),
        len(body.selected_record_keys or []),
        diagnostics,
    )

    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "query_date_label": query_date_label,
        "preview_audit_type_code": preview_audit_type_code,
        "preview_audit_type_name": preview_audit_type_name,
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "selected_count": len(body.selected_record_keys or []),
        "pushed_count": len([row for row in all_rows if row.get("pushed_before")]),
        "unpushed_count": len([row for row in all_rows if not row.get("pushed_before")]),
        "paged": bool(page_meta["paged"]),
        "page": int(page_meta["page"]),
        "page_size": int(page_meta["page_size"]),
        "total_rows": int(page_meta["total_rows"]),
        "total_pages": int(page_meta["total_pages"]),
        "diagnostics": diagnostics,
        "rows": rows,
    }


@router.post("/match-diagnostics", summary="Manual push match diagnostics")
def push_match_diagnostics(body: ManualPushRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    """只读展示 SQL 查询、bundle 合并、join_rules 和 payload 上下文匹配链路。"""
    config = load_config()
    _, audit_types = _resolve_manual_audit_types(config, body)
    if len(audit_types) != 1 or _is_legacy_single_type(audit_types):
        raise HTTPException(status_code=422, detail="match diagnostics requires one configured multi-source audit type")
    audit_type = audit_types[0]
    query_dates = _resolve_query_dates(body)
    if not query_dates:
        raise HTTPException(status_code=422, detail="query_date is required")

    all_bundles = []
    source_row_counts: dict[str, int] = {}
    skipped_records = 0
    for query_date in query_dates:
        bundles, diagnostics = load_patient_bundles(
            audit_type=audit_type,
            root_config=config,
            query_date=query_date,
            date_dimension=body.date_dimension,
            dept_filter=body.dept_filter or [],
            return_diagnostics=True,
        )
        all_bundles.extend(bundles)
        for source_name, count in (diagnostics.get("source_row_counts") or {}).items():
            source_row_counts[source_name] = int(source_row_counts.get(source_name, 0)) + int(count or 0)
        skipped_records += int(diagnostics.get("skipped_records") or 0)

    grouped = {bundle.bundle_id: bundle for bundle in all_bundles}
    grouped_before_selected = len(grouped)
    grouped = _filter_bundles_by_selected_record_keys(grouped, body.selected_record_keys, audit_type)
    grouped_after_selected = len(grouped)
    if body.selected_record_keys and not grouped:
        raise HTTPException(status_code=404, detail="selected record does not match current audit type/date range")

    limited_bundles = list(grouped.values())[:20]
    query_date_label = _date_label(query_dates)
    join_rules = []
    if getattr(audit_type, "join_rules", None):
        join_rules = [rule.model_dump() if hasattr(rule, "model_dump") else dict(rule) for rule in audit_type.join_rules]
    bundle_details = [_build_bundle_match_diagnostic(bundle, audit_type, query_date_label) for bundle in limited_bundles]

    logger.info(
        "[match_diagnostics] audit_type=%s query_dates=%s source_rows=%s grouped_before_selected=%s grouped_after_selected=%s returned=%s selected_record_keys=%s",
        audit_type.code,
        query_dates,
        source_row_counts,
        grouped_before_selected,
        grouped_after_selected,
        len(bundle_details),
        len(body.selected_record_keys or []),
    )
    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "query_date_label": query_date_label,
        "audit_type_code": audit_type.code,
        "audit_type_name": getattr(audit_type, "name", "") or "",
        "group_key": list(getattr(audit_type, "group_key", []) or []),
        "join_rules": join_rules,
        "source_row_counts": source_row_counts,
        "skipped_records": skipped_records,
        "grouped_before_selected": grouped_before_selected,
        "grouped_after_selected": grouped_after_selected,
        "returned_bundle_count": len(bundle_details),
        "bundle_details": bundle_details,
    }


@router.post("/precheck", summary="Manual push precheck")
def push_precheck(body: ManualPushRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    """预检推送数据，不实际推送，不调用 Dify。"""
    from app.services.audit_precheck import summarize_bundles

    config = load_config()
    _, audit_types = _resolve_manual_audit_types(config, body)
    query_dates = _resolve_query_dates(body)
    if not query_dates:
        raise HTTPException(status_code=422, detail="precheck requires explicit query_date/date range")

    all_results = []
    for audit_type in audit_types:
        all_bundles = []
        source_row_counts = {}
        for query_date in query_dates:
            bundles, diagnostics = load_patient_bundles(
                audit_type=audit_type,
                root_config=config,
                query_date=query_date,
                date_dimension=body.date_dimension,
                dept_filter=body.dept_filter or [],
                return_diagnostics=True,
            )
            all_bundles.extend(bundles)
            for src, count in diagnostics.get("source_row_counts", {}).items():
                source_row_counts[src] = source_row_counts.get(src, 0) + count

        grouped = {bundle.bundle_id: bundle for bundle in all_bundles}
        grouped = _filter_bundles_by_selected_record_keys(grouped, body.selected_record_keys, audit_type)

        precheck = summarize_bundles(audit_type, list(grouped.values()), source_row_counts)
        bundle_skip_reasons = precheck.get("bundle_skip_reasons", {})

        from app.services.push_skip_policy import get_surgery_chain_skip_reason
        for bundle in grouped.values():
            bundle_id = getattr(bundle, "bundle_id", "")
            if bundle_skip_reasons.get(bundle_id):
                continue
            surgery_reason, _ = get_surgery_chain_skip_reason(audit_type, bundle)
            if surgery_reason:
                precheck["skip_reason_counts"][surgery_reason] = precheck["skip_reason_counts"].get(surgery_reason, 0) + 1
                precheck["skip_count"] = precheck.get("skip_count", 0) + 1
                precheck["pushable_count"] = max(0, precheck.get("pushable_count", 0) - 1)
                bundle_skip_reasons[bundle_id] = surgery_reason

        # 基于 source_record_key 查询历史推送记录，只对未被空数据跳过的 bundle 检查
        if grouped:
            # 使用 source_record_key 查询历史，与实际推送逻辑一致
            source_keys = [get_bundle_source_key(bundle, audit_type) for bundle in grouped.values()]
            latest_push_map = _load_latest_push_map(db, source_keys)

            # 查询被整改抑制的患者（按审计类型隔离）
            suppressed_patient_keys: set[str] = set()
            patient_ids = [str(bundle.group_values.get("patient_id", "")) for bundle in grouped.values()]
            patient_ids = [pid for pid in patient_ids if pid]
            if patient_ids:
                audit_type_code = str(audit_type.code or "progress_vs_nursing").strip() or "progress_vs_nursing"
                suppressed_query = (
                    db.query(PushLog.patient_id, PushLog.visit_number)
                    .join(QCFeedback, QCFeedback.push_log_id == PushLog.id)
                    .filter(QCFeedback.suppress_ai_push == True)
                    .filter(QCFeedback.status == "rectified")
                    .filter(PushLog.patient_id.in_(patient_ids))
                    .distinct()
                )
                if audit_type_code == "progress_vs_nursing":
                    suppressed_query = suppressed_query.filter(
                        or_(PushLog.audit_type_code == audit_type_code, PushLog.audit_type_code == "")
                    )
                else:
                    suppressed_query = suppressed_query.filter(PushLog.audit_type_code == audit_type_code)
                suppressed_rows = suppressed_query.all()
                for row in suppressed_rows:
                    suppressed_patient_keys.add(f"{row[0]}::{row[1]}" if row[1] else str(row[0]))

            for bundle in grouped.values():
                bundle_id = getattr(bundle, "bundle_id", "")
                # 如果已经被空数据跳过，不再重复计数
                if bundle_skip_reasons.get(bundle_id):
                    continue

                source_key = get_bundle_source_key(bundle, audit_type)
                latest = latest_push_map.get(source_key)
                patient_id = str(bundle.group_values.get("patient_id", ""))
                visit_number = str(bundle.group_values.get("visit_number", ""))
                patient_key = f"{patient_id}::{visit_number}" if visit_number else patient_id

                # 检查是否被整改抑制（优先级高于已推送未复核）
                if patient_key in suppressed_patient_keys:
                    precheck["skip_reason_counts"]["rectified_suppressed"] = precheck["skip_reason_counts"].get("rectified_suppressed", 0) + 1
                    precheck["skip_count"] = precheck.get("skip_count", 0) + 1
                    precheck["pushable_count"] = max(0, precheck.get("pushable_count", 0) - 1)
                    continue

                if latest:
                    status = str(getattr(latest, "status", "") or "")
                    reviewed = int(getattr(latest, "reviewed_flag", 0) or 0)
                    override = int(getattr(latest, "manual_override", 0) or 0)
                    if status == "success" and reviewed == 0 and override == 0:
                        precheck["skip_reason_counts"]["unreviewed_pending"] = precheck["skip_reason_counts"].get("unreviewed_pending", 0) + 1
                        precheck["skip_count"] = precheck.get("skip_count", 0) + 1
                        precheck["pushable_count"] = max(0, precheck.get("pushable_count", 0) - 1)
                    elif status == "success":
                        precheck["skip_reason_counts"]["already_succeeded"] = precheck["skip_reason_counts"].get("already_succeeded", 0) + 1
                        precheck["skip_count"] = precheck.get("skip_count", 0) + 1
                        precheck["pushable_count"] = max(0, precheck.get("pushable_count", 0) - 1)

        # 移除内部使用的 bundle_skip_reasons，不暴露给前端
        precheck.pop("bundle_skip_reasons", None)

        all_results.append({
            "audit_type_code": audit_type.code,
            "audit_type_name": audit_type.name,
            "bundle_count": len(grouped),
            "precheck": precheck,
        })

    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "results": all_results,
    }


@router.post("/retry", summary="Retry failed pushes")
def retry_push(body: RetryRequest, db: Session = Depends(get_db), _admin=Depends(require_role("admin"))):
    config = load_config()
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    data_source = ConfigParser.get_data_source_type(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
    results = executor.execute_retry(db, body.log_ids, push_settings["max_retry"])
    return {"results": results}


@router.get("/status/{task_id}", response_model=PushProgress, summary="Get async task progress")
def get_push_status(task_id: str, _admin=Depends(require_role("admin"))):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)
    if not progress:
        return PushProgress(task_id=task_id, status="not_found")
    return PushProgress(
        task_id=progress.task_id,
        status=progress.status,
        total=progress.total,
        processed=progress.processed,
        success=progress.success,
        failed=progress.failed,
        skipped=progress.skipped,
        cancelled=progress.cancelled,
    )


@router.get("/tasks/latest", response_model=PushProgress, summary="Get latest async task progress")
def get_latest_push_task(_admin=Depends(require_role("admin"))):
    task_manager = get_task_manager()
    progress = task_manager.get_latest_task(status_filter="running") or task_manager.get_latest_task()
    if not progress:
        return PushProgress(task_id="", status="not_found")
    return PushProgress(
        task_id=progress.task_id,
        status=progress.status,
        total=progress.total,
        processed=progress.processed,
        success=progress.success,
        failed=progress.failed,
        skipped=progress.skipped,
        cancelled=progress.cancelled,
    )


@router.post("/cancel/{task_id}", summary="Cancel running async task")
def cancel_push_task(task_id: str, _admin=Depends(require_role("admin"))):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Task not found")
    if progress.status != "running":
        raise HTTPException(status_code=409, detail=f"Task is not running (status={progress.status})")
    ok = task_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Failed to cancel task")
    return {"message": "cancel requested", "task_id": task_id}


def _async_push(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    db = SessionLocal()
    task_manager = get_task_manager()
    try:
        body = ManualPushRequest(**body_data)
        query_dates, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, _, dept_config = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        grouped = _filter_grouped_records(grouped, body.selected_record_keys)
        # 断点续推：过滤已成功记录
        pre_skip_succeeded_items: list[dict] = []
        if body.skip_already_succeeded:
            grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)
        task_manager.update_task(task_id, total=len(grouped) + len(pre_skip_succeeded_items))
        # 已跳过的直接计入进度
        for _ in pre_skip_succeeded_items:
            task_manager.increment_processed(task_id, result_status="skipped")

        audit_type = _resolve_legacy_audit_type(config)
        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            audit_type_code="progress_vs_nursing",
            audit_type=audit_type,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )

        executor = AsyncCallbackPushExecutor(
            dify_cfg,
            config.get("notify", {}),
            field_mapping,
            on_item_done=lambda status: task_manager.increment_processed(
                task_id,
                result_status=status if status in ("success", "skipped") else "failed",
            ),
            stop_check=lambda: task_manager.is_cancelled(task_id),
            cancel_log_prefix="async",
        )
        result = executor.execute(db, grouped, push_config)
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        # 若任务被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="completed")
    except Exception as exc:
        logger.error("async push failed: %s", exc, exc_info=True)
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _async_push_bulk(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    task_manager = get_task_manager()
    final_status = "failed"
    try:
        body = ManualPushRequest(**body_data)
        _, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, _, dept_config = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        grouped = _filter_grouped_records(grouped, body.selected_record_keys)
        # 断点续推：过滤已成功记录
        pre_skip_succeeded_items: list[dict] = []
        if body.skip_already_succeeded:
            db = SessionLocal()
            try:
                grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)
            finally:
                db.close()
        task_manager.update_task(task_id, total=len(grouped) + len(pre_skip_succeeded_items))
        # 已跳过的直接计入进度
        for _ in pre_skip_succeeded_items:
            task_manager.increment_processed(task_id, result_status="skipped")
        audit_type = _resolve_legacy_audit_type(config)
        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            audit_type_code="progress_vs_nursing",
            audit_type=audit_type,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        if worker_note:
            logger.warning("[async bulk] %s task_id=%s requested=%s effective=%s", worker_note, task_id, body.parallel_workers, effective_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg, config),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(
            grouped,
            push_config,
            on_item_done=lambda status: task_manager.increment_processed(
                task_id,
                result_status="success" if status == "success" else ("skipped" if status == "skipped" else "failed"),
            ),
            stop_check=lambda: task_manager.is_cancelled(task_id),
        )
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
        logger.info(
            "[async bulk] task_id=%s target_metrics=%s empty_retry_total=%s",
            task_id,
            target_metrics,
            empty_retry_total,
        )
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        final_status = "completed"
    except Exception as exc:
        logger.error("async bulk push failed: %s", exc, exc_info=True)
        final_status = "failed"
    finally:
        try:
            # 若任务已被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
            if not task_manager.is_cancelled(task_id):
                task_manager.update_task(task_id, status=final_status)
        except Exception as exc:
            logger.error("async bulk push: failed to update task status: %s", exc, exc_info=True)


def _async_push_for_configured_audit_types_v2(task_id: str, body_data: dict, config: dict, audit_type_codes: list[str]):
    task_manager = get_task_manager()
    final_status = "failed"
    try:
        body = ManualPushRequest(**body_data)
        body.audit_type_codes = audit_type_codes
        _, audit_types = _resolve_manual_audit_types(config, body)
        audit_types = _scope_audit_types_by_selected_record_keys(audit_types, body.selected_record_keys)
        query_dates = _resolve_query_dates(body)
        if not query_dates:
            raise ValueError("multi audit type requires explicit query_date/date range")

        use_bulk_executor = _should_use_bulk_executor(body)
        field_mapping = ConfigParser.get_field_mapping(config, ConfigParser.get_data_source_type(config))
        push_settings = ConfigParser.get_push_settings(config)
        query_date_label = _date_label(query_dates)
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers) if use_bulk_executor else (1, "")
        if worker_note:
            logger.warning("[async audit-types] %s task_id=%s requested=%s effective=%s", worker_note, task_id, body.parallel_workers, effective_workers)

        grouped_by_type: dict[str, dict] = {}
        for audit_type in audit_types:
            if task_manager.is_cancelled(task_id):
                return
            all_bundles = []
            for query_date in query_dates:
                if task_manager.is_cancelled(task_id):
                    return
                all_bundles.extend(
                    load_patient_bundles(
                        audit_type=audit_type,
                        root_config=config,
                        query_date=query_date,
                        date_dimension=body.date_dimension,
                        dept_filter=body.dept_filter or [],
                    )
                )
            grouped = {bundle.bundle_id: bundle for bundle in all_bundles}
            grouped = _filter_bundles_by_selected_record_keys(grouped, body.selected_record_keys, audit_type)
            grouped_by_type[audit_type.code] = grouped

        total = sum(len(grouped) for grouped in grouped_by_type.values())
        task_manager.update_task(task_id, total=total)

        for audit_type in audit_types:
            if task_manager.is_cancelled(task_id):
                return
            grouped = grouped_by_type.get(audit_type.code, {})
            if not grouped:
                continue

            push_config = PushConfig(
                trigger_type="manual",
                query_date=query_date_label,
                audit_type_code=audit_type.code,
                audit_type=audit_type,
                interval_ms=push_settings["interval_ms"],
                max_retry=push_settings["max_retry"],
                notify_enabled=True,
            )
            dify_override = audit_type.dify.model_dump()
            if dify_override.get("api_key_enc") and not dify_override.get("api_key"):
                dify_override["api_key"] = ConfigParser.parse_dify_config({"dify": dify_override}).get("api_key", "")

            if use_bulk_executor:
                executor = BulkPushExecutor(
                    dify_config=dify_override,
                    notify_config=config.get("notify", {}),
                    field_mapping=field_mapping,
                    dify_targets=_build_manual_dify_targets(body, dify_override, config),
                    max_workers=effective_workers,
                    empty_retry_max=body.empty_retry_max,
                    empty_retry_backoff_ms=body.empty_retry_backoff_ms,
                    target_strategy=body.target_strategy,
                )
                result = executor.execute(
                    grouped,
                    push_config,
                    on_item_done=lambda status: task_manager.increment_processed(
                        task_id,
                        result_status="success" if status == "success" else ("skipped" if status == "skipped" else "failed"),
                    ),
                    stop_check=lambda: task_manager.is_cancelled(task_id),
                )
            else:
                local_db = SessionLocal()
                try:
                    executor = AsyncCallbackPushExecutor(
                        dify_override,
                        config.get("notify", {}),
                        field_mapping,
                        on_item_done=lambda status: task_manager.increment_processed(
                            task_id,
                            result_status=status if status in ("success", "skipped") else "failed",
                        ),
                        stop_check=lambda: task_manager.is_cancelled(task_id),
                        cancel_log_prefix=f"async:{audit_type.code}",
                    )
                    result = executor.execute(local_db, grouped, push_config)
                finally:
                    local_db.close()

            _log_push_funnel(f"async:{audit_type.code}", query_date_label, len(grouped), len(grouped), len(grouped), result)

        final_status = "completed"
    except Exception as exc:
        logger.error("async audit-types push failed: %s", exc, exc_info=True)
        final_status = "failed"
    finally:
        try:
            if not task_manager.is_cancelled(task_id):
                task_manager.update_task(task_id, status=final_status)
        except Exception as exc:
            logger.error("async audit-types push: failed to update task status: %s", exc, exc_info=True)
