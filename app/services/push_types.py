"""推送执行器共享数据类型和工具函数。"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class PushResult:
    """推送结果数据类"""
    success: int = 0
    failed: int = 0
    skipped: int = 0
    total: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class PushConfig:
    """推送配置数据类"""
    trigger_type: str = "manual"  # auto | manual | retry
    query_date: str = ""
    audit_type_code: str = "progress_vs_nursing"
    audit_type: Any = None
    interval_ms: int = 500
    max_retry: int = 3
    notify_enabled: bool = True


def safe_json_dumps(value: Any) -> str:
    """序列化为 JSON 字符串，datetime/Decimal 等对象用 str 兜底。"""
    return json.dumps(value, ensure_ascii=False, default=str)


def normalize_query_date_for_log(value: str) -> str:
    """标准化落库 query_date，兼容范围格式，避免超出 VARCHAR2(10)。"""
    text = str(value or "").strip()
    if not text:
        return ""

    if "~" in text:
        parts = [p.strip() for p in text.split("~") if p.strip()]
        if parts:
            tail = parts[-1]
            if len(tail) >= 10:
                normalized = tail[:10]
                logger.debug("[push_log] normalize range query_date for db: raw=%s normalized=%s", text, normalized)
                return normalized

    normalized = text[:10]
    if normalized != text:
        logger.debug("[push_log] truncate query_date for db: raw=%s normalized=%s", text, normalized)
    return normalized
