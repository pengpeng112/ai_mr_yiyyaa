"""病程/护理上下文窗口选择器（Task 8）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.services.source_field_contract import normalize_date_to_ymd


DEFAULT_MAX_PROGRESS_RECORDS = 20
DEFAULT_MAX_NURSING_RECORDS = 20
DEFAULT_MAX_CHARS = 4000


def _as_text(value: Any) -> str:
    return str(value or "").strip()


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


def _resolve_record_date(record: dict[str, Any], time_keys: tuple[str, ...], fallback_query_date: str) -> str:
    for key in time_keys:
        normalized = normalize_date_to_ymd(record.get(key))
        if normalized:
            return normalized
    normalized = normalize_date_to_ymd(record.get("audit_date"))
    if normalized:
        return normalized
    return normalize_date_to_ymd(fallback_query_date)


def _resolve_sort_time(record: dict[str, Any], time_keys: tuple[str, ...]) -> datetime:
    for key in time_keys:
        parsed = _parse_datetime(record.get(key))
        if parsed:
            return parsed
    return datetime.min


def _normalize_base_days(query_date: str, raw_base_dates: Any) -> set[str]:
    base_days: set[str] = set()
    if isinstance(raw_base_dates, (list, tuple, set)):
        for item in raw_base_dates:
            normalized = normalize_date_to_ymd(item)
            if normalized:
                base_days.add(normalized)
    base_day = normalize_date_to_ymd(query_date)
    if not base_days and base_day:
        base_days.add(base_day)
    return base_days


def _normalize_base_events(raw_base_events: Any) -> list[datetime]:
    events: list[datetime] = []
    if not isinstance(raw_base_events, (list, tuple, set)):
        return events
    seen: set[datetime] = set()
    for item in raw_base_events:
        parsed = _parse_datetime(item)
        if parsed and parsed not in seen:
            seen.add(parsed)
            events.append(parsed)
    events.sort()
    return events


def _match_record_after_event(record_time: datetime, base_events: list[datetime]) -> datetime | None:
    matched: datetime | None = None
    record_day = record_time.strftime("%Y-%m-%d")
    for event_time in base_events:
        if event_time.strftime("%Y-%m-%d") != record_day:
            continue
        if record_time <= event_time:
            continue
        if matched is None or event_time > matched:
            matched = event_time
    return matched


def _name_allowed(record_name: str, include_names: set[str], exclude_names: set[str]) -> bool:
    if include_names and record_name not in include_names:
        return False
    if exclude_names and record_name in exclude_names:
        return False
    return True


def _truncate_records(
    records: list[dict[str, Any]],
    max_records: int,
    max_chars: int,
    content_key: str = "content",
) -> tuple[list[dict[str, Any]], bool]:
    selected = records[:max_records]
    if not selected:
        return [], False

    rendered: list[dict[str, Any]] = []
    char_budget = max_chars
    truncated = len(records) > max_records
    for row in selected:
        item = dict(row)
        content = _as_text(item.get(content_key))
        if char_budget <= 0:
            if content:
                item[content_key] = ""
                item["content_truncated"] = True
                truncated = True
            rendered.append(item)
            continue

        if len(content) > char_budget:
            item[content_key] = content[:char_budget]
            item["content_truncated"] = True
            truncated = True
            char_budget = 0
        else:
            item["content_truncated"] = False
            char_budget -= len(content)
        rendered.append(item)

    return rendered, truncated


def select_progress_nursing_context(
    progress_records: list[dict[str, Any]],
    nursing_records: list[dict[str, Any]],
    query_date: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """选择病程同日+随访窗口与护理同日上下文，并控制数量/字符。"""
    cfg = options or {}
    progress_followup_days = int(cfg.get("progress_followup_days", 1) or 1)
    max_progress_records = int(cfg.get("max_progress_records", DEFAULT_MAX_PROGRESS_RECORDS) or DEFAULT_MAX_PROGRESS_RECORDS)
    max_nursing_records = int(cfg.get("max_nursing_records", DEFAULT_MAX_NURSING_RECORDS) or DEFAULT_MAX_NURSING_RECORDS)
    max_progress_chars = int(cfg.get("max_progress_chars", DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS)
    max_nursing_chars = int(cfg.get("max_nursing_chars", DEFAULT_MAX_CHARS) or DEFAULT_MAX_CHARS)

    progress_include = {str(name).strip() for name in cfg.get("progress_include_names", []) if str(name).strip()}
    progress_exclude = {str(name).strip() for name in cfg.get("progress_exclude_names", []) if str(name).strip()}
    nursing_include = {str(name).strip() for name in cfg.get("nursing_include_names", []) if str(name).strip()}
    nursing_exclude = {str(name).strip() for name in cfg.get("nursing_exclude_names", []) if str(name).strip()}

    base_events = _normalize_base_events(cfg.get("base_events"))
    require_record_after_base_time = bool(cfg.get("require_record_after_base_time", False)) and bool(base_events)
    base_days = {event_time.strftime("%Y-%m-%d") for event_time in base_events} or _normalize_base_days(query_date, cfg.get("base_dates"))
    if not base_days:
        return {
            "progress_context": {"records": [], "truncated": False, "followup_count": 0},
            "nursing_context": {"records": [], "truncated": False},
        }

    allowed_progress_days: set[str] = set()
    if require_record_after_base_time:
        allowed_progress_days = set(base_days)
    else:
        for base_day in base_days:
            base_dt = datetime.strptime(base_day, "%Y-%m-%d")
            allowed_progress_days.update(
                (base_dt + timedelta(days=delta)).strftime("%Y-%m-%d")
                for delta in range(max(progress_followup_days, 0) + 1)
            )

    progress_time_keys = ("event_time", "record_time", "title_time", "create_time", "sign_time")
    nursing_time_keys = ("event_time", "record_time", "nurse_time")

    progress_candidates: list[dict[str, Any]] = []
    for raw in progress_records or []:
        record_name = _as_text(raw.get("record_name"))
        if not _name_allowed(record_name, progress_include, progress_exclude):
            continue
        record_day = _resolve_record_date(raw, progress_time_keys, query_date)
        if record_day not in allowed_progress_days:
            continue
        matched_event_time: datetime | None = None
        if require_record_after_base_time:
            record_time = _resolve_sort_time(raw, progress_time_keys)
            if record_time == datetime.min:
                continue
            matched_event_time = _match_record_after_event(record_time, base_events)
            if matched_event_time is None:
                continue
        item = dict(raw)
        item["context_date"] = record_day
        item["is_followup"] = record_day not in base_days
        if matched_event_time:
            item["matched_event_time"] = matched_event_time.strftime("%Y-%m-%d %H:%M:%S")
        progress_candidates.append(item)

    progress_candidates.sort(key=lambda row: _resolve_sort_time(row, progress_time_keys), reverse=True)
    progress_selected, progress_truncated = _truncate_records(
        progress_candidates,
        max_records=max_progress_records,
        max_chars=max_progress_chars,
        content_key="content",
    )

    nursing_candidates: list[dict[str, Any]] = []
    for raw in nursing_records or []:
        record_name = _as_text(raw.get("record_name"))
        if not _name_allowed(record_name, nursing_include, nursing_exclude):
            continue
        record_day = _resolve_record_date(raw, nursing_time_keys, query_date)
        if record_day not in base_days:
            continue
        matched_event_time = None
        if require_record_after_base_time:
            record_time = _resolve_sort_time(raw, nursing_time_keys)
            if record_time == datetime.min:
                continue
            matched_event_time = _match_record_after_event(record_time, base_events)
            if matched_event_time is None:
                continue
        item = dict(raw)
        item["context_date"] = record_day
        if matched_event_time:
            item["matched_event_time"] = matched_event_time.strftime("%Y-%m-%d %H:%M:%S")
        nursing_candidates.append(item)

    nursing_candidates.sort(key=lambda row: _resolve_sort_time(row, nursing_time_keys), reverse=True)
    nursing_selected, nursing_truncated = _truncate_records(
        nursing_candidates,
        max_records=max_nursing_records,
        max_chars=max_nursing_chars,
        content_key="content",
    )

    return {
        "progress_context": {
            "records": progress_selected,
            "total_selected": len(progress_selected),
            "followup_count": sum(1 for item in progress_selected if item.get("is_followup")),
            "truncated": progress_truncated,
        },
        "nursing_context": {
            "records": nursing_selected,
            "total_selected": len(nursing_selected),
            "truncated": nursing_truncated,
        },
    }
