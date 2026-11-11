"""时限与时间计算纯函数（病历时效质控 T3）。

- compute_deadline()：t0 + limit_minutes；workday_only=True 时按调用方传入的
  非工作日集合（节假日+周末，来源待 D9，先由调用方传入）整天跳过，
  时限分钟只在工作日消耗（一个工作日=整天 1440 分钟，夜间不折减）。
- 本模块只做时间运算，不连库、不读配置、不发消息。
- 所有输入时间既接受 datetime 也接受 ISO 字符串（to_datetime 统一规整）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

# workday_only 迭代安全上限：连续跳过超过该天数仍未排完时限，视为非工作日集合异常。
MAX_WORKDAY_SKIP_DAYS = 3660  # ≈10 年，防止病态集合导致死循环


def to_datetime(value: Any) -> datetime | None:
    """把 datetime / ISO 字符串 / 时间戳字符串规整为 datetime；空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"无法解析为时间: {value!r}") from exc
    return parsed


def to_date(value: Any) -> date | None:
    """把 date / datetime / ISO 字符串规整为 date；空值返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    dt = to_datetime(value)
    return dt.date() if dt else None


def to_non_workday_set(values: Iterable[Any] | None) -> set[date]:
    """把调用方传入的节假日/非工作日集合规整为 date 集合（容忍 datetime 与字符串）。"""
    result: set[date] = set()
    for value in values or ():
        day = to_date(value)
        if day is not None:
            result.add(day)
    return result


def compute_deadline(
    t0: Any,
    limit_minutes: int | None,
    *,
    workday_only: bool = False,
    non_workdays: Iterable[Any] | None = None,
) -> datetime | None:
    """计算截止时间：t0 + limit_minutes。

    - limit_minutes 为 None 表示时限待定，返回 None（事件长期停在 PENDING）；
    - limit_minutes=0 表示截止=t0（如 PREOP_SUMMARY 截止=手术开始）；
    - workday_only=True：非工作日整天跳过、不消耗时限；集合由调用方传入
      （引擎不内置周末规则——节假日口径属业务决策，见 D9）。
    """
    start = to_datetime(t0)
    if start is None:
        raise ValueError("t0 不能为空")
    if limit_minutes is None:
        return None
    if isinstance(limit_minutes, bool) or not isinstance(limit_minutes, int):
        raise ValueError(f"limit_minutes 须为整数或 None: {limit_minutes!r}")
    if limit_minutes < 0:
        raise ValueError(f"limit_minutes 不能为负数: {limit_minutes!r}")

    if not workday_only:
        return start + timedelta(minutes=limit_minutes)

    budget = limit_minutes
    skip_set = to_non_workday_set(non_workdays)
    cursor = start
    skipped_days = 0
    while True:
        if cursor.date() in skip_set:
            cursor = datetime.combine(cursor.date(), datetime.min.time()) + timedelta(days=1)
            skipped_days += 1
            if skipped_days > MAX_WORKDAY_SKIP_DAYS:
                raise ValueError("非工作日集合异常：连续多年无工作日，无法计算截止时间")
            continue
        minutes_left_today = int(
            (datetime.combine(cursor.date(), datetime.min.time()) + timedelta(days=1) - cursor).total_seconds() // 60
        )
        if budget <= minutes_left_today:
            return cursor + timedelta(minutes=budget)
        budget -= minutes_left_today
        cursor = datetime.combine(cursor.date(), datetime.min.time()) + timedelta(days=1)


def warn_threshold(deadline: Any, warn_before_minutes: int | None) -> datetime | None:
    """预警窗起点 = 截止时间 - warn_before_minutes；无截止或未配预警返回 None。"""
    dl = to_datetime(deadline)
    if dl is None:
        return None
    if warn_before_minutes is None:
        return None
    if isinstance(warn_before_minutes, bool) or not isinstance(warn_before_minutes, int) or warn_before_minutes < 0:
        raise ValueError(f"warn_before_minutes 须为非负整数或 None: {warn_before_minutes!r}")
    return dl - timedelta(minutes=warn_before_minutes)


def overdue_minutes(now: Any, deadline: Any) -> int:
    """now 超过 deadline 的分钟数；未超过或无截止返回 0。"""
    current = to_datetime(now)
    dl = to_datetime(deadline)
    if current is None or dl is None:
        return 0
    delta = current - dl
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 60)
