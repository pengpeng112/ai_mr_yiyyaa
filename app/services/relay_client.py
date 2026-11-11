"""通用签名中继发送层（病历时效质控 T7；主设计文档 §14.3 调整 3 / §15 T7）。

从 `relay_alert_service.py` 抽出的、不依赖 PushLog / QCRecordAlertLog 的通用发送函数：

- `build_signed_request(payload, secret)`：HMAC-SHA256 签名（自 RelayAlertService 同名
  函数原样迁入，行为不变）；
- `send_signed_relay(url, payload, secret, ...)`：签名并 POST。

既有高危告警（RelayAlertService）与时效提醒（app/timeliness/notifier.py）共用本层；
relay_alert_service 的既有测试 mock 目标为 `app.services.relay_alert_service.requests.post`
（patch 的是共享 requests 模块对象的 post 属性），本模块经属性访问调用
`requests.post(...)`，mock 依然命中，回归结果不变。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import requests


def build_signed_request(payload: dict, secret: str) -> tuple[bytes, dict[str, str]]:
    """构建 HMAC_SHA256 签名的请求体和 headers。"""
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    message = timestamp.encode("utf-8") + b"." + raw_body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "X-Relay-Timestamp": timestamp,
        "X-Relay-Signature": signature,
    }
    return raw_body, headers


def send_signed_relay(
    url: str,
    payload: dict,
    secret: str,
    *,
    timeout: int = 10,
    isolated_mode: bool = False,
) -> requests.Response:
    """签名并 POST 到中继（通用发送层）。

    - isolated_mode=True：不跟随重定向（与 RelayAlertService 既有口径一致）。
      回环地址断言（assert_loopback_url）仍由调用方在取得 url 后、进入循环/发送前
      执行——本函数不重复断言，保证 dispatch_pending 的断言时序（先断言再动数据库）不变。
    - 异常不捕获，由调用方既有 try/except 统一处理（错误分类行为不变）。
    """
    raw_body, headers = build_signed_request(payload, secret)
    if isolated_mode:
        return requests.post(url, data=raw_body, headers=headers, timeout=timeout, allow_redirects=False)
    return requests.post(url, data=raw_body, headers=headers, timeout=timeout)
