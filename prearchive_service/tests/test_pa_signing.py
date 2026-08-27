# -*- coding: utf-8 -*-
"""HMAC 契约测试：向量文件 + 测试内独立复算 + 独立实现三方一致（028 A8）。

测试内的独立实现逐行复刻 relay 协议构造（json 紧凑序列化 + ts.body 消息 +
HMAC-SHA256 hex），与本服务 signing 模块、tests/contract_vectors.json 三方比对。
"""

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from prearchive.signing import (
    HEADER_SIGNATURE,
    HEADER_TIMESTAMP,
    build_signed_request,
    canonical_body,
    sign,
    verify_signature,
)

VECTORS = Path(__file__).resolve().parent / "contract_vectors.json"


def _independent_relay_build(payload: dict, secret: str, timestamp: str):
    """独立实现：与 app/services/relay_alert_service.build_signed_request 同构（只读复刻）。"""
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    message = timestamp.encode("utf-8") + b"." + raw_body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return raw_body, signature


@pytest.fixture(scope="module")
def vector_data():
    return json.loads(VECTORS.read_text(encoding="utf-8"))


def test_vectors_file_structure(vector_data):
    assert vector_data["protocol"] == "relay-hmac-sha256/v1"
    assert len(vector_data["vectors"]) >= 2


def test_contract_triple_agreement(vector_data):
    for vector in vector_data["vectors"]:
        payload = vector["payload"]
        secret = vector["secret"]
        timestamp = vector["timestamp"]

        # 1) 独立复算（relay 协议同构实现）
        body_ref, sig_ref = _independent_relay_build(payload, secret, timestamp)
        assert body_ref.hex() == vector["expected_body_hex"]
        assert sig_ref == vector["expected_signature"]
        assert body_ref.decode("utf-8") == vector["expected_body"]

        # 2) 本服务实现
        body, headers = build_signed_request(payload, secret, timestamp=timestamp)
        assert body.hex() == vector["expected_body_hex"]
        assert headers[HEADER_TIMESTAMP] == timestamp
        assert headers[HEADER_SIGNATURE] == vector["expected_signature"]
        assert headers["Content-Type"].startswith("application/json")


def test_chinese_payload_ensure_ascii_false(vector_data):
    """中文必须原样保留（ensure_ascii=False）——签名与 body 都依赖该口径。"""
    vector = next(v for v in vector_data["vectors"] if v["name"] == "chinese-payload")
    assert "测试医生甲" in vector["expected_body"]
    assert "\\u" not in vector["expected_body"]
    body = canonical_body(vector["payload"])
    assert body.decode("utf-8") == vector["expected_body"]


def test_signature_changes_with_secret_or_timestamp():
    payload = {"a": 1}
    body1, h1 = build_signed_request(payload, "secret-a", timestamp="100")
    body2, h2 = build_signed_request(payload, "secret-b", timestamp="100")
    body3, h3 = build_signed_request(payload, "secret-a", timestamp="101")
    assert h1[HEADER_SIGNATURE] != h2[HEADER_SIGNATURE]
    assert h1[HEADER_SIGNATURE] != h3[HEADER_SIGNATURE]
    assert h1["Content-Type"].endswith("charset=utf-8")


def test_verify_signature_roundtrip_and_tamper():
    payload = {"event": "prearchive_check_issue", "n": 1}
    secret = "verify-secret"
    body, headers = build_signed_request(payload, secret)
    assert verify_signature(body, headers[HEADER_TIMESTAMP],
                            headers[HEADER_SIGNATURE], secret) is True
    # 篡改 body / 时间戳 / 密钥
    assert verify_signature(body + b"x", headers[HEADER_TIMESTAMP],
                            headers[HEADER_SIGNATURE], secret) is False
    assert verify_signature(body, "999", headers[HEADER_SIGNATURE], secret) is False
    assert verify_signature(body, headers[HEADER_TIMESTAMP],
                            headers[HEADER_SIGNATURE], "other") is False


def test_sign_helper():
    assert sign("s", "1", b"{}") == hmac.new(
        b"s", b"1.{}", hashlib.sha256).hexdigest()
