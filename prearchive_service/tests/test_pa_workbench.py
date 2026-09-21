# -*- coding: utf-8 -*-
"""046 T5 核查工作台测试：issue 生命周期 / checks API / 权限矩阵 / 复检收敛。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from prearchive.closed_loop_api import create_closed_loop_router
from prearchive.closed_loop_models import IssueRow, RunRow
from prearchive.eval_store import EvalRunStore
from prearchive.issue_service import IssueConflictError, IssueService, issue_key_for
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import Actor, RuleService

from test_pa_closed_loop_api import ADMIN_TOKEN, SIGNING_SECRET

VIEW_PERMS = ("prearchive_rule_view,prearchive_check_view")
FULL_PERMS = ("prearchive_rule_view,prearchive_check_view,"
              "prearchive_issue_review,prearchive_issue_feedback,"
              "prearchive_match_run,prearchive_trial_manage")


@pytest.fixture()
def session_factory():
    return build_session_factory(build_sqlite_engine(":memory:"))


@pytest.fixture()
def stack(session_factory):
    repo = RuleRepository(session_factory)
    service = RuleService(repo)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file", "governance": {}}}
    app = FastAPI()
    app.include_router(create_closed_loop_router(config, session_factory, repo,
                                                 service))
    return TestClient(app), session_factory


def _headers(perms=FULL_PERMS, actor_id="admin-1", request_id="req-1"):
    from urllib.parse import quote
    from prearchive.admin_api import (
        ACTOR_ID_HEADER, ACTOR_NAME_HEADER, ACTOR_PERMS_HEADER,
        ACTOR_SIGNATURE_HEADER, ADMIN_TOKEN_HEADER, REQUEST_ID_HEADER,
        actor_signature,
    )
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


def _make_run(session_factory, *, patient="TEST0300", visit="1",
              fails=(("R-TIME-X", "admission-1", 14),), dept="D001",
              run_id=None):
    """造一个完成 run + fail 评估（走 EvalRunStore 真实路径）。"""
    from prearchive.rule_models import new_id
    store = EvalRunStore(session_factory)
    run = store.start_run(patient_id=patient, visit_number=visit,
                          trigger_type="paperless_rpa",
                          ruleset_revision="v1", dept_code=dept,
                          dept_name="普外科")
    evals = []
    for rule_id, event, fid in fails:
        evals.append({"rule_id": rule_id, "rule_version": "v1", "fid": fid,
                      "status": "pass" if fid is None else "fail",
                      "event_instance_id": event,
                      "reason_code": "time_limit", "evidence": {}})
    # 修正：fails 里指定 fail；额外 pass 一条
    evals = [{"rule_id": rid, "rule_version": "v1", "fid": fid,
              "status": "fail", "event_instance_id": event,
              "reason_code": "time_limit", "evidence": {"severity": "medium",
                                                        "message": "超时"}}
             for rid, event, fid in fails]
    evals.append({"rule_id": "R-OK-1", "rule_version": "v1", "fid": None,
                  "status": "pass", "event_instance_id": "admission-1",
                  "reason_code": "within_limit", "evidence": {}})
    store.record_evals(run.id, evals)
    store.finish_run(run.id, "completed",
                     {"fail_count": len(fails), "status": "fail"}, {})
    return run


# ---------------------------------------------------------------- issue 生命周期


def test_materialize_creates_stable_issues(session_factory):
    service = IssueService(session_factory)
    run = _make_run(session_factory)
    report = service.materialize_for_run(run.id)
    assert report["fail_keys"] == 1
    with session_factory() as session:
        rows = session.execute(select(IssueRow)).scalars().all()
    assert len(rows) == 1
    issue = rows[0]
    assert issue.issue_key == issue_key_for("TEST0300", "1", "R-TIME-X",
                                            "admission-1")
    assert issue.status == "open" and issue.is_trial == 0

    # 复检同 key 再 fail → 同一实例 last_seen 更新（不新建）
    run2 = _make_run(session_factory, run_id="r2")   # 同患者同就诊 → revision 2
    report2 = service.materialize_for_run(run2.id)
    assert report2["fail_keys"] == 1 and report2["resolved"] == 0
    with session_factory() as session:
        rows = session.execute(select(IssueRow)).scalars().all()
    assert len(rows) == 1 and rows[0].last_seen_run_id == run2.id
    assert rows[0].version >= 2


def test_materialize_resolves_when_fail_disappears(session_factory):
    service = IssueService(session_factory)
    run1 = _make_run(session_factory)
    service.materialize_for_run(run1.id)
    # 新 run 无该 fail（已整改）→ resolved + resolved_run_id
    store = EvalRunStore(session_factory)
    run2 = store.start_run(patient_id="TEST0300", visit_number="1",
                           trigger_type="manual_recheck", ruleset_revision="v2",
                           dept_code="D001")
    store.record_evals(run2.id, [
        {"rule_id": "R-TIME-X", "rule_version": "v2", "fid": 14,
         "status": "pass", "event_instance_id": "admission-1",
         "reason_code": "within_limit", "evidence": {}}])
    store.finish_run(run2.id, "completed", {"fail_count": 0, "status": "pass"}, {})
    report = service.materialize_for_run(run2.id)
    assert report["resolved"] == 1
    issue = service.list_issues(patient_id="TEST0300")[0]
    assert issue.status == "resolved" and issue.resolved_run_id == run2.id

    # 已解决后问题复现（第三轮又 fail）→ 重开
    run3 = _make_run(session_factory)   # revision 3，fail 回来
    service.materialize_for_run(run3.id)
    issue = service.list_issues(patient_id="TEST0300")[0]
    assert issue.status == "open"


def test_action_state_machine_and_optimistic_lock(session_factory):
    service = IssueService(session_factory)
    doctor = Actor(id="doc-1", name="医生甲", permissions=["prearchive_issue_feedback"])
    qc = Actor(id="qc-1", name="质控员", permissions=["prearchive_issue_review"])
    run = _make_run(session_factory)
    service.materialize_for_run(run.id)
    issue = service.list_issues()[0]
    version0 = issue.version

    # viewed → rectified（医生）
    row = service.apply_action(issue.id, action="viewed", operator=doctor)
    assert row.status == "viewed"
    row = service.apply_action(issue.id, action="rectified", operator=doctor,
                               reason="已补录文书", document_revision="rev-9")
    assert row.status == "rectifying"
    # rectifying 只允许 recheck_passed/manual_closed
    with pytest.raises(IssueConflictError):
        service.apply_action(issue.id, action="false_positive", operator=qc)
    # 乐观锁：旧 version 拒绝
    with pytest.raises(IssueConflictError):
        service.apply_action(issue.id, action="recheck_passed", operator=qc,
                             expect_issue_version=version0)
    row = service.apply_action(issue.id, action="recheck_passed", operator=qc,
                               expect_issue_version=row.version)
    assert row.status == "resolved"
    # manual_closed 原因必填
    issue2 = _make_run(session_factory, patient="TEST0301",
                       fails=(("R-TIME-Y", "admission-1", 34),))
    service.materialize_for_run(issue2.id)
    row2 = service.list_issues(patient_id="TEST0301")[0]
    with pytest.raises(IssueConflictError):
        service.apply_action(row2.id, action="manual_closed", operator=qc)
    row2 = service.apply_action(row2.id, action="manual_closed", operator=qc,
                                reason="豁免科室")
    assert row2.status == "manual_closed"
    # 动作历史 append-only
    actions = service.list_actions(issue.id)
    assert [a.action for a in actions] == ["viewed", "rectified", "recheck_passed"]


# ---------------------------------------------------------------- checks/issues API


def test_checks_list_and_detail(stack):
    client, session_factory = stack
    run = _make_run(session_factory)
    IssueService(session_factory).materialize_for_run(run.id)

    r = client.get("/api/admin/checks", headers=_headers())
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["patient_id"] == "TEST0300" and entry["open_issues"] == 1
    assert entry["summary"]["fail_count"] == 1

    # 科室过滤
    r = client.get("/api/admin/checks", headers=_headers(),
                   params={"dept_code": "D999"})
    assert r.json()["total"] == 0

    r = client.get(f"/api/admin/checks/{run.id}", headers=_headers())
    detail = r.json()
    assert detail["summary"]["fail_count"] == 1
    fail_clause = [c for c in detail["clauses"] if c["status"] == "fail"][0]
    assert fail_clause["fid"] == 14
    assert fail_clause["issue"]["status"] == "open"

    r = client.get("/api/admin/checks/missing", headers=_headers())
    assert r.status_code == 404


def test_issues_api_flow_with_permissions(stack):
    client, session_factory = stack
    run = _make_run(session_factory)
    IssueService(session_factory).materialize_for_run(run.id)
    issues = client.get("/api/admin/issues", headers=_headers()).json()["items"]
    assert len(issues) == 1
    issue_id = issues[0]["issue_id"]

    # 无 check_view 权限 → 403
    no_view = _headers(perms="prearchive_rule_view")
    assert client.get("/api/admin/issues", headers=no_view).status_code == 403

    # 医生（仅 feedback）：viewed/rectified 可以；终态动作 403
    doctor = _headers(perms="prearchive_rule_view,prearchive_check_view,"
                            "prearchive_issue_feedback", actor_id="doc-1")
    r = client.post(f"/api/admin/issues/{issue_id}/actions", headers=doctor,
                    json={"action": "viewed"})
    assert r.status_code == 200
    r = client.post(f"/api/admin/issues/{issue_id}/actions", headers=doctor,
                    json={"action": "rectified", "reason": "已整改"})
    assert r.status_code == 200
    r = client.post(f"/api/admin/issues/{issue_id}/actions", headers=doctor,
                    json={"action": "false_positive", "reason": "x"})
    assert r.status_code == 403, "终态动作需 issue_review"

    # 质控（review）：复检通过
    qc = _headers(perms="prearchive_rule_view,prearchive_check_view,"
                        "prearchive_issue_review", actor_id="qc-1")
    detail = client.get(f"/api/admin/issues/{issue_id}", headers=qc).json()
    r = client.post(f"/api/admin/issues/{issue_id}/actions", headers=qc,
                    json={"action": "recheck_passed",
                          "expect_issue_version": detail["version"]})
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    history = client.get(f"/api/admin/issues/{issue_id}", headers=qc).json()
    assert [a["action"] for a in history["actions"]] == \
           ["viewed", "rectified", "recheck_passed"]

    # 未知动作 → 409
    r = client.post(f"/api/admin/issues/{issue_id}/actions", headers=qc,
                    json={"action": "delete"})
    assert r.status_code == 409


def test_issue_action_requires_any_issue_permission(stack):
    client, _sf = stack
    viewer = _headers(perms="prearchive_rule_view,prearchive_check_view")
    r = client.post("/api/admin/issues/whatever/actions", headers=viewer,
                    json={"action": "viewed"})
    assert r.status_code == 403
