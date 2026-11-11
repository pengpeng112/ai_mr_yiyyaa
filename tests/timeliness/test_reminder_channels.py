"""T10：提醒通道抽象测试（app/timeliness/reminder_channels.py）。

覆盖（§15 T10 验收口径）：
- Reminder 校验（source 枚举/patient_id/dedupe_key 必填）与 payload 无 PHI 扩展；
- WeComChannel：LOG_ONLY（默认）零 HTTP（mock relay_client 断言零调用）+ tl_action_log
  DRY_RUN 留痕；dedupe_key 幂等（二次 SKIPPED duplicate 不新增留痕）；D6 强制降级
  （notify_mode=SEND 但契约未确认 → forced LOG_ONLY）；TIMELINESS 源挂 event_id、
  AI/RULE 源 event_id 为空；不同 dedupe_key 互不去重；
- WeComChannel SEND 生效路径（契约确认）：先留痕后外呼 + 结果回填（mock relay）；
  缺中继配置 → BLOCKED；
- JhemrMonitorChannel：TIMELINESS + writer 抛 NotImplementedError → UNAVAILABLE（D3）；
  RULE/AI 源 → SKIPPED；writer 正常 outcome 透传；
- JhemrRectificationChannel：构造即 ChannelDisabled（勘误 E7）；
- dispatch_reminder：单通道异常折叠 BLOCKED 不中断整批；
- build_reminders_from_ai_results：只读查询高危维度（severity 过滤/dedupe_key 格式/
  无 PHI），断言查询前后表行数不变（不改表）；
- 基线：全部测试不连任何真实库；relay 调用以 mock 注入。
"""
from __future__ import annotations

from datetime import datetime
from unittest import mock

import pytest
from fastapi import FastAPI  # noqa: F401  (保持与相邻测试一致的导入风格)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuditDimensionResult, PushLog
from app.timeliness.models import TLActionLog, TLEvent, TLRule, TLRuleVersion
from app.timeliness.reminder_channels import (
    ChannelDisabled,
    JhemrMonitorChannel,
    JhemrRectificationChannel,
    Reminder,
    ReminderChannel,
    WeComChannel,
    build_reminders_from_ai_results,
    dispatch_reminder,
)

TL_MODELS = (TLRule, TLRuleVersion, TLEvent, TLActionLog)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[m.__table__ for m in (*TL_MODELS, PushLog, AuditDimensionResult)])
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def _reminder(**overrides) -> Reminder:
    base = dict(
        source="TIMELINESS",
        patient_id="P001",
        visit_id="1",
        file_unique_id="F001",
        severity="high",
        title="首次病程记录即将超时",
        detail="距截止还有 30 分钟",
        dedupe_key="FIRST_COURSE:P001:1:1",
    )
    base.update(overrides)
    return Reminder(**base)


def _config(**timeliness) -> dict:
    return {
        "timeliness": timeliness or {},
        "relay_alert": {"base_url": "http://relay", "secret_key": "s3cret"},
    }


def _make_event(db) -> TLEvent:
    rule = TLRule(rule_code="FIRST_COURSE", rule_name="首次病程", category="TIMELINESS", enabled=False)
    db.add(rule)
    db.flush()
    version = TLRuleVersion(rule_id=rule.id, version_no=1, trigger_type="ADMISSION",
                            completion_basis="FIRST_SIGN", limit_minutes=480,
                            workday_only=False, action_mode="SHADOW", created_by="test")
    db.add(version)
    db.flush()
    rule.current_version_id = version.id
    event = TLEvent(event_uid="FIRST_COURSE:P001:1:1", rule_code="FIRST_COURSE",
                    rule_version_id=version.id, patient_id="P001", visit_id="1",
                    dept_code="0201", t0=datetime(2026, 11, 12, 8, 0), status="WARNING")
    db.add(event)
    db.commit()
    return event


# ---- Reminder 契约 ----


def test_reminder_validates_source_patient_and_dedupe_key():
    with pytest.raises(ValueError):
        _reminder(source="SMS")
    with pytest.raises(ValueError):
        _reminder(patient_id=" ")
    with pytest.raises(ValueError):
        _reminder(dedupe_key="")
    reminder = _reminder()
    payload = reminder.payload()
    assert payload["source"] == "TIMELINESS" and payload["severity"] == "high"
    assert "patient_name" not in payload  # 无 PHI 扩展字段


# ---- WeComChannel ----


def test_wecom_log_only_records_once_and_dedups_without_http(db):
    event = _make_event(db)
    channel = WeComChannel(db, _config())  # 默认 LOG_ONLY
    with mock.patch("app.timeliness.reminder_channels.send_signed_relay") as relay:
        first = channel.send(_reminder())
        second = channel.send(_reminder())

    relay.assert_not_called()  # LOG_ONLY 零 HTTP
    assert first.handled and not first.sent and first.mode == "DRY_RUN"
    assert first.action_log_id is not None
    assert second.mode == "SKIPPED" and "duplicate" in second.reason
    assert second.action_log_id == first.action_log_id  # 指向同一留痕
    assert db.query(TLActionLog).count() == 1
    row = db.query(TLActionLog).one()
    assert row.action_type == "NOTIFY" and row.mode == "DRY_RUN"
    assert row.target == "WECOM/TIMELINESS/FIRST_COURSE:P001:1:1"
    assert row.event_id == event.id  # TIMELINESS 源且事件存在 → 关联 event_id


def test_wecom_non_timeliness_sources_have_no_event_id(db):
    channel = WeComChannel(db, _config())
    for source, key in (("AI", "101:DIM01"), ("RULE", "R01:doc1")):
        channel.send(_reminder(source=source, dedupe_key=key))
    rows = db.query(TLActionLog).all()
    assert len(rows) == 2
    assert all(row.event_id is None for row in rows)
    assert {row.target for row in rows} == {"WECOM/AI/101:DIM01", "WECOM/RULE/R01:doc1"}


def test_wecom_forced_log_only_when_d6_unconfirmed(db, monkeypatch):
    db, _ = db, None
    channel = WeComChannel(db, _config(notify_mode="SEND", relay_contract_confirmed=False))
    sentinel = mock.Mock(side_effect=AssertionError("must not send"))
    with mock.patch("app.timeliness.reminder_channels.send_signed_relay", sentinel):
        result = channel.send(_reminder())
    assert result.mode == "DRY_RUN" and not result.sent
    row = db.query(TLActionLog).one()
    assert "relay_contract_confirmed" in row.result and "D6" in row.result


def test_wecom_send_mode_writes_log_before_http_and_backfills(db, monkeypatch):
    channel = WeComChannel(db, _config(notify_mode="SEND", relay_contract_confirmed=True))
    observed = {}

    def probing_send(url, payload, secret, **kwargs):
        row = db.query(TLActionLog).one()  # 发送时留痕行已存在
        observed["url"] = url
        observed["result_during_send"] = row.result
        return mock.Mock(status_code=200)

    with mock.patch("app.timeliness.reminder_channels.send_signed_relay", probing_send):
        result = channel.send(_reminder())
    assert result.sent and result.mode == "EXECUTED"
    assert observed["url"] == "http://relay/timeliness-alert"
    assert observed["result_during_send"] == "sending"
    assert db.query(TLActionLog).one().result == "sent: HTTP 200"


def test_wecom_send_mode_without_relay_config_is_blocked(db):
    channel = WeComChannel(db, {"timeliness": {"notify_mode": "SEND", "relay_contract_confirmed": True},
                                "relay_alert": {}})
    result = channel.send(_reminder())
    assert result.mode == "BLOCKED" and not result.sent
    row = db.query(TLActionLog).one()
    assert row.mode == "BLOCKED"  # BLOCKED 不计入去重（可补配置后重试）


def test_wecom_channel_failure_is_folded_into_blocked_result(db, monkeypatch):
    channel = WeComChannel(db, _config(notify_mode="SEND", relay_contract_confirmed=True))
    monkeypatch.setattr(channel, "_find_existing", mock.Mock(side_effect=RuntimeError("boom")))
    result = channel.send(_reminder())
    assert result.mode == "BLOCKED" and "error_type=RuntimeError" in result.reason


# ---- JhemrMonitorChannel ----


def test_monitor_channel_unavailable_while_d3_pending(db):
    def d3_blocked(*args, **kwargs):
        raise NotImplementedError("模板 A 未启用：D3 待嘉和确认")

    channel = JhemrMonitorChannel(writer=mock.Mock(insert_monitor_row=d3_blocked))
    result = channel.send(_reminder())
    assert result.mode == "UNAVAILABLE" and not result.sent
    assert "D3" in result.reason


def test_monitor_channel_skips_non_timeliness_sources():
    channel = JhemrMonitorChannel(writer=mock.Mock())
    result = channel.send(_reminder(source="AI", dedupe_key="101:DIM01"))
    assert result.mode == "SKIPPED"
    channel._writer.insert_monitor_row.assert_not_called()


def test_monitor_channel_passes_through_writer_outcome(db):
    writer = mock.Mock()
    writer.insert_monitor_row.return_value = {
        "handled": True, "executed": False, "mode": "DRY_RUN",
        "action_log_id": 5, "reason": "",
    }
    result = JhemrMonitorChannel(writer=writer).send(_reminder())
    assert result.mode == "DRY_RUN" and result.reference == 5
    writer.insert_monitor_row.assert_called_once()


# ---- JhemrRectificationChannel（E7） ----


def test_rectification_channel_disabled_on_construction():
    with pytest.raises(ChannelDisabled):
        JhemrRectificationChannel()
    assert JhemrRectificationChannel.experimental is True


# ---- 分发 ----


def test_dispatch_folds_channel_errors_and_collects_results(db):
    good = WeComChannel(db, _config())
    class _Broken(ReminderChannel):
        name = "broken"
        def _deliver(self, reminder):
            raise RuntimeError("channel down")
    results = dispatch_reminder(_reminder(), [_Broken(), good])
    assert results[0].mode == "BLOCKED" and "channel down" not in ("",)
    assert results[1].mode == "DRY_RUN"  # 好通道不受坏通道影响


# ---- AI 接入点（只读） ----


def _seed_ai_rows(db, severity="high"):
    push = PushLog(push_time=datetime(2026, 11, 12, 9, 0), trigger_type="daily", query_date="2026-11-12",
                   patient_id="P100", patient_name="张三", visit_number="1", audit_type_code="AT01",
                   dept="耳科", status="success", severity=severity)
    db.add(push)
    db.flush()
    dim = AuditDimensionResult(push_log_id=push.id, dimension_code="D01", dimension="首次病程缺失",
                               status="fail", severity=severity, issue_summary="入院 24h 未书写首次病程")
    db.add(dim)
    db.commit()
    return push, dim


def test_build_reminders_from_ai_results_readonly(db):
    _seed_ai_rows(db, severity="high")
    before = (db.query(PushLog).count(), db.query(AuditDimensionResult).count())
    reminders = build_reminders_from_ai_results(db)
    after = (db.query(PushLog).count(), db.query(AuditDimensionResult).count())
    assert before == after  # 只读：不改表
    assert len(reminders) == 1
    reminder = reminders[0]
    assert reminder.source == "AI"
    assert reminder.patient_id == "P100" and reminder.visit_id == "1"
    assert reminder.dedupe_key.endswith(":D01") and reminder.dedupe_key.split(":")[0].isdigit()
    assert reminder.severity == "high"
    assert "首次病程" in reminder.detail
    assert "张三" not in reminder.title + reminder.detail  # 无 PHI（姓名不入提醒）


def test_build_reminders_filters_severity_levels(db):
    _seed_ai_rows(db, severity="medium")
    assert build_reminders_from_ai_results(db) == []  # 默认仅 high
    reminders = build_reminders_from_ai_results(db, severity_levels=("medium",))
    assert len(reminders) == 1


def test_built_ai_reminder_flows_through_wecom_log_only(db):
    _seed_ai_rows(db, severity="high")
    channel = WeComChannel(db, _config())
    reminder = build_reminders_from_ai_results(db)[0]
    result = channel.send(reminder)
    assert result.mode == "DRY_RUN" and result.handled
    assert db.query(TLActionLog).one().target.startswith("WECOM/AI/")
