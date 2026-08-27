# -*- coding: utf-8 -*-
"""推送模块单测：合并/去重/严重度阈值/接收人兜底/通道独立。"""

from datetime import datetime

import pytest

from prearchive.context import PatientContext
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.pusher import WeComPusher, build_push_payload
from prearchive.receivers import (
    DefaultReceiverResolver,
    Receiver,
    passthrough_userid_mapper,
)
from prearchive.store import ResultRepository

from helpers import dt


class MockSender:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def send(self, url, body, headers, timeout):
        self.calls.append({"url": url, "body": body, "headers": headers})
        return self.status, "mock"

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


def _make_result(problems=None, finished="2026-08-26 10:00:00", patient="P1"):
    repo = ResultRepository(build_session_factory(build_sqlite_engine(":memory:")))
    problems = problems if problems is not None else [
        {"rule_id": "R1", "name": "问题一", "severity": "medium", "message": "msg1"},
        {"rule_id": "R2", "name": "问题二", "severity": "low", "message": "msg2"},
        {"rule_id": "R3", "name": "问题三", "severity": "high", "message": "msg3"},
    ]
    row = repo.upsert_result(
        patient_id=patient, visit_id="1", finished_date_time=dt(finished),
        problems=problems, rule_version="v1", dept_code="D1", dept_name="普外科",
        patient_name="测试甲",
        receiver=None)
    return repo, row


def _ctx(patient="P1"):
    return PatientContext(
        patient_id=patient, visit_id="1", patient_name="测试甲",
        dept_code="D1", dept_name="普外科",
        finished_date_time=dt("2026-08-26 10:00:00"),
        first_finished_doctor_id="TESTDOC01", first_finished_doctor_name="测试医生甲")


def _pusher(sender, enabled=True, levels=None, resolver=None):
    return WeComPusher(
        push_config={"enabled": enabled, "base_url": "http://relay.test",
                     "endpoint": "/qc-record-alert",
                     "severity_levels": levels or ["medium", "high"]},
        secret_provider=lambda: "push-secret",
        sender=sender, resolver=resolver)


def test_push_merged_single_message_per_result():
    """单患者单次合并一条：3 个问题合成一条 payload（R5 打扰纪律）。"""
    repo, row = _make_result()
    sender = MockSender()
    pusher = _pusher(sender)
    outcome = pusher.push_result(row, _ctx())
    assert outcome["status"] == "sent"
    assert len(sender.calls) == 1

    payload = outcome["payload"]
    assert payload["event"] == "prearchive_check_issue"
    assert payload["problem_count"] == 3
    assert len(payload["problems"]) == 3
    assert payload["doctor_id"] == "TESTDOC01"
    assert payload["source"] == "prearchive-service"

    # 签名头齐备（协议字段由 signing 模块测试详查）
    headers = sender.last["headers"]
    assert "X-Relay-Timestamp" in headers and "X-Relay-Signature" in headers


def test_push_dedup_same_result_not_sent_twice():
    repo, row = _make_result()
    sender = MockSender()
    pusher = _pusher(sender)
    assert pusher.push_result(row, _ctx())["status"] == "sent"
    repo.set_push_status(row.id, "wecom", "sent", "HTTP 200")

    # 重新拉行（status 已回写 sent）→ 同 result_id 去重，不再发送
    fresh = repo.get_current("P1", "1")
    outcome = pusher.push_result(fresh, _ctx())
    assert outcome["status"] == "sent" and outcome.get("deduped") is True
    assert len(sender.calls) == 1


def test_push_disabled_and_no_problems():
    sender = MockSender()
    _, row = _make_result(problems=[])
    assert _pusher(sender, enabled=False).push_result(row, _ctx())["status"] == "skipped"
    assert _pusher(sender, enabled=True).push_result(row, _ctx())["status"] == "skipped"
    assert sender.calls == []


def test_push_severity_threshold():
    _, row = _make_result(problems=[{"rule_id": "R", "name": "n",
                                     "severity": "low", "message": "m"}])
    sender = MockSender()
    outcome = _pusher(sender, levels=["medium", "high"]).push_result(row, _ctx())
    assert outcome["status"] == "skipped"
    assert "severity" in outcome["detail"]
    assert sender.calls == []


def test_push_no_receiver_skipped():
    repo, row = _make_result()
    sender = MockSender()
    resolver = DefaultReceiverResolver(userid_mapper=lambda _id: None)
    outcome = _pusher(sender, resolver=resolver).push_result(row, _ctx())
    assert outcome["status"] == "skipped"
    assert "receiver" in outcome["detail"]
    assert sender.calls == []


def test_push_sender_failure_then_retry():
    repo, row = _make_result()
    sender = MockSender(status=500)
    pusher = _pusher(sender)
    outcome1 = pusher.push_result(row, _ctx())
    assert outcome1["status"] == "failed" and "500" in outcome1["detail"]
    repo.set_push_status(row.id, "wecom", "failed", outcome1["detail"])

    sender.status = 200
    fresh = repo.get_current("P1", "1")   # failed ≠ sent → 可重试
    outcome2 = pusher.push_result(fresh, _ctx())
    assert outcome2["status"] == "sent"
    assert len(sender.calls) == 2


def test_push_base_url_placeholder_fails_clean():
    repo, row = _make_result()
    pusher = WeComPusher(
        push_config={"enabled": True, "base_url": "<RELAY_BASE_URL_PLACEHOLDER>",
                     "endpoint": "/qc-record-alert"},
        secret_provider=lambda: "s", sender=MockSender())
    outcome = pusher.push_result(row, _ctx())
    assert outcome["status"] == "failed"
    assert "not configured" in outcome["detail"]


def test_receiver_priority_first_finished_then_attending():
    ctx = _ctx()
    ctx.attending_doctor_id = "TESTDOC02"
    resolver = DefaultReceiverResolver(userid_mapper=passthrough_userid_mapper)
    receiver = resolver.resolve(ctx)
    assert receiver.doctor_id == "TESTDOC01" and receiver.is_fallback is False

    ctx.first_finished_doctor_id = ""      # 工号缺失 → 管床兜底（D1/A4）
    fallback = resolver.resolve(ctx)
    assert fallback.doctor_id == "TESTDOC02" and fallback.is_fallback is True
    assert fallback.via == "attending_doctor"

    ctx.attending_doctor_id = ""
    assert resolver.resolve(ctx) is None


def test_receiver_mapper_can_be_mocked():
    resolver = DefaultReceiverResolver(
        userid_mapper=lambda doctor_id: {"TESTDOC01": "wecom-uid-7"}.get(doctor_id))
    receiver = resolver.resolve(_ctx())
    assert receiver.user_id == "wecom-uid-7"


def test_push_payload_privacy_minimal():
    """R10：推送文案最小化——只带问题摘要，不带病历原文。"""
    repo, row = _make_result()
    payload = build_push_payload(row, _ctx(), Receiver(user_id="u", doctor_id="d"))
    text = json_dumps(payload)
    assert "mr_text" not in text and "病历原文" not in text
    for problem in payload["problems"]:
        assert set(problem.keys()) == {"rule_id", "name", "severity", "message"}


def json_dumps(obj):
    import json

    return json.dumps(obj, ensure_ascii=False)
