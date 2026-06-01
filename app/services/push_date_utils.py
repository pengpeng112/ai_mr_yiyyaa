"""推送日期解析与范围工具函数。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import HTTPException


def parse_date(date_text: str) -> date:
    """解析 YYYY-MM-DD 格式日期字符串。"""
    return datetime.strptime(date_text, "%Y-%m-%d").date()


def coerce_to_date(value: Any) -> date | None:
    """将 Oracle/PG 返回的日期字段尽量解析为 date。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass

    head = text[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except Exception:
            pass

    return None


def resolve_query_dates(date_from: str | None, date_to: str | None, query_date: str | None) -> list[str]:
    """从请求参数解析查询日期列表。返回 YYYY-MM-DD 字符串列表。"""
    if date_from and date_to:
        start_date = parse_date(date_from)
        end_date = parse_date(date_to)
    elif query_date:
        start_date = parse_date(query_date)
        end_date = start_date
    else:
        return []

    span_days = (end_date - start_date).days + 1
    if span_days <= 0:
        raise HTTPException(status_code=422, detail="date_to must be >= date_from")
    if span_days > 120:
        raise HTTPException(status_code=422, detail="date range cannot exceed 120 days")

    return [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(span_days)]


def date_label(query_dates: list[str]) -> str:
    """将日期列表转换为标签字符串。"""
    if not query_dates:
        return "ALL"
    if len(query_dates) == 1:
        return query_dates[0]
    return f"{query_dates[0]}~{query_dates[-1]}"


def record_date_in_range(record: dict, field_candidates: list[str], date_from: str, date_to: str) -> bool:
    """判断记录的日期字段是否在指定范围内。"""
    if not field_candidates:
        return True
    start = parse_date(date_from)
    end = parse_date(date_to)
    for field_name in field_candidates:
        parsed = coerce_to_date(record.get(field_name))
        if parsed is None:
            continue
        if start <= parsed <= end:
            return True
    return False
