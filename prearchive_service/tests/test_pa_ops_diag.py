# -*- coding: utf-8 -*-
"""046 T9b 运维诊断测试。

覆盖：诊断面字段（引擎版本/最后成功采集/源故障/任务积压/Outbox 积压/死信/
连续失败/compare 差异计数）；/healthz additive diagnostics 块；admin 端点鉴权；
**零 PHI/密钥**（序列化结果不含患者标识/正文/secret）；故障隔离验收——
任务/源/目标分别故障时预检主流程继续、故障恢复后可补齐、旧记录不错标通过。
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
from prearchive.admin_api import create_admin_router
from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.delivery_wiring import DeliveryGovernance, ResultEventEmitter
from prearchive.diagnostics import build_diagnostics
from prearchive.engine import RuleEngine
from prearchive.eval_store import EvalRunStore
from prearchive.fixture_sources import build_demo_fixtures
from prearchive.issue_service import IssueService
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.outbox import DeliveryWorker, HttpResponse
from prearchive.pusher import WeComPusher
from prearchive.rule_repository import RuleRepository
from prearchive.rules import load_rules, rules_version
from prearchive.store import ResultRepository
from prearchive.trigger import PrecheckProcessor

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"
ADMIN_TOKEN = "ops-admin-token"
SIGNING = "ops-signing-secret"


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


def _build_processor(session_factory, gateways):
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]))
    rules = load_rules(RULES_FILE)
    engine = RuleEngine(rules, rule_version=rules_version(RULES_FILE))
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    rule_repo = RuleRepository(session_factory)
    return PrecheckProcessor(
        builder, engine, ResultRepository(session_factory), pusher,
        eval_store=EvalRunStore(session_factory), trigger_type="finished",
        issue_service=IssueService(session_factory),
        delivery_emitter=ResultEventEmitter(
            rule_repo, DeliveryGovernance(enabled=True))), rule_repo


def _headers(perms="prearchive_rule_view", request_id="r-1"):
    from urllib.parse import quote
    name = quote("运维", safe="")
    return {
        ADMIN_TOKEN_HEADER: ADMIN_TOKEN,
        ACTOR_ID_HEADER: "ops-1",
        ACTOR_NAME_HEADER: name,
        ACTOR_PERMS_HEADER: perms,
        REQUEST_ID_HEADER: request_id,
        ACTOR_SIGNATURE_HEADER: actor_signature(
            SIGNING, "ops-1", name, perms, request_id),
    }


def test_diagnostics_fields_and_no_phi(tmp_path):
    gateways = build_demo_fixtures()
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    processor, rule_repo = _build_processor(session_factory, gateways)
    # 目标故障面：transport 500 → dead/连续失败计数（目标先于处理创建：
    # emit 在 process 时入队）
    rule_repo.upsert_destination(
        code="emr_mock", kind="mock", enabled=1, base_url="http://127.0.0.1:9",
        endpoint="/x", auth_type="none", secret_ref="",
        allow_insecure_internal_http=1, max_attempts=1,
        send_severities_json="[]")
    from prearchive.context import FinishedVisit, parse_datetime
    row = gateways["jhemr"].pat_visits[1]      # 李某（有缺陷）
    visit = FinishedVisit(patient_id=row["patient_id"], visit_id=row["visit_id"],
                          finished_date_time=parse_datetime(row["finished_date_time"]))
    processor.process(visit)

    def failing_transport(url, headers, body, timeout_seconds):
        return HttpResponse(status=500, body={"message": "boom"})

    worker = DeliveryWorker(rule_repo, transport=failing_transport,
                            delivery_enabled=True)
    worker.dispatch_round()                     # max_attempts=1 → dead
    # 再投一个事件（另一患者）保持 retry 面需要时，先看 dead 即可

    diag = build_diagnostics(session_factory,
                             engine=processor.engine, watermark="w-1")
    assert diag["engine_version"] == rules_version(RULES_FILE)
    assert diag["last_successful_check_at"] is not None
    assert isinstance(diag["source_faults"], list)
    assert diag["outbox"]["dead"] >= 1
    assert diag["outbox"]["backlog"] >= 0
    assert "status_counts" in diag["outbox"]
    assert diag["compare_diff_count"] is None   # 非 compare 引擎=None（不编造）

    # 零 PHI/密钥：序列化诊断面不含患者 ID/姓名/正文/secret
    blob = json.dumps(diag, ensure_ascii=False)
    for token in ("TEST0001", "TEST0002", "张某某", "李某某", "secret",
                  "password", "王某某"):
        assert token not in blob, f"诊断面泄漏：{token}"


def test_diagnostics_task_backlog_and_source_faults(tmp_path):
    gateways = build_demo_fixtures()
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    processor, _repo = _build_processor(session_factory, gateways)
    from prearchive.closed_loop_models import RunRow
    from datetime import datetime
    with session_factory() as session:
        session.add(RunRow(id="backlogrun000000001", run_revision=1,
                           patient_id="TEST0009", visit_number="1",
                           trigger_type="emr_submit", status="queued"))
        session.add(RunRow(id="backlogrun000000002", run_revision=1,
                           patient_id="TEST0010", visit_number="1",
                           trigger_type="emr_submit", status="running"))
        session.commit()
    diag = build_diagnostics(session_factory)
    assert diag["task_backlog"]["count"] == 2
    assert diag["task_backlog"]["oldest_at"] is not None


def test_diagnostics_source_faults_from_latest_run():
    """源故障：LIS 采集抛错 → run partial + source_faults 呈现短键。"""
    gateways = build_demo_fixtures()

    class BrokenLisGateway:
        def fetch_itf_entries(self, patient_id, visit_id):
            raise RuntimeError("lis unreachable")

    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(BrokenLisGateway()))
    rules = load_rules(RULES_FILE)
    engine = RuleEngine(rules, rule_version=rules_version(RULES_FILE))
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    processor = PrecheckProcessor(
        builder, engine, ResultRepository(session_factory), pusher,
        eval_store=EvalRunStore(session_factory), trigger_type="finished",
        issue_service=IssueService(session_factory))
    from prearchive.context import FinishedVisit, parse_datetime
    row = gateways["jhemr"].pat_visits[2]      # 王某
    visit = FinishedVisit(patient_id=row["patient_id"], visit_id=row["visit_id"],
                          finished_date_time=parse_datetime(row["finished_date_time"]))
    processor.process(visit)                   # 主流程不因源故障中断

    repo = ResultRepository(session_factory)
    assert repo.get_current("TEST0003", "1") is not None     # 结果仍落库
    diag = build_diagnostics(session_factory)
    assert any("lis" in fault for fault in diag["source_faults"])


def test_admin_diagnostics_endpoint_auth_and_content():
    gateways = build_demo_fixtures()
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    _processor, rule_repo = _build_processor(session_factory, gateways)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING}}
    app = FastAPI()
    app.include_router(create_admin_router(config, rule_repo,
                                           type("S", (), {})()))
    client = TestClient(app)
    assert client.get("/api/admin/diagnostics").status_code == 401
    response = client.get("/api/admin/diagnostics", headers=_headers())
    assert response.status_code == 200
    body = response.json()
    assert {"engine_version", "last_successful_check_at", "source_faults",
            "task_backlog", "outbox", "compare_diff_count"} <= set(body)


def test_healthz_diagnostics_block_additive(tmp_path):
    """api.create_app 的 /healthz 追加 diagnostics 块（既有键不动）。"""
    from prearchive.api import create_app
    from prearchive.heartbeat import Heartbeat
    from prearchive.trigger import RunLock, StateStore, TriggerPoller

    gateways = build_demo_fixtures()
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    processor, rule_repo = _build_processor(session_factory, gateways)
    heartbeat = Heartbeat(tmp_path / "hb.json")
    poller = TriggerPoller(
        jhemr_collector=JhemrCollector(gateways["jhemr"]),
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=heartbeat)
    app = create_app(config={"api": {}}, repository=processor.repository,
                     heartbeat=heartbeat, poller=poller,
                     rule_center={"repository": rule_repo,
                                  "service": type("S", (), {})()})
    payload = TestClient(app).get("/healthz").json()
    for legacy_key in ("status", "heartbeat", "heartbeat_alive",
                       "heartbeat_max_age_seconds"):
        assert legacy_key in payload            # 既有契约不动
    assert "diagnostics" in payload
    assert payload["diagnostics"]["engine_version"]


def test_compare_diff_count_exposed():
    """compare 影子引擎的 diff_count 通过诊断面暴露。"""
    class FakeCompareEngine:
        rule_version = "v-x"
        diff_count = 7

        def evaluate(self, ctx):
            raise NotImplementedError

    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    diag = build_diagnostics(session_factory, engine=FakeCompareEngine())
    assert diag["compare_diff_count"] == 7


def test_failed_check_task_does_not_block_pipeline(tmp_path):
    """任务故障隔离：一个 run 执行失败（failed）不影响后续处理与诊断。"""
    from prearchive.integration_api import _execute_check
    from prearchive.closed_loop_models import RunRow

    gateways = build_demo_fixtures()
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    processor, _repo = _build_processor(session_factory, gateways)
    with session_factory() as session:
        session.add(RunRow(id="failingrun0000001", run_revision=1,
                           patient_id="NO_SUCH_PATIENT", visit_number="1",
                           trigger_type="emr_submit", status="queued"))
        session.commit()
    _execute_check(processor, "failingrun0000001")    # 患者不存在 → failed

    from prearchive.context import FinishedVisit, parse_datetime
    row = gateways["jhemr"].pat_visits[0]
    visit = FinishedVisit(patient_id=row["patient_id"], visit_id=row["visit_id"],
                          finished_date_time=parse_datetime(row["finished_date_time"]))
    processor.process(visit)                          # 主流程继续
    assert processor.repository.get_current("TEST0001", "1") is not None
    diag = build_diagnostics(session_factory)
    assert diag["task_backlog"]["count"] == 0         # failed 不算积压
    with session_factory() as session:
        run = session.get(RunRow, "failingrun0000001")
        assert run.status == "failed"                 # 如实失败，不错标通过
