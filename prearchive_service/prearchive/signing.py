# -*- coding: utf-8 -*-
"""HMAC-SHA256 签名（独立实现）。

协议与 Med-Audit relay 通道一致（只读参考 app/services/relay_alert_service.py 的
build_signed_request，禁止 import）：
  body    = JSON 紧凑序列化（ensure_ascii=False，逗号冒号分隔）UTF-8
  message = timestamp + "." + body
  sign    = HMAC-SHA256(secret, message) hexdigest
  headers = X-Relay-Timestamp / X-Relay-Signature

契约测试向量见 tests/contract_vectors.json；协议变更必须双改并更新向量（028 A8）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

HEADER_TIMESTAMP = "X-Relay-Timestamp"
HEADER_SIGNATURE = "X-Relay-Signature"


def canonical_body(payload: dict) -> bytes:
    """与 relay 相同的 JSON 序列化（紧凑分隔符 + 非 ASCII 保留）。"""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign(secret: str, timestamp: str, body: bytes) -> str:
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def build_signed_request(payload: dict, secret: str,
                         timestamp: str = None) -> tuple:
    """返回 (body_bytes, headers)。timestamp 可注入（契约测试用固定值）。"""
    if timestamp is None:
        timestamp = str(int(time.time()))
    body = canonical_body(payload)
    signature = sign(secret, timestamp, body)
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        HEADER_TIMESTAMP: timestamp,
        HEADER_SIGNATURE: signature,
    }
    return body, headers


def verify_signature(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    """常量时间比对（供回放校验/联调工具复用）。"""
    expected = sign(secret, str(timestamp), body or b"")
    return hmac.compare_digest(expected, str(signature or ""))
