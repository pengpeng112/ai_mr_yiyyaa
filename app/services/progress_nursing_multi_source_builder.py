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


def _render_relation_edges(run_mode: str, progress_count: int, nursing_count: int, query_date: str) -> str:
    if run_mode == RUN_MODE_DISCHARGE:
        return (
            f"关系边: same_calendar_day（护理 created_date 与病程完成时间同日，LEFT 语义）；"
            f"病程 {progress_count} 条 / 护理 {nursing_count} 条"
        )
    return (
        f"关系边: same_audit_day（query_date={query_date}，双侧均存在才成候选）；"
        f"病程 {progress_count} 条 / 护理 {nursing_count} 条"
    )


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

    mr_text = (
        "【病程时间线】\n" + _render_progress_timeline(progress_records)
        + "\n\n【护理时间线】\n" + _render_nursing_timeline(nursing_records)
        + "\n\n【关系边】\n" + _render_relation_edges(run_mode, len(progress_records), len(nursing_records), query_date)
    ).strip()
    if len(mr_text) > _MAX_TOTAL_CHARS:
        mr_text = mr_text[:_MAX_TOTAL_CHARS]

    patient_info = {
        "patient_id": str(bundle.group_values.get("patient_id") or ""),
        "visit_number": str(bundle.group_values.get("visit_number") or ""),
    }
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
