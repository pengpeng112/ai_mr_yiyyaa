"""T7：通用通知层与时效提醒器单元测试。

覆盖（§15 T7 验收口径）：
- relay_client 签名正确性：固定时间戳下 HMAC-SHA256 逐字节核对、headers 契约、
  send_signed_relay 的 POST 参数（isolated_mode 的 allow_redirects 分支）；
- notify 幂等去重：同一 event_uid + 同一通知类型只处理一次；不同通知类型互不去重；
  BLOCKED（缺中继配置）不计入去重，补齐后可重试；
- LOG_ONLY（默认）与「SEND 但 relay_contract_confirmed!=True 强制 LOG_ONLY」：
  mock 断言零 HTTP 调用，且 tl_action_log 先留痕（mode=DRY_RUN）；
- SEND 生效路径：先写 tl_action_log 再发送、结果回填、失败不抛出；
- 事件不存在 / notify_type 非法 → TimelinessNotifierError。
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from unittest import mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.services import relay_client
from app.timeliness.models import TLActionLog, TLEvent, TLRule, TLRuleVersion, TLScanRun
from app.timeliness.notifier import (
    LOG_ONLY,
    SEND,
    TimelinessNotifier,
    TimelinessNotifierError,
    resolve_notify_mode,
)

TL_MODELS = (TLRule, TLRuleVersion, TLEvent, TLActionLog, TLScanRun)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[model.__table__ for model in TL_MODELS])
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def _make_event(db, event_uid: str = "FIRST_COURSE:P001:1:V001") -> TLEvent:
    rule = TLRule(rule_code="FIRST_COURSE", rule_name="首次病程记录", category="TIMELINESS", enabled=False)
    db.add(rule)
    db.flush()
    version = TLRuleVersion(
        rule_id=rule.id, version_no=1, trigger_type="ADMISSION",
        completion_basis="FIRST_SIGN", limit_minutes=480, workday_only=False,
        action_mode="SHADOW", created_by="test",
    )
    db.add(version)
    db.flush()
    rule.current_version_id = version.id
    event = TLEvent(
        event_uid=event_uid, rule_code="FIRST_COURSE", rule_version_id=version.id,
        patient_id="P001", visit_id="1", dept_code="0101", t0=datetime(2026, 11, 11, 8, 0, 0),
        deadline=datetime(2026, 11, 11, 16, 0, 0), status="WARNING",
    )
    db.add(event)
    db.commit()
    return event


def _resp(status_code: int = 200):
    return mock.Mock(status_code=status_code)


# ---- relay_client 签名正确性 ----


class TestRelayClientSignature:
    def test_build_signed_request_hmac_exact(self):
        payload = {"msg_type": "timeliness_notify", "event_uid": "R:P:1:X"}
        secret = "unit-test-secret"
        fixed_ts = 1762857600
        with mock.patch.object(relay_client.time, "time", return_value=float(fixed_ts)):
            raw_body, headers = relay_client.build_signed_request(payload, secret)
        expected_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        expected_sig = hmac.new(
            secret.encode("utf-8"),
            str(fixed_ts).encode("utf-8") + b"." + expected_body,
            hashlib.sha256,
        ).hexdigest()
        assert raw_body == expected_body
        assert headers["X-Relay-Timestamp"] == str(fixed_ts)
        assert headers["X-Relay-Signature"] == expected_sig
        assert headers["Content-Type"] == "application/json; charset=utf-8"

    def test_send_signed_relay_posts_signed_body(self):
        payload = {"a": 1}
        with mock.patch.object(relay_client.time, "time", return_value=1762857600.0), \
                mock.patch.object(relay_client.requests, "post") as post:
            post.return_value = _resp(200)
            resp = relay_client.send_signed_relay("http://relay/timeliness-alert", payload, "s", timeout=7)
        assert resp is post.return_value
        args, kwargs = post.call_args
        assert args[0] == "http://relay/timeliness-alert"
        assert kwargs["data"] == json.dumps(payload, separators=(",", ":")).encode("utf-8")
        assert kwargs["timeout"] == 7
        # 默认（非隔离）分支不传 allow_redirects → requests 默认跟随重定向（与原实现一致）
        assert "allow_redirects" not in kwargs
        assert kwargs["headers"]["X-Relay-Signature"]

    def test_send_signed_relay_isolated_mode_disallows_redirects(self):
        with mock.patch.object(relay_client.requests, "post") as post:
            relay_client.send_signed_relay(
                "http://127.0.0.1:9/x", {"a": 1}, "s", isolated_mode=True,
            )
        assert post.call_args.kwargs["allow_redirects"] is False


# ---- notify_mode 解析（D6 闸门） ----


class TestResolveNotifyMode:
    def test_default_is_log_only(self):
        assert resolve_notify_mode({}) == (LOG_ONLY, "")
        assert resolve_notify_mode({"timeliness": {}}) == (LOG_ONLY, "")
        assert resolve_notify_mode(None) == (LOG_ONLY, "")

    def test_send_requires_relay_contract_confirmed(self):
        # D6：契约未确认（缺键 / 显式 False / 大小写形态），SEND 一律强制 LOG_ONLY
        for confirmed in (None, False, "false", "true", 1):
            mode, reason = resolve_notify_mode({
                "timeliness": {"notify_mode": "SEND", "relay_contract_confirmed": confirmed},
            })
            assert mode == LOG_ONLY
            assert "relay_contract_confirmed" in reason and "D6" in reason
        mode, reason = resolve_notify_mode({
            "timeliness": {"notify_mode": "SEND", "relay_contract_confirmed": True},
        })
        assert (mode, reason) == (SEND, "")

    def test_invalid_mode_falls_back_to_log_only(self):
        assert resolve_notify_mode({"timeliness": {"notify_mode": "SMS"}}) == (LOG_ONLY, "")


# ---- 幂等去重与留痕顺序 ----


class TestNotifyDedupAndOrdering:
    def config(self, **timeliness) -> dict:
        return {
            "timeliness": timeliness or {},
            "relay_alert": {"base_url": "http://relay", "secret_key": "s3cret"},
        }

    def test_log_only_records_once_then_dedups_without_http(self, db):
        event = _make_event(db)
        notifier = TimelinessNotifier(db, self.config())  # 默认 LOG_ONLY
        with mock.patch.object(relay_client, "requests") as fake_requests:
            first = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
            second = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")

        assert first["handled"] is True and first["sent"] is False and first["mode"] == LOG_ONLY
        assert first["forced"] is False
        # 幂等去重：第二次直接跳过，不新增留痕
        assert second["handled"] is False
        assert second["reason"].startswith("duplicate")
        assert second["action_log_id"] == first["action_log_id"]
        rows = db.query(TLActionLog).all()
        assert len(rows) == 1
        assert rows[0].action_type == "NOTIFY"
        assert rows[0].mode == "DRY_RUN"  # LOG_ONLY 留痕：只记录未真发
        assert "LOG_ONLY" in rows[0].result
        # LOG_ONLY 绝不发真实 HTTP
        fake_requests.post.assert_not_called()

    def test_different_notify_types_do_not_dedup_each_other(self, db):
        event = _make_event(db)
        notifier = TimelinessNotifier(db, self.config())
        with mock.patch.object(relay_client, "requests"):
            warn = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
            overdue = notifier.notify_event(event_uid=event.event_uid, notify_type="OVERDUE")
        assert warn["handled"] is True and overdue["handled"] is True
        assert db.query(TLActionLog).count() == 2

    def test_forced_log_only_when_contract_unconfirmed(self, db):
        event = _make_event(db)
        notifier = TimelinessNotifier(
            db, self.config(notify_mode="SEND", relay_contract_confirmed=False),
            sender=_failing_sender(),
        )
        result = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
        # SEND 被强制降级：标记 forced、零 HTTP（sender 为必炸哨兵即证明未调用）
        assert result["mode"] == LOG_ONLY
        assert result["forced"] is True
        assert "relay_contract_confirmed" in result["reason"]
        row = db.query(TLActionLog).one()
        assert row.mode == "DRY_RUN"
        assert "forced LOG_ONLY" in row.result

    def test_send_mode_writes_action_log_before_http_and_backfills(self, db):
        event = _make_event(db)
        calls: list[str] = []

        def probing_sender(url, payload, secret, *, timeout=10, isolated_mode=False):
            # 发送时刻：tl_action_log 必须已落库（先留痕后外呼）
            calls.append(url)
            row = db.query(TLActionLog).one()
            assert row.result == "sending"
            assert row.mode == "EXECUTED"
            assert json.loads(row.params_json)["event_uid"] == event.event_uid
            return _resp(200)

        notifier = TimelinessNotifier(
            db, self.config(notify_mode="SEND", relay_contract_confirmed=True),
            sender=probing_sender,
        )
        result = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
        assert result["sent"] is True and result["mode"] == SEND
        assert calls == ["http://relay/timeliness-alert"]  # 默认端点，D6 契约后可配
        row = db.query(TLActionLog).one()
        assert row.result == "sent: HTTP 200"
        assert row.mode == "EXECUTED"

    def test_send_mode_http_failure_records_and_does_not_raise(self, db):
        event = _make_event(db)

        def failing_sender(url, payload, secret, **kwargs):
            raise RuntimeError("connection refused")

        notifier = TimelinessNotifier(
            db, self.config(notify_mode="SEND", relay_contract_confirmed=True),
            sender=failing_sender,
        )
        result = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
        assert result["sent"] is False
        assert result["reason"] == "error_type=RuntimeError"
        row = db.query(TLActionLog).one()
        assert row.result == "failed: RuntimeError"
        assert row.mode == "EXECUTED"  # 已尝试外呼，计入去重

    def test_blocked_missing_relay_config_is_retryable(self, db):
        event = _make_event(db)
        # relay_contract_confirmed=True 但无 base_url/secret → BLOCKED，不计入去重
        notifier = TimelinessNotifier(
            db, {"timeliness": {"notify_mode": "SEND", "relay_contract_confirmed": True},
                 "relay_alert": {}},
            sender=_failing_sender(),
        )
        first = notifier.notify_event(event_uid=event.event_uid, notify_type="WARN")
        assert first["handled"] is False
        assert first["reason"].startswith("blocked")
        assert db.query(TLActionLog).one().mode == "BLOCKED"

        # 补齐配置后同一 event_uid + 类型可重试成功
        fixed = TimelinessNotifier(
            db, self.config(notify_mode="SEND", relay_contract_confirmed=True),
            sender=lambda *a, **k: _resp(200),
        )
        second = fixed.notify_event(event_uid=event.event_uid, notify_type="WARN")
        assert second["sent"] is True
        assert db.query(TLActionLog).count() == 2  # BLOCKED 1 + EXECUTED 1

    def test_unknown_event_or_bad_notify_type_raises(self, db):
        notifier = TimelinessNotifier(db, self.config())
        with pytest.raises(TimelinessNotifierError):
            notifier.notify_event(event_uid="NOPE:P:1:X", notify_type="WARN")
        _make_event(db)
        with pytest.raises(TimelinessNotifierError):
            notifier.notify_event(event_uid="FIRST_COURSE:P001:1:V001", notify_type="")
        with pytest.raises(TimelinessNotifierError):
            notifier.notify_event(event_uid="FIRST_COURSE:P001:1:V001", notify_type="X" * 33)


def _failing_sender():
    def sender(*args, **kwargs):  # pragma: no cover - 调用即测试失败
        raise AssertionError("sender must not be called in LOG_ONLY mode")

    return sender
