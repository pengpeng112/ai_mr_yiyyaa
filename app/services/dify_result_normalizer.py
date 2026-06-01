"""Dify 结果归一化服务 —— 统一 severity、alert_level、status 等字段。"""
from __future__ import annotations

from typing import Any


def normalize_status(status: str) -> str:
    text = str(status or "").lower()
    if text in {"pass", "warn", "fail", "unknown"}:
        return text
    if text in {"ok", "success", "normal", "matched"}:
        return "pass"
    if text in {"warning", "partial", "partially matched"}:
        return "warn"
    if text in {"error", "conflict", "mismatch"}:
        return "fail"
    if text in {"na", "n/a", "none", "uncertain"}:
        return "unknown"
    if "✅" in text or "通过" in text or "一致" in text:
        return "pass"
    if "⚠" in text or "警告" in text or "风险" in text:
        return "warn"
    if "❌" in text or "不一致" in text or "失败" in text:
        return "fail"
    return "unknown"


def normalize_severity(severity: str) -> str:
    text = str(severity or "").lower()
    if text in {"low", "medium", "high"}:
        return text
    if text in {"minor", "small"}:
        return "low"
    if text in {"moderate", "middle"}:
        return "medium"
    if text in {"critical", "major", "severe"}:
        return "high"
    if "高" in text:
        return "high"
    if "中" in text:
        return "medium"
    if "低" in text:
        return "low"
    return ""


def normalize_alert_level(alert_level: str) -> str:
    """归一化预警灯号为 red/yellow/blue/gray 或空字符串"""
    text = str(alert_level or "").lower().strip()
    if text in {"red", "yellow", "blue", "gray"}:
        return text
    mapping = {
        "红": "red", "红灯": "red", "高危": "red",
        "黄": "yellow", "黄灯": "yellow", "中危": "yellow",
        "蓝": "blue", "蓝灯": "blue", "低危": "blue",
        "灰": "gray", "灰灯": "gray", "不确定": "gray", "grey": "gray",
    }
    return mapping.get(text, "")


def alert_level_to_severity(alert_level: str) -> str:
    """从 alert_level 派生 severity"""
    return {
        "red": "high",
        "yellow": "medium",
        "blue": "low",
        "gray": "low",
    }.get(alert_level, "")


def normalize_push_strategy(strategy: str) -> str:
    text = str(strategy or "").lower().strip()
    if text in {"immediate", "batch", "shift_summary", "review_only"}:
        return text
    return ""


def normalize_outcome_bucket(bucket: str) -> str:
    text = str(bucket or "").lower().strip()
    if text in {"primary", "secondary", "none"}:
        return text
    return ""


def derive_severity_from_dimensions(dimensions: list[dict]) -> str:
    levels = [dim.get("severity", "") for dim in dimensions if dim.get("severity")]
    if "high" in levels:
        return "high"
    if "medium" in levels:
        return "medium"
    return "low" if levels else ""


def derive_alert_level_from_dimensions(dimensions: list[dict]) -> str:
    """从维度中取最高预警灯号"""
    priority = {"red": 0, "yellow": 1, "blue": 2, "gray": 3}
    best = ""
    best_rank = 999
    for dim in dimensions:
        al = dim.get("alert_level", "")
        if al in priority and priority[al] < best_rank:
            best = al
            best_rank = priority[al]
    return best


def safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def severity_from_status(status: str) -> str:
    if status == "fail":
        return "high"
    if status == "warn":
        return "medium"
    return "low" if status == "pass" else ""


def risk_score_from_dimensions(dimensions: list[dict], inconsistency: bool) -> int:
    if not dimensions:
        return 60 if inconsistency else 0
    score = 0
    for dim in dimensions:
        if dim.get("status") == "fail":
            score += 25
        elif dim.get("status") == "warn":
            score += 15
        elif dim.get("status") == "pass":
            score += 2
    return min(score, 100)
