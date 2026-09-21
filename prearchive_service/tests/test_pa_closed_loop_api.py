# -*- coding: utf-8 -*-
"""046 T1a 闭环 API 契约测试：覆盖账本 / AI 匹配 / trial 申请（HTTP 层）。

同一鉴权口径（admin token + actor 签名）；权限矩阵生效；trial 仅落申请契约。
"""

import json

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
)
from prearchive.closed_loop_api import create_closed_loop_router
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import RuleService

ADMIN_TOKEN = "unit-admin-token"
SIGNING_SECRET = "unit-signing-secret"
PERMS_ALL = ("prearchive_rule_view,prearchive_rule_edit,prearchive_rule_approve,"
             "prearchive_rule_publish,prearchive_integration_manage,"
             "prearchive_delivery_retry,prearchive_match_run,"
             "prearchive_trial_manage")
PERMS_VIEW_ONLY = "prearchive_rule_view"


@pytest.fixture()
def stack():
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    repo = RuleRepository(session_factory)
    service = RuleService(repo)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file", "governance": {}}}
    app = FastAPI()
    app.include_router(create_closed_loop_router(config, session_factory, repo,
                                                 service))
    return TestClient(app), repo, session_factory


def _headers(perms=PERMS_ALL, actor_id="admin-1", request_id="req-1"):
    from urllib.parse import quote
    name = quote("管理员", safe="")
    return {
        ADMIN_TOKEN_HEADER: ADMIN_TOKEN,
        ACTOR_ID_HEADER: actor_id,
        ACTOR_NAME_HEADER: name,
        ACTOR_PERMS_HEADER: perms,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: actor_signature(
            SIGNING_SECRET, actor_id, name, perms, request_id),
    }


# ---------------------------------------------------------------- 鉴权


def test_auth_required(stack):
    client, _repo, _sf = stack
    assert client.get("/api/admin/coverage").status_code == 401       # 无 token
    bad = _headers()
    bad[ADMIN_TOKEN_HEADER] = "wrong"
    assert client.get("/api/admin/coverage", headers=bad).status_code == 401
    bad_sig = _headers()
    bad_sig[ACTOR_SIGNATURE_HEADER] = "0" * 64
    assert client.get("/api/admin/coverage", headers=bad_sig).status_code == 401


def test_permission_matrix_enforced(stack):
    client, _repo, _sf = stack
    viewer = _headers(perms=PERMS_VIEW_ONLY)
    assert client.get("/api/admin/coverage", headers=viewer).status_code == 200
    assert client.post("/api/admin/match/tasks", headers=viewer,
                       json={}).status_code == 403
    assert client.post("/api/admin/trial/runs", headers=viewer,
                       json={"fids": [1]}).status_code == 403
    assert client.post("/api/admin/coverage/import-snapshot", headers=viewer,
                       json={}).status_code == 403


# ---------------------------------------------------------------- 覆盖账本


def test_coverage_import_list_confirm_export(stack):
    client, repo, _sf = stack
    r = client.post("/api/admin/coverage/import-snapshot",
                    headers=_headers(), json={"apply": True})
    assert r.status_code == 200
    body = r.json()
    assert body["catalog_created"] == 92

    r = client.get("/api/admin/coverage", headers=_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 92
    assert data["counts"]["catalog_count"] == 92

    r = client.post("/api/admin/coverage/57/confirm", headers=_headers(),
                    json={"reason": "人工核对完成"})
    assert r.status_code == 200 and r.json()["confirmed_rows"] >= 1
    r = client.get("/api/admin/coverage", headers=_headers(),
                   params={"fid": 57})
    assert r.json()["items"][0]["status"] == "confirmed"

    r = client.get("/api/admin/coverage/export", headers=_headers())
    assert r.status_code == 200 and r.json()["total"] == 92
    actions = [a.action for a in repo.list_audit(limit=50)]
    assert "coverage_import" in actions and "coverage_export" in actions


def test_coverage_search_and_filters(stack):
    client, _repo, _sf = stack
    client.post("/api/admin/coverage/import-snapshot", headers=_headers(),
                json={"apply": True})
    r = client.get("/api/admin/coverage", headers=_headers(),
                   params={"method": "data_blocked"})
    assert all(
        all(c["method"] == "data_blocked" for c in e["clauses"])
        for e in r.json()["items"]) and r.json()["total"] > 0
    r = client.get("/api/admin/coverage", headers=_headers(),
                   params={"q": "手术"})
    assert r.json()["total"] >= 1


# ---------------------------------------------------------------- AI 匹配


def test_match_task_full_http_flow(stack):
    client, _repo, _sf = stack
    client.post("/api/admin/coverage/import-snapshot", headers=_headers(),
                json={"apply": True})
    r = client.post("/api/admin/match/tasks", headers=_headers(),
                    json={"fids": [38, 41]})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    assert r.json()["status"] == "pending"

    r = client.post(f"/api/admin/match/tasks/{task_id}/run", headers=_headers())
    assert r.status_code == 200
    assert r.json()["status"] in ("completed", "partial")   # stub 无故障注入时完成

    r = client.get(f"/api/admin/match/tasks/{task_id}", headers=_headers())
    data = r.json()
    assert data["task_id"] == task_id
    fid38 = [c for c in data["candidates"] if c["fid"] == 38
             and c["clause_id"] == "FID38-C1"]
    assert fid38 and fid38[0]["validation_ok"] is True

    if fid38:
        r = client.post(f"/api/admin/match/candidates/{fid38[0]['candidate_id']}/decision",
                        headers=_headers(),
                        json={"decision": "accepted", "note": "采纳候选"})
        assert r.status_code == 200 and r.json()["decision"] == "accepted"
    # 非法决策
    r = client.post(f"/api/admin/match/candidates/{fid38[0]['candidate_id']}/decision",
                    headers=_headers(), json={"decision": "maybe"})
    assert r.status_code == 409


def test_match_task_cancel_and_404(stack):
    client, _repo, _sf = stack
    r = client.post("/api/admin/match/tasks/missing/run", headers=_headers())
    assert r.status_code == 404
    r = client.post("/api/admin/match/tasks", headers=_headers(),
                    json={"fids": [38]})
    task_id = r.json()["task_id"]
    r = client.post(f"/api/admin/match/tasks/{task_id}/cancel", headers=_headers())
    assert r.status_code == 200 and r.json()["status"] == "cancelled"


def test_match_unknown_fid_422(stack):
    client, _repo, _sf = stack
    r = client.post("/api/admin/match/tasks", headers=_headers(),
                    json={"fids": [9999]})
    assert r.status_code == 422 and "unknown fids" in r.json()["detail"]


# ---------------------------------------------------------------- trial 申请契约


def test_trial_run_request_contract(stack):
    client, repo, _sf = stack
    r = client.post("/api/admin/trial/runs", headers=_headers(),
                    json={"rule_keys": [{"rule_key": "R-TIME-ADMISSION-RECORD-24H",
                                         "rule_version": "v1"}],
                          "fids": [14],
                          "scope": {"dept_codes": ["TEST"], "synthetic_only": True},
                          "reason": "首轮观察"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "requested" and data["trigger_type"] == "trial"
    assert data["payload"]["fids"] == [14]
    assert data["scope"]["synthetic_only"] is True

    # 持久化契约：RunRow is_trial=1 / requested / 载荷可回读
    from prearchive.closed_loop_models import RunRow
    with _sf() as session:
        from sqlalchemy import select
        rows = session.execute(select(RunRow).where(
            RunRow.id == data["trial_run_id"])).scalars().all()
        assert rows and rows[0].is_trial == 1
        assert rows[0].status == "requested"
        assert json.loads(rows[0].trial_rules_json)["fids"] == [14]
    # 空申请拒绝
    r = client.post("/api/admin/trial/runs", headers=_headers(), json={})
    assert r.status_code == 422
    # 审计留痕
    actions = [a.action for a in repo.list_audit(limit=20)]
    assert "trial_create" in actions


def test_trial_runs_listing(stack):
    client, _repo, _sf = stack
    client.post("/api/admin/trial/runs", headers=_headers(),
                json={"fids": [14], "scope": {}})
    r = client.get("/api/admin/trial/runs", headers=_headers())
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
    assert r.json()["items"][0]["trial_rules"]["fids"] == [14]
