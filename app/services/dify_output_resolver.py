"""
Dify 输出解析模块 —— 从 dify_pusher.py 拆分，负责 extra_inputs 清洗和 output key 解析。
"""
import logging
from typing import Any

# 专用审计日志器：与 dify_pusher.py 使用同一个 logger name
audit_logger = logging.getLogger("audit.dify")


def sanitize_extra_inputs(extra: Any, input_var: str = "mr_txt") -> dict:
    """Sanitize extra_inputs to avoid payload pollution.

    - Only allow dict
    - Filter reserved top-level keys used by Dify request envelope
    - Flatten accidental nested `inputs` dict into same level
    """
    if not isinstance(extra, dict):
        return {}

    reserved = {"inputs", "response_mode", "user", "files"}
    main_input_var = str(input_var or "mr_txt").strip() or "mr_txt"
    cleaned: dict = {}
    for key, value in extra.items():
        k = str(key or "").strip()
        if not k:
            continue
        if k in reserved or k == main_input_var:
            continue
        cleaned[k] = value

    nested_inputs = extra.get("inputs")
    if isinstance(nested_inputs, dict):
        for key, value in nested_inputs.items():
            k = str(key or "").strip()
            if not k or k in reserved or k == main_input_var:
                continue
            if k not in cleaned:
                cleaned[k] = value

    return cleaned


def _sanitize_extra_inputs(extra: Any) -> dict:
    return sanitize_extra_inputs(extra)


def _merge_safe_extra_inputs(input_var: str, payload_input: Any, config: dict) -> tuple[dict, list[str]]:
    """Merge extra_inputs without allowing overwrite of the main workflow input."""
    inputs = {input_var: payload_input}
    extra = sanitize_extra_inputs(config.get("extra_inputs", {}), input_var)
    ignored_keys: list[str] = []
    for key, value in extra.items():
        if key == input_var:
            ignored_keys.append(key)
            continue
        inputs[key] = value
    return inputs, ignored_keys


def _resolve_output_value(outputs: dict, output_key: str) -> Any:
    raw_value = outputs.get(output_key)
    if raw_value is not None:
        return raw_value
    for fallback_key in ["result", "output", "text", "analysis"]:
        raw_value = outputs.get(fallback_key)
        if raw_value is not None:
            audit_logger.warning(
                "[Dify输出键不匹配] 期望 output_key='%s' 未命中, 实际命中 fallback='%s', "
                "outputs_keys=%s — 请在 Dify 工作流中将 End 节点输出变量改为 '%s'",
                output_key, fallback_key, list(outputs.keys()), output_key,
            )
            return raw_value
    if len(outputs) == 1:
        only_key = list(outputs.keys())[0]
        audit_logger.warning(
            "[Dify输出键不匹配] 期望 output_key='%s' 未命中, 唯一 key='%s', "
            "outputs_keys=%s — 请在 Dify 工作流中将 End 节点输出变量改为 '%s'",
            output_key, only_key, list(outputs.keys()), output_key,
        )
        return list(outputs.values())[0]
    return None


def _load_output_root(outputs: dict, output_key: str) -> Any:
    from app.services.dify_json_parser import _load_json_with_tolerance

    raw_value = _resolve_output_value(outputs, output_key)
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        try:
            return _load_json_with_tolerance(raw_value)
        except Exception:
            return raw_value
    return raw_value
