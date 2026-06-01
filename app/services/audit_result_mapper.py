"""结构化审计结果映射工具（Task 10）。"""
from __future__ import annotations

import json
from typing import Any


LEGACY_AUDIT_TYPES = {"progress_vs_nursing"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _json_text(value: Any, fallback: str) -> str:
    if value in (None, "", [], {}):
        return fallback
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def map_dimension_row(dim: dict[str, Any], audit_type_code: str) -> tuple[dict[str, Any], str]:
    """将 dimension 项映射为 ORM 字段字典与 extra_json 字符串。"""
    source = _as_dict(dim)
    is_legacy = str(audit_type_code or "").strip() in LEGACY_AUDIT_TYPES
    dimension_name = (
        source.get("dimension")
        or source.get("dimension_name")
        or source.get("dimension_code")
        or "未命名维度"
    )

    extra_data = _as_dict(source.get("extra"))
    if not is_legacy:
        # 新审计类型不复用旧 evidence 列，防止语义错位
        if source.get("medical_evidence"):
            extra_data.setdefault("medical_evidence_legacy", source.get("medical_evidence"))
        if source.get("nursing_evidence"):
            extra_data.setdefault("nursing_evidence_legacy", source.get("nursing_evidence"))

    row = {
        "dimension_code": source.get("dimension_code", ""),
        "dimension": str(dimension_name),
        "status": source.get("status", "❓"),
        "severity": source.get("severity", ""),
        "confidence": source.get("confidence", 0),
        "medical_content": source.get("medical_content", ""),
        "nursing_content": source.get("nursing_content", ""),
        "explanation": source.get("explanation", ""),
        "issue_summary": source.get("issue_summary", ""),
        "recommendation": source.get("recommendation", ""),
        "medical_evidence_json": _json_text(source.get("medical_evidence", []) if is_legacy else [], "[]"),
        "nursing_evidence_json": _json_text(source.get("nursing_evidence", []) if is_legacy else [], "[]"),
        "alert_level": source.get("alert_level", ""),
        "closure_hours": source.get("closure_hours", 0),
        "push_strategy": source.get("push_strategy", ""),
        "outcome_bucket": source.get("outcome_bucket", ""),
    }
    return row, _json_text(extra_data, "{}")


def map_conclusion_row(parsed: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """将 parsed_output 映射为结论字段与 extra_json 字符串。"""
    source = _as_dict(parsed)
    focus_items = source.get("focus_items", [])
    extra = _as_dict(source.get("extra"))

    # 将聚合统计类字段并入 extra_json，便于后续导出/排查
    for key in ("parse_warning", "omitted_count", "aggregation_stats"):
        if key in source and source.get(key) not in (None, "", [], {}):
            extra[key] = source.get(key)

    row = {
        "has_inconsistency": 1 if source.get("inconsistency") else 0,
        "severity": source.get("severity", ""),
        "risk_score": source.get("risk_score", 0),
        "overall_conclusion": source.get("overall_conclusion", ""),
        "focus_items": _json_text(focus_items, "[]"),
        "audit_date": source.get("audit_date", ""),
        "reasoning_brief": source.get("reasoning_brief", ""),
        "ai_version": source.get("version", "1.0"),
        "alert_level": source.get("alert_level", ""),
        "closure_hours": source.get("closure_hours", 0),
        "push_strategy": source.get("push_strategy", ""),
        "outcome_bucket": source.get("outcome_bucket", ""),
        "overall_qc_summary": source.get("overall_qc_summary", ""),
    }
    return row, _json_text(extra, "{}")
