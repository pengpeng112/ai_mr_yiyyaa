"""lab_exam_vs_progress_nursing payload builder（Task 9）。"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.schemas import AuditTypeConfig
from app.services.exam_aggregation import aggregate_exam_reports
from app.services.lab_aggregation import aggregate_lab_records
from app.services.progress_nursing_context_window import select_progress_nursing_context
from app.services.source_field_contract import normalize_date_to_ymd

if TYPE_CHECKING:
    from app.services.data_source_loader import PatientBundle
else:
    PatientBundle = Any


def _pick(record: dict[str, Any], *keys: str | None) -> str:
    for key in keys:
        if not key:
            continue
        value = record.get(key)
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _is_abnormal_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = _as_text(value).upper()
    return text in {"TRUE", "Y", "YES", "1", "ABNORMAL", "异常", "阳性", "是"}


def _append_normalized_date(target: list[str], value: Any) -> None:
    normalized = normalize_date_to_ymd(value)
    if normalized and normalized not in target:
        target.append(normalized)


def _append_text(target: list[str], value: Any) -> None:
    text = _as_text(value)
    if text and text not in target:
        target.append(text)


def _append_event_spec(target: list[dict[str, str]], seen_keys: set[tuple[str, str, str]], source: str, source_id: str, event_time: Any, name: str = "") -> None:
    text = _as_text(event_time)
    if not text:
        return
    dedup_key = (source, source_id or "", text)
    if dedup_key in seen_keys:
        return
    seen_keys.add(dedup_key)
    target.append(
        {
            "source": source,
            "source_id": source_id,
            "event_time": text,
            "event_date": normalize_date_to_ymd(text),
            "name": name,
        }
    )


def _extract_lab_exam_event_specs(lab_summary: dict[str, Any], exam_summary: dict[str, Any]) -> list[dict[str, str]]:
    event_specs: list[dict[str, str]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for item in lab_summary.get("items", []) or []:
        if not _is_abnormal_truthy(item.get("is_abnormal")):
            continue
        _append_event_spec(
            event_specs,
            seen_keys,
            "lab",
            _as_text(item.get("test_no")),
            item.get("result_time"),
            _as_text(item.get("test_name")) or _as_text(item.get("item_name")),
        )
    for report in exam_summary.get("reports", []) or []:
        if not _is_abnormal_truthy(report.get("is_abnormal")):
            continue
        # 检查事件时间只使用 report_time（报告出具时间），不回退 exam_time。
        # exam_time 仅表示检查执行时间，报告未出具前医生无法参考结果，不应产生关联日期。
        report_time = report.get("report_time")
        if not report_time:
            continue
        _append_event_spec(
            event_specs,
            seen_keys,
            "exam",
            _as_text(report.get("exam_no")),
            report_time,
            _as_text(report.get("exam_name")) or _as_text(report.get("exam_class")),
        )
    return event_specs


def _extract_event_times(event_specs: list[dict[str, str]]) -> list[str]:
    return [item["event_time"] for item in event_specs if item.get("event_time")]


def _extract_event_dates(event_specs: list[dict[str, str]]) -> list[str]:
    event_dates: list[str] = []
    for item in event_specs:
        _append_normalized_date(event_dates, item.get("event_time"))
    return event_dates


def _filter_context_event_specs(event_specs: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str], str]:
    lab_dates = {item.get("event_date") for item in event_specs if item.get("source") == "lab" and item.get("event_date")}
    exam_dates = {item.get("event_date") for item in event_specs if item.get("source") == "exam" and item.get("event_date")}
    if not lab_dates or not exam_dates:
        single_source_dates = sorted(lab_dates or exam_dates)
        return event_specs, single_source_dates, "single_source"
    matched_dates = sorted(lab_dates & exam_dates)
    if not matched_dates:
        return [], [], "no_same_day_lab_exam_event"
    matched_date_set = set(matched_dates)
    return [item for item in event_specs if item.get("event_date") in matched_date_set], matched_dates, "same_day_lab_exam"


def _event_source_summary(event_spec: dict[str, str] | None) -> str:
    if not event_spec:
        return ""
    source_label = "检验" if event_spec.get("source") == "lab" else "检查" if event_spec.get("source") == "exam" else _as_text(event_spec.get("source"))
    name = _as_text(event_spec.get("name"))
    source_id = _as_text(event_spec.get("source_id"))
    parts = [item for item in [source_label, name, source_id] if item]
    return " ".join(parts)


def _annotate_matched_event_sources(context: dict[str, Any], event_specs: list[dict[str, str]]) -> None:
    events_by_time: dict[str, list[dict[str, str]]] = {}
    for item in event_specs:
        event_time = item.get("event_time")
        if event_time:
            events_by_time.setdefault(event_time, []).append(item)
    for context_key in ("progress_context", "nursing_context"):
        for row in ((context.get(context_key) or {}).get("records") or []):
            matched_event_time = _as_text(row.get("matched_event_time"))
            matched_specs = events_by_time.get(matched_event_time) or []
            if not matched_specs:
                continue
            row["matched_event_sources"] = [dict(item) for item in matched_specs]
            row["matched_event_source_labels"] = [_event_source_summary(item) for item in matched_specs]
            row["matched_event_source"] = dict(matched_specs[0])
            row["matched_event_source_label"] = "；".join(row["matched_event_source_labels"])


def _build_event_day_summary(event_specs: list[dict[str, str]], context: dict[str, Any]) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for item in event_specs:
        day = _as_text(item.get("event_date"))
        if not day:
            continue
        entry = by_day.setdefault(day, {"date": day, "lab_events": [], "exam_events": [], "matched_progress": [], "matched_nursing": []})
        if item.get("source") == "lab":
            entry["lab_events"].append(item)
        elif item.get("source") == "exam":
            entry["exam_events"].append(item)

    for source_key, target_key in (("progress_context", "matched_progress"), ("nursing_context", "matched_nursing")):
        for row in ((context.get(source_key) or {}).get("records") or []):
            day = normalize_date_to_ymd(row.get("event_time"))
            if not day:
                continue
            entry = by_day.setdefault(day, {"date": day, "lab_events": [], "exam_events": [], "matched_progress": [], "matched_nursing": []})
            entry[target_key].append(
                {
                    "record_id": _as_text(row.get("record_id")),
                    "record_name": _as_text(row.get("record_name")),
                    "event_time": _as_text(row.get("event_time")),
                    "matched_event_time": _as_text(row.get("matched_event_time")),
                    "matched_event_source_label": _as_text(row.get("matched_event_source_label")),
                }
            )

    return [by_day[day] for day in sorted(by_day)]


def _has_abnormal_findings(lab_summary: dict[str, Any], exam_summary: dict[str, Any]) -> bool:
    return any(_is_abnormal_truthy(item.get("is_abnormal")) for item in (lab_summary.get("items", []) or [])) or any(
        _is_abnormal_truthy(report.get("is_abnormal")) for report in (exam_summary.get("reports", []) or [])
    )


def _empty_context() -> dict[str, Any]:
    return {
        "progress_context": {"records": [], "total_selected": 0, "followup_count": 0, "truncated": False},
        "nursing_context": {"records": [], "total_selected": 0, "truncated": False},
    }


def _pick_from_sources(bundle: PatientBundle, *keys: str | None) -> str:
    source_names = ["patient", bundle.primary_source, *bundle.sources.keys()]
    seen: set[str] = set()
    for source_name in source_names:
        if not source_name or source_name in seen:
            continue
        seen.add(source_name)
        mapping = bundle.source_field_mappings.get(source_name, {})
        records = bundle.sources.get(source_name) or []
        for record in records:
            if not isinstance(record, dict):
                continue
            mapped_keys: list[str | None] = []
            for key in keys:
                mapped_keys.append(mapping.get(key) if key else None)
                mapped_keys.append(key)
            value = _pick(record, *mapped_keys)
            if value:
                return value
    return ""


def _extract_patient_info(bundle: PatientBundle) -> dict[str, str]:
    first_record: dict[str, Any] = {}
    first_mapping: dict[str, str] = {}
    for source_name in [bundle.primary_source, *bundle.sources.keys()]:
        if source_name == "patient":
            continue
        records = bundle.sources.get(source_name) or []
        if records:
            first_record = records[0]
            first_mapping = bundle.source_field_mappings.get(source_name, {})
            break

    patient_records = bundle.sources.get("patient") or []
    patient_record = patient_records[0] if patient_records else {}
    patient_mapping = bundle.source_field_mappings.get("patient", {}) if patient_records else {}
    dept = _pick(patient_record, patient_mapping.get("dept"), "dept", "所在科室名称") or _pick(first_record, first_mapping.get("dept"), "dept", "所在科室名称")

    patient_info = {
        "patient_id": bundle.group_values.get("patient_id", "") or _pick(first_record, first_mapping.get("patient_id"), "patient_id", "患者ID"),
        "visit_number": bundle.group_values.get("visit_number", "") or _pick(first_record, first_mapping.get("visit_number"), "visit_number", "次数"),
        "patient_name": _pick(patient_record, patient_mapping.get("patient_name"), "patient_name", "患者姓名") or _pick(first_record, first_mapping.get("patient_name"), "patient_name", "患者姓名"),
        "dept": dept,
        "department": dept,
        "admission_no": _pick(patient_record, patient_mapping.get("admission_no"), "admission_no", "住院号") or _pick(first_record, first_mapping.get("admission_no"), "admission_no", "住院号"),
    }
    local_fields = {
        "admission_date": ("admission_date", "入院日期"),
        "discharge_date": ("discharge_date", "出院日期"),
        "admission_diagnosis": ("admission_diagnosis", "入院诊断"),
        "is_discharged": ("is_discharged", "是否出院"),
        "admission_dept_name": ("admission_dept_name", "入院科室名称"),
        "discharge_dept_name": ("discharge_dept_name", "出院科室名称"),
        "discharge_main_diagnosis": ("discharge_main_diagnosis", "出院主诊断"),
        "surgery": ("surgery", "手术", "手术名称"),
        "id_card": ("id_card", "idcard", "身份证号", "身份证"),
        "address": ("address", "住址", "家庭住址"),
        "phone": ("phone", "联系电话", "手机号", "手机"),
    }
    for field_name, aliases in local_fields.items():
        value = _pick(patient_record, patient_mapping.get(field_name), *aliases) or _pick_from_sources(bundle, field_name, *aliases)
        if value:
            patient_info[field_name] = value
    return patient_info


def _build_mr_text(
    query_date: str,
    patient_info: dict[str, str],
    lab_summary: dict[str, Any],
    exam_summary: dict[str, Any],
    context: dict[str, Any],
) -> str:
    lines: list[str] = [
        f"审核日期: {query_date}",
        f"患者ID: {patient_info.get('patient_id', '')}",
        f"住院次数: {patient_info.get('visit_number', '')}",
        f"患者姓名: {patient_info.get('patient_name', '')}",
        f"科室: {patient_info.get('dept', '')}",
        "",
        "[检验异常摘要]",
    ]

    lab_items = lab_summary.get("items", []) or []
    if not lab_items:
        lines.append("- 无异常检验项")
    else:
        for idx, item in enumerate(lab_items, start=1):
            lines.append(
                f"- {idx}. {item.get('item_name', '')}={item.get('result', '')}{item.get('units', '')} "
                f"(标记:{item.get('abnormal_indicator', '')}, 风险:{item.get('risk_level', '')}, 时间:{item.get('result_time', '')})"
            )

    lines.extend(["", "[检查异常摘要]"])
    exam_reports = exam_summary.get("reports", []) or []
    if not exam_reports:
        lines.append("- 无异常检查摘要")
    else:
        for idx, item in enumerate(exam_reports, start=1):
            lines.append(
                f"- {idx}. [{item.get('exam_class', '')}] {item.get('summary', '')} "
                f"(检查号:{item.get('exam_no', '')}, 时间:{item.get('exam_time', '')})"
            )

    lines.extend(["", "[病程记录]"])
    progress_records = ((context.get("progress_context") or {}).get("records") or [])
    if not progress_records:
        lines.append("- 无病程上下文")
    else:
        for idx, row in enumerate(progress_records, start=1):
            followup_tag = "[随访]" if row.get("is_followup") else ""
            lines.append(
                f"- {idx}. {followup_tag}{row.get('record_name', '')} {row.get('event_time', '')}: {row.get('content', '')}"
            )

    lines.extend(["", "[护理记录]"])
    nursing_records = ((context.get("nursing_context") or {}).get("records") or [])
    if not nursing_records:
        lines.append("- 无护理上下文")
    else:
        for idx, row in enumerate(nursing_records, start=1):
            lines.append(f"- {idx}. {row.get('record_name', '')} {row.get('event_time', '')}: {row.get('content', '')}")

    return "\n".join(lines).strip()


def _collect_lab_exam_context(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload_cfg = audit_type.payload or {}
    patient_info = _extract_patient_info(bundle)

    lab_summary = aggregate_lab_records(
        bundle.sources.get("lab", []) or [],
        {
            "max_lab_items": payload_cfg.get("max_lab_items", 30),
            "include_normal_summary": payload_cfg.get("include_normal_summary", False),
        },
    )
    exam_summary = aggregate_exam_reports(
        bundle.sources.get("exam", []) or [],
        {
            "max_exam_reports": payload_cfg.get("max_exam_reports", 10),
            "include_normal_summary": payload_cfg.get("include_normal_summary", False),
        },
    )

    all_event_specs = _extract_lab_exam_event_specs(lab_summary, exam_summary)
    event_specs, same_day_lab_exam_dates, event_filter_mode = _filter_context_event_specs(all_event_specs)
    event_times = _extract_event_times(event_specs)
    event_dates = _extract_event_dates(event_specs)
    has_abnormal_findings = _has_abnormal_findings(lab_summary, exam_summary)

    # 出院日期/query_date 只用于圈定患者；默认按检验结果时间、检查报告时间匹配病程/护理。
    discharge_date = patient_info.get("discharge_date", "")
    if discharge_date and discharge_date == query_date:
        context_base_date = discharge_date
    else:
        context_base_date = query_date
    context_base_dates = event_dates

    if not has_abnormal_findings or not event_times:
        context = _empty_context()
    else:
        context = select_progress_nursing_context(
            progress_records=bundle.sources.get("progress", []) or [],
            nursing_records=bundle.sources.get("nursing", []) or [],
            query_date=context_base_date,
            options={
                "base_dates": context_base_dates,
                "base_events": event_times,
                "require_record_after_base_time": bool(event_times),
                "progress_followup_days": payload_cfg.get("progress_followup_days", 1),
                "max_progress_records": payload_cfg.get("max_progress_records", 20),
                "max_nursing_records": payload_cfg.get("max_nursing_records", 20),
                "max_progress_chars": payload_cfg.get("max_progress_chars", 4000),
                "max_nursing_chars": payload_cfg.get("max_nursing_chars", 4000),
            },
        )
        _annotate_matched_event_sources(context, event_specs)
    rules = {
        "match_rule": "patient_id + visit_number, then same-day context time > lab/exam report time",
        "include_normal_summary": bool(payload_cfg.get("include_normal_summary", False)),
        "max_lab_items": int(payload_cfg.get("max_lab_items", 30) or 30),
        "max_exam_reports": int(payload_cfg.get("max_exam_reports", 10) or 10),
        "progress_followup_days": int(payload_cfg.get("progress_followup_days", 1) or 1),
        "context_base_dates": context_base_dates,
        "context_base_events": event_times,
        "context_event_sources": event_specs,
        "all_context_event_sources": all_event_specs,
        "same_day_lab_exam_dates": same_day_lab_exam_dates,
        "context_event_filter_mode": event_filter_mode,
        "has_abnormal_findings": has_abnormal_findings,
        "context_skipped_reason": "" if event_times else ("no_same_day_lab_exam_event" if all_event_specs else ("no_abnormal_event_time" if has_abnormal_findings else "no_abnormal_findings")),
        "context_match_rule": "if only abnormal lab or only abnormal exam exists, use that source's event day; if both abnormal lab and exam exist, require same-day lab/exam dates; progress/nursing must be on the matched day and event_time > matched report time",
    }
    return payload_cfg, patient_info, lab_summary, exam_summary, context, rules


def _base_payload(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
    patient_info: dict[str, str],
    lab_summary: dict[str, Any],
    exam_summary: dict[str, Any],
    context: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    return {
        "request_id": f"{audit_type.code}:{bundle.bundle_id}:{query_date}",
        "audit_date": query_date,
        "audit_type_code": audit_type.code,
        "audit_type_name": audit_type.name,
        "patient_info": patient_info,
        "abnormal_labs": lab_summary,
        "abnormal_exams": exam_summary,
        "progress_context": context.get("progress_context", {}),
        "nursing_context": context.get("nursing_context", {}),
        "rules": rules,
        "context_match_diagnostics": {
            "rule": rules.get("context_match_rule", ""),
            "included_event_sources": rules.get("context_event_sources", []),
            "all_event_sources": rules.get("all_context_event_sources", []),
            "same_day_lab_exam_dates": rules.get("same_day_lab_exam_dates", []),
            "context_event_filter_mode": rules.get("context_event_filter_mode", ""),
            "event_day_summary": _build_event_day_summary(rules.get("context_event_sources", []), context),
            "context_skipped_reason": rules.get("context_skipped_reason", ""),
            "matched_progress": [
                {
                    "record_id": _as_text(row.get("record_id")),
                    "record_name": _as_text(row.get("record_name")),
                    "event_time": _as_text(row.get("event_time")),
                    "matched_event_time": _as_text(row.get("matched_event_time")),
                    "matched_event_source": row.get("matched_event_source") or {},
                    "matched_event_sources": row.get("matched_event_sources") or [],
                    "matched_event_source_labels": row.get("matched_event_source_labels") or [],
                    "matched_event_source_label": _as_text(row.get("matched_event_source_label")),
                }
                for row in ((context.get("progress_context") or {}).get("records") or [])
            ],
            "matched_nursing": [
                {
                    "record_id": _as_text(row.get("record_id")),
                    "record_name": _as_text(row.get("record_name")),
                    "event_time": _as_text(row.get("event_time")),
                    "matched_event_time": _as_text(row.get("matched_event_time")),
                    "matched_event_source": row.get("matched_event_source") or {},
                    "matched_event_sources": row.get("matched_event_sources") or [],
                    "matched_event_source_labels": row.get("matched_event_source_labels") or [],
                    "matched_event_source_label": _as_text(row.get("matched_event_source_label")),
                }
                for row in ((context.get("nursing_context") or {}).get("records") or [])
            ],
        },
    }


def _join_unique(values: list[str]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _as_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return "、".join(result)


def _build_structured_lab_reports(lab_summary: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    name_candidates: dict[str, list[str]] = {}
    for index, item in enumerate(lab_summary.get("items", []) or [], start=1):
        test_no = _as_text(item.get("test_no"))
        group_key = test_no or f"__row_{index}"
        report_item_name = _as_text(item.get("report_item_name")) or _as_text(item.get("item_name"))
        if group_key not in grouped:
            grouped[group_key] = {
                "检验单号": test_no,
                "检验项目": _as_text(item.get("test_name")),
                "结果时间": _as_text(item.get("result_time")),
                "报告项目": [],
            }
            name_candidates[group_key] = []
        if not grouped[group_key].get("结果时间"):
            grouped[group_key]["结果时间"] = _as_text(item.get("result_time"))
        if not grouped[group_key].get("检验项目") and _as_text(item.get("test_name")):
            grouped[group_key]["检验项目"] = _as_text(item.get("test_name"))
        name_candidates[group_key].append(report_item_name)
        grouped[group_key]["报告项目"].append(
            {
                "报告项目名称": report_item_name,
                "检验结果": _as_text(item.get("result")),
                "单位": _as_text(item.get("units")),
                "异常标记": _as_text(item.get("abnormal_indicator")),
                "参考范围": _as_text(item.get("reference_range")) or _as_text(item.get("print_context")),
                "结果时间": _as_text(item.get("result_time")),
            }
        )

    reports = list(grouped.values())
    for group_key, entry in zip(grouped.keys(), reports):
        if not entry.get("检验项目"):
            entry["检验项目"] = _join_unique(name_candidates.get(group_key, []))
    return reports


def _build_structured_exam_reports(exam_summary: dict[str, Any]) -> list[dict[str, str]]:
    reports: list[dict[str, str]] = []
    for item in exam_summary.get("reports", []) or []:
        reports.append(
            {
                "检查号": _as_text(item.get("exam_no")),
                "检查类别": _as_text(item.get("exam_class")),
                "检查名称": _as_text(item.get("exam_name")) or _as_text(item.get("description")),
                "报告时间": _as_text(item.get("report_time")) or _as_text(item.get("exam_time")),
                "检查所见": _as_text(item.get("description")),
            }
        )
    return reports


def _build_structured_input(
    audit_type: AuditTypeConfig,
    query_date: str,
    patient_info: dict[str, str],
    lab_summary: dict[str, Any],
    exam_summary: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    progress_records = ((context.get("progress_context") or {}).get("records") or [])
    nursing_records = ((context.get("nursing_context") or {}).get("records") or [])
    structured_patient_info = {
        "患者ID": patient_info.get("patient_id", ""),
        "住院次数": patient_info.get("visit_number", ""),
        "患者姓名": patient_info.get("patient_name", ""),
        "科室": patient_info.get("dept", ""),
        "住院号": patient_info.get("admission_no", ""),
    }

    return {
        "核查信息": {
            "审核日期": query_date,
            "核查类型": audit_type.name,
            "审计类型编码": audit_type.code,
            "关联规则": "按同一自然日关联：只有异常检验或只有异常检查时，病程/护理需与该来源同日且晚于报告时间；异常检验和异常检查同时存在时，仅使用两者同日的日期关联病程/护理。",
        },
        "患者信息": structured_patient_info,
        "检验检查": {
            "检验报告信息": _build_structured_lab_reports(lab_summary),
            "检查报告": _build_structured_exam_reports(exam_summary),
        },
        "病程": {
            "病程记录": [
                {
                    "病程时间": _as_text(row.get("event_time")),
                    "关联报告时间": _as_text(row.get("matched_event_time")),
                    "关联报告来源": _as_text(row.get("matched_event_source_label")),
                    "病程名称": _as_text(row.get("record_name")),
                    "病程内容": _as_text(row.get("content")),
                }
                for row in progress_records
            ]
        },
        "护理": {
            "护理记录": [
                {
                    "护理时间": _as_text(row.get("event_time")),
                    "关联报告时间": _as_text(row.get("matched_event_time")),
                    "关联报告来源": _as_text(row.get("matched_event_source_label")),
                    "护理单类型": _as_text(row.get("record_name")),
                    "护理内容": _as_text(row.get("content")),
                }
                for row in nursing_records
            ]
        },
    }


def build_lab_exam_progress_nursing_payload(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> tuple[dict[str, Any], str]:
    """构建检验/检查 vs 病程/护理核查 payload。"""
    _, patient_info, lab_summary, exam_summary, context, rules = _collect_lab_exam_context(audit_type, bundle, query_date)
    payload = _base_payload(audit_type, bundle, query_date, patient_info, lab_summary, exam_summary, context, rules)
    mr_text = _build_mr_text(query_date, patient_info, lab_summary, exam_summary, context)
    payload["mr_text"] = mr_text
    return payload, mr_text


def build_lab_exam_structured_progress_nursing_payload(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> tuple[dict[str, Any], str]:
    """构建检验/检查 vs 病程/护理结构化 JSON 字符串输入。"""
    _, patient_info, lab_summary, exam_summary, context, rules = _collect_lab_exam_context(audit_type, bundle, query_date)
    structured_input = _build_structured_input(audit_type, query_date, patient_info, lab_summary, exam_summary, context)
    mr_text = json.dumps(structured_input, ensure_ascii=False, indent=2)
    payload = _base_payload(audit_type, bundle, query_date, patient_info, lab_summary, exam_summary, context, rules)
    payload["structured_input"] = structured_input
    payload["mr_text"] = mr_text
    return payload, mr_text


def build_lab_exam_structured_input_for_diagnostics(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> dict[str, Any]:
    """构建诊断面板专用结构化关联内容，不影响真实推送 payload。"""
    _, patient_info, lab_summary, exam_summary, context, _ = _collect_lab_exam_context(audit_type, bundle, query_date)
    return _build_structured_input(audit_type, query_date, patient_info, lab_summary, exam_summary, context)
