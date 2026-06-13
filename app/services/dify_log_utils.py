"""
Dify 日志工具模块 —— 从 dify_pusher.py 拆分，纯函数无副作用。
"""
import logging
import os
from typing import Any

from app.utils.json_utils import safe_json_dumps as _safe_json_dumps


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_full_debug_log_enabled(config: dict) -> bool:
    """完整 Dify 请求/响应日志必须显式开启，避免病历内容默认落盘。"""
    return _truthy((config or {}).get("full_debug_log")) or _truthy(os.getenv("DIFY_FULL_DEBUG_LOG"))


def _truncate_for_log(value: Any, limit: int = 800) -> str:
    text = value if isinstance(value, str) else _safe_json_dumps(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated, total_chars={len(text)})"


def _summarize_dify_payload(payload: dict, input_var: str) -> dict:
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    main_value = inputs.get(input_var) if isinstance(inputs, dict) else None
    extra_keys = [k for k in inputs.keys() if k != input_var] if isinstance(inputs, dict) else []
    extra_preview = {}
    if isinstance(inputs, dict) and "mr_type" in inputs:
        extra_preview["mr_type"] = inputs.get("mr_type")
    return {
        "response_mode": payload.get("response_mode"),
        "user": payload.get("user"),
        "input_variable": input_var,
        "main_input_type": type(main_value).__name__,
        "main_input_size": len(_safe_json_dumps(main_value)) if isinstance(main_value, (dict, list)) else len(str(main_value or "")),
        "main_input_preview": _truncate_for_log(main_value, 300),
        "extra_input_keys": extra_keys,
        "extra_inputs_preview": extra_preview,
    }


def _summarize_dify_outputs(outputs: Any) -> dict:
    if not isinstance(outputs, dict):
        return {
            "output_type": type(outputs).__name__,
            "output_size": len(_safe_json_dumps(outputs)),
            "output_preview": _truncate_for_log(outputs, 500),
        }
    return {
        "output_keys": list(outputs.keys()),
        "output_sizes": {str(k): len(_safe_json_dumps(v)) for k, v in outputs.items()},
        "output_preview": {str(k): _truncate_for_log(v, 300) for k, v in outputs.items()},
    }
