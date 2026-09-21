# -*- coding: utf-8 -*-
"""050 T2 D-J1 契约测试：终态与 issue 物化的顺序一致性。

D-J1（049 §4）：trigger.process 原先先 finish_run（置 completed）后
materialize_for_run，JHEMR GET 轮询方在 completed 后毫秒级窗口内可能读到
issues 空/不齐（L1 实测 first observed=0、稳定态=4）。050 §0.1-1 契约：
run 状态首次变为 completed/partial 起，GET 的 issues 已含本次 run 的物化
结果（本次 fail evals 去重 keys ⊆ GET keys）；物化失败不得发布 completed
（内联重试一次→仍败降级 partial+诊断标记）。

- test_materialize_precedes_finish_run：spy finish_run，物化必须已发生
  （旧代码必 FAIL=复现证据；A 案修复后 PASS）。
- test_http_first_query_contract：完成后 GET 与库内物化状态一致（防回归）。
  注（050 T2.3）：TestClient 同步执行 BackgroundTasks，旧代码该测试同样
  通过——仅作防回归，D-J1 复现证据只认 spy 测试与 L1 first==stable。
- test_materialize_failure_downgrades_run：故障注入（物化始终抛异常）→
  run 不得为 completed，须 partial 且 source_health 含 issues_materialization。
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from prearchive.admin_api import (
    ACTOR_ID_HEADER, ACTOR_NAME_HEADER, ACTOR_PERMS_HEADER,
    ACTOR_SIGNATURE_HEADER, ADMIN_TOKEN_HEADER, REQUEST_ID_HEADER,
    actor_signature,
)
from prearchive.collectors import (
    HisCollector, JhemrCollector, LisCollector, PatientContextBuilder, SmCollector,
)
from prearchive.closed_loop_models import IssueRow, RunRow
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
PERMS_INT = "prearchive_check_view,prearchive_issue_feedback"


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


class SpyEvalRunStore(EvalRunStore):
    """finish_run 前快照该 run 已物化的 issue 数（D-J1 顺序判据）。"""

    def __init__(self, session_factory):
        super().__init__(session_factory)
        self.issues_at_finish = {}

    def finish_run(self, run_id, *args, **kwargs):
        with self.session_factory() as session:
            n = session.execute(
                select(func.count()).select_from(IssueRow).where(
                    IssueRow.last_seen_run_id == run_id,
                    IssueRow.is_trial == 0)).scalar_one()
        self.issues_at_finish[run_id] = n
        return super().finish_run(run_id, *args, **kwargs)


def _build_stack():
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
    store = SpyEvalRunStore(session_factory)
    processor = PrecheckProcessor(
        builder, engine, ResultRepository(session_factory), pusher,
        eval_store=store, trigger_type="finished",
        issue_service=IssueService(session_factory),
        delivery_emitter=ResultEventEmitter(
            rule_repo, DeliveryGovernance(enabled=False)))
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "jhemr_integration": {"ticket_ttl_seconds": 300}}
    app = FastAPI()
    app.include_router(create_integration_router(
        config, session_factory, rule_repo, processor))
    return {"client": TestClient(app), "sf": session_factory, "store": store,
            "processor": processor}


def _headers(request_id="req-1"):
    from urllib.parse import quote
    name = quote("集成服务", safe="")
    return {
        ADMIN_TOKEN_HEADER: ADMIN_TOKEN,
        ACTOR_ID_HEADER: "jhemr-svc",
        ACTOR_NAME_HEADER: name,
        ACTOR_PERMS_HEADER: PERMS_INT,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: actor_signature(
            SIGNING_SECRET, "jhemr-svc", name, PERMS_INT, request_id),
    }


def _submission_body(submission_id="SUB-DJ1-1", patient="TEST0002"):
    return {"request_id": "req-dj1-001", "patient_id": patient,
            "visit_number": "1",
            "operator": {"id": "DOC77", "name": "测试医生"},
            "dept": "D002", "submission_id": submission_id,
            "document_refs": [{"doc_id": "DOC-1", "revision": "r3"}],
            "submitted_at": "2026-09-21 10:00:00"}


def _latest_run(session_factory, patient):
    with session_factory() as session:
        return session.execute(
            select(RunRow).where(RunRow.patient_id == patient)
            .order_by(RunRow.id.desc()).limit(1)).scalar_one()


# ---------------------------------------------------------------- 顺序契约


def test_materialize_precedes_finish_run():
    """D-J1 复现/修复判据：finish_run 执行时，本 run 的 issue 已物化。

    旧顺序（finish → materialize）下 issues_at_finish == 0（FAIL=A 案修复的
    复现证据）；A 案（materialize 前移）下 >= 1。
    """
    stack = _build_stack()
    r = stack["client"].post("/api/integration/jhemr/submission-checks",
                             json=_submission_body(), headers=_headers())
    assert r.status_code == 202, r.text
    run = _latest_run(stack["sf"], "TEST0002")
    assert run.status in ("completed", "partial")
    counted = stack["store"].issues_at_finish.get(run.id)
    assert counted is not None, "finish_run 未被调用（流程异常）"
    assert counted >= 1, (
        f"D-J1 复现：finish_run({run.id}→{run.status}) 时已物化 issue 数={counted}，"
        "终态先于物化——JHEMR GET 在 completed 后存在 issues 未齐窗口")


# ---------------------------------------------------------------- HTTP 防回归


def test_http_first_query_contract():
    """完成后 GET：status=completed 且 issues 与库内物化状态完全一致（防回归）。

    TestClient 同步执行 BackgroundTasks，旧代码此测试同样通过——见模块 docstring
    注记，D-J1 复现证据不依赖本测试。
    """
    stack = _build_stack()
    client = stack["client"]
    created = client.post("/api/integration/jhemr/submission-checks",
                          json=_submission_body("SUB-DJ1-2"),
                          headers=_headers("req-2")).json()
    check_id = created["check_id"]

    detail = client.get(f"/api/integration/jhemr/submission-checks/{check_id}",
                        headers=_headers("req-3")).json()
    assert detail["status"] == "completed", detail["status"]

    with stack["sf"]() as session:
        db_rows = session.execute(select(IssueRow).where(
            IssueRow.patient_id == "TEST0002",
            IssueRow.visit_number == "1",
            IssueRow.is_trial == 0)).scalars().all()
    db_keys = {(r.rule_id, r.event_instance_id) for r in db_rows}
    get_keys = {(i["rule_id"], i["event_instance_id"])
                for i in detail["issues"] or []}
    assert db_keys, "fixture 应至少物化 1 条 issue"
    assert get_keys == db_keys, (
        f"GET 与库内物化不一致：仅GET={get_keys - db_keys} 仅DB={db_keys - get_keys}")


# ---------------------------------------------------------------- 故障注入


def test_materialize_failure_downgrades_run(monkeypatch):
    """物化始终失败（重试亦败）→ run 不得发布 completed：降级 partial+诊断标记。"""
    stack = _build_stack()

    def boom(run_id):
        raise RuntimeError("injected materialize failure")

    monkeypatch.setattr(stack["processor"].issue_service,
                        "materialize_for_run", boom)
    r = stack["client"].post("/api/integration/jhemr/submission-checks",
                             json=_submission_body("SUB-DJ1-3"),
                             headers=_headers("req-4"))
    assert r.status_code == 202, r.text
    run = _latest_run(stack["sf"], "TEST0002")
    assert run.status == "partial", (
        f"物化失败后 run={run.status}——契约要求不得发布 completed")
    assert "issues_materialization" in (run.source_health_json or ""), (
        "物化失败未留 issues_materialization 诊断标记")
