"""
Dify Workflow API 推送模块
增强功能：结构化响应解析 + 详细请求/响应日志
"""
import json
import logging
import time
from typing import Any
import requests

from app.config import normalize_dify_base_url
from app.services.response_path_utils import apply_response_paths as _apply_response_paths
from app.utils.json_utils import safe_json_dumps as _safe_json_dumps

# ── 日志工具 ──
from app.services.dify_log_utils import (
    _is_full_debug_log_enabled,
    _summarize_dify_payload,
    _summarize_dify_outputs,
)

# ── 输出解析 ──
from app.services.dify_output_resolver import (
    sanitize_extra_inputs,
    _merge_safe_extra_inputs,
    _resolve_output_value,
    _load_output_root,
)

# ── JSON 容错 ──
from app.services.dify_json_parser import (
    _load_json_with_tolerance,
)

# ── Schema 解析 ──
from app.services.dify_schema_parser import (
    _normalize_parsed_root,
    _looks_like_new_schema,
    _parse_new_schema,
    _parse_legacy_schema,
    _fallback_keyword_match,
    _append_parse_warning,
    _append_output_quality_warnings,
    _post_process_result,
    _normalize_status,
    _normalize_severity,
    _normalize_alert_level,
    _alert_level_to_severity,
    _normalize_push_strategy,
    _normalize_outcome_bucket,
    _derive_severity_from_dimensions,
    _derive_alert_level_from_dimensions,
    _safe_int,
    _safe_float,
    _ensure_string_list,
    _to_bool,
    _dimension_code_from_name,
    _severity_from_status,
    _risk_score_from_dimensions,
)

logger = logging.getLogger(__name__)

# 专用审计日志器：记录 Dify 请求/响应详情
audit_logger = logging.getLogger("audit.dify")


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _sanitize_extra_inputs(extra: Any) -> dict:
    return sanitize_extra_inputs(extra)


def apply_response_paths(raw: Any, paths: dict | None) -> dict:
    """兼容入口：委托给 response_path_utils.apply_response_paths。"""
    return _apply_response_paths(raw, paths)


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

        if not outputs or (isinstance(outputs, dict) and len(outputs) == 0):
            audit_logger.warning(
                "[Dify空输出] patient_id=%s, HTTP 200 但 outputs 为空, "
                "workflow_run_id=%s — 请检查 Dify 工作流 End 节点是否连接并设置了输出变量",
                patient_id, data.get("workflow_run_id", ""),
            )

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

        path_values = _apply_response_paths(_load_output_root(outputs, output_key), response_paths)
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
            elif len(outputs) == 0:
                audit_logger.warning(
                    "[Dify解析] outputs 为空字典, output_key='%s' — 请检查 Dify 工作流 End 节点是否连接并设置了输出变量",
                    output_key,
                )
                result["raw_text"] = ""
                return result
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
