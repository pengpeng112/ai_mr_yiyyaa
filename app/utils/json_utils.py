"""JSON 序列化/反序列化工具函数。"""
from __future__ import annotations

import json
from typing import Any


def safe_json_dumps(value: Any) -> str:
    """序列化为 JSON 字符串，datetime/Decimal 等对象用 str 兜底。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def safe_json_loads(value: Any, default: Any = None) -> Any:
    """安全反序列化 JSON 字符串，失败返回 default。"""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    text = str(value).strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default
