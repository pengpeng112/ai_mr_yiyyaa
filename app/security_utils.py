"""对外错误信息和通知测试目标的安全校验。"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse


_SENSITIVE_ERROR_RE = re.compile(
    r"(?:ORA-\d+|SQLSTATE|sqlalchemy|psycopg|cx[_-]?oracle|traceback|"
    r"\b(?:select|insert|update|delete|drop|alter|create)\b|"
    r"(?:password|passwd|secret|api[_-]?key|connection refused|connection string)|"
    r"(?:host\s*=|port\s*=|dsn\s*=|file \"|line \d+))",
    re.IGNORECASE,
)


def public_error_message(exc: BaseException, fallback: str = "请求处理失败") -> str:
    """返回可对外暴露的错误消息，过滤数据库、连接和敏感配置细节。"""
    message = " ".join(str(exc or "").split()).strip()
    if not message or len(message) > 240 or _SENSITIVE_ERROR_RE.search(message):
        return fallback
    return message


def _allowed_notification_hosts() -> set[str]:
    raw = os.getenv("NOTIFY_TEST_ALLOWED_HOSTS", "")
    return {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}


def _host_is_allowlisted(host: str, allowlist: set[str]) -> bool:
    return host.strip().lower().rstrip(".") in allowlist


def _resolved_addresses(host: str, port: int) -> set[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("通知目标域名无法解析") from exc
    addresses: set[ipaddress._BaseAddress] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addresses.add(ipaddress.ip_address(str(sockaddr[0])))
        except ValueError as exc:
            raise ValueError("通知目标地址解析失败") from exc
    if not addresses:
        raise ValueError("通知目标没有可用地址")
    return addresses


def _validate_host(host: str, port: int, allowlist: set[str]) -> None:
    if not host or len(host) > 253 or any(ch.isspace() for ch in host):
        raise ValueError("通知目标主机名无效")
    if not 1 <= port <= 65535:
        raise ValueError("通知目标端口无效")
    if _host_is_allowlisted(host, allowlist):
        return
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        addresses = _resolved_addresses(host, port)
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        ):
            raise ValueError("通知测试目标属于禁止访问的内网或保留地址")


def validate_test_notification_target(channel_type: str, config: dict) -> None:
    """校验测试通知目标；默认拒绝任意内网、回环和保留地址。"""
    config = config if isinstance(config, dict) else {}
    allowlist = _allowed_notification_hosts()
    if channel_type in {"wechat", "dingtalk", "webhook"}:
        key = "webhook_url" if channel_type in {"wechat", "dingtalk"} else "url"
        raw_url = str(config.get(key) or "").strip()
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("通知测试 URL 必须使用有效的 http/https 地址")
        if parsed.username or parsed.password:
            raise ValueError("通知测试 URL 不允许携带用户凭据")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise ValueError("通知测试 URL 端口无效") from exc
        _validate_host(parsed.hostname, port, allowlist)
        return
    if channel_type == "email":
        host = str(config.get("smtp_host") or "").strip()
        try:
            port = int(config.get("smtp_port") or 25)
        except (TypeError, ValueError) as exc:
            raise ValueError("SMTP 端口无效") from exc
        _validate_host(host, port, allowlist)
        return
    raise ValueError("未知通知渠道类型")
