"""
通知渠道策略实现。
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import Callable, Dict

import requests


class BaseNotifyChannel:
    """通知渠道基类。"""

    channel_type: str = ""

    def send(self, patient_id: str, result: dict, config: dict, build_content: Callable[[str, dict], str]):
        raise NotImplementedError


class WeChatChannel(BaseNotifyChannel):
    channel_type = "wechat"

    def send(self, patient_id: str, result: dict, config: dict, build_content: Callable[[str, dict], str]):
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            raise ValueError("企业微信 webhook_url 未配置")
        content = build_content(patient_id, result)
        payload = {"msgtype": "text", "text": {"content": content}}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()


class DingTalkChannel(BaseNotifyChannel):
    channel_type = "dingtalk"

    def send(self, patient_id: str, result: dict, config: dict, build_content: Callable[[str, dict], str]):
        webhook_url = config.get("webhook_url", "")
        if not webhook_url:
            raise ValueError("钉钉 webhook_url 未配置")
        content = build_content(patient_id, result)
        payload = {"msgtype": "text", "text": {"content": content}}
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()


class EmailChannel(BaseNotifyChannel):
    channel_type = "email"

    def send(self, patient_id: str, result: dict, config: dict, build_content: Callable[[str, dict], str]):
        smtp_host = config.get("smtp_host", "")
        smtp_port = config.get("smtp_port", 25)
        sender = config.get("sender", "")
        password = config.get("password", "")
        recipients = config.get("recipients", [])
        use_tls = config.get("use_tls", False)
        use_ssl = config.get("use_ssl", False)

        if not smtp_host or not sender or not recipients:
            raise ValueError("邮件配置不完整")

        content = build_content(patient_id, result)

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


class WebhookChannel(BaseNotifyChannel):
    channel_type = "webhook"

    def send(self, patient_id: str, result: dict, config: dict, build_content: Callable[[str, dict], str]):
        url = config.get("url", "")
        if not url:
            raise ValueError("HTTP 回调 URL 未配置")
        payload = {
            "event": "inconsistency_detected",
            "patient_id": patient_id,
            "severity": result.get("severity", ""),
            "alert_level": result.get("parsed_output", {}).get("alert_level", ""),
            "timestamp": datetime.now().isoformat(),
            "detail": result.get("result", {}),
        }
        headers = config.get("headers", {"Content-Type": "application/json"})
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()


CHANNEL_REGISTRY: Dict[str, BaseNotifyChannel] = {
    cls.channel_type: cls()
    for cls in [WeChatChannel, DingTalkChannel, EmailChannel, WebhookChannel]
}
