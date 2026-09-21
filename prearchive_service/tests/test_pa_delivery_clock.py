# -*- coding: utf-8 -*-
"""046 ST-003：投递重试时序用可控时钟判定（不依赖真实 sleep / 缩短 Retry-After）。

- compute_next_retry 的 now 可注入；
- DeliveryWorker 的 clock 可注入：throttle(Retry-After) 后「到期前不重发、到期后重发」
  两态由时钟推进显式触发，机器快慢不再影响判定；
- 与真实 mock receiver 组合验证同一链路（429 → retry → 时钟推进 → sent）。
"""

from datetime import datetime, timedelta, timezone

import pytest

from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.outbox import DeliveryWorker, HttpResponse, compute_next_retry
from prearchive.rule_repository import RuleRepository

from helpers import dt

_CN = timezone(timedelta(hours=8))


def _aware(naive: datetime) -> datetime:
    return naive.replace(tzinfo=_CN)


class _FakeClock:
    """可控时钟：返回 +08:00 aware（与生产 now_cn 同口径，防 naive/aware 比较崩）。"""

    def __init__(self, start: datetime):
        self.now = _aware(start)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs):
        self.now = self.now + timedelta(**kwargs)


@pytest.fixture()
def repo():
    return RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))


def _enable(repo, base_url="http://127.0.0.1:1", max_attempts=6):
    repo.upsert_destination(
        code="emr_mock", kind="mock", enabled=1, base_url=base_url,
        endpoint="/mock/qc-results", auth_type="none", secret_ref="",
        max_attempts=max_attempts, allow_insecure_internal_http=1)


def _enqueue(repo, event_id):
    from prearchive.result_contract import build_contract_test_envelope
    envelope = build_contract_test_envelope("emr_mock")
    envelope.event_id = event_id
    envelope.idempotency_key = f"sha256:{event_id}"
    repo.enqueue_outbox(event_id=event_id, destination_code="emr_mock",
                        payload_json=envelope.model_dump_json(),
                        idempotency_key=envelope.idempotency_key)


def test_compute_next_retry_injectable_now():
    base = dt("2026-09-10 12:00:00")
    at = compute_next_retry(1, retry_after=3600, now=base)
    assert at == base + timedelta(seconds=3600)
    at2 = compute_next_retry(2, now=base)
    assert at2 > base            # 指数退避为正
    assert at2 <= base + timedelta(seconds=3600)   # 封顶


def test_retry_not_due_before_deadline_and_sent_after(repo):
    """同一 429 重试行：到期前 dispatch 不认领；时钟推进过 deadline 后认领并发送成功。"""
    clock = _FakeClock(dt("2026-09-10 12:00:00"))
    _enable(repo, base_url="http://127.0.0.1:1")
    _enqueue(repo, "evt-clock-1")

    calls = []

    def transport(url, headers, body, timeout):
        calls.append((url, clock.now))
        # 首次 429 限流（Retry-After 1 小时），其后放行
        if len(calls) == 1:
            return HttpResponse(status=429, body={"message": "slow down"},
                                retry_after_seconds=3600)
        return HttpResponse(status=200, body={
            "schema_version": "1.0.0", "event_id": "evt-clock-1",
            "accepted": True, "receiver_reference": "R1"})

    worker = DeliveryWorker(repo, transport=transport, delivery_enabled=True,
                            clock=clock)
    stats1 = worker.dispatch_round()
    assert stats1["retried"] == 1
    row = [r for r in repo.list_outbox(limit=10)
           if r.event_id == "evt-clock-1"][0]
    assert row.status == "retry"

    # 到期前：时钟未过 next_retry_at，不重发（不依赖机器速度，无需 sleep）
    clock.advance(minutes=59, seconds=59)
    stats_before = worker.dispatch_round()
    assert stats_before["claimed"] == 0 and stats_before["sent"] == 0
    assert len(calls) == 1, "重试到期前不得再次发送"

    # 到期后：认领并发送成功
    clock.advance(seconds=2)
    stats_after = worker.dispatch_round()
    assert stats_after["sent"] == 1
    row = repo.get_outbox(row.id)
    assert row.status == "sent"
    assert len(calls) == 2


def test_backoff_retry_deadline_from_injected_clock(repo):
    """网络失败（无 Retry-After）走指数退避：到期判定同样由注入时钟推进。"""
    clock = _FakeClock(dt("2026-09-10 12:00:00"))
    _enable(repo, base_url="http://127.0.0.1:1", max_attempts=2)
    _enqueue(repo, "evt-backoff-1")
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(clock.now)
        if len(calls) == 1:
            return HttpResponse(status=None, error="timeout: simulated")
        return HttpResponse(status=200, body={
            "schema_version": "1.0.0", "event_id": "evt-backoff-1",
            "accepted": True})

    worker = DeliveryWorker(repo, transport=transport, delivery_enabled=True,
                            clock=clock)
    assert worker.dispatch_round()["retried"] == 1
    row = [r for r in repo.list_outbox(limit=10)
           if r.event_id == "evt-backoff-1"][0]
    # 退避基准=注入时钟（12:00:00 + 基础 5s + jitter ≤1.5s），到期前不认领
    clock.advance(seconds=4)
    assert worker.dispatch_round()["claimed"] == 0
    clock.advance(seconds=4)
    stats = worker.dispatch_round()
    assert stats["sent"] == 1 and len(calls) == 2


def test_clock_default_is_cn_now():
    """缺省 clock=now_cn（生产行为不变）。"""
    from prearchive.result_contract import now_cn
    worker = DeliveryWorker(None, delivery_enabled=False)
    assert worker.clock() is not None
    assert abs((worker.clock() - now_cn()).total_seconds()) < 5
