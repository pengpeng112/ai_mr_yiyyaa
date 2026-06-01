"""文本工具函数。"""
from __future__ import annotations

from typing import Any


def safe_text(value: Any) -> str:
    """None 安全的字符串转换。"""
    if value is None:
        return ""
    return str(value)


def first_non_empty(*values: Any) -> str:
    """返回第一个非空字符串值。"""
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""
