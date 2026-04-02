"""
预警通知模块 —— 企微/钉钉/邮件/HTTP回调
"""
import logging
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import requests

from app.config import load_config
from app.database import SessionLocal
from app.models import NotifyLog

logger = logging.getLogger(__name__)


def send_notification(patient_id: str, result: dict, notify_config: dict):
    """根据配置向多个渠道发送通知"""
    channels = notify_config.get("channels", [])
    for channel in channels:
        if not channel.get("enabled", False):
            continue
        ch_type = channel.get("type", "")
        ch_config = channel.get("config", {})
        try:
            if ch_type == "wechat":
                _send_wechat(patient_id, result, ch_config)
            elif ch_type == "dingtalk":
                _send_dingtalk(patient_id, result, ch_config)
            elif ch_type == "email":
                _send_email(patient_id, result, ch_config)
            elif ch_type == "webhook":
                _send_webhook(patient_id, result, ch_config)
            _log_notify(ch_type, patient_id, "sent", "")
        except Exception as e:
            logger.error(f"通知发送失败 [{ch_type}]: {e}")
            _log_notify(ch_type, patient_id, "failed", str(e))


def _build_notify_content(patient_id: str, result: dict) -> str:
    severity = result.get("severity", "unknown")
    severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(severity, "⚪")
    outputs = result.get("result", {})
    detail = ""
    for key in ("result", "output", "text", "analysis"):
        if key in outputs:
            detail = str(outputs[key])[:500]
            break

    return (
        f"{severity_emoji} 【医疗记录不一致预警】\n"
        f"患者ID: {patient_id}\n"
        f"严重程度: {severity}\n"
        f"发现时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"分析摘要:\n{detail}\n"
    )


def _send_wechat(patient_id: str, result: dict, config: dict):
    """企业微信机器人 Webhook"""
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        raise ValueError("企业微信 webhook_url 未配置")
    content = _build_notify_content(patient_id, result)
    payload = {"msgtype": "text", "text": {"content": content}}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()


def _send_dingtalk(patient_id: str, result: dict, config: dict):
    """钉钉机器人 Webhook"""
    webhook_url = config.get("webhook_url", "")
    if not webhook_url:
        raise ValueError("钉钉 webhook_url 未配置")
    content = _build_notify_content(patient_id, result)
    payload = {"msgtype": "text", "text": {"content": content}}
    resp = requests.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()


def _send_email(patient_id: str, result: dict, config: dict):
    """SMTP 邮件通知（支持 TLS/SSL）"""
    smtp_host = config.get("smtp_host", "")
    smtp_port = config.get("smtp_port", 25)
    sender = config.get("sender", "")
    password = config.get("password", "")
    recipients = config.get("recipients", [])
    use_tls = config.get("use_tls", False)       # STARTTLS（端口 587）
    use_ssl = config.get("use_ssl", False)        # SSL/TLS（端口 465）

    if not smtp_host or not sender or not recipients:
        raise ValueError("邮件配置不完整")

    content = _build_notify_content(patient_id, result)

    msg = MIMEMultipart()
    msg["Subject"] = f"[医疗记录预警] 患者 {patient_id} 发现不一致"
    msg["From"] = sender
    msg["To"] = ",".join(recipients)
    msg.attach(MIMEText(content, "plain", "utf-8"))

    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            if password:
                server.login(sender, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            if password:
                server.login(sender, password)
            server.send_message(msg)


def _send_webhook(patient_id: str, result: dict, config: dict):
    """自定义 HTTP 回调"""
    url = config.get("url", "")
    if not url:
        raise ValueError("HTTP 回调 URL 未配置")
    payload = {
        "event": "inconsistency_detected",
        "patient_id": patient_id,
        "severity": result.get("severity", ""),
        "timestamp": datetime.now().isoformat(),
        "detail": result.get("result", {}),
    }
    headers = config.get("headers", {"Content-Type": "application/json"})
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()


def _log_notify(channel_type: str, patient_id: str, status: str, error_msg: str):
    """记录通知日志"""
    db = None
    try:
        db = SessionLocal()
        log = NotifyLog(
            notify_time=datetime.now(),
            channel_type=channel_type,
            patient_id=patient_id,
            status=status,
            error_msg=error_msg,
        )
        db.add(log)
        db.commit()
    except Exception as e:
        logger.error(f"通知日志写入失败: {e}")
        if db:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        if db:
            db.close()


def test_notify_channel(channel: dict) -> dict:
    """测试通知渠道"""
    ch_type = channel.get("type", "")
    ch_config = channel.get("config", {})
    test_result = {
        "severity": "low",
        "result": {"text": "这是一条测试通知，请忽略。"},
    }
    try:
        if ch_type == "wechat":
            _send_wechat("TEST-001", test_result, ch_config)
        elif ch_type == "dingtalk":
            _send_dingtalk("TEST-001", test_result, ch_config)
        elif ch_type == "email":
            _send_email("TEST-001", test_result, ch_config)
        elif ch_type == "webhook":
            _send_webhook("TEST-001", test_result, ch_config)
        else:
            return {"success": False, "message": f"未知渠道类型: {ch_type}"}
        return {"success": True, "message": "测试通知发送成功"}
    except Exception as e:
        return {"success": False, "message": str(e)}
