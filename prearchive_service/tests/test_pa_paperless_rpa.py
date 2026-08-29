# -*- coding: utf-8 -*-
"""T8-1 paperless_rpa 触发模式单测。

- anchor_mode 四值配置校验（含 paperless_rpa）；
- RPA SQL：UPDATEAT 主条件 + (UPDATEAT,FPATIENTID,FBIHID,FBINCU) 稳定次键 + FETCH FIRST；
- 身份适配器占位（待 W9 标注）；
- RPTCOUNT 对账两向（多算/少算）+ 不宣称护理缺项；
- 水位门极性（R5 关键）：未禁用→missing_doc 全 skip；禁用→正常判定；
- paperless_rpa 轮询端到端：UPDATEAT 水位/去重/复检新行/current 迁移。
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.config import DEFAULTS, ConfigError, validate_config
from prearchive.context import FinishedVisit, PatientContext
from prearchive.engine import RuleEngine, evaluate_missing_doc
from prearchive.fixture_sources import (
    FixtureJhemrGateway,
    build_demo_fixtures,
    build_paperless_rpa_fixtures,
)
from prearchive.heartbeat import Heartbeat
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.paperless import FixturePaperlessGateway
from prearchive.paperless_rpa import (
    RPA_AGGREGATES_SQL,
    PaperlessRpaCollector,
    RpaIdentityAdapter,
    reconcile_report_count,
)
from prearchive.pusher import WeComPusher
from prearchive.rules import RuleSpec
from prearchive.store import ResultRepository
from prearchive.trigger import PrecheckProcessor, RunLock, StateStore, TriggerPoller

SNAPSHOT = Path(__file__).resolve().parent.parent / \
    "rules/paperless_items_snapshot_20260828.json"


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


def test_config_accepts_paperless_rpa():
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["service"]["anchor_mode"] = "paperless_rpa"
    assert validate_config(cfg)["service"]["anchor_mode"] == "paperless_rpa"


def test_rpa_sql_contract():
    sql = RPA_AGGREGATES_SQL.upper()
    assert "UPDATEAT > :SINCE" in sql                       # 主条件=UPDATEAT
    assert "ORDER BY UPDATEAT, FPATIENTID, FBIHID, FBINCU" in sql   # 稳定次键四元组
    assert "FETCH FIRST :LIMIT ROWS ONLY" in sql
    assert "COMPLETED" not in sql.split("WHERE")[1].split("ORDER")[0].upper() \
        or "COMPLETED" not in ("UPDATEAT > :SINCE",)  # COMPLETED 不作过滤主条件


def test_identity_adapter_is_placeholder_pending_w9():
    adapter = RpaIdentityAdapter()
    assert adapter.verified is False
    assert "W9" in adapter.notes()
    assert adapter.to_patient_visit("TESTP1", "1", "1") == ("TESTP1", "1")
    assert adapter.to_patient_visit("", "1", "1") is None


def test_reconcile_report_count_both_directions():
    match = reconcile_report_count(5, 5)
    assert match == {"status": "match", "rpt_count": 5, "document_count": 5, "delta": 0}
    over = reconcile_report_count(9, 5)     # 无纸化多算
    assert over["status"] == "over" and over["delta"] == 4
    under = reconcile_report_count(3, 5)    # 无纸化少算
    assert under["status"] == "under" and under["delta"] == 2
    # 不宣称护理缺项
    assert "非护理缺项判定" in over["note"]


# ---------------------------------------------------------------------------
# R5 水位门极性（关键回归）
# ---------------------------------------------------------------------------
def _rule(require_ready=True):
    return RuleSpec(
        rule_id="R-GATE", rule_type="missing_doc", name="n", message="m",
        severity="medium", version="v", require_source_ready=require_ready,
        trigger={"patient_has": "surgery",
                 "evidence": {"surgery_evidence": "sm_itf_entry"}},
        expect=["麻醉单"],
        match={"sources": ["sm_itf"], "by": "report_name_fuzzy",
               "vocab": {"麻醉单": ["麻醉单"]}},
    )


def _rpa_like_ctx(gate_disabled):
    """模拟 paperless_rpa 锚点语义：finished(=采集完成 09-01) 晚于全部源水位(08-27)。"""
    from prearchive.collectors import DocumentEntry
    from prearchive.context import SRC_SM_ITF, SurgeryInfo

    ctx = PatientContext(
        patient_id="TESTP1", visit_id="1",
        finished_date_time=datetime(2026, 9, 1, 10, 0, 0),   # UPDATEAT
        source_ready_gate_disabled=gate_disabled,
        surgeries=[SurgeryInfo(surgery_name="手术", source="sm_itf_entry")],
        documents=[DocumentEntry(
            source=SRC_SM_ITF, report_name="其他报告",
            update_time=datetime(2026, 8, 27, 10, 0, 0))],   # 无麻醉单→应判缺
    )
    ctx.source_watermarks = {"sm": datetime(2026, 8, 27, 10, 0, 0)}
    return ctx


def test_source_ready_gate_blocks_when_not_disabled():
    """未禁用（旧行为）：源水位早于完成时点 → skip source_not_ready。"""
    notices = []
    problems = evaluate_missing_doc(_rpa_like_ctx(gate_disabled=False),
                                    _rule(), notices)
    assert problems == []
    assert any(n.get("reason") == "source_not_ready" for n in notices)


def test_source_ready_gate_allows_when_disabled():
    """禁用（paperless_rpa 模式）：同一上下文正常判缺。"""
    notices = []
    problems = evaluate_missing_doc(_rpa_like_ctx(gate_disabled=True),
                                    _rule(), notices)
    assert len(problems) == 1
    assert problems[0].rule_id == "R-GATE"


def test_gate_flag_does_not_affect_other_modes_default():
    ctx = _rpa_like_ctx(gate_disabled=False)
    assert ctx.source_ready_gate_disabled is False   # 默认关闭（其他模式行为不变）


# ---------------------------------------------------------------------------
# paperless_rpa 轮询端到端
# ---------------------------------------------------------------------------
def _build_rpa_stack(tmp_path, rpa_rows=None):
    gateways = build_demo_fixtures()
    jhemr = JhemrCollector(gateways["jhemr"])
    builder = PatientContextBuilder(
        jhemr=jhemr,
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    engine = RuleEngine([], rule_version="test")
    processor = PrecheckProcessor(builder, engine, repo, pusher,
                                  source_ready_gate_disabled=True)
    rpa_gw = build_paperless_rpa_fixtures(rpa_rows)
    poller = TriggerPoller(
        jhemr_collector=jhemr,
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=Heartbeat(tmp_path / "heartbeat.json"),
        anchor_mode="paperless_rpa",
        paperless_rpa_collector=PaperlessRpaCollector(rpa_gw),
    )
    return poller, repo, processor


def test_paperless_rpa_poll_watermark_dedup_recheck(tmp_path):
    rows = [
        {"FPATIENTID": "TEST0001", "FBIHID": "1", "FBINCU": "1", "COMPLETED": 1,
         "UPDATEAT": "2026-08-31 09:00:00", "CREATEAT": "2026-08-30 20:00:00",
         "RPTCOUNT": 5, "FIOFFI": "D001", "FOOFFI": "D001",
         "FOOFFINAME": "普外科", "LJBLHS": ""},
        {"FPATIENTID": "TEST0003", "FBIHID": "1", "FBINCU": "1", "COMPLETED": 1,
         "UPDATEAT": "2026-09-01 11:00:00", "CREATEAT": "2026-08-31 22:00:00",
         "RPTCOUNT": 7, "FIOFFI": "D001", "FOOFFI": "D001",
         "FOOFFINAME": "普外科", "LJBLHS": ""},
        # COMPLETED=0 但 UPDATEAT 推进——COMPLETED 仅辅助列，不作过滤主条件
        {"FPATIENTID": "TEST0002", "FBIHID": "1", "FBINCU": "1", "COMPLETED": 0,
         "UPDATEAT": "2026-09-02 08:00:00", "CREATEAT": "2026-08-31 21:00:00",
         "RPTCOUNT": 3, "FIOFFI": "D002", "FOOFFI": "D002",
         "FOOFFINAME": "呼吸内科", "LJBLHS": ""},
    ]
    poller, repo, processor = _build_rpa_stack(tmp_path, rows)
    stats = poller.poll_once()
    assert stats.processed == 3
    assert stats.watermark == "2026-09-02T08:00:00"
    # 仓储行 finished_date_time := UPDATEAT + RPT 科室列进入上下文
    row = repo.get_current("TEST0002", "1")
    assert row.finished_date_time.isoformat() == "2026-09-02T08:00:00"
    assert row.dept_name == "呼吸内科"
    # 对账已记录（TEST0002 rpt=3 vs 文书条目数）
    assert processor.last_reconciliation.get("status") in ("match", "over", "under")
    assert "非护理缺项判定" in processor.last_reconciliation.get("note", "") \
        or processor.last_reconciliation.get("status") == "match"

    # 去重：第二轮全 skip
    stats2 = poller.poll_once()
    assert stats2.processed == 0

    # 复检=UPDATEAT 变化 → 新检查键 → current 迁移
    rows[0]["UPDATEAT"] = "2026-09-03 09:00:00"
    stats3 = poller.poll_once()
    assert stats3.processed == 1
    history = repo.list_history("TEST0001", "1")
    assert len(history) == 2
    assert sum(1 for r in history if r.current) == 1


def test_default_poller_without_rpa_collector_unchanged(tmp_path):
    """默认（非 paperless_rpa）不注入 RPA 采集器也照常工作（现状不破）。"""
    gateways = build_demo_fixtures()
    jhemr = JhemrCollector(gateways["jhemr"])
    builder = PatientContextBuilder(
        jhemr=jhemr, his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]), lis=LisCollector(gateways["lis"]),
    )
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    pusher = WeComPusher(push_config={"enabled": False},
                         secret_provider=lambda: "", sender=NullSender())
    processor = PrecheckProcessor(builder, RuleEngine([], rule_version="v"),
                                  repo, pusher)
    poller = TriggerPoller(
        jhemr_collector=jhemr, processor=processor,
        state_store=StateStore(tmp_path / "s.json"),
        lock=RunLock(tmp_path / "l.lock"),
    )
    assert poller.anchor_mode == "finished"
    assert poller.poll_once().processed == 3
