# -*- coding: utf-8 -*-
"""anchor_mode 三模式单测（031 T2-1）。

- 默认 finished：行为与现状完全一致（配置默认值 + 轮询器默认值）；
- discharge：检查键第三列=出院时间，水位/去重/复检语义与 finished 等价；
- blws_status：v_blws.modify_date 患者聚合"疑似完成"，pat_visit 回填患者字段；
- 新模式仅显式配置生效；blws_status 生产不可用（README 标注，029 K5）。
"""
import json

import pytest

from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.config import DEFAULTS, ConfigError, validate_config
from prearchive.engine import RuleEngine
from prearchive.fixture_sources import FixtureJhemrGateway, build_demo_fixtures
from prearchive.heartbeat import Heartbeat
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.pusher import WeComPusher
from prearchive.store import ResultRepository
from prearchive.trigger import PrecheckProcessor, RunLock, StateStore, TriggerPoller


class NullSender:
    def send(self, url, body, headers, timeout):
        return 200, "ok"


def build_stack(tmp_path, gateways=None, anchor_mode="finished"):
    gateways = gateways or build_demo_fixtures()
    jhemr = JhemrCollector(gateways["jhemr"])
    builder = PatientContextBuilder(
        jhemr=jhemr,
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    pusher = WeComPusher(
        push_config={"enabled": False},
        secret_provider=lambda: "",
        sender=NullSender(),
    )
    engine = RuleEngine([], rule_version="test-v1")
    processor = PrecheckProcessor(builder, engine, repo, pusher)
    poller = TriggerPoller(
        jhemr_collector=jhemr,
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=Heartbeat(tmp_path / "heartbeat.json"),
        interval_seconds=300,
        batch_limit=100,
        anchor_mode=anchor_mode,
    )
    return poller, repo, gateways


# ---------------------------------------------------------------------------
# 配置契约
# ---------------------------------------------------------------------------
def test_config_defaults_anchor_mode_finished():
    assert DEFAULTS["service"]["anchor_mode"] == "finished"
    assert "anchor_mode" in (validate_config(DEFAULTS)["service"])


@pytest.mark.parametrize("mode", ["finished", "discharge", "blws_status"])
def test_config_accepts_three_anchor_modes(mode):
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["service"]["anchor_mode"] = mode
    assert validate_config(cfg)["service"]["anchor_mode"] == mode


def test_config_rejects_unknown_anchor_mode():
    cfg = json.loads(json.dumps(DEFAULTS))
    cfg["service"]["anchor_mode"] = "paperless"
    with pytest.raises(ConfigError):
        validate_config(cfg)


def test_poller_default_anchor_mode_is_finished():
    # 新模式默认不生效：未显式传入时轮询器行为与现状一致
    poller, _, _ = build_stack(__import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    assert poller.anchor_mode == "finished"


# ---------------------------------------------------------------------------
# discharge 模式：水位/去重/复检等价性
# ---------------------------------------------------------------------------
def test_discharge_mode_watermark_and_dedup(tmp_path):
    poller, repo, _ = build_stack(tmp_path, anchor_mode="discharge")
    stats = poller.poll_once()
    # fixture 出院时间最大 = TEST0003 2026-08-27 10:00:00（≠完成时间 11:00）
    assert stats.processed == 3
    assert stats.watermark == "2026-08-27T10:00:00"
    row = repo.get_current("TEST0003", "1")
    assert row.finished_date_time.isoformat() == "2026-08-27T10:00:00"

    stats2 = poller.poll_once()
    assert stats2.processed == 0
    # 回看窗（24h）内仍有 2 条（08-27 的两位），但检查键已处理 → 全 skipped_seen
    assert stats2.skipped_seen >= 2


def test_discharge_mode_recheck_on_time_update(tmp_path):
    poller, repo, gateways = build_stack(tmp_path, anchor_mode="discharge")
    poller.poll_once()
    # 出院时间更新（复检发现）：检查键第三列变化 → 重新处理
    for row in gateways["jhemr"].pat_visits:
        if row["patient_id"] == "TEST0002":
            row["discharge_time"] = "2026-08-28 08:00:00"
    stats2 = poller.poll_once()
    assert stats2.processed == 1
    row = repo.get_current("TEST0002", "1")
    assert row.finished_date_time.isoformat() == "2026-08-28T08:00:00"
    # 旧检查行让位（current 迁移）
    history = repo.list_history("TEST0002", "1")
    assert len(history) == 2
    assert sum(1 for r in history if r.current) == 1


# ---------------------------------------------------------------------------
# blws_status 模式：文书修改聚合 + pat_visit 回填
# ---------------------------------------------------------------------------
def test_blws_status_mode_aggregates_and_enriches(tmp_path):
    poller, repo, gateways = build_stack(tmp_path, anchor_mode="blws_status")
    stats = poller.poll_once()
    assert stats.processed == 3
    # 锚点=该患者文书最新 update_time（fixture：TEST0001=10:05 / 0002=09:35 / 0003=11:05）
    row1 = repo.get_current("TEST0001", "1")
    assert row1.finished_date_time.isoformat() == "2026-08-26T10:05:00"
    row3 = repo.get_current("TEST0003", "1")
    assert row3.finished_date_time.isoformat() == "2026-08-27T11:05:00"
    # pat_visit 回填：患者姓名/科室进入结果行
    assert row1.patient_name == "张某某"
    assert row1.dept_name == "普外科"
    assert stats.watermark == "2026-08-27T11:05:00"


def test_blws_status_mode_dedup_and_recheck(tmp_path):
    poller, repo, gateways = build_stack(tmp_path, anchor_mode="blws_status")
    poller.poll_once()
    stats2 = poller.poll_once()
    assert stats2.processed == 0
    # 文书再修改 → 聚合锚点变化 → 复检
    gateways["jhemr"].blws["TEST0002|1"][0]["update_time"] = "2026-08-28 12:00:00"
    stats3 = poller.poll_once()
    assert stats3.processed == 1
    assert repo.get_current("TEST0002", "1").finished_date_time.isoformat() == \
        "2026-08-28T12:00:00"


# ---------------------------------------------------------------------------
# README 标注（文件内容断言）
# ---------------------------------------------------------------------------
def test_readme_documents_blws_status_production_unusable():
    from pathlib import Path
    readme = Path(__file__).resolve().parent.parent / "README.md"
    text = readme.read_text(encoding="utf-8")
    assert "anchor_mode" in text
    assert "blws_status" in text
    assert "生产不可用" in text
