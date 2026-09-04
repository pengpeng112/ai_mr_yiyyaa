# -*- coding: utf-8 -*-
"""投递目标 Adapter（039 §7.1）：HMAC 签名 / SSRF 防护 / secret 引用。

- 首期仅 hmac_sha256（预留 mtls）；禁止 Basic 明文口令落库；
- HMAC 对「原始 body 字节」计算：hex(X-Relay-Signature 风格)，签名头
  X-Delivery-Timestamp + X-Delivery-Signature，时间戳参与签名（防重放窗口）；
- 目标 URL 必须过 allowlist 校验：scheme https 默认；http 仅显式
  allow_insecure_internal_http=true 且主机为内网/环回段；
- secret 只从环境变量读取（secret_ref=env:NAME），API/UI 永不回明文；
- 空字符串 secret 不得覆盖已有 secret_ref（BFF/管理 API 侧同样守卫）。
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .rule_repository import RuleRepository

SIGNATURE_HEADER = "X-Delivery-Signature"
TIMESTAMP_HEADER = "X-Delivery-Timestamp"
SIGNATURE_ALGORITHM = "hmac-sha256-hex"
# 签名时间窗（秒）：接收方可据此拒收重放
SIGNATURE_WINDOW_SECONDS = 300


class DestinationError(Exception):
    """目标配置非法（SSRF/协议/密钥引用）。"""


@dataclass
class ResolvedDestination:
    code: str
    kind: str
    enabled: bool
    url: str
    auth_type: str
    secret: str
    schema_version: str
    timeout_seconds: int
    max_attempts: int
    send_severities: list


def build_signature(secret: str, body: bytes, timestamp: str) -> str:
    """HMAC-SHA256(secret, timestamp + '.' + body) → hex。固定契约向量见测试。"""
    message = timestamp.encode("utf-8") + b"." + body
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def resolve_secret(secret_ref: str) -> str:
    """secret_ref=env:VAR_NAME → 环境变量值；空/未设置返回 ''。"""
    ref = str(secret_ref or "").strip()
    if not ref:
        return ""
    if not ref.startswith("env:"):
        raise DestinationError(
            f"secret_ref must be env:VAR_NAME form, got {secret_ref!r}")
    return os.environ.get(ref[4:], "").strip()


def _is_internal_address(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return host.endswith(".local") or host.endswith(".internal") \
            or host == "localhost"


def validate_target_url(base_url: str, endpoint: str,
                        allow_insecure_internal_http: bool) -> str:
    """SSRF 防护：https 默认；http 仅内网+显式开关；禁 file/ftp/非标准端口外联。"""
    raw = f"{str(base_url or '').rstrip('/')}{str(endpoint or '')}"
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https"):
        raise DestinationError(f"scheme must be http/https, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise DestinationError("target url has no host")
    if parsed.scheme == "http":
        if not allow_insecure_internal_http:
            raise DestinationError(
                "plain http target requires allow_insecure_internal_http=true")
        if not _is_internal_address(parsed.hostname):
            raise DestinationError(
                f"plain http target host {parsed.hostname!r} is not an internal address")
    if parsed.username or parsed.password:
        raise DestinationError("credentials in url are forbidden")
    return raw


def resolve_destination(repository: RuleRepository, code: str) -> ResolvedDestination:
    row = repository.get_destination(code)
    if row is None:
        raise DestinationError(f"destination not found: {code}")
    url = validate_target_url(row.base_url, row.endpoint,
                              bool(row.allow_insecure_internal_http))
    secret = resolve_secret(row.secret_ref) if row.auth_type == "hmac_sha256" else ""
    return ResolvedDestination(
        code=row.code, kind=row.kind, enabled=bool(row.enabled), url=url,
        auth_type=row.auth_type, secret=secret,
        schema_version=row.schema_version,
        timeout_seconds=int(row.timeout_seconds or 5),
        max_attempts=int(row.max_attempts or 6),
        send_severities=row.send_severities(),
    )


def severity_eligible(destination: ResolvedDestination, highest_severity: str) -> bool:
    """send_severities 过滤：空列表=不过滤。"""
    levels = destination.send_severities or []
    return not levels or str(highest_severity or "") in levels


def seed_default_destinations(repository: RuleRepository,
                              updated_by: str = "system") -> None:
    """初始两个禁用 mock 目标（emr_mock / his_mock，039 G2/G3 默认处理）。"""
    defaults = [
        {"code": "emr_mock", "kind": "emr", "enabled": 0,
         "base_url": "http://127.0.0.1:8601", "endpoint": "/mock/qc-results",
         "auth_type": "hmac_sha256", "secret_ref": "env:PREARCHIVE_EMR_HMAC_SECRET",
         "send_severities_json": '["medium","high"]',
         "allow_insecure_internal_http": 1},
        {"code": "his_mock", "kind": "his", "enabled": 0,
         "base_url": "http://127.0.0.1:8602", "endpoint": "/mock/qc-results",
         "auth_type": "hmac_sha256", "secret_ref": "env:PREARCHIVE_HIS_HMAC_SECRET",
         "send_severities_json": '["medium","high"]',
         "allow_insecure_internal_http": 1},
    ]
    for fields in defaults:
        if repository.get_destination(fields["code"]) is None:
            repository.upsert_destination(updated_by=updated_by, **fields)


def now_ts() -> str:
    return str(int(time.time()))


def build_delivery_headers(destination: ResolvedDestination, body: bytes) -> dict:
    """构造投递请求头（含 HMAC 签名；mtls 由部署层证书承载）。"""
    headers = {
        "Content-Type": "application/json",
        "X-Delivery-Schema-Version": destination.schema_version,
    }
    if destination.auth_type == "hmac_sha256":
        if not destination.secret:
            raise DestinationError(
                f"destination {destination.code}: hmac secret not configured "
                f"(check {destination.code} secret_ref env)")
        timestamp = now_ts()
        headers[TIMESTAMP_HEADER] = timestamp
        headers[SIGNATURE_HEADER] = build_signature(destination.secret, body, timestamp)
    return headers


def mask_url_for_log(url: str) -> str:
    """日志脱敏：去 query、只留 scheme://host/path。"""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
