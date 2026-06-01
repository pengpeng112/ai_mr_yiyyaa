"""检验记录聚合、去重与风险排序（Task 6）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any


DEFAULT_MAX_LAB_ITEMS = 30
DEFAULT_ABNORMAL_KEYWORDS = (
    "异常",
    "高",
    "低",
    "阳性",
    "危急",
    "升高",
    "降低",
    "偏高",
    "偏低",
)
DEFAULT_CRITICAL_KEYWORDS = (
    "危急",
    "critical",
    "panic",
    "警报",
)
DEFAULT_KEY_ITEM_KEYWORDS = (
    "血糖",
    "葡萄糖",
    "钾",
    "钠",
    "氯",
    "钙",
    "镁",
    "血红蛋白",
    "白细胞",
    "中性粒",
    "肌酐",
    "乳酸",
    "降钙素原",
)
ABNORMAL_INDICATORS = {
    "H",
    "L",
    "HH",
    "LL",
    "+",
    "++",
    "+++",
    "++++",
    "POS",
    "POSITIVE",
    "ABN",
    "CRIT",
    "异常",
    "阳性",
    "危急",
    "高",
    "低",
}
NORMAL_INDICATORS = {"N", "NORMAL", "阴性", "正常"}

LAB_FIELD_ALIASES = {
    "test_no": ["检验单号", "TEST_NO"],
    "test_name": ["检验项目", "ITEM_NAME"],
    "item_name": ["检验项目", "ITEM_NAME"],
    "report_item_name": ["报告项目名称", "REPORT_ITEM_NAME"],
    "report_item_code": ["报告项目编码", "REPORT_ITEM_CODE"],
    "result": ["检验结果", "结果值", "RESULT_VALUE", "RESULT"],
    "units": ["单位", "UNITS"],
    "abnormal_indicator": ["异常标记", "ABNORMAL_INDICATOR"],
    "reference_range": ["参考范围", "PRINT_CONTEXT"],
    "print_context": ["参考范围", "PRINT_CONTEXT"],
    "result_time": ["结果时间", "RESULT_DATE_TIME"],
    "specimen": ["标本", "SPECIMEN"],
}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _with_alias_fields(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw or {})
    for canonical_key, aliases in LAB_FIELD_ALIASES.items():
        if _as_text(row.get(canonical_key)):
            continue
        for alias in aliases:
            value = row.get(alias)
            if _as_text(value):
                row[canonical_key] = value
                break
    return row


def _parse_result_datetime(raw: Any) -> datetime | None:
    text = _as_text(raw)
    if not text:
        return None
    normalized = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    patterns = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y%m%d%H%M%S",
        "%Y%m%d",
    )
    for pattern in patterns:
        try:
            return datetime.strptime(normalized, pattern)
        except ValueError:
            continue
    return None


def _is_abnormal(item: dict[str, Any], abnormal_keywords: tuple[str, ...]) -> bool:
    indicator = _as_text(item.get("abnormal_indicator")).upper()
    if indicator in ABNORMAL_INDICATORS:
        return True
    if indicator in NORMAL_INDICATORS:
        return False

    target = " ".join(
        [
            _as_text(item.get("test_name")).lower(),
            _as_text(item.get("report_item_name")).lower(),
            _as_text(item.get("item_name")).lower(),
            _as_text(item.get("result")).lower(),
            _as_text(item.get("reference_range")).lower(),
            _as_text(item.get("print_context")).lower(),
        ]
    )
    return any(keyword.lower() in target for keyword in abnormal_keywords)


def _calc_risk_score(
    item: dict[str, Any],
    is_abnormal: bool,
    critical_keywords: tuple[str, ...],
    key_item_keywords: tuple[str, ...],
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []

    if is_abnormal:
        score += 60
        reasons.append("abnormal_indicator_or_text")

    haystack = " ".join(
        [
            _as_text(item.get("test_name")).lower(),
            _as_text(item.get("report_item_name")).lower(),
            _as_text(item.get("item_name")).lower(),
            _as_text(item.get("result")).lower(),
            _as_text(item.get("reference_range")).lower(),
            _as_text(item.get("print_context")).lower(),
        ]
    )

    if any(keyword.lower() in haystack for keyword in critical_keywords):
        score += 30
        reasons.append("critical_keyword")

    if any(keyword.lower() in haystack for keyword in key_item_keywords):
        score += 20
        reasons.append("key_lab_item")

    if any(flag in haystack for flag in ("++", "+++", "++++", "明显", "重度")):
        score += 10
        reasons.append("strong_abnormal_text")

    return score, reasons


def _risk_level(score: int) -> str:
    if score >= 90:
        return "high"
    if score >= 60:
        return "medium"
    return "low"


def aggregate_lab_records(records: list[dict[str, Any]], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """按 (TEST_NO, REPORT_ITEM_CODE|ITEM_NAME) 去重，并输出风险排序结果。"""
    cfg = options or {}
    max_lab_items = int(cfg.get("max_lab_items", DEFAULT_MAX_LAB_ITEMS) or DEFAULT_MAX_LAB_ITEMS)
    include_normal_summary = bool(cfg.get("include_normal_summary", False))
    abnormal_keywords = tuple(cfg.get("abnormal_keywords") or DEFAULT_ABNORMAL_KEYWORDS)
    critical_keywords = tuple(cfg.get("critical_keywords") or DEFAULT_CRITICAL_KEYWORDS)
    key_item_keywords = tuple(cfg.get("key_item_keywords") or DEFAULT_KEY_ITEM_KEYWORDS)

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in records or []:
        raw = _with_alias_fields(raw)
        test_no = _as_text(raw.get("test_no"))
        report_item_code = _as_text(raw.get("report_item_code"))
        item_name = _as_text(raw.get("report_item_name")) or _as_text(raw.get("item_name"))
        dedup_key = (test_no, report_item_code or item_name)
        if not dedup_key[0] and not dedup_key[1]:
            continue

        current = deduped.get(dedup_key)
        if current is None:
            deduped[dedup_key] = raw
            continue

        current_dt = _parse_result_datetime(current.get("result_time"))
        candidate_dt = _parse_result_datetime(raw.get("result_time"))
        if candidate_dt and (not current_dt or candidate_dt >= current_dt):
            deduped[dedup_key] = raw

    ranked: list[dict[str, Any]] = []
    normal_count = 0
    abnormal_count = 0
    for row in deduped.values():
        abnormal = _is_abnormal(row, abnormal_keywords)
        if abnormal:
            abnormal_count += 1
        else:
            normal_count += 1
            if not include_normal_summary:
                continue

        risk_score, reasons = _calc_risk_score(row, abnormal, critical_keywords, key_item_keywords)
        ranked.append(
            {
                "test_no": _as_text(row.get("test_no")),
                "test_name": _as_text(row.get("test_name")),
                "report_item_code": _as_text(row.get("report_item_code")),
                "report_item_name": _as_text(row.get("report_item_name")) or _as_text(row.get("item_name")),
                "item_name": _as_text(row.get("item_name")),
                "result": _as_text(row.get("result")),
                "units": _as_text(row.get("units")),
                "abnormal_indicator": _as_text(row.get("abnormal_indicator")),
                "result_time": _as_text(row.get("result_time")),
                "reference_range": _as_text(row.get("reference_range")) or _as_text(row.get("print_context")),
                "print_context": _as_text(row.get("print_context")),
                "is_abnormal": abnormal,
                "risk_score": risk_score,
                "risk_level": _risk_level(risk_score),
                "risk_reasons": reasons,
            }
        )

    ranked.sort(
        key=lambda item: (
            item.get("risk_score", 0),
            _parse_result_datetime(item.get("result_time")) or datetime.min,
        ),
        reverse=True,
    )

    selected = ranked[:max_lab_items]
    omitted_count = max(0, len(ranked) - len(selected))
    return {
        "items": selected,
        "total_deduped": len(deduped),
        "selected_count": len(selected),
        "abnormal_count": abnormal_count,
        "normal_count": normal_count,
        "omitted_count": omitted_count,
        "normal_summary": {
            "included": include_normal_summary,
            "normal_count": normal_count,
        },
    }
