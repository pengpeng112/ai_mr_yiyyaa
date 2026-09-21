# -*- coding: utf-8 -*-
"""046 T7 JHEMR 集成内部 API 测试（L1 本地 Mock 验收的核心面）。

覆盖：submission-checks 幂等创建/异步执行/T7.1 完整汇总（queued=null+provisional、
completed=计数守恒）、rechecks 同锚点新 revision、view-tickets 一次性票据、
issue feedback 幂等+版本+不改判、鉴权矩阵。执行通道=fixtures（零真实库）。
"""

import json
from pathlib import Path

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
from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.delivery_wiring import DeliveryGovernance, ResultEventEmitter
from prearchive.engine import RuleEngine
from prearchive.eval_store import EvalRunStore
from prearchive.fixture_sources import build_demo_fixtures
from prearchive.integration_api import create_integration_router
from prearchive.issue_service import IssueService
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.pusher import WeComPusher
from prearchive.rule_repository import RuleRepository
from prearchive.rules import load_rules, rules_version
from prearchive.store import ResultRepository
from prearchive.trigger import PrecheckProcessor

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"
ADMIN_TOKEN = "unit-admin-token"
SIGNING_SECRET = "unit-signing-secret"
PERMS_INT = ("prearchive_check_view,prearchive_issue_feedback")
PERMS_VIEW_ONLY = "prearchive_rule_view"


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


@pytest.fixture()
def stack(tmp_path):
    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    rules = load_rules(RULES_FILE)
    engine = RuleEngine(rules, rule_version=rules_version(RULES_FILE))
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    rule_repo = RuleRepository(session_factory)
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    processor = PrecheckProcessor(
        builder, engine, ResultRepository(session_factory), pusher,
        eval_store=EvalRunStore(session_factory),
        trigger_type="finished",
        issue_service=IssueService(session_factory),
        delivery_emitter=ResultEventEmitter(
            rule_repo, DeliveryGovernance(enabled=False)))
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "jhemr_integration": {"ticket_ttl_seconds": 300}}
    app = FastAPI()
    app.include_router(create_integration_router(
        config, session_factory, rule_repo, processor))
    return {"client": TestClient(app), "sf": session_factory,
            "rule_repo": rule_repo, "gateways": gateways}


def _headers(perms=PERMS_INT, actor_id="jhemr-svc", request_id="req-1"):
    from urllib.parse import quote
    name = quote("集成服务", safe="")
    return {
        ADMIN_TOKEN_HEADER: ADMIN_TOKEN,
        ACTOR_ID_HEADER: actor_id,
        ACTOR_NAME_HEADER: name,
        ACTOR_PERMS_HEADER: perms,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: actor_signature(
            SIGNING_SECRET, actor_id, name, perms, request_id),
    }


def _submission_body(submission_id="SUB-001", patient="TEST0002"):
    return {"request_id": "req-jhemr-001", "patient_id": patient,
            "visit_number": "1",
            "operator": {"id": "DOC77", "name": "测试医生"},
            "dept": "D002", "submission_id": submission_id,
            "document_refs": [{"doc_id": "DOC-1", "revision": "r3"}],
            "submitted_at": "2026-09-11 10:00:00"}


# ---------------------------------------------------------------- 鉴权

def test_auth_and_permission_matrix(stack):
    client = stack["client"]
    body = _submission_body()
    assert client.post("/api/integration/jhemr/submission-checks",
                       json=body).status_code == 401            # 无 token
    assert client.post("/api/integration/jhemr/submission-checks",
                       json=body,
                       headers=_headers(perms=PERMS_VIEW_ONLY)
                       ).status_code == 403                     # 无 check_view
    assert client.get("/api/integration/jhemr/submission-checks/missing",
                      headers=_headers(perms=PERMS_VIEW_ONLY)
                      ).status_code == 403


# ---------------------------------------------------------------- submission-checks

def test_submission_check_create_idempotent_and_execute(stack):
    client = stack["client"]
    body = _submission_body("SUB-100")
    response = client.post("/api/integration/jhemr/submission-checks",
                           json=body, headers=_headers())
    assert response.status_code == 202
    created = response.json()
    assert created["status"] in ("queued", "running", "completed")
    assert created["submission_policy"] == "notify_only"

    # 幂等：同 submission_id 未终态复用同一 check
    again = client.post("/api/integration/jhemr/submission-checks",
                        json=body, headers=_headers(request_id="req-2"))
    assert again.status_code == 200 and again.json()["reused"] is True
    assert again.json()["check_id"] == created["check_id"]

    # TestClient 同步执行 BackgroundTasks → 检查已完成
    check = client.get(f"/api/integration/jhemr/submission-checks/"
                       f"{created['check_id']}", headers=_headers()).json()
    assert check["status"] in ("completed", "partial")
    assert check["trigger_type"] == "emr_submit"
    assert check["submission_id"] == "SUB-100"
    assert check["submission_policy"] == "notify_only"
    summary = check["summary"]
    # T7.1 计数守恒（不用全 0 伪装；unknown/pending 如实计数）
    assert summary["applicable_count"] == (summary["pass_count"]
                                           + summary["fail_count"]
                                           + summary["unknown_count"]
                                           + summary["pending_count"])
    assert summary["rule_instance_count"] == (summary["applicable_count"]
                                              + summary["excluded_count"])
    assert summary["evaluated_count"] == (summary["pass_count"]
                                          + summary["fail_count"])
    assert summary["provisional"] is False
    assert summary["catalog_count"] == 92
    # 李某（D002）检查出缺陷：issues 非空且带条款引用
    assert check["issues"], "issues must be returned, not only summary"
    assert all("rule_id" in i and "status" in i for i in check["issues"])
    assert check["subject"]["patient_id"] == "TEST0002"
    assert check["source_health"]        # 源健康面必须返回


def test_submission_check_unknown_patient_404(stack):
    client = stack["client"]
    response = client.post(
        "/api/integration/jhemr/submission-checks",
        json=_submission_body("SUB-404", patient="NO_SUCH"),
        headers=_headers())
    assert response.status_code == 404


def test_submission_check_missing_fields_422(stack):
    client = stack["client"]
    body = _submission_body("SUB-422")
    body.pop("submission_id")
    assert client.post("/api/integration/jhemr/submission-checks",
                       json=body, headers=_headers()).status_code == 422
    body = _submission_body("SUB-422b")
    body.pop("patient_id")
    assert client.post("/api/integration/jhemr/submission-checks",
                       json=body, headers=_headers()).status_code == 422


def test_queued_view_returns_null_counts_and_provisional(stack):
    """queued 阶段：未定计数 null + provisional=true（占位 run 不执行直接查）。"""
    from prearchive.closed_loop_models import RunRow
    from sqlalchemy import select
    client, sf = stack["client"], stack["sf"]
    # 直接落一个 queued 占位（模拟后台任务尚未执行）
    with sf() as session:
        run = RunRow(id="placeholdercheck0001", run_revision=1,
                     patient_id="TEST0002", visit_number="1",
                     trigger_type="emr_submit", submission_id="SUB-Q",
                     status="queued")
        session.add(run)
        session.commit()
    view = client.get("/api/integration/jhemr/submission-checks/"
                      "placeholdercheck0001", headers=_headers()).json()
    assert view["status"] == "queued"
    summary = view["summary"]
    for field in ("fail_count", "pass_count", "unknown_count",
                  "pending_count", "rule_instance_count", "issue_count",
                  "evaluation_coverage_pct", "data_coverage_pct"):
        assert summary[field] is None, f"{field} must be null while queued"
    assert summary["provisional"] is True
    assert view["issues"] is None and view["source_health"] is None


# ---------------------------------------------------------------- rechecks

def test_recheck_same_anchor_new_revision(stack):
    client = stack["client"]
    first = client.post(
        "/api/integration/jhemr/submission-checks",
        json=_submission_body("SUB-200"), headers=_headers()).json()
    recheck = client.post(
        "/api/integration/jhemr/rechecks",
        json={"patient_id": "TEST0002", "visit_number": "1",
              "operator": {"id": "DOC77", "name": "测试医生"},
              "reason": "医生已补出院记录", "issue_ids": []},
        headers=_headers(request_id="req-3"))
    assert recheck.status_code == 202
    check_id = recheck.json()["check_id"]
    view = client.get(f"/api/integration/jhemr/submission-checks/{check_id}",
                      headers=_headers()).json()
    first_view = client.get(
        f"/api/integration/jhemr/submission-checks/{first['check_id']}",
        headers=_headers()).json()
    # 原锚点未变也生成新 revision（046 §5.2.4）
    assert view["run_revision"] == first_view["run_revision"] + 1
    assert view["trigger_type"] == "manual_recheck"
    assert view["check_id"] != first["check_id"]


# ---------------------------------------------------------------- view tickets

def test_view_ticket_lifecycle_one_time(stack):
    client = stack["client"]
    created = client.post(
        "/api/integration/jhemr/view-tickets",
        json={"patient_id": "TEST0002", "visit_number": "1",
              "operator_id": "DOC77", "scope": "issue_view"},
        headers=_headers()).json()
    nonce = created["ticket_nonce"]
    assert nonce and created["scope"] == "issue_view"

    ok = client.post(f"/api/integration/jhemr/view-tickets/{nonce}/redeem",
                     json={"operator_id": "DOC77"}, headers=_headers())
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["patient_id"] == "TEST0002"
    assert payload["operator_id"] == "DOC77"

    replay = client.post(f"/api/integration/jhemr/view-tickets/{nonce}/redeem",
                         json={"operator_id": "DOC77"}, headers=_headers())
    assert replay.status_code == 409                  # 一次性

    other = client.post(
        "/api/integration/jhemr/view-tickets",
        json={"patient_id": "TEST0002", "visit_number": "1",
              "operator_id": "DOC88"}, headers=_headers()).json()
    bound = client.post(
        f"/api/integration/jhemr/view-tickets/{other['ticket_nonce']}/redeem",
        json={"operator_id": "DOC77"}, headers=_headers())
    assert bound.status_code == 403                   # 绑定操作者不匹配


def test_view_ticket_expired_rejected(stack):
    from datetime import datetime, timedelta
    from prearchive.closed_loop_models import ViewTicketRow
    client, sf = stack["client"], stack["sf"]
    with sf() as session:
        session.add(ViewTicketRow(
            id="expiredticket000001", nonce="nonce-expired",
            patient_id="TEST0002", visit_number="1", operator_id="DOC77",
            scope="issue_view", expires_at=datetime.now() - timedelta(seconds=1),
            issued_by="test"))
        session.commit()
    response = client.post(
        "/api/integration/jhemr/view-tickets/nonce-expired/redeem",
        json={"operator_id": "DOC77"}, headers=_headers())
    assert response.status_code == 403


# ---------------------------------------------------------------- issue feedback

def _first_open_issue(stack):
    service = IssueService(stack["sf"])
    issues = service.list_issues(patient_id="TEST0002")
    assert issues, "precondition: run a check first"
    return issues[0]


def test_issue_feedback_flow_and_version_lock(stack):
    client = stack["client"]
    client.post("/api/integration/jhemr/submission-checks",
                json=_submission_body("SUB-300"), headers=_headers())
    issue = _first_open_issue(stack)

    seen = client.post(
        f"/api/integration/jhemr/issues/{issue.id}/feedback",
        json={"action": "viewed", "operator": {"id": "DOC77", "name": "医生"},
              "expect_issue_version": int(issue.version or 1)},
        headers=_headers())
    assert seen.status_code == 200
    assert seen.json()["status"] == "viewed"
    assert seen.json()["issue_version"] == int(issue.version or 1) + 1

    # 版本冲突 → 409（乐观锁）
    conflict = client.post(
        f"/api/integration/jhemr/issues/{issue.id}/feedback",
        json={"action": "rectified", "operator": {"id": "DOC77"},
              "expect_issue_version": int(issue.version or 1)},
        headers=_headers(request_id="req-c"))
    assert conflict.status_code == 409

    # 「已整改」不把机器判定改成通过：rectifying 等复检
    rectified = client.post(
        f"/api/integration/jhemr/issues/{issue.id}/feedback",
        json={"action": "rectified", "operator": {"id": "DOC77"},
              "expect_issue_version": int(issue.version or 1) + 1,
              "reason": "已补记"},
        headers=_headers(request_id="req-d"))
    assert rectified.status_code == 200
    assert rectified.json()["status"] == "rectifying"
    assert not rectified.json().get("resolved_run_id")


def test_issue_feedback_unknown_issue_and_action(stack):
    client = stack["client"]
    assert client.post("/api/integration/jhemr/issues/missing/feedback",
                       json={"action": "viewed"}, headers=_headers()
                       ).status_code == 404
    client.post("/api/integration/jhemr/submission-checks",
                json=_submission_body("SUB-301"), headers=_headers())
    issue = _first_open_issue(stack)
    assert client.post(
        f"/api/integration/jhemr/issues/{issue.id}/feedback",
        json={"action": "not_an_action"}, headers=_headers()
    ).status_code == 409


# ---------------------------------------------------------------- 落库与审计

def test_check_writes_run_eval_result_and_audit(stack):
    """集成检查走主链路：RUN/RULE_EVAL/RESULT 全落库；审计动作可查。"""
    from prearchive.closed_loop_models import RuleEvalRow
    from sqlalchemy import select
    client, sf, rule_repo = (stack["client"], stack["sf"],
                             stack["rule_repo"])
    created = client.post(
        "/api/integration/jhemr/submission-checks",
        json=_submission_body("SUB-400"), headers=_headers()).json()
    with sf() as session:
        evals = session.execute(select(RuleEvalRow).where(
            RuleEvalRow.run_id == created["check_id"])).scalars().all()
        assert evals, "RULE_EVAL must be recorded via main pipeline"
    audits = rule_repo.list_audit(action="jhemr_submission_check")
    assert any(a.detail_json and "SUB-400" in a.detail_json
               for a in audits)


def test_recheck_after_rectification_collects_issue(stack):
    """复检（同锚点）后 ISSUE 物化收敛：fail 消失 → resolved。"""
    client, gateways = stack["client"], stack["gateways"]
    client.post("/api/integration/jhemr/submission-checks",
                json=_submission_body("SUB-500"), headers=_headers())
    issues = IssueService(stack["sf"]).list_issues(patient_id="TEST0002")
    assert issues and all(i.status == "open" for i in issues)

    # 整改：补出院记录 + 锚点前移 + 源新鲜度推进（与 T6 测试同一现实口径）
    for row in gateways["jhemr"].pat_visits:
        if row["patient_id"] == "TEST0002":
            row["finished_date_time"] = "2026-08-27 12:00:00"
    gateways["jhemr"].blws["TEST0002|1"].append({
        "progress_template_name": "出院记录", "progress_status": "完成",
        "record_time": "2026-08-27 09:00:00",
        "finished_time": "2026-08-27 09:00:00",
        "update_time": "2026-08-27 12:06:00"})
    for gw_key in ("his", "lis", "sm"):
        for entry in gateways[gw_key].itf_entries:
            if entry.get("PATIENTID") == "TEST0002":
                entry["FUPDATE"] = "2026-08-27 12:06:00"

    recheck = client.post(
        "/api/integration/jhemr/rechecks",
        json={"patient_id": "TEST0002", "visit_number": "1",
              "operator": {"id": "DOC77"}, "reason": "补出院记录后复检"},
        headers=_headers(request_id="req-5"))
    assert recheck.status_code == 202
    issues_after = IssueService(stack["sf"]).list_issues(patient_id="TEST0002")
    resolved = [i for i in issues_after if i.status == "resolved"]
    assert len(resolved) == 1
    assert resolved[0].rule_id == "R-TIME-DISCHARGE-RECORD-24H"
