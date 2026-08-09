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
import hashlib
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

# 兼容旧测试/调用方的常量名称；不再用于对完整 mr_text 做整体硬切。
_MAX_TOTAL_CHARS = 5000
_MAX_CONTENT_PER_RECORD = 1500
_MAX_RECORDS_PER_SOURCE = 20


def _fmt_time(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else value.strftime("%Y-%m-%d")
    return str(value or "")


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    text = str(text or "").strip()
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _source_hash(records: list[dict[str, Any]]) -> str:
    """哈希稳定身份、时间、状态和正文摘要；不把明文记录写入 metadata。"""
    if not records:
        return ""
    digest = hashlib.sha256()
    for item in sorted(records, key=lambda value: str(value.get("record_id") or "")):
        content_hash = hashlib.sha256(str(item.get("content") or "").encode("utf-8")).hexdigest()
        summary = "\x1f".join((
            str(item.get("record_id") or ""),
            _fmt_time(item.get("event_time")),
            _fmt_time(item.get("created_at")),
            _fmt_time(item.get("source_updated_at")),
            str(item.get("source_status") or ""),
            str(item.get("mapping_version") or ""),
            content_hash,
        ))
        digest.update(summary.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _render_content(record: dict[str, Any], limit: int) -> str:
    content, truncated = _truncate(record.get("content") or "", limit)
    status = str(record.get("source_status") or "").strip()
    truncated = truncated or bool(record.get("_content_truncated"))
    notes = []
    if status == "missing_content":
        notes.append("正文缺失")
    if truncated:
        notes.append("正文已按配置截断")
    if notes:
        return f"{content}（{'；'.join(notes)}）"
    return content


def _apply_source_budget(
    records: list[dict[str, Any]], max_records: int, max_chars: int,
) -> tuple[list[dict[str, Any]], int, int, bool]:
    """按稳定顺序应用每个来源的总字符预算，不重置跨日预算。"""
    selected = [dict(record) for record in records[:max_records]]
    omitted_records = max(0, len(records) - max_records)
    remaining = max_chars
    content_omitted = 0
    truncated = omitted_records > 0
    for record in selected:
        content = str(record.get("content") or "").strip()
        if len(content) > remaining:
            record["content"] = content[:remaining]
            record["_content_truncated"] = True
            truncated = True
            if content and remaining == 0:
                content_omitted += 1
            remaining = 0
        else:
            record["content"] = content
            record["_content_truncated"] = False
            remaining -= len(content)
    return selected, omitted_records, content_omitted, truncated


def _render_progress_timeline(records: list[dict[str, Any]], max_records: int = _MAX_RECORDS_PER_SOURCE, max_chars: int = _MAX_CONTENT_PER_RECORD) -> str:
    lines: list[str] = []
    for rec in records[:max_records]:
        content = _render_content(rec, max_chars)
        subtype = str(rec.get("record_subtype") or "")
        title = str(rec.get("record_name") or "病程记录")
        status_note = "（正文缺失）" if rec.get("source_status") == "missing_content" else ""
        lines.append(f"- {_fmt_time(rec.get('event_time'))} [{subtype}] {title}{status_note}\n{content}")
    return "\n".join(lines) if lines else "（无病程记录）"


def _render_nursing_timeline(records: list[dict[str, Any]], max_records: int = _MAX_RECORDS_PER_SOURCE, max_chars: int = _MAX_CONTENT_PER_RECORD) -> str:
    lines: list[str] = []
    for rec in records[:max_records]:
        content = _render_content(rec, max_chars)
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
    result = {
        "patient_id": str(values.get("patient_id") or ""),
        "visit_number": str(values.get("visit_number") or ""),
        "admission_no": str(values.get("admission_no") or ""),
        "patient_name": str(values.get("patient_name") or ""),
        "department": dept,
        "dept": dept,
    }
    # 只转发 anchor 已经提供的旧消费者字段，不从其他源补查患者信息。
    for key in (
        "gender", "birth_date", "admission_date", "discharge_date",
        "admission_diagnosis", "discharge_main_diagnosis", "admission_condition",
        "attending_doctor", "attending_doctor_name", "attending_doctor_userid",
        "doctor_id", "nurse_head_userid", "nurse_head_name", "nursing_level",
        "admission_dept_name", "discharge_dept_name",
    ):
        value = values.get(key)
        if value not in (None, ""):
            result[key] = str(value)
    return result


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
    max_progress_records: int,
    max_nursing_records: int,
    max_progress_chars: int,
    max_nursing_chars: int,
    progress_omitted_count: int = 0,
    nursing_omitted_count: int = 0,
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
    for index, rec in enumerate(progress_records[:max_progress_records], start=1):
        lines.extend([
            f"{index}. 时间: {_fmt_time(rec.get('event_time'))}",
            f"   名称: {rec.get('record_name') or ''}",
            f"   医师: {rec.get('author_name') or rec.get('author_code') or ''}",
            f"   内容: {_render_content(rec, max_progress_chars)}",
        ])
    if progress_omitted_count:
        lines.append(f"（病程其余 {progress_omitted_count} 条记录已省略）")
    lines.extend(["", "[护理记录]"])
    for index, rec in enumerate(nursing_records[:max_nursing_records], start=1):
        structured = rec.get("structured_fields") or {}
        lines.extend([
            f"{index}. 时间: {_fmt_time(rec.get('created_at') or rec.get('event_time'))}",
            f"   类型: {rec.get('record_name') or ''}",
            f"   记录人: {structured.get('recorder_name') or rec.get('author_code') or ''}",
            f"   内容: {_render_content(rec, max_nursing_chars)}",
            *_nursing_detail_lines(rec),
        ])
    if nursing_omitted_count:
        lines.append(f"（护理其余 {nursing_omitted_count} 条记录已省略）")
    return "\n".join(lines).strip()


def _build_legacy_discharge_text(
    query_date: str,
    patient_info: dict[str, str],
    progress_records: list[dict[str, Any]],
    nursing_records: list[dict[str, Any]],
    max_progress_records: int,
    max_nursing_records: int,
    max_progress_chars: int,
    max_nursing_chars: int,
    progress_omitted_count: int = 0,
    nursing_omitted_count: int = 0,
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
        for index, rec in enumerate(day_progress[:max_progress_records], start=1):
            lines.extend([
                f"  [病程 #{index}] {rec.get('record_name') or ''} ({_fmt_time(rec.get('event_time'))})",
                f"    {_render_content(rec, max_progress_chars)}",
            ])
        for index, rec in enumerate(day_nursing[:max_nursing_records], start=1):
            lines.extend([
                f"  [护理 #{index}] {rec.get('record_name') or ''} ({_fmt_time(rec.get('created_at'))})",
                f"    {_render_content(rec, max_nursing_chars)}",
            ])
        lines.append("")
    if progress_omitted_count:
        lines.append(f"（病程其余 {progress_omitted_count} 条记录已省略）")
    if nursing_omitted_count:
        lines.append(f"（护理其余 {nursing_omitted_count} 条记录已省略）")
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
    progress_records.sort(key=lambda r: (_fmt_time(r.get("event_time")), str(r.get("record_id") or "")))
    # form_time 用于 daily 查询筛选；展示和出院同日关系统一按 created_date。
    nursing_records.sort(key=lambda r: (
        _fmt_time(r.get("created_at")),
        _fmt_time(r.get("event_time")),
        str(r.get("record_id") or ""),
    ))
    all_progress_records = list(progress_records)
    all_nursing_records = list(nursing_records)

    payload_cfg = audit_type.payload.model_dump() if hasattr(audit_type.payload, "model_dump") else dict(audit_type.payload or {})

    def _positive_limit(key: str, default: int) -> int:
        raw = payload_cfg.get(key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"payload.{key} must be a positive integer") from exc
        if value <= 0:
            raise ValueError(f"payload.{key} must be a positive integer")
        return value

    max_progress_records = _positive_limit("max_progress_records", _MAX_RECORDS_PER_SOURCE)
    max_nursing_records = _positive_limit("max_nursing_records", _MAX_RECORDS_PER_SOURCE)
    max_progress_chars = _positive_limit("max_progress_chars", _MAX_CONTENT_PER_RECORD)
    max_nursing_chars = _positive_limit("max_nursing_chars", _MAX_CONTENT_PER_RECORD)

    progress_records, progress_omitted, progress_content_omitted, progress_truncated = _apply_source_budget(
        progress_records, max_progress_records, max_progress_chars,
    )
    nursing_records, nursing_omitted, nursing_content_omitted, nursing_truncated = _apply_source_budget(
        nursing_records, max_nursing_records, max_nursing_chars,
    )

    patient_info = _patient_info(bundle)
    if run_mode == RUN_MODE_DISCHARGE:
        mr_text = _build_legacy_discharge_text(
            query_date, patient_info, progress_records, nursing_records,
            max_progress_records, max_nursing_records,
            max_progress_chars, max_nursing_chars,
            progress_omitted, nursing_omitted,
        )
    else:
        mr_text = _build_legacy_daily_text(
            query_date, patient_info, progress_records, nursing_records,
            max_progress_records, max_nursing_records,
            max_progress_chars, max_nursing_chars,
            progress_omitted, nursing_omitted,
        )

    relation_metadata = dict(getattr(bundle, "relation_metadata", {}) or {})
    relation_metadata.setdefault("policy_version", policy.version)
    relation_metadata.setdefault("edge_types", list(policy.relation_edges))
    relation_metadata.setdefault("progress_count", len(all_progress_records))
    relation_metadata.setdefault("nursing_count", len(all_nursing_records))
    relation_metadata.setdefault("matched_counts", {
        "progress": len(all_progress_records),
        "nursing": len(all_nursing_records),
    })
    relation_metadata.setdefault("filtered_counts", {})
    relation_metadata["missing_content_count"] = sum(
        1 for record in all_progress_records + all_nursing_records
        if str(record.get("source_status") or "").strip() == "missing_content"
    )
    relation_metadata["truncated"] = {
        "progress": progress_truncated,
        "nursing": nursing_truncated,
    }
    relation_metadata["omitted_count"] = {
        "progress": progress_omitted,
        "nursing": nursing_omitted,
    }
    relation_metadata["content_omitted_count"] = {
        "progress": progress_content_omitted,
        "nursing": nursing_content_omitted,
    }
    relation_metadata["source_hashes"] = {
        "progress": _source_hash(all_progress_records),
        "nursing": _source_hash(all_nursing_records),
    }

    payload = {
        "request_id": f"{audit_type.code}:{bundle.bundle_id}:{query_date}",
        "audit_date": query_date,
        "audit_type_code": audit_type.code,
        "audit_type_name": audit_type.name,
        "patient_info": patient_info,
        "sources": {
            "progress": {"count": len(all_progress_records)},
            "nursing": {"count": len(all_nursing_records)},
        },
        "relation_policy_version": policy.version,
        "mapping_versions": {
            "progress": str((progress_records[0] or {}).get("mapping_version") or "") if progress_records else "",
            "nursing": str((nursing_records[0] or {}).get("mapping_version") or "") if nursing_records else "",
        },
        "relation": relation_metadata,
        "mr_text": mr_text,
    }
    return payload, mr_text


def register_dual_source_builder() -> None:
    """注册双源 builder（幂等）。由 dual_source_loader 导入时调用。"""
    from app.services.builder_registry import has_builder

    if not has_builder(BUILDER_NAME):
        register_builder(BUILDER_NAME, build_progress_nursing_multi_source_payload)
