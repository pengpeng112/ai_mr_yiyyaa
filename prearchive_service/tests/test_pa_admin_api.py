# -*- coding: utf-8 -*-
"""管理 API 测试（039 T3 / §12.1 Security、BFF 前置）。

覆盖：token+actor 签名鉴权、权限矩阵、规则生命周期端点、并发 409、
destinations 非敏感维护、outbox/retry、fields、audit、dry-run。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prearchive.admin_api import (
    ACTOR_ID_HEADER,
    ACTOR_NAME_HEADER,
    ACTOR_PERMS_HEADER,
    ACTOR_SIGNATURE_HEADER,
    ADMIN_TOKEN_HEADER,
    REQUEST_ID_HEADER,
    create_admin_router,
    actor_signature,
)
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import RuleService

ADMIN_TOKEN = "unit-admin-token"
SIGNING_SECRET = "unit-signing-secret"
ALL_PERMS = ("prearchive_rule_view,prearchive_rule_edit,prearchive_rule_approve,"
             "prearchive_rule_publish,prearchive_integration_manage,"
             "prearchive_delivery_retry")


@pytest.fixture()
def stack():
    repo = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    service = RuleService(repo)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file", "require_separate_approver": False,
                                "governance": {"pilot_dept_codes": [],
                                               "action_policy": "notify_only"}}}
    app = FastAPI()
    app.include_router(create_admin_router(config, repo, service))
    return TestClient(app), repo, service


def _headers(actor_id="admin-1", actor_name="管理员", perms=ALL_PERMS,
             request_id="req-1", token=ADMIN_TOKEN):
    from urllib.parse import quote
    encoded_name = quote(actor_name, safe="")
    signature = actor_signature(SIGNING_SECRET, actor_id, encoded_name,
                                perms, request_id)
    return {
        ADMIN_TOKEN_HEADER: token,
        ACTOR_ID_HEADER: actor_id,
        ACTOR_NAME_HEADER: encoded_name,
        ACTOR_PERMS_HEADER: perms,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: signature,
    }


RULE_BODY = {
    "rule_id": "R-API-1", "name": "接口规则", "message": "m",
    "type": "empty_field", "fields": ["过敏史"], "version": "2026.09.02.1",
}


def test_auth_rejects_missing_token_and_bad_signature(stack):
    client, _, _ = stack
    assert client.get("/api/admin/rules").status_code == 401        # 无头
    bad = _headers()
    bad[ACTOR_SIGNATURE_HEADER] = "0" * 64
    assert client.get("/api/admin/rules", headers=bad).status_code == 401
    wrong_token = _headers(token="wrong")
    assert client.get("/api/admin/rules", headers=wrong_token).status_code == 401


def test_permission_matrix(stack):
    client, _, _ = stack
    viewer = _headers(perms="prearchive_rule_view")
    assert client.get("/api/admin/rules", headers=viewer).status_code == 200
    # viewer 不能建草稿
    assert client.post("/api/admin/rules", headers=viewer,
                       json=RULE_BODY).status_code == 403
    # 无 view 权限者连列表都不可见
    no_view = _headers(perms="prearchive_rule_edit")
    assert client.get("/api/admin/rules", headers=no_view).status_code == 403
    # viewer 不能改目标
    assert client.get("/api/admin/destinations",
                      headers=viewer).status_code == 403


def test_rule_lifecycle_endpoints(stack):
    client, _, _ = stack
    headers = _headers()
    created = client.post("/api/admin/rules", headers=headers, json=RULE_BODY)
    assert created.status_code == 200
    assert created.json()["status"] == "draft"

    validated = client.post("/api/admin/rules/R-API-1/validate", headers=headers,
                            json={"rule_version": "2026.09.02.1"}).json()
    assert validated["valid"] is True

    approved = client.post("/api/admin/rules/R-API-1/approve", headers=headers,
                           json={"rule_version": "2026.09.02.1", "reason": "ok"})
    assert approved.status_code == 200

    published = client.post("/api/admin/rules/R-API-1/publish", headers=headers,
                            json={"rule_version": "2026.09.02.1"})
    assert published.status_code == 200
    assert published.json()["pointer_version"] == 1

    # 非法跳转：draft 不存在了 → 再 publish 应 409（status 已 published）
    again = client.post("/api/admin/rules/R-API-1/publish", headers=headers,
                        json={"rule_version": "2026.09.02.1"})
    assert again.status_code == 409

    # 非法 DSL → 422
    bad_rule = dict(RULE_BODY, rule_id="R-API-BAD", type="hackable")
    assert client.post("/api/admin/rules", headers=headers,
                       json=bad_rule).status_code == 422

    # 未知规则 → 404
    assert client.post("/api/admin/rules/NOPE/validate", headers=headers,
                       json={"rule_version": "1"}).status_code == 404


def test_draft_optimistic_lock_409(stack):
    client, _, _ = stack
    headers = _headers()
    created = client.post("/api/admin/rules", headers=headers, json=RULE_BODY).json()
    stale = client.put("/api/admin/rules/R-API-1/draft", headers=headers, json={
        "rule_version": "2026.09.02.1",
        "expect_edit_version": created["draft_edit_version"],
        "content": dict(RULE_BODY, message="第一次修改"),
    })
    assert stale.status_code == 200
    conflict = client.put("/api/admin/rules/R-API-1/draft", headers=headers, json={
        "rule_version": "2026.09.02.1",
        "expect_edit_version": created["draft_edit_version"],   # 旧锁
        "content": dict(RULE_BODY, message="旧锁写入"),
    })
    assert conflict.status_code == 409


def test_versions_diff_and_rollback_endpoints(stack):
    client, _, service = stack
    headers = _headers()
    for version, message in (("2026.09.02.1", "消息一"), ("2026.09.02.2", "消息二")):
        client.post("/api/admin/rules", headers=headers,
                    json=dict(RULE_BODY, version=version, message=message))
        client.post("/api/admin/rules/R-API-1/validate", headers=headers,
                    json={"rule_version": version})
        client.post("/api/admin/rules/R-API-1/approve", headers=headers,
                    json={"rule_version": version})
        client.post("/api/admin/rules/R-API-1/publish", headers=headers,
                    json={"rule_version": version})

    versions = client.get("/api/admin/rules/R-API-1/versions",
                          headers=headers).json()["items"]
    assert len(versions) == 2

    diff = client.get("/api/admin/rules/R-API-1/diff", headers=headers,
                      params={"version_a": "2026.09.02.1",
                              "version_b": "2026.09.02.2"}).json()
    assert "message" in diff["changed_keys"]

    rollback = client.post("/api/admin/rules/R-API-1/rollback", headers=headers,
                           json={"to_version": "2026.09.02.1",
                                 "reason": "接口回滚"})
    assert rollback.status_code == 200
    assert rollback.json()["to"] == "2026.09.02.1"


def test_destinations_crud_and_secret_guard(stack, monkeypatch):
    client, _, _ = stack
    monkeypatch.setenv("TEST_EMR_SECRET", "unit-secret")
    headers = _headers()
    created = client.post("/api/admin/destinations", headers=headers, json={
        "code": "emr_test", "kind": "emr", "enabled": False,
        "base_url": "http://127.0.0.1:9900", "endpoint": "/qc",
        "auth_type": "hmac_sha256", "secret_ref": "env:TEST_EMR_SECRET",
        "allow_insecure_internal_http": True,   # 127.0.0.1 内网 http 显式放行
    })
    assert created.status_code == 200
    assert created.json()["secret_configured"] is True

    # 空 secret_ref 不覆盖既有引用
    updated = client.post("/api/admin/destinations", headers=headers, json={
        "code": "emr_test", "base_url": "http://127.0.0.1:9901",
    }).json()
    assert updated["secret_ref"] == "env:TEST_EMR_SECRET"
    assert updated["base_url"] == "http://127.0.0.1:9901"
    # 明文密钥永不回显
    assert "secret" not in updated or updated.get("secret") is None

    # 契约测试：合成事件 + 阶段 A 只构造不发送
    contract = client.post("/api/admin/destinations/emr_test/contract-test",
                           headers=headers).json()
    assert contract["ok"] is True and contract["preview_only"] is True
    assert contract["event_type"] == "hospital_qc.contract_test"

    audits = client.get("/api/admin/audit", headers=headers,
                        params={"action": "contract_test"}).json()["items"]
    assert audits


def test_outbox_list_and_retry(stack):
    client, repo, _ = stack
    headers = _headers()
    repo.upsert_destination(code="dst", kind="mock", enabled=0,
                            base_url="http://127.0.0.1:1", endpoint="/x",
                            auth_type="none", secret_ref="",
                            max_attempts=1, allow_insecure_internal_http=1)
    row = repo.enqueue_outbox(event_id="evt-api-1", destination_code="dst",
                              payload_json="{}", idempotency_key="k")
    listing = client.get("/api/admin/outbox", headers=headers).json()["items"]
    assert any(item["event_id"] == "evt-api-1" for item in listing)

    # pending 不可 retry → 409；置 dead 后 retry 成功
    assert client.post("/api/admin/outbox/%s/retry" % row.id,
                       headers=headers).status_code == 409
    repo.finish_outbox(row.id, status="dead", error="test")
    ok = client.post("/api/admin/outbox/%s/retry" % row.id, headers=headers)
    assert ok.status_code == 200
    retry_only = _headers(perms="prearchive_delivery_retry")
    # 仅有 retry 权限者可重试但不能看规则列表
    assert client.get("/api/admin/rules",
                      headers=retry_only).status_code == 403


def test_fields_and_settings(stack):
    client, _, _ = stack
    headers = _headers()
    fields = client.get("/api/admin/fields", headers=headers).json()["items"]
    statuses = {f["status"] for f in fields}
    assert {"confirmed", "candidate", "blocked"} <= statuses
    blocked = [f for f in fields if f["status"] == "blocked"]
    assert all(not f["usable_for_publish"] for f in blocked)

    settings = client.get("/api/admin/settings", headers=headers).json()
    assert settings["mode"] == "file"
    assert settings["governance"]["action_policy"] == "notify_only"


def test_dry_run_uses_fixtures_not_real_db(stack):
    client, _, service = stack
    headers = _headers()
    client.post("/api/admin/rules", headers=headers, json=RULE_BODY)
    result = client.post("/api/admin/rules/R-API-1/dry-run", headers=headers,
                         json={"rule_version": "2026.09.02.1"}).json()
    assert result["ok"] is True
    assert isinstance(result["fixture_results"], list)
