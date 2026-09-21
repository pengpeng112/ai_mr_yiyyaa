# -*- coding: utf-8 -*-
"""046 T6 结果→Outbox 自动接线验收（F03/F07）。

证据口径（046 §T6）：从合成触发的**正常入口**（TriggerPoller.poll_once + fixtures）
出发，断言业务事件自动生成（本文件任何用例都不手工调用 enqueue_for_result 或向
Outbox 插行）→ DeliveryWorker dispatch → Mock 接收 ACK → 本地送达状态；
治理矩阵（总开关/试点科室/影子/严重级/零通知/trial 不投）；复检=新事件且旧事件
不动；崩溃窗口由 reconcile 幂等补齐；目标停用阻止已排队发送；resolutions 携带
issue_key；envelope 的 run_revision/ruleset_revision 正确。
"""

import json
from pathlib import Path

import pytest

from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.delivery_wiring import (
    DeliveryGovernance,
    ResultEventEmitter,
    reconcile_recent_results,
)
from prearchive.engine import RuleEngine
from prearchive.eval_store import EvalRunStore
from prearchive.fixture_sources import build_demo_fixtures
from prearchive.heartbeat import Heartbeat
from prearchive.issue_service import IssueService
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.outbox import DeliveryWorker, HttpResponse
from prearchive.pusher import WeComPusher
from prearchive.rule_repository import RuleRepository
from prearchive.rules import load_rules, rules_version
from prearchive.store import ResultRepository
from prearchive.trigger import (
    PrecheckProcessor,
    RunLock,
    StateStore,
    TriggerPoller,
)

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


class AckTransport:
    """Mock 接收端（传输层注入）：记录请求并回正确 ACK。"""

    def __init__(self):
        self.calls = []

    def __call__(self, url, headers, body, timeout_seconds):
        payload = json.loads(body)
        self.calls.append({"url": url, "payload": payload})
        return HttpResponse(
            status=200,
            body={"schema_version": "1.0.0",
                  "event_id": payload.get("event_id"),
                  "accepted": True,
                  "receiver_reference": f"MOCK-REF-{payload.get('event_id')}"})


def _enable_destination(rule_repo):
    rule_repo.upsert_destination(
        code="emr_mock", kind="mock", enabled=1, base_url="http://127.0.0.1:9",
        endpoint="/mock/qc-results", auth_type="none", secret_ref="",
        max_attempts=6, allow_insecure_internal_http=1,
        send_severities_json="[]")


def build_stack(tmp_path, *, governance: DeliveryGovernance, with_emitter=True):
    """fixtures + 真规则 + eval/issue/emitter 全链栈（与 run_service.build_stack
    同构；仓库根 CWD 下运行）。"""
    gateways = build_demo_fixtures()
    jhemr = JhemrCollector(gateways["jhemr"])
    builder = PatientContextBuilder(
        jhemr=jhemr,
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    rules = load_rules(RULES_FILE)
    engine = RuleEngine(rules, rule_version=rules_version(RULES_FILE))
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    repo = ResultRepository(session_factory)
    rule_repo = RuleRepository(session_factory)
    _enable_destination(rule_repo)
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    emitter = ResultEventEmitter(rule_repo, governance) if with_emitter else None
    processor = PrecheckProcessor(
        builder, engine, repo, pusher,
        eval_store=EvalRunStore(session_factory),
        trigger_type="finished",
        issue_service=IssueService(session_factory),
        delivery_emitter=emitter)
    poller = TriggerPoller(
        jhemr_collector=jhemr,
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=Heartbeat(tmp_path / "heartbeat.json"))
    return {"gateways": gateways, "repo": repo, "rule_repo": rule_repo,
            "processor": processor, "poller": poller,
            "session_factory": session_factory}


def _default_governance(**overrides) -> DeliveryGovernance:
    fields = {"enabled": True}
    fields.update(overrides)
    return DeliveryGovernance(**fields)


def _outbox_payloads(rule_repo, status: str = ""):
    rows = rule_repo.list_outbox(limit=500)
    if status:
        rows = [r for r in rows if r.status == status]
    return [(r.event_id, json.loads(r.payload_json or "{}")) for r in rows]


# ---------------------------------------------------------------------------
# 1) 合成触发端到端：poll_once → 自动事件 → dispatch → ACK → sent
# ---------------------------------------------------------------------------

def test_synthetic_trigger_end_to_end_delivery(tmp_path):
    gov = _default_governance()
    stack = build_stack(tmp_path, governance=gov)
    poller, repo, rule_repo = stack["poller"], stack["repo"], stack["rule_repo"]

    stats = poller.poll_once()
    assert stats.processed == 3 and not stats.errors

    # 事件由主链路自动生成（本用例无任何手工 enqueue/插行）
    pending = rule_repo.list_outbox(limit=500)
    assert {r.status for r in pending} == {"pending"}
    by_patient = {}
    for row in pending:
        payload = json.loads(row.payload_json or "{}")
        by_patient[payload["subject"]["patient_id"]] = (row, payload)
    assert set(by_patient) == {"TEST0001", "TEST0002", "TEST0003"}
    for patient_id, (row, payload) in by_patient.items():
        assert row.event_id.startswith("res-") and payload["event_id"] == row.event_id
        assert payload["run_revision"] == 1
        assert payload["ruleset_revision"] == str(rules_version(RULES_FILE))
        assert payload["run"]["trigger_mode"] == "finished"
        assert payload["shadow"] is False
    assert len(by_patient["TEST0001"][1]["issues"]) == 9
    assert len(by_patient["TEST0002"][1]["issues"]) == 6
    assert by_patient["TEST0003"][1]["issues"] == []   # 零问题默认通知（撤销依赖）

    # dispatch → Mock 接收 ACK → 本地送达状态 sent
    transport = AckTransport()
    worker = DeliveryWorker(rule_repo, transport=transport, delivery_enabled=True)
    round_stats = worker.dispatch_round()
    assert round_stats == {"claimed": 3, "sent": 3, "retried": 0, "dead": 0}
    assert len(transport.calls) == 3
    for call in transport.calls:
        assert call["url"] == "http://127.0.0.1:9/mock/qc-results"
        assert call["payload"]["event_id"].startswith("res-")   # ACK 回显同一 event
    assert {r.status for r in rule_repo.list_outbox(limit=500)} == {"sent"}
    # 结果行推送状态（wecom 侧）不受投递接线影响
    assert repo.get_current("TEST0003", "1") is not None


# ---------------------------------------------------------------------------
# 2) 治理矩阵（F07）
# ---------------------------------------------------------------------------

def test_governance_master_switch_blocks_all_events(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance(enabled=False))
    stack["poller"].poll_once()
    assert stack["rule_repo"].list_outbox(limit=10) == []


def test_governance_pilot_dept_scoping(tmp_path):
    stack = build_stack(tmp_path,
                        governance=_default_governance(pilot_dept_codes=["D001"]))
    stack["poller"].poll_once()
    payloads = _outbox_payloads(stack["rule_repo"])
    patients = {p["subject"]["patient_id"] for _, p in payloads}
    assert patients == {"TEST0001", "TEST0003"}   # D001 普外科；D002 呼吸内科不投


def test_governance_shadow_marker(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance(shadow=True))
    stack["poller"].poll_once()
    for _, payload in _outbox_payloads(stack["rule_repo"]):
        assert payload["shadow"] is True


def test_governance_severity_gate(tmp_path):
    # fixtures 问题最高级=medium/low：notify 只留 high → 带问题结果全部拦截；
    # 零问题结果不经过严重级门（撤销旧缺陷依赖零问题事件）
    stack = build_stack(tmp_path,
                        governance=_default_governance(notify_severities=["high"]))
    stack["poller"].poll_once()
    payloads = _outbox_payloads(stack["rule_repo"])
    assert [p for _, p in payloads if p["issues"]] == []
    assert {p["subject"]["patient_id"] for _, p in payloads} == {"TEST0003"}


def test_governance_zero_result_notify_off(tmp_path):
    stack = build_stack(tmp_path,
                        governance=_default_governance(zero_result_notify=False))
    stack["poller"].poll_once()
    payloads = _outbox_payloads(stack["rule_repo"])
    patients = {p["subject"]["patient_id"] for _, p in payloads}
    assert patients == {"TEST0001", "TEST0002"}   # 王某零问题不再通知


def test_trial_run_not_delivered(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance())
    rule_repo = stack["rule_repo"]
    emitter = stack["processor"].delivery_emitter
    eval_store = stack["processor"].eval_store
    before = len(rule_repo.list_outbox(limit=500))

    run = eval_store.start_run(patient_id="TEST0001", visit_number="1",
                               trigger_type="trial", is_trial=True,
                               dept_code="D001")
    created = emitter.emit(run=run, result_row=None, problems=[], summary={})
    assert created == []
    assert len(rule_repo.list_outbox(limit=500)) == before


# ---------------------------------------------------------------------------
# 3) 复检=新事件（revision 2），旧事件不动；resolutions 携带 issue_key
# ---------------------------------------------------------------------------

def test_recheck_new_event_resolutions_and_old_events_untouched(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance())
    poller, repo, rule_repo = stack["poller"], stack["repo"], stack["rule_repo"]
    transport = AckTransport()
    worker = DeliveryWorker(rule_repo, transport=transport, delivery_enabled=True)

    poller.poll_once()
    worker.dispatch_round()
    events_before = {r.event_id: r.status
                     for r in rule_repo.list_outbox(limit=500)}
    assert set(events_before.values()) == {"sent"}

    # 整改：李某补出院记录（出院 08-27 08:00 → 记录 09:00，24h 内）+ 锚点前移；
    # 各源更新时间同步推进过新锚点（否则 source_not_ready→unknown 是正确防御，
    # 无法演示收敛）
    gateways = stack["gateways"]
    for row in gateways["jhemr"].pat_visits:
        if row["patient_id"] == "TEST0002":
            row["finished_date_time"] = "2026-08-27 12:00:00"
    gateways["jhemr"].blws["TEST0002|1"].append({
        "progress_template_name": "出院记录", "progress_status": "完成",
        "record_time": "2026-08-27 09:00:00",
        "finished_time": "2026-08-27 09:00:00",
        "update_time": "2026-08-27 12:06:00"})
    freshness = "2026-08-27 12:06:00"
    for gw_key in ("his", "lis", "sm"):
        for entry in gateways[gw_key].itf_entries:
            if entry.get("PATIENTID") == "TEST0002":
                entry["FUPDATE"] = freshness
    for blws_row in gateways["jhemr"].blws.get("TEST0002|1", []):
        blws_row["update_time"] = freshness

    stats = poller.poll_once()
    assert stats.processed == 1 and not stats.errors

    new_rows = [r for r in rule_repo.list_outbox(limit=500)
                if r.event_id not in events_before]
    assert len(new_rows) == 1 and new_rows[0].status == "pending"
    payload = json.loads(new_rows[0].payload_json or "{}")
    assert payload["subject"]["patient_id"] == "TEST0002"
    assert payload["run_revision"] == 2                      # 新复检=新事件
    assert len(payload["issues"]) == 5                       # 出院记录缺陷已收敛
    assert len(payload["resolutions"]) == 1                  # 解决通知（撤销锚点）
    resolution = payload["resolutions"][0]
    assert resolution["rule_id"] == "R-TIME-DISCHARGE-RECORD-24H"
    assert resolution["fid"] == 71
    assert "TEST0002" in resolution["issue_key"]
    # 旧事件不动：三个已发送事件状态不变、无重复
    after = {r.event_id: r.status for r in rule_repo.list_outbox(limit=500)}
    for event_id, status in events_before.items():
        assert after[event_id] == status
    # ISSUE 生命周期收敛：6 open → 5 open + 1 resolved
    issue_service = stack["processor"].issue_service
    issues = issue_service.list_issues(patient_id="TEST0002")
    assert len(issues) == 6
    assert sum(1 for i in issues if i.status == "resolved") == 1


# ---------------------------------------------------------------------------
# 4) 崩溃窗口：结果已提交、事件未落 → reconcile 幂等补齐（含治理过滤）
# ---------------------------------------------------------------------------

def test_crash_window_reconcile_backfills_and_idempotent(tmp_path):
    # 模拟崩溃：处理器不接 emitter，结果正常落库但事件未生成
    stack = build_stack(tmp_path, governance=_default_governance(),
                        with_emitter=False)
    poller, repo, rule_repo = stack["poller"], stack["repo"], stack["rule_repo"]
    stats = poller.poll_once()
    assert stats.processed == 3
    assert rule_repo.list_outbox(limit=10) == []

    transport = AckTransport()
    worker = DeliveryWorker(rule_repo, transport=transport, delivery_enabled=True)
    report = reconcile_recent_results(rule_repo, repo, _default_governance(), worker)
    assert report["checked"] == 3 and report["enqueued"] == 3

    round_stats = worker.dispatch_round()
    assert round_stats["sent"] == 3
    assert {r.status for r in rule_repo.list_outbox(limit=500)} == {"sent"}

    # 幂等：再对账不重复入队
    again = reconcile_recent_results(rule_repo, repo, _default_governance(), worker)
    assert again["enqueued"] == 0 and again["checked"] == 3
    assert len(rule_repo.list_outbox(limit=500)) == 3


def test_crash_window_reconcile_respects_governance(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance(),
                        with_emitter=False)
    poller, repo, rule_repo = stack["poller"], stack["repo"], stack["rule_repo"]
    poller.poll_once()

    worker = DeliveryWorker(rule_repo, transport=AckTransport(),
                            delivery_enabled=True)
    report = reconcile_recent_results(
        rule_repo, repo, _default_governance(pilot_dept_codes=["D001"]), worker)
    assert report["enqueued"] == 2                     # 补偿不越权：仅试点科室
    patients = {json.loads(r.payload_json or "{}")["subject"]["patient_id"]
                for r in rule_repo.list_outbox(limit=500)}
    assert patients == {"TEST0001", "TEST0003"}


# ---------------------------------------------------------------------------
# 5) 目标停用阻止已排队发送
# ---------------------------------------------------------------------------

def test_destination_disabled_blocks_queued_sends(tmp_path):
    stack = build_stack(tmp_path, governance=_default_governance())
    poller, rule_repo = stack["poller"], stack["rule_repo"]
    poller.poll_once()
    assert len(rule_repo.list_outbox(limit=500)) == 3   # 已排队

    rule_repo.upsert_destination(code="emr_mock", enabled=0)   # 投递前停用

    transport = AckTransport()
    worker = DeliveryWorker(rule_repo, transport=transport, delivery_enabled=True)
    round_stats = worker.dispatch_round()
    assert round_stats["claimed"] == 3 and round_stats["sent"] == 0
    assert transport.calls == []                        # 零网络
    assert {r.status for r in rule_repo.list_outbox(limit=500)} == {"disabled"}
