"""
012 P2 草案：双源 Builder（progress_nursing_multi_source）。

输入：PatientBundle.sources 中独立的 progress / nursing 记录数组
（由 dual_source_loader 以 CanonicalRecordEnvelope 序列化填充）。
输出：payload 字典 + mr_text 字符串（命名约定：只用 mr_text，mr_txt 映射
仍仅由 dify_pusher.py 负责）。

设计约束（012 §8.3）：
- 分别输出病程时间线、护理时间线和关系边；
- 关系边只标注（same_audit_day / same_calendar_day），不生成记录级笛卡尔积；
- 本 builder 仅在新源 flag 启用时被配置引用；旧 builder 路径不受影响。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.schemas import AuditTypeConfig
from app.services.builder_registry import register_builder
from app.services.data_source_loader import PatientBundle
from app.services.relation_policy import (
    RUN_MODE_DAILY,
    RUN_MODE_DISCHARGE,
    get_relation_policy,
)

logger = logging.getLogger(__name__)

BUILDER_NAME = "progress_nursing_multi_source"

_MAX_TOTAL_CHARS = 5000
_MAX_CONTENT_PER_RECORD = 1500
_MAX_RECORDS_PER_SOURCE = 20


def _fmt_time(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    return str(value or "")


def _truncate(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit]


def _render_progress_timeline(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for rec in records[:_MAX_RECORDS_PER_SOURCE]:
        content = _truncate(str(rec.get("content") or ""), _MAX_CONTENT_PER_RECORD)
        subtype = str(rec.get("record_subtype") or "")
        title = str(rec.get("record_name") or "病程记录")
        status_note = "（正文缺失）" if rec.get("source_status") == "missing_content" else ""
        lines.append(f"- {_fmt_time(rec.get('event_time'))} [{subtype}] {title}{status_note}\n{content}")
    return "\n".join(lines) if lines else "（无病程记录）"


def _render_nursing_timeline(records: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for rec in records[:_MAX_RECORDS_PER_SOURCE]:
        content = _truncate(str(rec.get("content") or ""), _MAX_CONTENT_PER_RECORD)
        title = str(rec.get("record_name") or "护理记录")
        created_note = f"，创建 {_fmt_time(rec.get('created_at'))}" if rec.get("created_at") else ""
        vitals = []
        structured = rec.get("structured_fields") or {}
        for key, label in (("temperature", "体温"), ("pulse", "脉搏"), ("respiration", "呼吸"),
                           ("blood_pressure", "血压"), ("oxygen_saturation", "血氧")):
            value = structured.get(key)
            if value not in (None, ""):
                vitals.append(f"{label}{value}")
        vitals_text = f"（{'，'.join(vitals)}）" if vitals else ""
        lines.append(f"- {_fmt_time(rec.get('event_time'))}{created_note} {title}{vitals_text}\n{content}")
    return "\n".join(lines) if lines else "（无护理记录）"


def _patient_info(bundle: PatientBundle) -> dict[str, str]:
    values = bundle.group_values
    dept = str(values.get("dept_name") or values.get("dept") or "")
    return {
        "patient_id": str(values.get("patient_id") or ""),
        "visit_number": str(values.get("visit_number") or ""),
        "admission_no": str(values.get("admission_no") or ""),
        "patient_name": str(values.get("patient_name") or ""),
        "department": dept,
        "dept": dept,
    }


def _nursing_detail_lines(rec: dict[str, Any]) -> list[str]:
    structured = rec.get("structured_fields") or {}
    vitals = {
        "temperature": structured.get("temperature"),
        "heart_rate_pulse": structured.get("pulse"),
        "respiratory_rate": structured.get("respiration"),
        "blood_pressure": structured.get("blood_pressure"),
        "oxygen_saturation": structured.get("oxygen_saturation"),
        "blood_glucose": structured.get("blood_glucose"),
    }
    assessments = {
        "consciousness": structured.get("consciousness"),
        "skin_condition": structured.get("skin_status"),
        "wound_condition": structured.get("incision_status"),
        "tube_care": structured.get("tube_care"),
        "high_risk": structured.get("high_risk"),
    }
    supportive = {
        "intake": structured.get("intake_amount"),
        "output": structured.get("output_amount"),
        "urine_volume": structured.get("urine_amount"),
        "oxygen_nasal_cannula": structured.get("oxygen_nasal_cannula"),
        "oxygen_mask": structured.get("oxygen_mask"),
    }

    def joined(items: dict[str, Any]) -> str:
        return "; ".join(f"{key}={value}" for key, value in items.items() if value not in (None, ""))

    return [
        f"   生命体征: {joined(vitals)}",
        f"   评估: {joined(assessments)}",
        f"   出入量: {joined(supportive)}",
    ]


def _build_legacy_daily_text(
    query_date: str,
    patient_info: dict[str, str],
    progress_records: list[dict[str, Any]],
    nursing_records: list[dict[str, Any]],
) -> str:
    lines = [
        f"审核日期: {query_date}",
        f"患者ID: {patient_info['patient_id']}",
        f"住院次数: {patient_info['visit_number']}",
        f"住院号: {patient_info['admission_no']}",
        f"患者姓名: {patient_info['patient_name']}",
        f"所在科室: {patient_info['department']}",
        "",
        "[病历文书]",
    ]
    for index, rec in enumerate(progress_records[:_MAX_RECORDS_PER_SOURCE], start=1):
        lines.extend([
            f"{index}. 时间: {_fmt_time(rec.get('event_time'))}",
            f"   名称: {rec.get('record_name') or ''}",
            f"   医师: {rec.get('author_name') or rec.get('author_code') or ''}",
            f"   内容: {_truncate(rec.get('content') or '', _MAX_CONTENT_PER_RECORD)}",
        ])
    lines.extend(["", "[护理记录]"])
    for index, rec in enumerate(nursing_records[:_MAX_RECORDS_PER_SOURCE], start=1):
        structured = rec.get("structured_fields") or {}
        lines.extend([
            f"{index}. 时间: {_fmt_time(rec.get('created_at') or rec.get('event_time'))}",
            f"   类型: {rec.get('record_name') or ''}",
            f"   记录人: {structured.get('recorder_name') or rec.get('author_code') or ''}",
            f"   内容: {_truncate(rec.get('content') or '', _MAX_CONTENT_PER_RECORD)}",
            *_nursing_detail_lines(rec),
        ])
    return "\n".join(lines).strip()


def _build_legacy_discharge_text(
    query_date: str,
    patient_info: dict[str, str],
    progress_records: list[dict[str, Any]],
    nursing_records: list[dict[str, Any]],
) -> str:
    lines = [
        f"审核日期: {query_date}",
        f"患者ID: {patient_info['patient_id']}",
        f"住院次数: {patient_info['visit_number']}",
        f"患者姓名: {patient_info['patient_name']}",
        f"科室: {patient_info['dept']}",
        "",
    ]
    days = sorted({_fmt_time(rec.get("event_time"))[:10] for rec in progress_records if rec.get("event_time")})
    for day in days:
        lines.append(f"── {day} ──")
        day_progress = [rec for rec in progress_records if _fmt_time(rec.get("event_time"))[:10] == day]
        day_nursing = [rec for rec in nursing_records if _fmt_time(rec.get("created_at"))[:10] == day]
        for index, rec in enumerate(day_progress, start=1):
            lines.extend([
                f"  [病程 #{index}] {rec.get('record_name') or ''} ({_fmt_time(rec.get('event_time'))})",
                f"    {_truncate(rec.get('content') or '', _MAX_CONTENT_PER_RECORD)}",
            ])
        for index, rec in enumerate(day_nursing, start=1):
            lines.extend([
                f"  [护理 #{index}] {rec.get('record_name') or ''} ({_fmt_time(rec.get('created_at'))})",
                f"    {_truncate(rec.get('content') or '', _MAX_CONTENT_PER_RECORD)}",
            ])
        lines.append("")
    return "\n".join(lines).strip()


def build_progress_nursing_multi_source_payload(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
    audit_run_mode: str = "daily_increment",
) -> tuple[dict[str, Any], str]:
    """双源病程/护理 payload：病程时间线 + 护理时间线 + 关系边标注。"""
    run_mode = RUN_MODE_DISCHARGE if "discharge" in str(audit_run_mode or "") else RUN_MODE_DAILY
    policy = get_relation_policy(audit_type.code, run_mode)  # 未知组合 fail-closed

    progress_records = list(bundle.sources.get("progress") or [])
    nursing_records = list(bundle.sources.get("nursing") or [])
    progress_records.sort(key=lambda r: _fmt_time(r.get("event_time")))
    nursing_records.sort(key=lambda r: _fmt_time(r.get("event_time")))

    patient_info = _patient_info(bundle)
    if run_mode == RUN_MODE_DISCHARGE:
        mr_text = _build_legacy_discharge_text(
            query_date, patient_info, progress_records, nursing_records,
        )
    else:
        mr_text = _build_legacy_daily_text(
            query_date, patient_info, progress_records, nursing_records,
        )
    if len(mr_text) > _MAX_TOTAL_CHARS:
        mr_text = mr_text[:_MAX_TOTAL_CHARS]

    payload = {
        "request_id": f"{audit_type.code}:{bundle.bundle_id}:{query_date}",
        "audit_date": query_date,
        "audit_type_code": audit_type.code,
        "audit_type_name": audit_type.name,
        "patient_info": patient_info,
        "sources": {
            "progress": {"count": len(progress_records)},
            "nursing": {"count": len(nursing_records)},
        },
        "relation_policy_version": policy.version,
        "mapping_versions": {
            "progress": str((progress_records[0] or {}).get("mapping_version") or "") if progress_records else "",
            "nursing": str((nursing_records[0] or {}).get("mapping_version") or "") if nursing_records else "",
        },
        "mr_text": mr_text,
    }
    return payload, mr_text


def register_dual_source_builder() -> None:
    """注册双源 builder（幂等）。由 dual_source_loader 导入时调用。"""
    from app.services.builder_registry import has_builder

    if not has_builder(BUILDER_NAME):
        register_builder(BUILDER_NAME, build_progress_nursing_multi_source_payload)
