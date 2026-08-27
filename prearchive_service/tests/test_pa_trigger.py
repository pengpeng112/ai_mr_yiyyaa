# -*- coding: utf-8 -*-
"""触发轮询单测：水位/防重入/检查键去重/复检发现/断点续跑。"""

import json
import os

import pytest

from prearchive.collectors import (
    HisCollector,
    JhemrCollector,
    LisCollector,
    PatientContextBuilder,
    SmCollector,
)
from prearchive.fixture_sources import build_demo_fixtures
from prearchive.heartbeat import Heartbeat
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.pusher import WeComPusher
from prearchive.engine import RuleEngine
from prearchive.store import ResultRepository
from prearchive.trigger import (
    PrecheckProcessor,
    RunLock,
    StateStore,
    TriggerPoller,
)

from helpers import dt


class NullSender:
    def __init__(self):
        self.calls = []

    def send(self, url, body, headers, timeout):
        self.calls.append((url, body, headers))
        return 200, "ok"


def build_stack(tmp_path, gateways=None, push_enabled=False, batch_limit=100,
                lookback_seconds=86400):
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
        push_config={"enabled": push_enabled, "base_url": "http://relay.test",
                     "endpoint": "/qc-record-alert", "severity_levels": ["low"]},
        secret_provider=lambda: "test-secret",
        sender=NullSender(),
    )
    engine = RuleEngine([], rule_version="test-v1")   # 规则留空：轮询语义测试不依赖判定
    processor = PrecheckProcessor(builder, engine, repo, pusher)
    poller = TriggerPoller(
        jhemr_collector=jhemr,
        processor=processor,
        state_store=StateStore(tmp_path / "state.json"),
        lock=RunLock(tmp_path / "poller.lock"),
        heartbeat=Heartbeat(tmp_path / "heartbeat.json"),
        interval_seconds=300,
        batch_limit=batch_limit,
        lookback_seconds=lookback_seconds,
    )
    return poller, repo, pusher, gateways


def test_poll_once_processes_all_and_persists_watermark(tmp_path):
    poller, repo, _, _ = build_stack(tmp_path)
    stats = poller.poll_once()
    assert stats.processed == 3 and stats.fetched == 3
    assert stats.watermark == "2026-08-27T11:00:00"
    assert repo.get_current("TEST0001", "1") is not None
    assert repo.get_current("TEST0003", "1") is not None

    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["watermark"] == "2026-08-27T11:00:00"
    assert len(state["last_processed"]) == 3
    assert state["iterations"] == 3

    # 心跳已写（R13）
    hb = json.loads((tmp_path / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["alive"] is True and hb["watermark"] == state["watermark"]


def test_second_poll_dedupes_by_check_key(tmp_path):
    poller, repo, _, _ = build_stack(tmp_path)
    poller.poll_once()
    stats2 = poller.poll_once()
    # 回看窗内李某/王某仍在查询结果里，但检查键已处理 → 全部 skipped_seen
    assert stats2.processed == 0
    assert stats2.skipped_seen >= 1
    rows = repo.list_history("TEST0002", "1")
    assert len(rows) == 1


def test_refinish_within_lookback_rediscovered(tmp_path):
    """复检闭环：完成时间更新（即使早于另一患者的更高水位）→ 重新预检新行。"""
    poller, repo, _, gateways = build_stack(tmp_path)
    poller.poll_once()
    assert len(repo.list_history("TEST0002", "1")) == 1

    # 李某复检：完成时间 09:30 → 13:00（水位已被王某 11:00 推高，靠回看窗发现）
    for row in gateways["jhemr"].pat_visits:
        if row["patient_id"] == "TEST0002":
            row["finished_date_time"] = "2026-08-27 13:00:00"

    stats = poller.poll_once()
    assert stats.processed == 1
    history = repo.list_history("TEST0002", "1")
    assert len(history) == 2                       # 旧行保留
    currents = [r for r in history if r.current == 1]
    assert currents[0].finished_date_time == dt("2026-08-27 13:00:00")


def test_older_refinish_not_processed_twice(tmp_path):
    """完成时间回退到已处理值（迟到旧值）→ 去重跳过。"""
    poller, repo, _, gateways = build_stack(tmp_path)
    poller.poll_once()
    for row in gateways["jhemr"].pat_visits:
        if row["patient_id"] == "TEST0002":
            row["finished_date_time"] = "2026-08-27 09:30:00"   # 同值
    stats = poller.poll_once()
    assert stats.processed == 0
    assert len(repo.list_history("TEST0002", "1")) == 1


def test_state_persistence_across_instances(tmp_path):
    """断点续跑：新轮询器实例复用旧状态文件，不重处理。"""
    poller1, repo1, _, _ = build_stack(tmp_path)
    poller1.poll_once()

    poller2, repo2, _, _ = build_stack(tmp_path)   # 同 tmp_path → 同 state.json
    stats = poller2.poll_once()
    assert stats.processed == 0


def test_lock_prevents_reentry(tmp_path):
    poller, _, _, _ = build_stack(tmp_path)
    # 用父进程 PID 模拟"别的活进程持锁"
    lock_path = tmp_path / "poller.lock"
    lock_path.write_text(json.dumps({"pid": os.getppid(), "ts": "x"}),
                         encoding="utf-8")
    stats = poller.poll_once()
    assert stats.lock_skipped is True
    assert stats.processed == 0
    # 锁文件未被吞掉
    assert lock_path.exists()


def test_stale_lock_taken_over(tmp_path):
    poller, repo, _, _ = build_stack(tmp_path)
    lock_path = tmp_path / "poller.lock"
    lock_path.write_text(json.dumps({"pid": 99999999, "ts": "x"}), encoding="utf-8")
    stats = poller.poll_once()
    assert stats.lock_skipped is False
    assert stats.processed == 3


def test_batch_limit_and_continuation(tmp_path):
    poller, repo, _, _ = build_stack(tmp_path, batch_limit=2)
    stats1 = poller.poll_once()
    assert stats1.processed == 2
    stats2 = poller.poll_once()
    assert stats2.processed == 1      # 回看窗内补齐剩余
    assert repo.get_current("TEST0003", "1") is not None


def test_processor_failure_does_not_poison_batch(tmp_path, monkeypatch):
    poller, repo, _, gateways = build_stack(tmp_path)
    original = poller.processor.process
    calls = {"n": 0}

    def flaky(visit, check_time=None):
        calls["n"] += 1
        if visit.patient_id == "TEST0002":
            raise RuntimeError("collect boom")
        return original(visit, check_time=check_time)

    monkeypatch.setattr(poller.processor, "process", flaky)
    stats = poller.poll_once()
    assert stats.processed == 2
    assert any("TEST0002" in e for e in stats.errors)
    # 失败患者不进 last_processed（下轮可重试）
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert "TEST0002|1" not in state["last_processed"]
