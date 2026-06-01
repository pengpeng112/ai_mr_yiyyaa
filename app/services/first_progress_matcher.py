"""术后首次病程匹配器（Task 14/16）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.source_field_contract import normalize_date_to_ymd


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _parse_int(value: Any) -> int | None:
    text = _as_text(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_datetime(raw: Any) -> datetime | None:
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


def _contains_any(text: str, keywords: list[str]) -> bool:
    lower_text = text.lower()
    return any(str(keyword).strip().lower() in lower_text for keyword in keywords if str(keyword).strip())


def _within_day_window(base_dates: list[str], record_date: str, window_days: int) -> bool:
    if not base_dates:
        return True
    if not record_date:
        return False
    try:
        record_dt = datetime.strptime(record_date, "%Y-%m-%d")
    except ValueError:
        return False
    for base in base_dates:
        try:
            base_dt = datetime.strptime(base, "%Y-%m-%d")
        except ValueError:
            continue
        delta_days = (record_dt - base_dt).days
        if 0 <= delta_days <= window_days:
            return True
    return False


def select_first_progress_record(
    surgeries: list[dict[str, Any]],
    progress_records: list[dict[str, Any]],
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按筛选与排序规则挑选首次病程，支持兜底与 warnings。"""
    cfg = options or {}
    record_name_include = list(cfg.get("record_name_include") or ["术后首次病程记录"])
    record_type_include = list(cfg.get("record_type_include") or [])
    rn_priority = [int(x) for x in (cfg.get("rn_priority") or [1])]
    time_window_days = int(cfg.get("time_window_days", 3) or 3)

    surgery_dates = [
        normalize_date_to_ymd(item.get("operation_date"))
        for item in (surgeries or [])
        if normalize_date_to_ymd(item.get("operation_date"))
    ]

    warnings: list[str] = []
    candidates: list[dict[str, Any]] = []
    for row in progress_records or []:
        record_name = _as_text(row.get("record_name"))
        record_type = _as_text(row.get("record_type"))
        if record_name_include and not _contains_any(record_name, record_name_include):
            continue
        if record_type_include and not _contains_any(record_type, record_type_include):
            continue
        record_day = normalize_date_to_ymd(row.get("title_time") or row.get("record_date") or row.get("event_time"))
        if not _within_day_window(surgery_dates, record_day, time_window_days):
            continue
        candidates.append(dict(row))

    if not candidates:
        warnings.append("no_post_op_first_progress")
        fallback = []
        for row in progress_records or []:
            row_copy = dict(row)
            record_day = normalize_date_to_ymd(row_copy.get("title_time") or row_copy.get("record_date") or row_copy.get("event_time"))
            if _within_day_window(surgery_dates, record_day, time_window_days):
                fallback.append(row_copy)
        candidates = fallback or [dict(row) for row in (progress_records or [])]

    if not candidates:
        warnings.append("no_first_progress_candidates")
        return {
            "selected_progress": None,
            "candidate_count": 0,
            "match_warnings": warnings,
        }

    def _sort_key(item: dict[str, Any]) -> tuple[int, datetime, datetime, datetime]:
        rn = _parse_int(item.get("rn"))
        rn_rank = rn_priority.index(rn) if rn in rn_priority else len(rn_priority)
        title_dt = _parse_datetime(item.get("title_time") or item.get("event_time")) or datetime.max
        create_dt = _parse_datetime(item.get("created_at")) or datetime.max
        sign_dt = _parse_datetime(item.get("signed_at")) or datetime.max
        return (rn_rank, title_dt, create_dt, sign_dt)

    ordered = sorted(candidates, key=_sort_key)
    selected = ordered[0]
    if len(ordered) > 1:
        warnings.append("multiple_first_progress_candidates")

    if surgery_dates:
        selected_date = normalize_date_to_ymd(selected.get("title_time") or selected.get("record_date") or selected.get("event_time"))
        if selected_date and not _within_day_window(surgery_dates, selected_date, time_window_days):
            warnings.append("operation_progress_date_mismatch")

    return {
        "selected_progress": selected,
        "candidate_count": len(ordered),
        "match_warnings": warnings,
    }
