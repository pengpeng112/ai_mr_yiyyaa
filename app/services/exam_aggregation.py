"""检查报告聚合与异常摘要服务（Task 7）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any


DEFAULT_MAX_EXAM_REPORTS = 10
DEFAULT_ABNORMAL_KEYWORDS = (
    "异常",
    "阳性",
    "占位",
    "结节",
    "感染",
    "积液",
    "出血",
    "梗死",
    "狭窄",
)
DEFAULT_NORMAL_HINTS = (
    "未见明显异常",
    "未见异常",
    "阴性",
    "正常",
)
ABNORMAL_FLAGS = {"Y", "YES", "TRUE", "1", "ABNORMAL", "异常", "阳性", "是"}

EXAM_FIELD_ALIASES = {
    "exam_no": ["检查号", "EXAM_NO"],
    "exam_class": ["检查类别", "EXAM_CLASS"],
    "exam_name": ["检查名称", "EXAM_ITEM", "EXAM_NAME"],
    "exam_time": ["报告时间", "检查时间", "REPORT_DATE_TIME"],
    "report_time": ["报告时间", "REPORT_DATE_TIME"],
    "description": ["检查所见", "报告内容", "REPORT_TEXT", "DESCRIPTION"],
    "impression": ["检查印象", "影像印象", "IMPRESSION"],
    "recommendation": ["检查建议", "RECOMMENDATION"],
    "is_abnormal": ["是否异常", "IS_ABNORMAL"],
}


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _with_alias_fields(raw: dict[str, Any]) -> dict[str, Any]:
    row = dict(raw or {})
    for canonical_key, aliases in EXAM_FIELD_ALIASES.items():
        if _as_text(row.get(canonical_key)):
            continue
        for alias in aliases:
            value = row.get(alias)
            if _as_text(value):
                row[canonical_key] = value
                break
    return row


def _parse_dt(raw: Any) -> datetime | None:
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


def _is_abnormal(record: dict[str, Any], abnormal_keywords: tuple[str, ...]) -> bool:
    flag = _as_text(record.get("is_abnormal")).upper()
    if flag in ABNORMAL_FLAGS:
        return True
    haystack = " ".join(
        [
            _as_text(record.get("exam_name")).lower(),
            _as_text(record.get("description")).lower(),
            _as_text(record.get("impression")).lower(),
            _as_text(record.get("recommendation")).lower(),
        ]
    )
    if any(hint.lower() in haystack for hint in DEFAULT_NORMAL_HINTS):
        return False
    return any(keyword.lower() in haystack for keyword in abnormal_keywords)


def _select_representative(records: list[dict[str, Any]], abnormal_keywords: tuple[str, ...]) -> dict[str, Any]:
    def _score(item: dict[str, Any]) -> tuple[int, int, datetime]:
        abnormal = 1 if _is_abnormal(item, abnormal_keywords) else 0
        has_detail = 1 if (_as_text(item.get("impression")) or _as_text(item.get("recommendation"))) else 0
        dt = _parse_dt(item.get("exam_time")) or datetime.min
        return (abnormal, has_detail, dt)

    return sorted(records, key=_score, reverse=True)[0]


def aggregate_exam_reports(records: list[dict[str, Any]], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """按 EXAM_NO 聚合并保留异常/关键信息摘要。"""
    cfg = options or {}
    max_exam_reports = int(cfg.get("max_exam_reports", DEFAULT_MAX_EXAM_REPORTS) or DEFAULT_MAX_EXAM_REPORTS)
    include_normal_summary = bool(cfg.get("include_normal_summary", False))
    abnormal_keywords = tuple(cfg.get("abnormal_keywords") or DEFAULT_ABNORMAL_KEYWORDS)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records or []:
        row = _with_alias_fields(row)
        exam_no = _as_text(row.get("exam_no"))
        if not exam_no:
            fallback = "|".join(
                [
                    _as_text(row.get("exam_class")),
                    _as_text(row.get("description")),
                    _as_text(row.get("exam_time")),
                ]
            )
            exam_no = fallback or "UNKNOWN"
        grouped.setdefault(exam_no, []).append(row)

    ranked: list[dict[str, Any]] = []
    abnormal_count = 0
    normal_count = 0
    for exam_no, exam_rows in grouped.items():
        chosen = _select_representative(exam_rows, abnormal_keywords)
        abnormal = _is_abnormal(chosen, abnormal_keywords)
        has_detail = bool(_as_text(chosen.get("impression")) or _as_text(chosen.get("recommendation")))

        if abnormal:
            abnormal_count += 1
        else:
            normal_count += 1

        if not abnormal and not has_detail and not include_normal_summary:
            continue

        summary = "；".join(
            part
            for part in [
                _as_text(chosen.get("description")),
                _as_text(chosen.get("impression")),
                _as_text(chosen.get("recommendation")),
            ]
            if part
        )
        ranked.append(
            {
                "exam_no": exam_no,
                "exam_class": _as_text(chosen.get("exam_class")),
                "exam_name": _as_text(chosen.get("exam_name")),
                "exam_time": _as_text(chosen.get("exam_time")),
                "report_time": _as_text(chosen.get("report_time")) or _as_text(chosen.get("exam_time")),
                "description": _as_text(chosen.get("description")),
                "impression": _as_text(chosen.get("impression")),
                "recommendation": _as_text(chosen.get("recommendation")),
                "is_abnormal": abnormal,
                "summary": summary,
            }
        )

    ranked.sort(
        key=lambda item: (
            1 if item.get("is_abnormal") else 0,
            _parse_dt(item.get("exam_time")) or datetime.min,
        ),
        reverse=True,
    )

    selected = ranked[:max_exam_reports]
    omitted_count = max(0, len(ranked) - len(selected))
    return {
        "reports": selected,
        "total_grouped": len(grouped),
        "selected_count": len(selected),
        "abnormal_count": abnormal_count,
        "normal_count": normal_count,
        "omitted_count": omitted_count,
        "normal_summary": {
            "included": include_normal_summary,
            "normal_count": normal_count,
        },
    }
