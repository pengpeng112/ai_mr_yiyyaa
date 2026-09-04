# -*- coding: utf-8 -*-
"""041 T5：demo 规则仓导入 + 生命周期 HTTP 冒烟（线程内 TestClient，零网络）。

覆盖：import-files 导入 14 条 mark_item 正式规则（system_push 0 条业务规则）、
完整 Admin-Token + Actor 四件套 + HMAC 鉴权（只带 token=401、缺权限=403）、
validate/approve/publish/rollback 指针流转、dry-run 仅 fixtures（PHI 哨兵：
患者 ID 全部 TEST 前缀合成、无内网地址渗入）、审计留痕含签名 actor 真名。
"""
import json
from pathlib import Path
from urllib.parse import quote

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
    actor_signature,
    create_admin_router,
)
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import Actor, RuleService

ADMIN_TOKEN = "demo-admin-token"
SIGNING_SECRET = "demo-admin-signing-secret"
RULES_DIR = Path(__file__).resolve().parents[1] / "rules"
ALL_PERMS = ("prearchive_rule_view,prearchive_rule_edit,prearchive_rule_approve,"
             "prearchive_rule_publish,prearchive_integration_manage,"
             "prearchive_delivery_retry")
VIEW_ONLY = "prearchive_rule_view"


def _headers(actor_id="demo-admin", actor_name="管理员", perms=ALL_PERMS,
             request_id="req-lc-1", token=ADMIN_TOKEN):
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


@pytest.fixture()
def stack():
    repo = RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))
    service = RuleService(repo)
    # 导入与 rule_admin CLI 同源：example（14 条）+ system_push（0 条业务规则）
    report = service.import_files(
        [str(RULES_DIR / "example_rules.json"),
         str(RULES_DIR / "system_push_rules.json")],
        apply=True, actor=Actor(id="cli:rule_admin", name="rule_admin"),
        domain_map={"system_push_rules.json": "system_push",
                    "example_rules.json": "medical_record"},
        origin_map={"system_push_rules.json": "system_push",
                    "example_rules.json": "paperless_t_mark_item"})
    assert report["errors"] == [] and report["conflicts"] == []

    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file",
                                "require_separate_approver": False}}
    app = FastAPI()
    app.include_router(create_admin_router(config, repo, service))
    return TestClient(app), repo, service, report


def test_import_brought_14_mark_item_and_zero_system_push(stack):
    client, repo, _, report = stack
    assert report["created"] == 14          # mark_item 正式规则 14 条首次落库
    rules = client.get("/api/admin/rules", headers=_headers()).json()
    items = rules["items"]
    assert len(items) == 14
    assert all(item["domain"] == "medical_record" for item in items)
    system_push = client.get("/api/admin/rules?domain=system_push",
                             headers=_headers()).json()
    assert system_push["items"] == []       # system_push 无业务规则（通道保留）


def test_auth_requires_full_actor_quartet_not_token_alone(stack):
    client, _, _, _ = stack
    # 只带 Admin-Token、不带 Actor 四件套+HMAC → 401（041 T1 --check 口径）
    token_only = {ADMIN_TOKEN_HEADER: ADMIN_TOKEN}
    assert client.get("/api/admin/settings", headers=token_only).status_code == 401
    # 无 view 权限者连 settings 都 403
    no_view = _headers(perms="prearchive_rule_edit")
    assert client.get("/api/admin/settings", headers=no_view).status_code == 403
    # view-only 可读不可写
    viewer = _headers(perms=VIEW_ONLY)
    assert client.get("/api/admin/rules", headers=viewer).status_code == 200
    body = {"rule_id": "R-X", "name": "x", "message": "m", "type": "empty_field",
            "fields": ["过敏史"], "version": "2026.09.04.1"}
    assert client.post("/api/admin/rules", headers=viewer,
                       json=body).status_code == 403


DRAFT_BODY = {
    "rule_id": "R-DEMO-LC", "name": "生命周期冒烟规则", "message": "demo 缺失提示",
    "type": "empty_field", "fields": ["过敏史"], "version": "2026.09.04.1",
    "severity": "medium", "enabled": True,
    "_domain": "medical_record", "_track": "main", "_origin": "manual",
}


def _create_draft_version(client, headers, version):
    body = {**DRAFT_BODY, "version": version}
    made = client.post("/api/admin/rules", headers=headers, json=body)
    assert made.status_code == 200, made.text
    return made.json()


def test_lifecycle_validate_approve_publish_rollback_pointers(stack):
    """导入的 14 条为 published 原样落库；新草稿走 draft→validated→approved→published。"""
    client, repo, _, _ = stack
    headers = _headers()
    imported = client.get("/api/admin/rules", headers=headers).json()["items"]
    assert len(imported) == 14
    assert all(item["status"] == "published" for item in imported)

    rule_key = DRAFT_BODY["rule_id"]
    _create_draft_version(client, headers, "2026.09.04.1")

    validated = client.post(f"/api/admin/rules/{rule_key}/validate", headers=headers,
                            json={"rule_version": "2026.09.04.1"})
    assert validated.status_code == 200
    approved = client.post(f"/api/admin/rules/{rule_key}/approve", headers=headers,
                           json={"rule_version": "2026.09.04.1", "reason": "demo 冒烟"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    published = client.post(f"/api/admin/rules/{rule_key}/publish", headers=headers,
                            json={"rule_version": "2026.09.04.1", "reason": "demo 冒烟"})
    assert published.status_code == 200
    pointer = {p.rule_key: p.published_version for p in repo.list_pointers()}
    assert pointer.get(rule_key) == "2026.09.04.1"

    versions = client.get(f"/api/admin/rules/{rule_key}/versions",
                          headers=headers).json()["items"]
    assert len(versions) >= 1
    diff = client.get(f"/api/admin/rules/{rule_key}/diff",
                      params={"version_a": "2026.09.04.1", "version_b": "2026.09.04.1"},
                      headers=headers)
    assert diff.status_code == 200
    assert diff.json()["changed_keys"] == []


def test_rollback_moves_pointer_back(stack):
    client, repo, _, _ = stack
    headers = _headers()
    rule_key = DRAFT_BODY["rule_id"]
    for version in ("2026.09.04.1", "2026.09.04.2"):
        _create_draft_version(client, headers, version)
        for step in ("approve", "publish"):
            made = client.post(f"/api/admin/rules/{rule_key}/{step}", headers=headers,
                               json={"rule_version": version, "reason": "demo"})
            assert made.status_code == 200, (step, version, made.text)
    pointer = {p.rule_key: p.published_version for p in repo.list_pointers()}
    assert pointer.get(rule_key) == "2026.09.04.2"   # 双发布后指针在 v2

    rolled = client.post(f"/api/admin/rules/{rule_key}/rollback", headers=headers,
                         json={"to_version": "2026.09.04.1", "reason": "demo 回滚"})
    assert rolled.status_code == 200, rolled.text
    pointer = {p.rule_key: p.published_version for p in repo.list_pointers()}
    assert pointer.get(rule_key) == "2026.09.04.1"   # 指针已回到 v1


def test_dry_run_uses_only_synthetic_fixtures_no_real_patients(stack):
    client, _, _, _ = stack
    headers = _headers()
    row = client.get("/api/admin/rules", headers=headers).json()["items"][0]
    rule_key, rule_version = row["rule_key"], row["rule_version"]
    result = client.post(f"/api/admin/rules/{rule_key}/dry-run", headers=headers,
                         json={"rule_version": rule_version})
    assert result.status_code == 200
    payload = result.json()
    assert payload.get("ok") is True, payload
    # PHI 哨兵：dry-run 只允许 demo fixtures 的 TEST 前缀合成患者
    assert payload["fixture_results"], "fixtures 至少评估一名合成患者"
    for item in payload["fixture_results"]:
        assert str(item["patient_id"]).startswith("TEST"), item
        assert "10." not in json.dumps(item), item   # 无内网地址渗入结果


def test_audit_trail_records_signed_actor_with_decoded_name(stack):
    client, _, _, _ = stack
    headers = _headers(actor_id="demo-admin", actor_name="审计员甲",
                       request_id="req-audit-1")
    rule_key = DRAFT_BODY["rule_id"]
    _create_draft_version(client, headers, "2026.09.04.1")
    approved = client.post(f"/api/admin/rules/{rule_key}/approve",
                           headers=headers,
                           json={"rule_version": "2026.09.04.1", "reason": "冒烟"})
    assert approved.status_code == 200, approved.text
    audit = client.get("/api/admin/audit", headers=headers).json()
    assert audit["items"], "生命周期必须留痕"
    mine = [e for e in audit["items"] if e["request_id"] == "req-audit-1"]
    assert mine, "按 request_id 追溯本次操作"
    assert mine[0]["actor_name"] == "审计员甲"      # percent-encode 解码后落审计
    assert mine[0]["actor_id"] == "demo-admin"
