# -*- coding: utf-8 -*-
"""046 T7 主服务 JHEMR 集成外部路由测试。

覆盖：默认 503 disabled（零网络）；签名四件套校验（client/timestamp 偏差/nonce
重放/签名绑定 method+path+body-hash）；BFF 代理转发（目标=白名单集成路径、
actor=集成服务账号最小权限）；BFF 关闭/不可用降级 503/502。
"""

import json
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import jhemr_integration
from app.routers.jhemr_integration import build_signature

CLIENT_ID = "jhemr-test-client"
SECRET = "unit-jhemr-secret"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JHEMR_INTEGRATION_ENABLED", "true")
    monkeypatch.setenv("JHEMR_INTEGRATION_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("JHEMR_INTEGRATION_HMAC_SECRET", SECRET)
    app = FastAPI()
    app.include_router(jhemr_integration.router, prefix="/api")
    return TestClient(app)


def _sign(method: str, path: str, body: bytes = b"", *,
          client_id: str = CLIENT_ID, secret: str = SECRET,
          timestamp: str | None = None, nonce: str | None = None):
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or uuid.uuid4().hex
    headers = {
        "X-Jhemr-Client-Id": client_id,
        "X-Jhemr-Timestamp": timestamp,
        "X-Jhemr-Nonce": nonce,
        "X-Jhemr-Signature": build_signature(
            secret, client_id, method, path, body, timestamp, nonce),
    }
    return headers


def _proxy_ok(self, method, path_template, actor, *, params=None, query=None,
              json_body=None):
    return {"status": 202, "json": {"check_id": "chk-1", "status": "queued",
                                    "proxied": path_template},
            "request_id": "bff-test"}


# ---------------------------------------------------------------- 开关与签名

def test_disabled_by_default_returns_503(monkeypatch):
    monkeypatch.delenv("JHEMR_INTEGRATION_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(jhemr_integration.router, prefix="/api")
    response = TestClient(app).post(
        "/api/integrations/jhemr/submission-checks", json={})
    assert response.status_code == 503


def test_not_configured_returns_503(client, monkeypatch):
    monkeypatch.setenv("JHEMR_INTEGRATION_HMAC_SECRET", "")
    response = client.post("/api/integrations/jhemr/submission-checks",
                           json={}, headers=_sign(
                               "POST", "/api/integrations/jhemr/submission-checks",
                               b"{}"))
    assert response.status_code == 503


def test_missing_signature_headers_401(client):
    assert client.post("/api/integrations/jhemr/submission-checks",
                       json={}).status_code == 401


def test_bad_signature_401(client):
    body = json.dumps({"patient_id": "TEST0002"}).encode()
    headers = _sign("POST", "/api/integrations/jhemr/submission-checks", body)
    headers["X-Jhemr-Signature"] = "0" * 64
    assert client.post("/api/integrations/jhemr/submission-checks",
                       content=body, headers=headers).status_code == 401


def test_signature_binds_body_401(client):
    """改一个字节的 body，签名即失效（绑定体哈希）。"""
    body = json.dumps({"patient_id": "TEST0002"}).encode()
    headers = _sign("POST", "/api/integrations/jhemr/submission-checks",
                    b'{"patient_id": "TEST0003"}')
    assert client.post("/api/integrations/jhemr/submission-checks",
                       content=body, headers=headers).status_code == 401


def test_expired_timestamp_401(client):
    old = str(int(time.time()) - 3600)
    headers = _sign("GET", "/api/integrations/jhemr/submission-checks/x",
                    timestamp=old)
    assert client.get("/api/integrations/jhemr/submission-checks/x",
                      headers=headers).status_code == 401


def test_nonce_replay_401(client):
    path = "/api/integrations/jhemr/submission-checks"
    nonce = uuid.uuid4().hex
    headers = _sign("POST", path, b"{}", nonce=nonce)
    assert client.post(path, content=b"{}", headers=headers).status_code != 401
    replay = _sign("POST", path, b"{}", nonce=nonce)
    assert client.post(path, content=b"{}", headers=replay).status_code == 401


def test_wrong_client_id_401(client):
    path = "/api/integrations/jhemr/submission-checks"
    headers = _sign("POST", path, b"{}", client_id="someone-else")
    assert client.post(path, content=b"{}", headers=headers).status_code == 401


# ---------------------------------------------------------------- 代理转发

def test_submission_check_proxies_to_whitelisted_target(client, monkeypatch):
    calls = []

    def fake_call(self, method, path_template, actor, *, params=None,
                  query=None, json_body=None):
        calls.append({"method": method, "path": path_template,
                      "actor": actor, "body": json_body})
        return {"status": 202, "json": {"check_id": "chk-1"},
                "request_id": "bff-1"}

    monkeypatch.setattr(jhemr_integration, "PrearchiveAdminClient",
                        type("FakeClient", (), {"call": fake_call}))
    body = {"patient_id": "TEST0002", "visit_number": "1",
            "submission_id": "SUB-1",
            "operator": {"id": "DOC77", "name": "医生"},
            "document_refs": [{"doc_id": "D1", "revision": "r1"}]}
    raw = json.dumps(body).encode()
    headers = _sign("POST", "/api/integrations/jhemr/submission-checks", raw)
    response = client.post("/api/integrations/jhemr/submission-checks",
                           content=raw, headers=headers)
    assert response.status_code == 202
    assert response.json()["check_id"] == "chk-1"
    assert calls[0]["path"] == "/api/integration/jhemr/submission-checks"
    # 服务账号最小权限（不含任何管理权限）
    assert set(calls[0]["actor"].permissions) == {
        "prearchive_check_view", "prearchive_issue_feedback"}
    assert calls[0]["actor"].id == "jhemr-integration"
    # 转发体保留幂等/操作者/文书引用
    forwarded = calls[0]["body"]
    assert forwarded["submission_id"] == "SUB-1"
    assert forwarded["operator"]["id"] == "DOC77"
    assert forwarded["document_refs"] == [{"doc_id": "D1", "revision": "r1"}]
    assert forwarded["request_id"]


def test_get_check_proxies_with_params(client, monkeypatch):
    calls = []

    def fake_call(self, method, path_template, actor, *, params=None,
                  query=None, json_body=None):
        calls.append({"method": method, "path": path_template,
                      "params": params})
        return {"status": 200, "json": {"status": "completed",
                                        "summary": {"provisional": False}},
                "request_id": "bff-2"}

    monkeypatch.setattr(jhemr_integration, "PrearchiveAdminClient",
                        type("FakeClient", (), {"call": fake_call}))
    path = "/api/integrations/jhemr/submission-checks/chk-42"
    response = client.get(path, headers=_sign("GET", path))
    assert response.status_code == 200
    assert calls[0]["path"] == \
        "/api/integration/jhemr/submission-checks/{check_id}"
    assert calls[0]["params"] == {"check_id": "chk-42"}


def test_bff_disabled_maps_503(client, monkeypatch):
    from app.services.prearchive_admin_client import PrearchiveAdminDisabled

    def fake_call(self, *args, **kwargs):
        raise PrearchiveAdminDisabled("disabled")

    monkeypatch.setattr(jhemr_integration, "PrearchiveAdminClient",
                        type("FakeClient", (), {"call": fake_call}))
    path = "/api/integrations/jhemr/submission-checks"
    raw = b"{}"
    response = client.post(path, content=raw,
                           headers=_sign("POST", path, raw))
    assert response.status_code == 503


def test_bff_unavailable_maps_502(client, monkeypatch):
    from app.services.prearchive_admin_client import PrearchiveAdminUnavailable

    def fake_call(self, *args, **kwargs):
        raise PrearchiveAdminUnavailable("unreachable")

    monkeypatch.setattr(jhemr_integration, "PrearchiveAdminClient",
                        type("FakeClient", (), {"call": fake_call}))
    path = "/api/integrations/jhemr/submission-checks"
    raw = b"{}"
    response = client.post(path, content=raw,
                           headers=_sign("POST", path, raw))
    assert response.status_code == 502


# ---------------------------------------------------------------- 签名向量

def test_signature_deterministic_vector():
    """确定性签名向量（联调包 SIGNATURE_VECTORS.md 的机器源）。"""
    signature = build_signature(
        "unit-jhemr-secret", "jhemr-test-client", "POST",
        "/api/integrations/jhemr/submission-checks",
        b'{"patient_id":"TEST0002"}', "1760000000", "nonce-0001")
    # 算法稳定性：同输入同输出；绑定六要素（任一变化即失效）
    again = build_signature(
        "unit-jhemr-secret", "jhemr-test-client", "POST",
        "/api/integrations/jhemr/submission-checks",
        b'{"patient_id":"TEST0002"}', "1760000000", "nonce-0001")
    assert signature == again and len(signature) == 64
    tampered = build_signature(
        "unit-jhemr-secret", "jhemr-test-client", "GET",
        "/api/integrations/jhemr/submission-checks",
        b'{"patient_id":"TEST0002"}', "1760000000", "nonce-0001")
    assert tampered != signature
