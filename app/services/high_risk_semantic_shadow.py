"""高危临床语义 shadow 规则（003 工作包 D）。

只计算候选降级原因并写日志/返回报告，不改变生产等级。
临床规则尚未书面确认前，代码层不提供可运行时开启的降级入口。
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def semantic_enforce_enabled() -> bool:
    """003-D 尚处 shadow 阶段；临床签字前始终禁止实际降级。"""
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
