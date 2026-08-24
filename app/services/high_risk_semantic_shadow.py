"""高危临床语义 shadow 规则（003 工作包 D；20260817 起支持授权开关）。

默认只计算候选降级原因并写日志/返回报告，不改变生产等级。
经运营方授权后，可通过 config["high_risk_semantic_enforce"]=true 或环境变量
HIGH_RISK_SEMANTIC_ENFORCE 开启实际降级；每次降级都在维度
extra.semantic_enforced_demote 留下原因审计，可追溯、可回滚。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
_TRUTHY = {"1", "true", "yes", "on"}

# 诊断列表编号（"1." "2、" "3）" 等）用于拆分诊断项
_DIAG_NUMBER_RE = re.compile(r"[0-9]{1,2}[、.．)）]")
# 生理不可能数值：BMI=0、体重 0kg、身高 0cm（模板占位/数据错误，非临床矛盾）
_IMPOSSIBLE_VALUE_RES = (
    re.compile(r"BMI[^0-9]{0,4}0(?:\.0+)?"),
    re.compile(r"[^0-9A-Za-z]W\s*[:：]?\s*0(?:\.0+)?\s*kg"),
    re.compile(r"[^0-9A-Za-z]H\s*[:：]?\s*0(?:\.0+)?\s*cm"),
)


def _join_evidence(value: Any) -> str:
    """把维度/issue 证据拼成原始文本（不做标点清洗，保留诊断编号）。"""
    if isinstance(value, list):
        return "".join(
            str((item.get("text") or item.get("content") or "") if isinstance(item, dict) else item or "")
            for item in value
        )
    if isinstance(value, dict):
        return str(value.get("text") or value.get("content") or "")
    return str(value or "")


def _diag_items(text: str) -> list[str]:
    """按编号拆诊断项；有编号时丢弃首段标签（如"初步诊断:"）。"""
    parts = _DIAG_NUMBER_RE.split(str(text or ""))
    items: list[str] = []
    for part in (parts[1:] if len(parts) > 1 else parts):
        item = _PUNCT_RE.sub("", str(part or "")).lower()
        if len(item) >= 2 and "诊断" not in item:
            items.append(item)
    return items


def semantic_enforce_enabled() -> bool:
    """语义降级开关：默认关闭；env HIGH_RISK_SEMANTIC_ENFORCE 优先，其次 config 键。"""
    if os.environ.get("HIGH_RISK_SEMANTIC_ENFORCE", "").strip().lower() in _TRUTHY:
        return True
    try:
        from app.config import load_config
        return bool(load_config().get("high_risk_semantic_enforce"))
    except Exception:
        return False


def _norm_evidence_text(value: Any) -> str:
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item or ""))
        text = "".join(parts)
    elif isinstance(value, dict):
        text = str(value.get("text") or value.get("content") or "")
    else:
        text = str(value or "")
    return _PUNCT_RE.sub("", text).lower()


def _evidence_char_len(value: Any) -> int:
    return len(_norm_evidence_text(value))


def _issue_has_structured_claim(issue: dict[str, Any]) -> bool:
    """短证据需结构化主张才可保留 high。"""
    keys = ("attribute", "value_a", "value_b", "claim", "normalized_claim")
    if any(str(issue.get(k) or "").strip() for k in keys):
        return True
    extra = issue.get("structured") if isinstance(issue.get("structured"), dict) else {}
    return any(str(extra.get(k) or "").strip() for k in keys)


def evaluate_semantic_high_risk_dim(dim: dict[str, Any], audit_type_code: str = "") -> dict[str, Any]:
    """
    对已通过形式门槛的 high 维度评估语义风险。
    返回: {should_demote, reasons, candidate_severity, shadow_only}
    """
    reasons: list[str] = []
    code = str(dim.get("dimension_code") or dim.get("code") or "").strip()
    med = dim.get("medical_evidence")
    nur = dim.get("nursing_evidence")
    med_n = _norm_evidence_text(med)
    nur_n = _norm_evidence_text(nur)

    if med_n and nur_n and med_n == nur_n:
        reasons.append("identical_evidence")

    extra = dim.get("extra") if isinstance(dim.get("extra"), dict) else {}
    issues = extra.get("issues") if isinstance(extra.get("issues"), list) else []

    # 新增诊断（一侧诊断列表是另一侧的严格超集）属于 omission/evolution，
    # 不是 contradiction；医学复核确认不得仅因"另一份没写"判红（20260817）。
    med_raw = _join_evidence(med)
    nur_raw = _join_evidence(nur)
    if "诊断" in med_raw and "诊断" in nur_raw:
        a_items = _diag_items(med_raw)
        b_items = _diag_items(nur_raw)
        if a_items and b_items:
            sa, sb = set(a_items), set(b_items)
            if (sa < sb) or (sb < sa):
                reasons.append("diagnosis_superset_not_contradiction")

    # 生理不可能数值（BMI=0、W 0kg、H 0cm）是模板占位/数据录入错误，
    # 归文本/数据质量，不得作为临床矛盾判红（20260817）。
    evidence_texts = [med_raw, nur_raw]
    for issue in issues:
        if isinstance(issue, dict):
            evidence_texts.append(_join_evidence(issue.get("evidence_a")))
            evidence_texts.append(_join_evidence(issue.get("evidence_b")))
    if any(rx.search(t) for t in evidence_texts for rx in _IMPOSSIBLE_VALUE_RES):
        reasons.append("impossible_vital_value_data_quality")

    short_without_claim = False
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        ea = _evidence_char_len(issue.get("evidence_a"))
        eb = _evidence_char_len(issue.get("evidence_b"))
        if (0 < ea < 12 or 0 < eb < 12) and not _issue_has_structured_claim(issue):
            short_without_claim = True
            break
    if short_without_claim:
        reasons.append("short_evidence_without_structured_claim")

    if code == "other":
        reasons.append("other_dimension_forbid_high")

    if code == "text_quality":
        # YML 契约：文本/模板/数据质量问题（错字、模板、BMI=0 等）不得红色高危。
        reasons.append("text_quality_forbid_high")

    if code == "physical_examination":
        # 默认 shadow 标记：无部位/侧别/过敏等安全类别时建议人工复核
        safety_ok = False
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            cat = str(issue.get("safety_category") or "").strip().lower()
            if cat in {
                "wrong_site_or_side",
                "wrong_procedure_or_implant",
                "allergy_medication",
                "critical_diagnosis_basis",
                "patient_identity",
                "current_vital_or_life_support",
            }:
                safety_ok = True
                break
        if not safety_ok:
            reasons.append("physical_examination_lacks_direct_safety_category")

    should_demote = bool(reasons)
    return {
        "should_demote": should_demote,
        "reasons": reasons,
        "candidate_severity": "medium" if should_demote else "high",
        "shadow_only": not semantic_enforce_enabled(),
        "audit_type_code": audit_type_code,
        "dimension_code": code,
    }


def apply_semantic_shadow(dim: dict[str, Any], audit_type_code: str = "") -> dict[str, Any]:
    """对 high 维度运行 shadow；仅 enforce 时改写 severity。"""
    if str(dim.get("severity") or "").lower() != "high" and str(dim.get("alert_level") or "") != "red":
        return {"applied": False, "report": None}

    report = evaluate_semantic_high_risk_dim(dim, audit_type_code)
    if not report["should_demote"]:
        return {"applied": False, "report": report}

    logger.info(
        "[high_risk_semantic_shadow] demote_candidate dim=%s reasons=%s enforce=%s",
        report.get("dimension_code"),
        report.get("reasons"),
        not report.get("shadow_only"),
    )
    extra = dim.get("extra") if isinstance(dim.get("extra"), dict) else {}
    shadow_list = extra.get("semantic_shadow")
    if not isinstance(shadow_list, list):
        shadow_list = []
    shadow_list.append(report)
    extra["semantic_shadow"] = shadow_list
    dim["extra"] = extra

    if not report["shadow_only"]:
        dim["severity"] = "medium"
        dim["alert_level"] = "yellow"
        dim["push_strategy"] = dim.get("push_strategy") or "review_only"
        extra["semantic_enforced_demote"] = report["reasons"]
        dim["extra"] = extra
        return {"applied": True, "report": report}
    return {"applied": False, "report": report}
