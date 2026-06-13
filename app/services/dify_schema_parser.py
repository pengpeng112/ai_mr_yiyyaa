"""
Dify Schema 解析模块 —— 从 dify_pusher.py 拆分，负责标准化解析新旧 Dify 输出 schema。
"""
import json
import logging
import re
from typing import Any

from app.services import dify_result_normalizer as _norm
from app.utils.text_utils import first_non_empty as _first_non_empty

audit_logger = logging.getLogger("audit.dify")


# ── schema 入口 ──

def _normalize_parsed_root(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        return {}

    root = dict(parsed)

    # 兼容围手术期核查旧结构: overall_status / overall_conclusion / dimensions
    if "overall_status" in root and "audit_summary" not in root:
        audit_logger.info(
            "[Dify解析] 检测到 surgery_chain 旧结构 (overall_status=%s), 映射到标准 audit_summary",
            root.get("overall_status"),
        )
        derived_severity = "high" if root.get("overall_status") == "fail" else "low"
        root["audit_summary"] = {
            "has_inconsistency": root.get("overall_status", "") == "fail",
            "severity": root.get("severity", "") or derived_severity,
            "risk_score": root.get("risk_score", 0),
            "overall_conclusion": root.get("overall_conclusion", ""),
            "focus_items": root.get("focus_items", []),
            "reasoning_brief": root.get("reasoning_brief", ""),
        }

    if "patient_summary" not in root and any(key in root for key in ["患者姓名", "患者ID", "住院号", "核查日期"]):
        root["patient_summary"] = {
            "patient_id": root.get("患者ID", root.get("patient_id", "")),
            "visit_number": root.get("次数", root.get("visit_number", "")),
            "patient_name": root.get("患者姓名", root.get("patient_name", "")),
            "dept": root.get("所在科室名称", root.get("科室", root.get("dept", ""))),
            "query_date": root.get("核查日期", root.get("query_date", "")),
        }

    if "audit_summary" not in root and any(key in root for key in ["总体结论", "重点关注项", "一致性结论", "风险等级"]):
        root["audit_summary"] = {
            "has_inconsistency": root.get("是否不一致", root.get("has_inconsistency", False)),
            "severity": root.get("风险等级", root.get("severity", "")),
            "risk_score": root.get("风险分值", root.get("risk_score", 0)),
            "overall_conclusion": root.get("总体结论", root.get("overall_conclusion", "")),
            "focus_items": root.get("重点关注项", root.get("focus_items", [])),
            "reasoning_brief": root.get("简要说明", root.get("reasoning_brief", "")),
        }

    if "dimensions" not in root:
        legacy_dimensions = root.get("核查结果") or root.get("审计结果") or root.get("results") or []
        if isinstance(legacy_dimensions, list):
            root["dimensions"] = legacy_dimensions

    return root


def _looks_like_new_schema(parsed: dict) -> bool:
    return any(key in parsed for key in ["audit_summary", "patient_summary", "dimensions"])


def _parse_new_schema(parsed: dict, result: dict):
    patient = parsed.get("patient_summary", {}) or {}
    summary = parsed.get("audit_summary", {}) or {}
    raw_judgement = parsed.get("raw_judgement", {}) or {}

    result["version"] = str(parsed.get("version", "1.0") or "1.0")
    result["patient_name"] = _first_non_empty(patient.get("patient_name"), patient.get("患者姓名"))
    result["patient_id"] = _first_non_empty(patient.get("patient_id"), patient.get("患者ID"))
    result["visit_number"] = _first_non_empty(patient.get("visit_number"), patient.get("次数"))
    result["dept"] = _first_non_empty(patient.get("dept"), patient.get("科室"), patient.get("所在科室名称"))
    result["audit_date"] = _first_non_empty(patient.get("query_date"), patient.get("核查日期"), parsed.get("audit_date"))
    result["overall_conclusion"] = _first_non_empty(summary.get("overall_conclusion"), summary.get("总体结论"))
    result["focus_items"] = _ensure_string_list(summary.get("focus_items", summary.get("重点关注项", [])))
    result["inconsistency"] = _to_bool(summary.get("has_inconsistency", summary.get("是否不一致", False)))
    result["severity"] = _normalize_severity(summary.get("severity", summary.get("风险等级", "")))
    result["risk_score"] = _safe_int(summary.get("risk_score", summary.get("风险分值", 0)))
    result["reasoning_brief"] = _first_non_empty(summary.get("reasoning_brief"), summary.get("简要说明"), raw_judgement.get("reasoning_brief"))
    result["alert_level"] = _normalize_alert_level(summary.get("alert_level", ""))
    result["closure_hours"] = _safe_int(summary.get("closure_hours", 0))
    result["push_strategy"] = _normalize_push_strategy(summary.get("push_strategy", ""))
    result["outcome_bucket"] = _normalize_outcome_bucket(summary.get("outcome_bucket", ""))
    result["overall_qc_summary"] = _first_non_empty(summary.get("overall_qc_summary"), summary.get("整体质控描述"))

    dimensions = parsed.get("dimensions", []) or []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        medical_evidence = _ensure_string_list(item.get("medical_evidence", item.get("病程记录证据", [])))
        nursing_evidence = _ensure_string_list(item.get("nursing_evidence", item.get("护理记录证据", [])))
        dimension_name = _first_non_empty(item.get("dimension_name"), item.get("dimension"), item.get("维度"))
        dim = {
            "dimension_code": _first_non_empty(item.get("dimension_code"), _dimension_code_from_name(dimension_name)),
            "dimension": dimension_name,
            "status": _normalize_status(item.get("status", "unknown")),
            "severity": _normalize_severity(item.get("severity", result["severity"])),
            "confidence": _safe_float(item.get("confidence", 0)),
            "medical_content": "\n".join(str(v) for v in medical_evidence if v),
            "nursing_content": "\n".join(str(v) for v in nursing_evidence if v),
            "explanation": _first_non_empty(item.get("issue_summary"), item.get("说明"), item.get("explanation")),
            "issue_summary": _first_non_empty(item.get("issue_summary"), item.get("说明"), item.get("explanation")),
            "recommendation": _first_non_empty(item.get("recommendation"), item.get("建议")),
            "medical_evidence": medical_evidence,
            "nursing_evidence": nursing_evidence,
            "alert_level": _normalize_alert_level(item.get("alert_level", "")),
            "closure_hours": _safe_int(item.get("closure_hours", 0)),
            "push_strategy": _normalize_push_strategy(item.get("push_strategy", "")),
            "outcome_bucket": _normalize_outcome_bucket(item.get("outcome_bucket", "")),
        }
        result["dimensions"].append(dim)


def _parse_legacy_schema(parsed: dict, result: dict):
    result["patient_name"] = _first_non_empty(parsed.get("患者姓名"), parsed.get("patient_name"))
    result["patient_id"] = _first_non_empty(parsed.get("患者ID"), parsed.get("patient_id"))
    result["visit_number"] = _first_non_empty(parsed.get("次数"), parsed.get("visit_number"))
    result["dept"] = _first_non_empty(parsed.get("所在科室名称"), parsed.get("科室"), parsed.get("dept"))
    result["audit_date"] = _first_non_empty(parsed.get("核查日期"), parsed.get("query_date"))
    result["overall_conclusion"] = _first_non_empty(parsed.get("总体结论"), parsed.get("overall_conclusion"))
    result["focus_items"] = _ensure_string_list(parsed.get("重点关注项", parsed.get("focus_items", [])))
    result["reasoning_brief"] = _first_non_empty(parsed.get("简要说明"), parsed.get("reasoning_brief"))

    audit_results = parsed.get("核查结果", parsed.get("审计结果", parsed.get("results", [])))
    has_fail = False
    has_warn = False

    for item in audit_results:
        if not isinstance(item, dict):
            continue
        status = _first_non_empty(item.get("状态"), item.get("status"), "❓")
        dimension_name = _first_non_empty(item.get("维度"), item.get("dimension"), item.get("dimension_name"))
        medical_content = _first_non_empty(item.get("病程记录内容"), item.get("medical_content"))
        nursing_content = _first_non_empty(item.get("护理记录内容"), item.get("nursing_content"))
        dim = {
            "dimension_code": _dimension_code_from_name(dimension_name),
            "dimension": dimension_name,
            "status": _normalize_status(status),
            "severity": "high" if "❌" in status else ("medium" if "⚠" in status else "low"),
            "confidence": 0,
            "medical_content": medical_content,
            "nursing_content": nursing_content,
            "explanation": _first_non_empty(item.get("说明"), item.get("issue_summary"), item.get("explanation")),
            "issue_summary": _first_non_empty(item.get("说明"), item.get("issue_summary"), item.get("explanation")),
            "recommendation": _first_non_empty(item.get("建议"), item.get("recommendation")),
            "medical_evidence": [medical_content] if medical_content else [],
            "nursing_evidence": [nursing_content] if nursing_content else [],
        }
        result["dimensions"].append(dim)

        if "❌" in status:
            has_fail = True
        elif "⚠" in status:
            has_warn = True

    if has_fail:
        result["inconsistency"] = True
        result["severity"] = "high"
        result["risk_score"] = 80
    elif has_warn:
        result["inconsistency"] = True
        result["severity"] = "medium"
        result["risk_score"] = 60
    else:
        result["inconsistency"] = False
        result["severity"] = "low"
        result["risk_score"] = 20 if result["dimensions"] else 0


# ── 回退方案 ──

def _fallback_keyword_match(result: dict):
    """
    回退方案：当结构化解析失败时，用关键字匹配判断不一致
    """
    text = result.get("raw_text", "").lower()
    if not text:
        return

    _append_parse_warning(result, "fallback_keyword_match")

    explicit_inconsistency = bool(re.search(r'["\'](?:has_)?inconsistency["\']\s*:\s*true\b', text))
    negative_inconsistency = any(
        phrase in text
        for phrase in ["无不一致", "不存在不一致", "未见不一致", "没有不一致", "无实质性不一致"]
    )
    keyword_inconsistency = any(
        phrase in text
        for phrase in ["存在不一致", "发现不一致", "有不一致", "不一致问题", "inconsistent", "mismatch", "conflict", "❌"]
    )

    if explicit_inconsistency or (keyword_inconsistency and not negative_inconsistency):
        result["inconsistency"] = True
        if "严重" in text or "high" in text or "重大" in text:
            result["severity"] = "high"
        elif "中等" in text or "medium" in text:
            result["severity"] = "medium"
        else:
            result["severity"] = "low"
        result["fallback_inference"] = True
        if not result.get("overall_conclusion"):
            result["overall_conclusion"] = "Dify 输出未能解析为结构化 JSON，已根据关键词回退判断存在不一致。"
        if not result.get("reasoning_brief"):
            raw_text = str(result.get("raw_text", "")).strip()
            result["reasoning_brief"] = raw_text[:200] if raw_text else result["overall_conclusion"]
    audit_logger.info(
        f"[Dify解析] 回退关键字匹配: inconsistency={result['inconsistency']}, severity={result['severity']}, fallback={result['fallback_inference']}"
    )


# ── 警告辅助 ──

def _append_parse_warning(result: dict, warning: str):
    warnings = [item.strip() for item in str(result.get("parse_warning") or "").split(";") if item.strip()]
    if warning not in warnings:
        warnings.append(warning)
    result["parse_warning"] = ";".join(warnings)


def _append_output_quality_warnings(result: dict):
    missing_patient_fields = [
        field for field in ["patient_id", "patient_name", "audit_date"]
        if not str(result.get(field) or "").strip()
    ]
    if missing_patient_fields:
        _append_parse_warning(result, "patient_summary_empty")
        audit_logger.warning(
            "[Dify解析] patient_summary 关键字段为空: fields=%s raw_text前200字符=%s",
            missing_patient_fields,
            str(result.get("raw_text") or "")[:200],
        )

    if result.get("inconsistency") and not result.get("risk_score"):
        _append_parse_warning(result, "inconsistency_without_risk_score")


# ── 归一化与派生函数 ──

def _normalize_status(status: str) -> str:
    return _norm.normalize_status(status)


def _normalize_severity(severity: str) -> str:
    return _norm.normalize_severity(severity)


def _normalize_alert_level(alert_level: str) -> str:
    return _norm.normalize_alert_level(alert_level)


def _alert_level_to_severity(alert_level: str) -> str:
    return _norm.alert_level_to_severity(alert_level)


def _normalize_push_strategy(strategy: str) -> str:
    return _norm.normalize_push_strategy(strategy)


def _normalize_outcome_bucket(bucket: str) -> str:
    return _norm.normalize_outcome_bucket(bucket)


def _derive_severity_from_dimensions(dimensions: list[dict]) -> str:
    return _norm.derive_severity_from_dimensions(dimensions)


def _derive_alert_level_from_dimensions(dimensions: list[dict]) -> str:
    return _norm.derive_alert_level_from_dimensions(dimensions)


def _safe_int(value: Any) -> int:
    return _norm.safe_int(value)


def _safe_float(value: Any) -> float:
    return _norm.safe_float(value)


# ── 工具函数 ──

def _ensure_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        parts = re.split(r"[\n；;，,]+", text)
        return [part.strip() for part in parts if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y", "是", "有", "存在", "存在不一致"}


def _dimension_code_from_name(name: str) -> str:
    normalized = str(name or "")
    mapping = {
        "诊断一致性": "diagnosis_consistency",
        "护理级别执行": "nursing_level_consistency",
        "护理级别一致性": "nursing_level_consistency",
        "生命体征交叉": "vital_sign_consistency",
        "生命体征一致性": "vital_sign_consistency",
        "病情描述一致性": "condition_consistency",
        "诊疗措施执行": "treatment_measure_consistency",
        "诊疗措施一致性": "treatment_measure_consistency",
        "时间合理性": "timeline_consistency",
    }
    return mapping.get(normalized, "")


def _severity_from_status(status: str) -> str:
    return _norm.severity_from_status(status)


def _risk_score_from_dimensions(dimensions: list[dict], inconsistency: bool) -> int:
    return _norm.risk_score_from_dimensions(dimensions, inconsistency)


# ── 后处理 ──

def _post_process_result(result: dict):
    result["focus_items"] = _ensure_string_list(result.get("focus_items", []))
    result["dimensions"] = [dim for dim in result.get("dimensions", []) if dim.get("dimension") or dim.get("dimension_code")]

    for dim in result["dimensions"]:
        dim["status"] = _normalize_status(dim.get("status", "unknown"))
        dim["severity"] = _normalize_severity(dim.get("severity", "")) or _severity_from_status(dim["status"])
        dim["confidence"] = min(max(_safe_float(dim.get("confidence", 0)), 0.0), 1.0)
        dim["dimension_code"] = dim.get("dimension_code") or _dimension_code_from_name(dim.get("dimension", ""))
        dim["medical_evidence"] = _ensure_string_list(dim.get("medical_evidence", []))
        dim["nursing_evidence"] = _ensure_string_list(dim.get("nursing_evidence", []))
        dim["medical_content"] = dim.get("medical_content") or "\n".join(dim["medical_evidence"])
        dim["nursing_content"] = dim.get("nursing_content") or "\n".join(dim["nursing_evidence"])
        dim["issue_summary"] = dim.get("issue_summary") or dim.get("explanation", "")
        dim["explanation"] = dim.get("explanation") or dim.get("issue_summary", "")
        dim["recommendation"] = dim.get("recommendation", "")
        dim["alert_level"] = _normalize_alert_level(dim.get("alert_level", ""))
        dim["closure_hours"] = _safe_int(dim.get("closure_hours", 0))
        dim["push_strategy"] = _normalize_push_strategy(dim.get("push_strategy", ""))
        dim["outcome_bucket"] = _normalize_outcome_bucket(dim.get("outcome_bucket", ""))
        if not dim.get("severity") and dim.get("alert_level"):
            dim["severity"] = _alert_level_to_severity(dim["alert_level"])

    if not result.get("severity"):
        result["severity"] = _derive_severity_from_dimensions(result["dimensions"])

    if not result.get("severity") and result.get("alert_level"):
        result["severity"] = _alert_level_to_severity(result["alert_level"])

    if not result.get("alert_level") and result["dimensions"]:
        result["alert_level"] = _derive_alert_level_from_dimensions(result["dimensions"])

    if not result.get("risk_score"):
        result["risk_score"] = _risk_score_from_dimensions(result["dimensions"], result.get("inconsistency", False))

    if not result.get("overall_conclusion") and result["dimensions"]:
        problem_dims = [dim["dimension"] for dim in result["dimensions"] if dim.get("status") in {"warn", "fail"}]
        if problem_dims:
            result["overall_conclusion"] = f"发现需要关注的维度：{'、'.join(problem_dims[:3])}。"
        else:
            result["overall_conclusion"] = "病历文书与护理记录整体基本一致。"

    if not result.get("reasoning_brief"):
        result["reasoning_brief"] = result.get("overall_conclusion", "")

    if not result.get("inconsistency"):
        result["inconsistency"] = any(dim.get("status") in {"warn", "fail"} for dim in result["dimensions"])
