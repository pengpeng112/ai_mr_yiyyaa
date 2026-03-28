"""
Dify Workflow API 推送模块
"""
import json
import logging
import time
import requests

logger = logging.getLogger(__name__)


def push_to_dify(mr_text: str, config: dict, patient_id: str) -> dict:
    """
    调用 Dify Workflow API（Blocking 模式）进行 AI 一致性分析

    Args:
        mr_text: 组装好的病程+护理记录文本
        config: Dify 配置 dict (base_url, api_key, workflow_input_variable, ...)
        patient_id: 患者ID

    Returns:
        dict with status, workflow_run_id, task_id, result, elapsed_ms, etc.
    """
    url = f"{config['base_url']}/workflows/run"
    input_var = config.get("workflow_input_variable", "mr_txt")
    output_key = config.get("workflow_output_key", "aa")
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {input_var: mr_text},
        "response_mode": "blocking",
        "user": config.get("user_identifier", f"auto-{patient_id}"),
    }
    timeout = config.get("timeout_seconds", 90)

    logger.info(
        f"Dify 请求开始 | patient_id={patient_id} | url={url} "
        f"| input_var={input_var} | output_key={output_key} "
        f"| text_length={len(mr_text)}"
    )

    start_time = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        outputs = data.get("data", {}).get("outputs", {})
        elapsed = int((time.time() - start_time) * 1000)

        logger.info(
            f"Dify 请求成功 | patient_id={patient_id} | elapsed_ms={elapsed} "
            f"| workflow_run_id={data.get('workflow_run_id', '')} "
            f"| outputs_keys={list(outputs.keys())}"
        )
        logger.debug(f"Dify 返回参数 | patient_id={patient_id} | outputs={json.dumps(outputs, ensure_ascii=False)[:2000]}")

        # 结构化解析 Dify 返回
        parsed = parse_dify_structured_output(outputs, output_key)

        return {
            "status": "success",
            "workflow_run_id": data.get("workflow_run_id", ""),
            "task_id": data.get("task_id", ""),
            "result": outputs,
            "parsed_output": parsed,
            "elapsed_ms": elapsed,
            "inconsistency": parsed.get("inconsistency", False),
            "severity": parsed.get("severity", ""),
        }
    except requests.exceptions.Timeout:
        elapsed = int((time.time() - start_time) * 1000)
        logger.error(f"Dify 请求超时 | patient_id={patient_id} | timeout={timeout}s")
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
        logger.error(f"Dify HTTP 错误 | patient_id={patient_id} | error={e} | detail={error_detail}")
        return {
            "status": "failed",
            "error": f"HTTP {resp.status_code}: {error_detail}",
            "elapsed_ms": elapsed,
        }
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        logger.error(f"Dify 推送异常 | patient_id={patient_id} | error={e}", exc_info=True)
        return {
            "status": "failed",
            "error": str(e),
            "elapsed_ms": elapsed,
        }


def test_dify_connection(config: dict) -> dict:
    """测试 Dify 连通性"""
    url = f"{config['base_url']}/workflows/run"
    input_var = config.get("workflow_input_variable", "mr_txt")
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {input_var: "【测试报文】系统连通性测试，请忽略。"},
        "response_mode": "blocking",
        "user": "system-test",
    }
    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        latency = int((time.time() - start) * 1000)
        if resp.status_code == 200:
            return {"status": "up", "latency_ms": latency}
        else:
            return {"status": "down", "latency_ms": latency, "message": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "down", "message": str(e)}


def parse_dify_structured_output(outputs: dict, output_key: str = "aa") -> dict:
    """
    结构化解析 Dify 返回的 outputs。

    实际 Dify 返回格式：
    {
      "data": {
        "outputs": {
          "aa": "{ \"患者姓名\": \"XX\", \"核查结果\": [{\"维度\":\"诊断一致性\",\"状态\":\"✅\",\"说明\":\"...\"},...],
                     \"总体结论\":\"...\", \"重点关注项\":[...] }"
        }
      }
    }

    返回结构包含 dimensions, overall_conclusion, focus_items, inconsistency, severity
    """
    # 1. 取目标 key，失败则遍历 fallback
    raw = outputs.get(output_key)
    if raw is None:
        for k in ("result", "output", "text", "analysis"):
            raw = outputs.get(k)
            if raw is not None:
                logger.info(f"parse_dify_structured_output: output_key='{output_key}' 未命中，回退到 key='{k}'")
                break

    if raw is None:
        logger.warning(f"parse_dify_structured_output: outputs 中未找到任何有效 key，outputs keys={list(outputs.keys())}")
        return _fallback_result(outputs)

    # 2. 若是字符串则 JSON 解析
    parsed_json = None
    if isinstance(raw, str):
        try:
            parsed_json = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"parse_dify_structured_output: JSON 解析失败，原始值长度={len(raw)}")
            return _fallback_text_result(raw)
    elif isinstance(raw, dict):
        parsed_json = raw
    else:
        logger.warning(f"parse_dify_structured_output: 未知类型 {type(raw)}")
        return _fallback_result(outputs)

    # 3. 提取 核查结果 列表
    dimensions = []
    has_inconsistency = False
    max_severity = "low"

    check_results = parsed_json.get("核查结果", [])
    if not isinstance(check_results, list):
        check_results = []

    for item in check_results:
        if not isinstance(item, dict):
            continue
        status_icon = item.get("状态", "❓")
        dim = {
            "dimension": item.get("维度", ""),
            "status": status_icon,
            "medical_content": item.get("病程记录内容", ""),
            "nursing_content": item.get("护理记录内容", ""),
            "explanation": item.get("说明", ""),
        }
        dimensions.append(dim)

        # 4. 状态映射
        if status_icon == "❌":
            has_inconsistency = True
            max_severity = "high"
        elif status_icon == "⚠️" and max_severity != "high":
            has_inconsistency = True
            max_severity = "medium"

    # 5. 总体结论 + 重点关注项
    overall_conclusion = parsed_json.get("总体结论", "")
    focus_items = parsed_json.get("重点关注项", [])
    if not isinstance(focus_items, list):
        focus_items = [str(focus_items)] if focus_items else []

    severity = max_severity if has_inconsistency else "low"

    logger.info(
        f"parse_dify_structured_output: 解析完成 | dimensions={len(dimensions)} "
        f"| inconsistency={has_inconsistency} | severity={severity} "
        f"| conclusion_len={len(overall_conclusion)}"
    )

    return {
        "dimensions": dimensions,
        "overall_conclusion": overall_conclusion,
        "focus_items": focus_items,
        "inconsistency": has_inconsistency,
        "severity": severity,
    }


def _fallback_result(outputs: dict) -> dict:
    """解析失败时回退：存原始输出，不中断推送流程"""
    raw_text = json.dumps(outputs, ensure_ascii=False)
    return _fallback_text_result(raw_text)


def _fallback_text_result(raw_text: str) -> dict:
    """从原始文本做关键字判断作为回退"""
    text_lower = raw_text.lower()
    has_inconsistency = "不一致" in raw_text or "inconsisten" in text_lower
    if has_inconsistency:
        if "严重" in raw_text or "high" in text_lower or "重大" in raw_text:
            severity = "high"
        elif "中等" in raw_text or "medium" in text_lower:
            severity = "medium"
        else:
            severity = "low"
    else:
        severity = "low"

    return {
        "dimensions": [],
        "overall_conclusion": raw_text[:500],
        "focus_items": [],
        "inconsistency": has_inconsistency,
        "severity": severity,
    }


def _extract_inconsistency(outputs: dict) -> dict:
    """
    向后兼容：从 Dify 返回的 outputs 中提取不一致信息（旧版本关键字匹配）。
    新代码请使用 parse_dify_structured_output。
    """
    parsed = parse_dify_structured_output(outputs, "aa")
    return {"found": parsed["inconsistency"], "severity": parsed["severity"]}
