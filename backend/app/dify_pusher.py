"""
Dify Workflow API 推送模块
"""
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
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {config.get("workflow_input_variable", "mr_text"): mr_text},
        "response_mode": "blocking",
        "user": config.get("user_identifier", f"auto-{patient_id}"),
    }
    timeout = config.get("timeout_seconds", 90)

    start_time = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

        outputs = data.get("data", {}).get("outputs", {})
        elapsed = int((time.time() - start_time) * 1000)

        # 尝试从 outputs 中提取不一致信息
        inconsistency = _extract_inconsistency(outputs)

        return {
            "status": "success",
            "workflow_run_id": data.get("workflow_run_id", ""),
            "task_id": data.get("task_id", ""),
            "result": outputs,
            "elapsed_ms": elapsed,
            "inconsistency": inconsistency.get("found", False),
            "severity": inconsistency.get("severity", ""),
        }
    except requests.exceptions.Timeout:
        elapsed = int((time.time() - start_time) * 1000)
        logger.error(f"Dify 请求超时 (patient_id={patient_id})")
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
        logger.error(f"Dify HTTP 错误: {e} — {error_detail}")
        return {
            "status": "failed",
            "error": f"HTTP {resp.status_code}: {error_detail}",
            "elapsed_ms": elapsed,
        }
    except Exception as e:
        elapsed = int((time.time() - start_time) * 1000)
        logger.error(f"Dify 推送异常: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "elapsed_ms": elapsed,
        }


def test_dify_connection(config: dict) -> dict:
    """测试 Dify 连通性"""
    url = f"{config['base_url']}/workflows/run"
    headers = {
        "Authorization": f"Bearer {config['api_key']}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": {config.get("workflow_input_variable", "mr_text"): "【测试报文】系统连通性测试，请忽略。"},
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


def _extract_inconsistency(outputs: dict) -> dict:
    """
    从 Dify 返回的 outputs 中提取不一致信息。
    这里的逻辑取决于你 Dify Workflow 的输出格式，
    以下是一个通用的解析方式。
    """
    import json

    result = {"found": False, "severity": ""}

    # 尝试常见的 output key
    for key in ("result", "output", "text", "analysis"):
        val = outputs.get(key, "")
        if not val:
            continue

        text = str(val).lower()

        # 简单关键字判断
        if "不一致" in text or "inconsisten" in text:
            result["found"] = True
            if "严重" in text or "high" in text or "重大" in text:
                result["severity"] = "high"
            elif "中等" in text or "medium" in text:
                result["severity"] = "medium"
            else:
                result["severity"] = "low"
            break

    return result
