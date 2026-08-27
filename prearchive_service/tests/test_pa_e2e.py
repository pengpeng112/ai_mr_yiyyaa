# -*- coding: utf-8 -*-
"""端到端链路：fixture 源 → 触发轮询 → 四源采集 → 规则判定 → 结果存储 → 企微推送(mock)。

使用 rules/example_rules.json 真实规则 + build_demo_fixtures 虚构患者：
- TEST0001 张某：缺核查表/护理单 + 缺术前小结/术前讨论/术后首次病程；首页不可用→首页族跳过
- TEST0002 李某：入院记录超24h + 过敏空 + 诊断重复 + 检验报告缺（血常规/生化）
- TEST0003 王某：全负例（零问题、零推送）
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
from prearchive.engine import RuleEngine
from prearchive.fixture_sources import build_demo_fixtures
from prearchive.heartbeat import Heartbeat
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.pusher import WeComPusher
from prearchive.rules import load_rules, rules_version
from prearchive.store import ResultRepository
from prearchive.trigger import (
    PrecheckProcessor,
    RunLock,
    StateStore,
    TriggerPoller,
)

from helpers import dt

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"


class RecordingSender:
    """mock 发送器：记录签名请求，永远 200。"""

    def __init__(self):
        self.sent = []

    def send(self, url, body, headers, timeout):
        self.sent.append({"url": url, "body": body, "headers": headers})
        return 200, "ok"


def build_pipeline(tmp_path, push_enabled=True):
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
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    sender = RecordingSender()
    pusher = WeComPusher(
        push_config={"enabled": push_enabled, "base_url": "http://relay.test",
                     "endpoint": "/qc-record-alert",
                     "severity_levels": ["medium", "high"]},
        secret_provider=lambda: "e2e-secret",
        sender=sender,
    )
    processor = PrecheckProcessor(builder, engine, repo, pusher)
    poller = TriggerPoller(
        jhemr_collector=jhemr,
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=Heartbeat(tmp_path / "heartbeat.json"),
    )
    return poller, repo, sender, gateways


def test_end_to_end_full_chain(tmp_path):
    poller, repo, sender, gateways = build_pipeline(tmp_path)
    stats = poller.poll_once()
    assert stats.processed == 3 and not stats.errors

    # ---- 张某：手术族两连中；首页族整族跳过 ----
    row1 = repo.get_current("TEST0001", "1")
    rule_ids1 = {p["rule_id"] for p in row1.problems()}
    assert "R-MISS-SURGERY-CHECKTABLE" in rule_ids1
    assert "R-MISS-SURGERY-PREPOST-DOCS" in rule_ids1
    checktable = next(p for p in row1.problems()
                      if p["rule_id"] == "R-MISS-SURGERY-CHECKTABLE")
    assert set(checktable["details"]["missing_docs"]) == {"手术安全核查表", "手术护理记录单"}
    assert "R-EMPTY-FIRSTPAGE-ALLERGY" not in rule_ids1      # 首页不可用→跳过
    assert "R-DUP-FIRSTPAGE-DIAGNOSIS" not in rule_ids1
    assert "R-MISS-LAB-REPORT-FAMILY" not in rule_ids1       # 三报告齐→不命中
    assert row1.doctor_id == "TESTDOC01" and row1.receiver_fallback == 0

    # ---- 李某：入院24h + 过敏空 + 诊断重复 + 检验报告族 ----
    row2 = repo.get_current("TEST0002", "1")
    rule_ids2 = {p["rule_id"] for p in row2.problems()}
    assert rule_ids2 == {
        "R-TIME-ADMISSION-RECORD-24H",
        "R-EMPTY-FIRSTPAGE-ALLERGY",
        "R-DUP-FIRSTPAGE-DIAGNOSIS",
        "R-MISS-LAB-REPORT-FAMILY",
    }
    lab = next(p for p in row2.problems()
               if p["rule_id"] == "R-MISS-LAB-REPORT-FAMILY")
    assert set(lab["details"]["missing_docs"]) == {"血常规检验报告", "生化检验报告"}
    assert row2.receiver_fallback == 0

    # ---- 王某：全负例 ----
    row3 = repo.get_current("TEST0003", "1")
    assert row3.problem_count == 0

    # ---- 推送：单患者合并一条、去重、签名协议 ----
    # 张某(medium×2) + 李某(medium 过敏空) 达阈值；王某零问题不推
    assert len(sender.sent) == 2
    pushed_patients = set()
    for request in sender.sent:
        payload = json.loads(request["body"].decode("utf-8"))
        pushed_patients.add(payload["patient_id"])
        # 签名头符合 relay 协议
        assert "X-Relay-Timestamp" in request["headers"]
        assert "X-Relay-Signature" in request["headers"]
        assert payload["event"] == "prearchive_check_issue"
    assert pushed_patients == {"TEST0001", "TEST0002"}

    # 状态回写：sent；王某 skipped
    assert repo.get_current("TEST0001", "1").push_wecom_status == "sent"
    assert repo.get_current("TEST0002", "1").push_wecom_status == "sent"
    assert repo.get_current("TEST0003", "1").push_wecom_status == "skipped"
    # 弹窗通道（agent）保持 pending：双通道独立去重字段
    assert repo.get_current("TEST0001", "1").push_agent_status == "pending"

    # 心跳与水位落盘
    hb = json.loads((tmp_path / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["alive"] is True and hb["watermark"] == "2026-08-27T11:00:00"


def test_end_to_end_recheck_pushes_new_result_only(tmp_path):
    """复检闭环：完成时间更新 → 新 result → 新推送；旧 result 不再重发。

    重新完成后各源数据同步刷新（水位推进），复检才能重新判定（R15 语义）。
    """
    poller, repo, sender, gateways = build_pipeline(tmp_path)
    poller.poll_once()
    assert len(sender.sent) == 2

    old_row1 = repo.get_current("TEST0001", "1")
    for pat in gateways["jhemr"].pat_visits:
        if pat["patient_id"] == "TEST0001":
            pat["finished_date_time"] = "2026-08-26 12:00:00"
    for row in gateways["jhemr"].blws["TEST0001|1"]:
        row["update_time"] = "2026-08-26 12:05:00"
    for row in gateways["sm"].itf_entries:
        if row["PATIENTID"] == "TEST0001":
            row["FUPDATE"] = "2026-08-26 12:30:00"
            row["FLOADDATE"] = "2026-08-26 12:31:00"
    for row in gateways["his"].itf_entries:
        if row["PATIENTID"] == "TEST0001":
            row["FUPDATE"] = "2026-08-26 12:30:00"
    for row in gateways["lis"].itf_entries:
        if row["PATIENTID"] == "TEST0001":
            row["FUPDATE"] = "2026-08-26 12:50:00"

    stats = poller.poll_once()
    assert stats.processed == 1

    new_row1 = repo.get_current("TEST0001", "1")
    assert new_row1.id != old_row1.id
    assert new_row1.finished_date_time == dt("2026-08-26 12:00:00")
    assert new_row1.problem_count > 0
    assert new_row1.push_wecom_status == "sent"        # 新 result 重新推一次
    assert old_row1.push_wecom_status == "sent"        # 旧 result 状态不回退
    history = repo.list_history("TEST0001", "1")
    assert len(history) == 2
    assert [r.current for r in history].count(1) == 1

    # 张某新推送 + 李某未变 → 本轮只多发 1 条
    assert len(sender.sent) == 3
    last_payload = json.loads(sender.sent[-1]["body"].decode("utf-8"))
    assert last_payload["patient_id"] == "TEST0001"
    assert last_payload["result_id"] == new_row1.id


def test_end_to_end_push_disabled_shadow_mode(tmp_path):
    """影子运行（P1-6）：push.enabled=false → 全部 skipped，零外发。"""
    poller, repo, sender, _ = build_pipeline(tmp_path, push_enabled=False)
    poller.poll_once()
    assert sender.sent == []
    assert repo.get_current("TEST0002", "1").push_wecom_status == "skipped"
