"""
Dify Workflow API 推送模块
增强功能：结构化响应解析 + 详细请求/响应日志
"""
import json
import logging
import os
import re
import time
from typing import Any
import requests

from app.config import normalize_dify_base_url
from app.services.response_path_utils import apply_response_paths as _apply_response_paths
from app.services import dify_result_normalizer as _norm

logger = logging.getLogger(__name__)

# 专用审计日志器：记录 Dify 请求/响应详情
audit_logger = logging.getLogger("audit.dify")


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


def apply_response_paths(raw: Any, paths: dict | None) -> dict:
    """兼容入口：委托给 response_path_utils.apply_response_paths。"""
    return _apply_response_paths(raw, paths)


def _resolve_output_value(outputs: dict, output_key: str) -> Any:
    raw_value = outputs.get(output_key)
    if raw_value is not None:
        return raw_value
    for fallback_key in ["result", "output", "text", "analysis"]:
        raw_value = outputs.get(fallback_key)
        if raw_value is not None:
            return raw_value
    if len(outputs) == 1:
        return list(outputs.values())[0]
    return None


def _load_output_root(outputs: dict, output_key: str) -> Any:
    raw_value = _resolve_output_value(outputs, output_key)
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        try:
            return _load_json_with_tolerance(raw_value)
        except Exception:
            return raw_value
    return raw_value


def push_to_dify(
    payload_input: Any,
    config: dict,
    patient_id: str,
    dify_config_override: dict | None = None,
    response_paths: dict | None = None,
    parse_strategy: str | None = None,
) -> dict:
    """
    调用 Dify Workflow API（Blocking 模式）进行 AI 一致性分析

    Args:
        payload_input: 结构化 JSON 或兼容旧版的文本内容
        config: Dify 配置 dict (base_url, api_key, workflow_input_variable, workflow_output_key, ...)
        patient_id: 患者ID

    Returns:
        dict with status, workflow_run_id, task_id, result, parsed_output, elapsed_ms, etc.
    """
    effective_config = dict(config or {})
    if dify_config_override:
        effective_config.update({k: v for k, v in dict(dify_config_override).items() if v is not None})

    base_url = normalize_dify_base_url(effective_config["base_url"])
    url = f"{base_url}/workflows/run"
    headers = {
        "Authorization": f"Bearer {effective_config['api_key']}",
        "Content-Type": "application/json",
    }
    # 构建 inputs：主变量 + 额外静态参数合并
    input_var = effective_config.get("workflow_input_variable", "mr_txt")
    effective_config["extra_inputs"] = sanitize_extra_inputs(effective_config.get("extra_inputs", {}), input_var)
    inputs, ignored_extra_keys = _merge_safe_extra_inputs(input_var, payload_input, effective_config)

    payload = {
        "inputs": inputs,
        "response_mode": "blocking",
        "user": effective_config.get("user_identifier", f"auto-{patient_id}"),
    }
    timeout = effective_config.get("timeout_seconds", 90)
    output_key = effective_config.get("workflow_output_key", "aa")
    target_name = str(effective_config.get("name") or "")
    target_base_url = base_url

    payload_size = len(_safe_json_dumps(payload_input)) if isinstance(payload_input, (dict, list)) else len(str(payload_input or ""))

    # 记录请求日志
    audit_logger.info(
        f"[Dify请求] patient_id={patient_id}, url={url}, "
        f"target_name={target_name}, "
        f"target_base_url={target_base_url}, "
        f"input_variable={input_var}, output_key={output_key}, "
        f"payload_type={type(payload_input).__name__}, payload_size={payload_size}, extra_inputs_keys={list(effective_config.get('extra_inputs', {}).keys()) if isinstance(effective_config.get('extra_inputs', {}), dict) else []}, ignored_extra_keys={ignored_extra_keys}, "
        f"timeout={timeout}s"
    )
    if _is_full_debug_log_enabled(effective_config):
        audit_logger.debug("[Dify请求JSON] patient_id=%s payload=%s", patient_id, _safe_json_dumps(payload))
    else:
        audit_logger.debug(
            "[Dify请求摘要] patient_id=%s payload=%s",
            patient_id,
            _safe_json_dumps(_summarize_dify_payload(payload, input_var)),
        )
    if ignored_extra_keys:
        audit_logger.warning(
            "[Dify请求] ignored extra_inputs keys conflicting with main input: patient_id=%s target_name=%s input_variable=%s ignored=%s",
            patient_id,
            target_name,
            input_var,
            ignored_extra_keys,
        )

    start_time = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        outputs = data.get("data", {}).get("outputs", {})
        elapsed = int((time.time() - start_time) * 1000)

        # 记录响应日志
        audit_logger.info(
            f"[Dify响应] patient_id={patient_id}, status=success, elapsed={elapsed}ms, "
            f"target_name={target_name}, "
            f"target_base_url={target_base_url}, "
            f"workflow_run_id={data.get('workflow_run_id', '')}, "
            f"task_id={data.get('task_id', '')}, "
            f"output_keys={list(outputs.keys())}"
        )
        if _is_full_debug_log_enabled(effective_config):
            audit_logger.debug(
                "[Dify响应JSON] patient_id=%s outputs=%s",
                patient_id,
                _safe_json_dumps(outputs),
            )
        else:
            audit_logger.debug(
                "[Dify响应摘要] patient_id=%s outputs=%s",
                patient_id,
                _safe_json_dumps(_summarize_dify_outputs(outputs)),
            )

        # 结构化解析 Dify 输出
        strategy = str(parse_strategy or "hybrid").strip() or "hybrid"
        if strategy == "raw_only":
            parsed = {
                "version": "1.0",
                "dimensions": [],
                "overall_conclusion": "",
                "focus_items": [],
                "audit_date": "",
                "patient_name": "",
                "patient_id": "",
                "visit_number": "",
                "dept": "",
                "inconsistency": False,
                "severity": "",
                "risk_score": 0,
                "reasoning_brief": "",
                "parse_success": False,
                "parse_error": "",
                "parse_warning": "",
                "raw_text": "",
                "alert_level": "",
                "closure_hours": 0,
                "push_strategy": "",
                "outcome_bucket": "",
                "overall_qc_summary": "",
                "fallback_inference": False,
            }
        else:
            parsed = parse_dify_structured_output(outputs, output_key)

        path_values = apply_response_paths(_load_output_root(outputs, output_key), response_paths)
        if path_values:
            parsed.update(path_values)
            try:
                _post_process_result(parsed)
            except Exception as exc:
                audit_logger.warning("[Dify路径后处理] patient_id=%s error=%s", patient_id, exc)

        return {
            "status": "success",
            "workflow_run_id": data.get("workflow_run_id", ""),
            "task_id": data.get("task_id", ""),
            "result": outputs,
            "raw_response": _load_output_root(outputs, output_key),
            "parsed_output": parsed,
            "elapsed_ms": elapsed,
            "inconsistency": parsed.get("inconsistency", False),
            "severity": parsed.get("severity", ""),
            "risk_score": parsed.get("risk_score", 0),
            "parse_error": parsed.get("parse_error", ""),
        }
    except requests.exceptions.Timeout:
        elapsed = int((time.time() - start_time) * 1000)
        audit_logger.error(f"[Dify超时] patient_id={patient_id}, target_name={target_name}, target_base_url={target_base_url}, elapsed={elapsed}ms, timeout={timeout}s")
        logger.error(f"Dify 请求超时 (patient_id={patient_id})", exc_info=True)
        return {
            "status": "failed",
            "error": f"请求超时（{timeout}s）",
            "elapsed_ms": elapsed,
        }
    except requests.exceptions.HTTPError as e:
        elapsed = int((time.time() - start_time) * 1000)
        error_detail = ""
        try:
            error_detail = resp.text[:500]
        except Exception:
            pass
        audit_logger.error(
            f"[Dify HTTP错误] patient_id={patient_id}, target_name={target_name}, target_base_url={target_base_url}, status_code={resp.status_code}, "
            f"elapsed={elapsed}ms, detail={error_detail}"
        )
        logger.error(f"Dify HTTP 错误: {e} — {error_detail}", exc_info=True)
        return {
            "status": "failed",
            "error": f"HTTP {resp.status_code}: {error_detail}",
            "elapsed_ms": elapsed,
        }
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        audit_logger.error(f"[Dify异常] patient_id={patient_id}, target_name={target_name}, target_base_url={target_base_url}, elapsed={elapsed}ms, error={e}")
        logger.error(f"Dify 推送异常: {e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "elapsed_ms": elapsed,
        }


def test_dify_connection(config: dict) -> dict:
    """测试 Dify 连通性"""
    base_url = normalize_dify_base_url(config["base_url"])
    url = f"{base_url}/workflows/run"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    input_var = config.get("workflow_input_variable", "mr_txt")
    payload = {
        "inputs": {input_var: "【测试报文】系统连通性测试，请忽略。"},
        "response_mode": "blocking",
        "user": "system-test",
    }
    audit_logger.info(f"[Dify连接测试] url={url}, input_variable={input_var}")

    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            audit_logger.info(f"[Dify连接测试] 成功, latency={latency}ms")
            return {"status": "up", "latency_ms": latency}
        else:
            detail = resp.text[:200]
            audit_logger.warning(f"[Dify连接测试] 失败, HTTP {resp.status_code}, detail={detail}")
            return {"status": "down", "latency_ms": latency, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        audit_logger.error(f"[Dify连接测试] 异常: {e}")
        return {"status": "down", "message": str(e)}


def parse_dify_structured_output(outputs: dict, output_key: str = "aa") -> dict:
    """
    结构化解析 Dify Workflow 返回的输出

    Dify 返回格式示例:
    outputs = {
        "aa": '{"患者姓名":"XX","核查结果":[{"维度":"诊断一致性","状态":"✅","说明":"..."}],"总体结论":"...","重点关注项":[...]}'
    }

    Returns:
        {
            "dimensions": [{"dimension":..., "status":..., "medical_content":..., "nursing_content":..., "explanation":...}],
            "overall_conclusion": "...",
            "focus_items": [...],
            "audit_date": "...",
            "patient_name": "...",
            "inconsistency": bool,
            "severity": "high|medium|low",
            "parse_success": True/False,
            "raw_text": "..."  # 原始文本（解析失败时保留）
        }
    """
    result = {
        "version": "1.0",
        "dimensions": [],
        "overall_conclusion": "",
        "focus_items": [],
        "audit_date": "",
        "patient_name": "",
        "patient_id": "",
        "visit_number": "",
        "dept": "",
        "inconsistency": False,
        "severity": "",
        "risk_score": 0,
        "reasoning_brief": "",
        "parse_success": False,
        "parse_error": "",
        "parse_warning": "",
        "raw_text": "",
        "alert_level": "",
        "closure_hours": 0,
        "push_strategy": "",
        "outcome_bucket": "",
        "overall_qc_summary": "",
        "fallback_inference": False,
    }

    try:
        # 1. 获取输出值：优先使用配置的 output_key，fallback 到常见 key
        raw_value = outputs.get(output_key)
        if raw_value is None:
            for fallback_key in ["result", "output", "text", "analysis"]:
                raw_value = outputs.get(fallback_key)
                if raw_value is not None:
                    audit_logger.info(f"[Dify解析] output_key='{output_key}'未找到，使用fallback='{fallback_key}'")
                    break

        if raw_value is None:
            # 如果只有一个 key，直接用它
            if len(outputs) == 1:
                raw_value = list(outputs.values())[0]
                audit_logger.info(f"[Dify解析] 使用唯一 output key='{list(outputs.keys())[0]}'")
            else:
                audit_logger.warning(f"[Dify解析] 未找到 output_key='{output_key}'，outputs keys={list(outputs.keys())}")
                result["raw_text"] = json.dumps(outputs, ensure_ascii=False)
                return result

        # 2. 解析 JSON
        if isinstance(raw_value, str):
            result["raw_text"] = raw_value
            parsed = _load_json_with_tolerance(raw_value)
        elif isinstance(raw_value, dict):
            result["raw_text"] = json.dumps(raw_value, ensure_ascii=False)
            parsed = raw_value
        else:
            result["raw_text"] = str(raw_value)
            audit_logger.warning(f"[Dify解析] 输出值类型不支持: {type(raw_value)}")
            return result

        if isinstance(parsed, list):
            parsed = {"dimensions": parsed}

        parsed = _normalize_parsed_root(parsed)

        if _looks_like_new_schema(parsed):
            _parse_new_schema(parsed, result)
        else:
            _parse_legacy_schema(parsed, result)

        _post_process_result(result)
        _append_output_quality_warnings(result)

        # JSON 解析成功但关键内容为空（如 Dify 输出被截断），标记为解析失败
        if not result.get("dimensions") and not str(result.get("overall_conclusion") or "").strip():
            result["parse_success"] = False
            result["parse_error"] = result.get("parse_error") or "parsed_json_missing_dimensions_and_conclusion"
            _append_parse_warning(result, "empty_after_json_parse")
            _fallback_keyword_match(result)
            audit_logger.warning(
                "[Dify解析] JSON 解析成功但关键内容为空: patient_id=%s dimensions=%s conclusion='%s'",
                result.get("patient_id", ""),
                len(result.get("dimensions") or []),
                str(result.get("overall_conclusion") or "")[:100],
            )
        else:
            result["parse_success"] = True
            audit_logger.info(
                f"[Dify解析] 成功, 维度数={len(result['dimensions'])}, "
                f"inconsistency={result['inconsistency']}, severity={result['severity']}"
            )

    except json.JSONDecodeError as e:
        audit_logger.warning(f"[Dify解析] JSON 解析失败: {e}, raw_value前200字符: {str(raw_value)[:200]}")
        result["raw_text"] = str(raw_value) if raw_value else ""
        result["parse_error"] = str(e)
        _append_parse_warning(result, "json_parse_failed_fallback")
        # 回退到旧版关键字匹配
        _fallback_keyword_match(result)

    except Exception as e:
        audit_logger.error(f"[Dify解析] 异常: {e}")
        result["raw_text"] = str(raw_value) if raw_value else ""
        result["parse_error"] = str(e)
        _append_parse_warning(result, "parse_exception_fallback")
        _fallback_keyword_match(result)

    return result


def _fallback_keyword_match(result: dict):
    """
    回退方案：当结构化解析失败时，用关键字匹配判断不一致
    """
    text = result.get("raw_text", "").lower()
    if not text:
        return

    _append_parse_warning(result, "fallback_keyword_match")

    explicit_inconsistency = bool(re.search(r'["\'](?:has_)?inconsistency["\']\s*:\s*true\b', text))
    negative_inconsistency = any(
        phrase in text
        for phrase in ["无不一致", "不存在不一致", "未见不一致", "没有不一致", "无实质性不一致"]
    )
    keyword_inconsistency = any(
        phrase in text
        for phrase in ["存在不一致", "发现不一致", "有不一致", "不一致问题", "inconsistent", "mismatch", "conflict", "❌"]
    )

    if explicit_inconsistency or (keyword_inconsistency and not negative_inconsistency):
        result["inconsistency"] = True
        if "严重" in text or "high" in text or "重大" in text:
            result["severity"] = "high"
        elif "中等" in text or "medium" in text:
            result["severity"] = "medium"
        else:
            result["severity"] = "low"
        result["fallback_inference"] = True
        if not result.get("overall_conclusion"):
            result["overall_conclusion"] = "Dify 输出未能解析为结构化 JSON，已根据关键词回退判断存在不一致。"
        if not result.get("reasoning_brief"):
            raw_text = str(result.get("raw_text", "")).strip()
            result["reasoning_brief"] = raw_text[:200] if raw_text else result["overall_conclusion"]
    audit_logger.info(
        f"[Dify解析] 回退关键字匹配: inconsistency={result['inconsistency']}, severity={result['severity']}, fallback={result['fallback_inference']}"
    )


def _append_parse_warning(result: dict, warning: str):
    warnings = [item.strip() for item in str(result.get("parse_warning") or "").split(";") if item.strip()]
    if warning not in warnings:
        warnings.append(warning)
    result["parse_warning"] = ";".join(warnings)


def _append_output_quality_warnings(result: dict):
    missing_patient_fields = [
        field for field in ["patient_id", "patient_name", "audit_date"]
        if not str(result.get(field) or "").strip()
    ]
    if missing_patient_fields:
        _append_parse_warning(result, "patient_summary_empty")
        audit_logger.warning(
            "[Dify解析] patient_summary 关键字段为空: fields=%s raw_text前200字符=%s",
            missing_patient_fields,
            str(result.get("raw_text") or "")[:200],
        )

    if result.get("inconsistency") and not result.get("risk_score"):
        _append_parse_warning(result, "inconsistency_without_risk_score")


def _load_json_with_tolerance(raw_text: str) -> Any:
    text = str(raw_text or "").strip()
    if not text:
        raise json.JSONDecodeError("empty text", text, 0)

    candidates = []
    for candidate in [
        text,
        _strip_code_fence(text),
        _extract_json_substring(text),
        _extract_json_substring(_strip_code_fence(text)),
    ]:
        original = str(candidate or "").strip()
        if original and original not in candidates:
            candidates.append(original)
        normalized = _normalize_json_text(original)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    last_error = None
    for candidate in candidates:
        try:
            return json.loads(candidate, strict=False)
        except json.JSONDecodeError as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise json.JSONDecodeError("unable to extract json", text, 0)


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_json_substring(text: str) -> str:
    if not text:
        return ""
    starts = [idx for idx in [text.find("{"), text.find("[")] if idx >= 0]
    if not starts:
        return ""
    start = min(starts)
    opening = text[start]
    closing = "}" if opening == "{" else "]"
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == opening:
            depth += 1
        elif ch == closing:
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return text[start:].strip()


def _normalize_json_text(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    replacements = {
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "，": ",",
        "：": ":",
    }
    for old, new in replacements.items():
        normalized = normalized.replace(old, new)
    normalized = normalized.strip("` \n\r\t")
    return normalized


def _normalize_parsed_root(parsed: dict) -> dict:
    if not isinstance(parsed, dict):
        return {}

    root = dict(parsed)

    if "patient_summary" not in root and any(key in root for key in ["患者姓名", "患者ID", "住院号", "核查日期"]):
        root["patient_summary"] = {
            "patient_id": root.get("患者ID", root.get("patient_id", "")),
            "visit_number": root.get("次数", root.get("visit_number", "")),
            "patient_name": root.get("患者姓名", root.get("patient_name", "")),
            "dept": root.get("所在科室名称", root.get("科室", root.get("dept", ""))),
            "query_date": root.get("核查日期", root.get("query_date", "")),
        }

    if "audit_summary" not in root and any(key in root for key in ["总体结论", "重点关注项", "一致性结论", "风险等级"]):
        root["audit_summary"] = {
            "has_inconsistency": root.get("是否不一致", root.get("has_inconsistency", False)),
            "severity": root.get("风险等级", root.get("severity", "")),
            "risk_score": root.get("风险分值", root.get("risk_score", 0)),
            "overall_conclusion": root.get("总体结论", root.get("overall_conclusion", "")),
            "focus_items": root.get("重点关注项", root.get("focus_items", [])),
            "reasoning_brief": root.get("简要说明", root.get("reasoning_brief", "")),
        }

    if "dimensions" not in root:
        legacy_dimensions = root.get("核查结果") or root.get("审计结果") or root.get("results") or []
        if isinstance(legacy_dimensions, list):
            root["dimensions"] = legacy_dimensions

    return root


def _looks_like_new_schema(parsed: dict) -> bool:
    return any(key in parsed for key in ["audit_summary", "patient_summary", "dimensions"])


def _parse_new_schema(parsed: dict, result: dict):
    patient = parsed.get("patient_summary", {}) or {}
    summary = parsed.get("audit_summary", {}) or {}
    raw_judgement = parsed.get("raw_judgement", {}) or {}

    result["version"] = str(parsed.get("version", "1.0") or "1.0")
    result["patient_name"] = _first_non_empty(patient.get("patient_name"), patient.get("患者姓名"))
    result["patient_id"] = _first_non_empty(patient.get("patient_id"), patient.get("患者ID"))
    result["visit_number"] = _first_non_empty(patient.get("visit_number"), patient.get("次数"))
    result["dept"] = _first_non_empty(patient.get("dept"), patient.get("科室"), patient.get("所在科室名称"))
    result["audit_date"] = _first_non_empty(patient.get("query_date"), patient.get("核查日期"), parsed.get("audit_date"))
    result["overall_conclusion"] = _first_non_empty(summary.get("overall_conclusion"), summary.get("总体结论"))
    result["focus_items"] = _ensure_string_list(summary.get("focus_items", summary.get("重点关注项", [])))
    result["inconsistency"] = _to_bool(summary.get("has_inconsistency", summary.get("是否不一致", False)))
    result["severity"] = _normalize_severity(summary.get("severity", summary.get("风险等级", "")))
    result["risk_score"] = _safe_int(summary.get("risk_score", summary.get("风险分值", 0)))
    result["reasoning_brief"] = _first_non_empty(summary.get("reasoning_brief"), summary.get("简要说明"), raw_judgement.get("reasoning_brief"))
    result["alert_level"] = _normalize_alert_level(summary.get("alert_level", ""))
    result["closure_hours"] = _safe_int(summary.get("closure_hours", 0))
    result["push_strategy"] = _normalize_push_strategy(summary.get("push_strategy", ""))
    result["outcome_bucket"] = _normalize_outcome_bucket(summary.get("outcome_bucket", ""))
    result["overall_qc_summary"] = _first_non_empty(summary.get("overall_qc_summary"), summary.get("整体质控描述"))

    dimensions = parsed.get("dimensions", []) or []
    for item in dimensions:
        if not isinstance(item, dict):
            continue
        medical_evidence = _ensure_string_list(item.get("medical_evidence", item.get("病程记录证据", [])))
        nursing_evidence = _ensure_string_list(item.get("nursing_evidence", item.get("护理记录证据", [])))
        dimension_name = _first_non_empty(item.get("dimension_name"), item.get("dimension"), item.get("维度"))
        dim = {
            "dimension_code": _first_non_empty(item.get("dimension_code"), _dimension_code_from_name(dimension_name)),
            "dimension": dimension_name,
            "status": _normalize_status(item.get("status", "unknown")),
            "severity": _normalize_severity(item.get("severity", result["severity"])),
            "confidence": _safe_float(item.get("confidence", 0)),
            "medical_content": "\n".join(str(v) for v in medical_evidence if v),
            "nursing_content": "\n".join(str(v) for v in nursing_evidence if v),
            "explanation": _first_non_empty(item.get("issue_summary"), item.get("说明"), item.get("explanation")),
            "issue_summary": _first_non_empty(item.get("issue_summary"), item.get("说明"), item.get("explanation")),
            "recommendation": _first_non_empty(item.get("recommendation"), item.get("建议")),
            "medical_evidence": medical_evidence,
            "nursing_evidence": nursing_evidence,
            "alert_level": _normalize_alert_level(item.get("alert_level", "")),
            "closure_hours": _safe_int(item.get("closure_hours", 0)),
            "push_strategy": _normalize_push_strategy(item.get("push_strategy", "")),
            "outcome_bucket": _normalize_outcome_bucket(item.get("outcome_bucket", "")),
        }
        result["dimensions"].append(dim)

    # severity 派生统一在 _post_process_result 中处理
    # 这里不提前派生，因为维度 severity 可能还未被 post-process 修正


def _parse_legacy_schema(parsed: dict, result: dict):
    result["patient_name"] = _first_non_empty(parsed.get("患者姓名"), parsed.get("patient_name"))
    result["patient_id"] = _first_non_empty(parsed.get("患者ID"), parsed.get("patient_id"))
    result["visit_number"] = _first_non_empty(parsed.get("次数"), parsed.get("visit_number"))
    result["dept"] = _first_non_empty(parsed.get("所在科室名称"), parsed.get("科室"), parsed.get("dept"))
    result["audit_date"] = _first_non_empty(parsed.get("核查日期"), parsed.get("query_date"))
    result["overall_conclusion"] = _first_non_empty(parsed.get("总体结论"), parsed.get("overall_conclusion"))
    result["focus_items"] = _ensure_string_list(parsed.get("重点关注项", parsed.get("focus_items", [])))
    result["reasoning_brief"] = _first_non_empty(parsed.get("简要说明"), parsed.get("reasoning_brief"))

    audit_results = parsed.get("核查结果", parsed.get("审计结果", parsed.get("results", [])))
    has_fail = False
    has_warn = False

    for item in audit_results:
        if not isinstance(item, dict):
            continue
        status = _first_non_empty(item.get("状态"), item.get("status"), "❓")
        dimension_name = _first_non_empty(item.get("维度"), item.get("dimension"), item.get("dimension_name"))
        medical_content = _first_non_empty(item.get("病程记录内容"), item.get("medical_content"))
        nursing_content = _first_non_empty(item.get("护理记录内容"), item.get("nursing_content"))
        dim = {
            "dimension_code": _dimension_code_from_name(dimension_name),
            "dimension": dimension_name,
            "status": _normalize_status(status),
            "severity": "high" if "❌" in status else ("medium" if "⚠" in status else "low"),
            "confidence": 0,
            "medical_content": medical_content,
            "nursing_content": nursing_content,
            "explanation": _first_non_empty(item.get("说明"), item.get("issue_summary"), item.get("explanation")),
            "issue_summary": _first_non_empty(item.get("说明"), item.get("issue_summary"), item.get("explanation")),
            "recommendation": _first_non_empty(item.get("建议"), item.get("recommendation")),
            "medical_evidence": [medical_content] if medical_content else [],
            "nursing_evidence": [nursing_content] if nursing_content else [],
        }
        result["dimensions"].append(dim)

        if "❌" in status:
            has_fail = True
        elif "⚠" in status:
            has_warn = True

    if has_fail:
        result["inconsistency"] = True
        result["severity"] = "high"
        result["risk_score"] = 80
    elif has_warn:
        result["inconsistency"] = True
        result["severity"] = "medium"
        result["risk_score"] = 60
    else:
        result["inconsistency"] = False
        result["severity"] = "low"
        result["risk_score"] = 20 if result["dimensions"] else 0


def _normalize_status(status: str) -> str:
    return _norm.normalize_status(status)


def _normalize_severity(severity: str) -> str:
    return _norm.normalize_severity(severity)


def _normalize_alert_level(alert_level: str) -> str:
    return _norm.normalize_alert_level(alert_level)


def _alert_level_to_severity(alert_level: str) -> str:
    return _norm.alert_level_to_severity(alert_level)


def _normalize_push_strategy(strategy: str) -> str:
    return _norm.normalize_push_strategy(strategy)


def _normalize_outcome_bucket(bucket: str) -> str:
    return _norm.normalize_outcome_bucket(bucket)


def _derive_severity_from_dimensions(dimensions: list[dict]) -> str:
    return _norm.derive_severity_from_dimensions(dimensions)


def _derive_alert_level_from_dimensions(dimensions: list[dict]) -> str:
    return _norm.derive_alert_level_from_dimensions(dimensions)


def _safe_int(value: Any) -> int:
    return _norm.safe_int(value)


def _safe_float(value: Any) -> float:
    return _norm.safe_float(value)


from app.utils.text_utils import first_non_empty as _first_non_empty


def _ensure_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
        parts = re.split(r"[\n；;，,]+", text)
        return [part.strip() for part in parts if part.strip()]
    return [str(value).strip()] if str(value).strip() else []


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"true", "1", "yes", "y", "是", "有", "存在", "存在不一致"}


def _dimension_code_from_name(name: str) -> str:
    normalized = str(name or "")
    mapping = {
        "诊断一致性": "diagnosis_consistency",
        "护理级别执行": "nursing_level_consistency",
        "护理级别一致性": "nursing_level_consistency",
        "生命体征交叉": "vital_sign_consistency",
        "生命体征一致性": "vital_sign_consistency",
        "病情描述一致性": "condition_consistency",
        "诊疗措施执行": "treatment_measure_consistency",
        "诊疗措施一致性": "treatment_measure_consistency",
        "时间合理性": "timeline_consistency",
    }
    return mapping.get(normalized, "")


def _post_process_result(result: dict):
    result["focus_items"] = _ensure_string_list(result.get("focus_items", []))
    result["dimensions"] = [dim for dim in result.get("dimensions", []) if dim.get("dimension") or dim.get("dimension_code")]

    for dim in result["dimensions"]:
        dim["status"] = _normalize_status(dim.get("status", "unknown"))
        dim["severity"] = _normalize_severity(dim.get("severity", "")) or _severity_from_status(dim["status"])
        dim["confidence"] = min(max(_safe_float(dim.get("confidence", 0)), 0.0), 1.0)
        dim["dimension_code"] = dim.get("dimension_code") or _dimension_code_from_name(dim.get("dimension", ""))
        dim["medical_evidence"] = _ensure_string_list(dim.get("medical_evidence", []))
        dim["nursing_evidence"] = _ensure_string_list(dim.get("nursing_evidence", []))
        dim["medical_content"] = dim.get("medical_content") or "\n".join(dim["medical_evidence"])
        dim["nursing_content"] = dim.get("nursing_content") or "\n".join(dim["nursing_evidence"])
        dim["issue_summary"] = dim.get("issue_summary") or dim.get("explanation", "")
        dim["explanation"] = dim.get("explanation") or dim.get("issue_summary", "")
        dim["recommendation"] = dim.get("recommendation", "")
        # alert 字段后处理：归一化 + 从 alert_level 派生 severity
        dim["alert_level"] = _normalize_alert_level(dim.get("alert_level", ""))
        dim["closure_hours"] = _safe_int(dim.get("closure_hours", 0))
        dim["push_strategy"] = _normalize_push_strategy(dim.get("push_strategy", ""))
        dim["outcome_bucket"] = _normalize_outcome_bucket(dim.get("outcome_bucket", ""))
        # 如果有 alert_level 但无 severity，从 alert_level 派生
        if not dim.get("severity") and dim.get("alert_level"):
            dim["severity"] = _alert_level_to_severity(dim["alert_level"])

    if not result.get("severity"):
        result["severity"] = _derive_severity_from_dimensions(result["dimensions"])

    # 从 alert_level 派生总体 severity（如果 severity 仍为空）
    if not result.get("severity") and result.get("alert_level"):
        result["severity"] = _alert_level_to_severity(result["alert_level"])

    # 如果总体 alert_level 为空，从维度中取最高级别
    if not result.get("alert_level") and result["dimensions"]:
        result["alert_level"] = _derive_alert_level_from_dimensions(result["dimensions"])

    if not result.get("risk_score"):
        result["risk_score"] = _risk_score_from_dimensions(result["dimensions"], result.get("inconsistency", False))

    if not result.get("overall_conclusion") and result["dimensions"]:
        problem_dims = [dim["dimension"] for dim in result["dimensions"] if dim.get("status") in {"warn", "fail"}]
        if problem_dims:
            result["overall_conclusion"] = f"发现需要关注的维度：{'、'.join(problem_dims[:3])}。"
        else:
            result["overall_conclusion"] = "病历文书与护理记录整体基本一致。"

    if not result.get("reasoning_brief"):
        result["reasoning_brief"] = result.get("overall_conclusion", "")

    if not result.get("inconsistency"):
        result["inconsistency"] = any(dim.get("status") in {"warn", "fail"} for dim in result["dimensions"])


def _severity_from_status(status: str) -> str:
    return _norm.severity_from_status(status)


def _risk_score_from_dimensions(dimensions: list[dict], inconsistency: bool) -> int:
    return _norm.risk_score_from_dimensions(dimensions, inconsistency)
