"""
Dify Schema 解析模块 —— 从 dify_pusher.py 拆分，负责标准化解析新旧 Dify 输出 schema。
"""
import json
import logging
import re
from typing import Any

from app.services import dify_result_normalizer as _norm
from app.services.dify_log_utils import _fingerprint_for_log
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
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
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
            "reasoning": _first_non_empty(item.get("reasoning"), item.get("reasoning_brief")),
            "extra": extra,
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
        for phrase in ["存在不一致", "发现不一致", "有不一致", "不一致问题", "不一致", "inconsistent", "mismatch", "conflict", "❌"]
    )

    if explicit_inconsistency or (keyword_inconsistency and not negative_inconsistency):
        result["inconsistency"] = True
        if "严重" in text or "high" in text or "重大" in text:
            # 非结构化回退无法证明双侧证据和高危硬门槛，最多保留为中风险人工关注。
            result["severity"] = "medium"
            _append_parse_warning(result, "fallback_high_suppressed")
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
            "[Dify解析] patient_summary 关键字段为空: fields=%s raw_type=%s raw_size=%s raw_sha256=%s",
            missing_patient_fields,
            type(result.get("raw_text")).__name__,
            len(str(result.get("raw_text") or "")),
            _fingerprint_for_log(result.get("raw_text") or ""),
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

_ADMISSION_DIMENSION_CODE_ALIASES = {
    "chief_complaint": "chief_complaint",
    "main_complaint": "chief_complaint",
    "history_of_present_illness": "history_of_present_illness",
    "history_of_illness": "history_of_present_illness",
    "present_illness_history": "history_of_present_illness",
    "past_history": "past_history",
    "past_medical_history": "past_history",
    "medical_history": "past_history",
    "physical_examination": "physical_examination",
    "physical_exam": "physical_examination",
    "physical_examination_consistency": "physical_examination",
    "auxiliary_examination": "auxiliary_examination",
    "auxiliary_exam": "auxiliary_examination",
    "auxiliary_examination_consistency": "auxiliary_examination",
    "initial_diagnosis": "initial_diagnosis",
    "initial_diagnosis_consistency": "initial_diagnosis",
    "diagnosis": "diagnosis_consistency",
    "diagnosis_consistency": "diagnosis_consistency",
    "diagnosis_basis": "diagnosis_consistency",
    "treatment_plan": "treatment_plan",
    "timeline_consistency": "timeline_consistency",
    "time_consistency": "timeline_consistency",
    "text_quality": "text_quality",
}


def _canonicalize_admission_dimension_code(dim: dict[str, Any]) -> None:
    """收敛入院记录核查的自由维度编码，同时保留 Dify 原始值。"""
    raw_code = str(dim.get("dimension_code") or "").strip()
    normalized = raw_code.lower().replace("-", "_").replace(" ", "_")
    canonical = _ADMISSION_DIMENSION_CODE_ALIASES.get(normalized, "")
    searchable = f"{normalized} {str(dim.get('dimension') or '').lower()}"

    if not canonical:
        if "chief" in searchable or "complaint" in searchable or "主诉" in searchable:
            canonical = "chief_complaint"
        elif "initial_diagnosis" in searchable or "初步诊断" in searchable:
            canonical = "initial_diagnosis"
        elif "diagnos" in searchable or "诊断" in searchable:
            canonical = "diagnosis_consistency"
        elif any(token in searchable for token in ("physical", "vital", "neuro", "专科", "体格")):
            canonical = "physical_examination"
        elif any(token in searchable for token in ("auxiliary", "imaging", "pathology", "lab", "test", "检查")):
            canonical = "auxiliary_examination"
        elif any(token in searchable for token in ("present_illness", "illness_history", "symptom", "onset", "现病史")):
            canonical = "history_of_present_illness"
        elif any(token in searchable for token in ("past_", "medical_history", "allergy", "drug_history", "surgical_history", "既往史")):
            canonical = "past_history"
        elif "treatment" in searchable or "治疗" in searchable or "计划" in searchable:
            canonical = "treatment_plan"
        elif "time" in searchable or "timeline" in searchable or "时间" in searchable:
            canonical = "timeline_consistency"
        elif "text" in searchable or "template" in searchable or "文书" in searchable:
            canonical = "text_quality"
        else:
            canonical = "other"

    if canonical != raw_code:
        extra = dim.get("extra") if isinstance(dim.get("extra"), dict) else {}
        if raw_code:
            extra.setdefault("raw_dimension_code", raw_code)
        dim["extra"] = extra
        dim["dimension_code"] = canonical


def _severity_rank(value: str) -> int:
    return {"": 0, "low": 1, "medium": 2, "high": 3}.get(value, 0)


def _severity_to_alert_level(value: str) -> str:
    return {"high": "red", "medium": "yellow", "low": "blue"}.get(value, "")


_HIGH_RISK_GOVERNED_AUDIT_TYPES = {
    "admission_vs_first_progress",
    "discharge_vs_first_progress",
    "discharge_vs_frontpage",
    "surgery_chain",
    "progress_vs_nursing",
    "jyjc_vs_bcnursing",
    "syssvsscbc",
}

_HIGH_RISK_SAFETY_CATEGORIES = {
    "admission_vs_first_progress": {
        "patient_identity", "allergy_medication", "wrong_site_or_side", "critical_diagnosis_basis",
    },
    "discharge_vs_first_progress": {
        "patient_identity", "allergy_medication", "wrong_site_or_side", "critical_diagnosis_basis",
    },
    # 生产环境沿用该 code；与 discharge_vs_first_progress 使用同一临床门槛。
    "discharge_vs_frontpage": {
        "patient_identity", "allergy_medication", "wrong_site_or_side", "critical_diagnosis_basis",
    },
    "surgery_chain": {
        "patient_identity", "wrong_site_or_side", "wrong_procedure_or_implant",
    },
    "progress_vs_nursing": {
        "allergy_medication", "current_vital_or_life_support",
    },
    "jyjc_vs_bcnursing": {"critical_diagnosis_basis"},
    "syssvsscbc": {"wrong_site_or_side", "wrong_procedure_or_implant"},
}

_EMPTY_EVIDENCE_MARKERS = {
    "", "无", "无记录", "未记录", "未见", "未提及", "未提供", "无资料", "无数据",
    "不详", "未知", "none", "null", "n/a", "na", "unknown",
}


def _is_high_risk_dimension(dim: dict[str, Any]) -> bool:
    return dim.get("severity") == "high" or dim.get("alert_level") == "red"


def _has_meaningful_evidence(values: Any) -> bool:
    for value in _ensure_string_list(values):
        normalized = re.sub(r"[\s:：;；,.，。]+", "", value).lower()
        if normalized and normalized not in _EMPTY_EVIDENCE_MARKERS:
            return True
    return False


def _iter_high_risk_issues(dim: dict[str, Any]) -> list[dict[str, Any]]:
    extra = dim.get("extra") if isinstance(dim.get("extra"), dict) else {}
    issues = extra.get("issues")
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues if isinstance(issue, dict)]


def _qualified_high_risk_issue(dim: dict[str, Any], audit_type_code: str) -> dict[str, Any] | None:
    """返回满足统一高危硬门槛的同一条 issue；否则返回 None。"""
    # `other` 仅用于兼容未知/越界维度，六类临床契约均不允许它触发红色高危。
    # 保留该维度供人工排查，但必须在进入结构化 issue 门槛前失败关闭。
    if str(dim.get("dimension_code") or "").strip().lower() == "other":
        return None
    if dim.get("status") != "fail" or dim.get("confidence", 0) < 0.8:
        return None
    if not _has_meaningful_evidence(dim.get("medical_evidence")):
        return None
    if not _has_meaningful_evidence(dim.get("nursing_evidence")):
        return None

    allowed_categories = _HIGH_RISK_SAFETY_CATEGORIES.get(audit_type_code, set())
    for issue in _iter_high_risk_issues(dim):
        source_a = str(issue.get("source_a") or "").strip()
        source_b = str(issue.get("source_b") or "").strip()
        if str(issue.get("level") or "").strip().lower() != "severe":
            continue
        if not _to_bool(issue.get("high_eligible")):
            continue
        if str(issue.get("issue_mode") or "").strip().lower() != "contradiction":
            continue
        if not source_a or not source_b or source_a == source_b:
            continue
        if not _has_meaningful_evidence(issue.get("evidence_a")):
            continue
        if not _has_meaningful_evidence(issue.get("evidence_b")):
            continue
        if _safe_float(issue.get("confidence", dim.get("confidence", 0))) < 0.8:
            continue
        if str(issue.get("safety_category") or "").strip() not in allowed_categories:
            continue
        return issue
    return None


def _has_qualified_high_risk(dimensions: list[dict[str, Any]], audit_type_code: str) -> bool:
    return any(
        _is_high_risk_dimension(dim) and _qualified_high_risk_issue(dim, audit_type_code)
        for dim in dimensions
    )


def _high_risk_rejection_reasons(dim: dict[str, Any], audit_type_code: str) -> list[str]:
    reasons: list[str] = []
    if str(dim.get("dimension_code") or "").strip().lower() == "other":
        reasons.append("dimension_code_other_not_high_eligible")
    if dim.get("status") != "fail":
        reasons.append("status_not_fail")
    if dim.get("confidence", 0) < 0.8:
        reasons.append("confidence_below_0_8")
    if not _has_meaningful_evidence(dim.get("medical_evidence")):
        reasons.append("source_a_evidence_missing")
    if not _has_meaningful_evidence(dim.get("nursing_evidence")):
        reasons.append("source_b_evidence_missing")
    if not _iter_high_risk_issues(dim):
        reasons.append("structured_high_risk_issue_missing")
    elif _qualified_high_risk_issue(dim, audit_type_code) is None:
        reasons.append("structured_high_risk_issue_unqualified")
    return reasons


def _downgrade_unqualified_high_risk(dim: dict[str, Any], audit_type_code: str) -> bool:
    """不满足硬门槛的 high 转为中风险问题或证据不足人工复核。"""
    if not _is_high_risk_dimension(dim) or _qualified_high_risk_issue(dim, audit_type_code):
        return False

    extra = dim.get("extra") if isinstance(dim.get("extra"), dict) else {}
    manual_reviews = extra.get("manual_review")
    if not isinstance(manual_reviews, list):
        manual_reviews = []
    manual_reviews.append({
        "review_type": "high_risk_evidence_insufficient",
        "reason": "高危判定未同时满足明确冲突、受控安全类别、双侧证据和置信度不低于 0.8 的要求。",
        "reason_codes": _high_risk_rejection_reasons(dim, audit_type_code),
        "audit_type_code": audit_type_code,
        "original_status": dim.get("status", ""),
        "original_severity": dim.get("severity", ""),
        "original_alert_level": dim.get("alert_level", ""),
        "original_confidence": dim.get("confidence", 0),
    })
    extra["manual_review"] = manual_reviews
    dim["extra"] = extra

    has_both_evidence = (
        _has_meaningful_evidence(dim.get("medical_evidence"))
        and _has_meaningful_evidence(dim.get("nursing_evidence"))
    )
    if has_both_evidence and dim.get("status") in {"warn", "fail"} and dim.get("issue_summary"):
        # 双侧明确问题仍保留，但不得触发企业微信高危告警。
        dim["status"] = "warn"
        dim["severity"] = "medium"
        dim["alert_level"] = "yellow"
        dim["closure_hours"] = 48 if audit_type_code == "jyjc_vs_bcnursing" else 72
        dim["push_strategy"] = "batch"
        dim["outcome_bucket"] = "secondary"
    else:
        dim["status"] = "unknown"
        dim["severity"] = "low"
        dim["alert_level"] = "gray"
        dim["closure_hours"] = 0
        dim["push_strategy"] = "review_only"
        dim["outcome_bucket"] = "none"
    return True


def _reconcile_summary_after_high_risk_guard(result: dict, audit_type_code: str) -> None:
    """高危维度被降级后，同步收敛总体告警级别，避免保留失效的红灯。"""
    dimensions = result.get("dimensions", [])
    valid_high = _has_qualified_high_risk(dimensions, audit_type_code)
    if valid_high:
        return

    problem_dimensions = [dim for dim in dimensions if dim.get("status") in {"warn", "fail"}]
    severity = _derive_severity_from_dimensions(problem_dimensions) or "low"
    result["severity"] = severity
    result["inconsistency"] = bool(problem_dimensions)
    if severity == "medium":
        result["alert_level"] = "yellow"
        result["risk_score"] = 60
        result["closure_hours"] = 48 if audit_type_code == "jyjc_vs_bcnursing" else 72
        result["push_strategy"] = "batch"
        result["outcome_bucket"] = "secondary"
    elif severity == "high":
        result["alert_level"] = "red"
        result["risk_score"] = 90
        result["closure_hours"] = 24
        result["push_strategy"] = "immediate"
        result["outcome_bucket"] = "primary"
    else:
        has_unknown = any(dim.get("status") == "unknown" for dim in dimensions)
        result["alert_level"] = "gray" if has_unknown else "blue"
        result["risk_score"] = 0 if has_unknown else (20 if dimensions else 0)
        result["closure_hours"] = 0
        result["push_strategy"] = "review_only" if has_unknown else "shift_summary"
        result["outcome_bucket"] = "none" if has_unknown else "secondary"


def _post_process_result(result: dict, audit_type_code: str = ""):
    result["focus_items"] = _ensure_string_list(result.get("focus_items", []))
    result["dimensions"] = [dim for dim in result.get("dimensions", []) if dim.get("dimension") or dim.get("dimension_code")]

    high_risk_downgraded = False
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
        if audit_type_code == "admission_vs_first_progress":
            _canonicalize_admission_dimension_code(dim)
        if audit_type_code in _HIGH_RISK_GOVERNED_AUDIT_TYPES:
            if _downgrade_unqualified_high_risk(dim, audit_type_code):
                high_risk_downgraded = True
            elif _is_high_risk_dimension(dim) and _qualified_high_risk_issue(dim, audit_type_code):
                # 003-D：形式门槛通过后跑语义 shadow；默认不改等级
                try:
                    from app.services.high_risk_semantic_shadow import apply_semantic_shadow
                    shadow_result = apply_semantic_shadow(dim, audit_type_code)
                    if shadow_result.get("applied"):
                        high_risk_downgraded = True
                except Exception:
                    audit_logger.exception("semantic shadow evaluation failed")

    problem_dimensions = [
        dim for dim in result["dimensions"]
        if dim.get("status") in {"warn", "fail"}
        or (dim.get("severity") in {"medium", "high"} and str(dim.get("issue_summary") or "").strip())
    ]
    if problem_dimensions:
        dimension_severity = _derive_severity_from_dimensions(problem_dimensions)
        if _severity_rank(dimension_severity) > _severity_rank(result.get("severity", "")):
            _append_parse_warning(result, "summary_dimension_severity_conflict")
            result["severity"] = dimension_severity
        if not result.get("inconsistency"):
            _append_parse_warning(result, "summary_dimension_inconsistency_conflict")
            result["inconsistency"] = True
        derived_alert_level = _severity_to_alert_level(result.get("severity", ""))
        if derived_alert_level:
            result["alert_level"] = derived_alert_level

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

    summary_marks_high_risk = result.get("severity") == "high" or result.get("alert_level") == "red"
    if audit_type_code in _HIGH_RISK_GOVERNED_AUDIT_TYPES and (
        high_risk_downgraded
        or (summary_marks_high_risk and not _has_qualified_high_risk(result["dimensions"], audit_type_code))
    ):
        _append_parse_warning(result, "high_risk_guard_downgraded")
        _reconcile_summary_after_high_risk_guard(result, audit_type_code)

    # P1-4: 结果契约校验
    try:
        from app.services.result_contract_validator import validate_result_contract
        contract_valid, contract_errors = validate_result_contract(result, audit_type_code)
        result["contract_valid"] = contract_valid
        result["contract_errors"] = contract_errors
        if not contract_valid:
            _append_parse_warning(result, "contract_invalid")
    except Exception as cv_exc:
        audit_logger.warning("contract validation error: %s", cv_exc)
        result["contract_valid"] = True
        result["contract_errors"] = []
