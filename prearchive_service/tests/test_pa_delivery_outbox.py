# -*- coding: utf-8 -*-
"""投递 Outbox/Worker/Destination 测试（039 T4 / §12.1 Delivery、Security）。

Mock receiver：本地线程 HTTP 服务覆盖 2xx/409/429/5xx/超时/坏 ACK；
传输层另用注入 transport 覆盖确定性矩阵；result_delivery.enabled=false 断言零网络。
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from prearchive.destinations import (
    DestinationError,
    build_signature,
    resolve_destination,
    severity_eligible,
    validate_target_url,
    seed_default_destinations,
)
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.outbox import DeliveryWorker, HttpResponse
from prearchive.rule_repository import RuleRepository
from prearchive.result_contract import build_contract_test_envelope, serialize_result

from helpers import dt


# ---- Mock receiver（127.0.0.1 本地线程服务） ----

class _MockReceiverHandler(BaseHTTPRequestHandler):
    behavior = {"mode": "ok"}   # 由测试替换

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        mode = _MockReceiverHandler.behavior["mode"]
        payload = json.loads(body or b"{}")
        if mode == "ok":
            self._respond(200, {"schema_version": "1.0.0",
                                "event_id": payload.get("event_id"),
                                "accepted": True,
                                "receiver_reference": "MOCK-REF-1"})
        elif mode == "conflict":
            self._respond(409, {"message": "duplicate event"})
        elif mode == "throttle":
            self._respond(429, {"message": "slow down"}, headers={"Retry-After": "2"})
        elif mode == "server_error":
            self._respond(503, {"message": "boom"})
        elif mode == "bad_ack":
            self._respond(200, {"schema_version": "1.0.0",
                                "event_id": "not-the-event",
                                "accepted": True})
        elif mode == "bad_request":
            self._respond(400, {"message": "bad payload"})
        else:  # pragma: no cover
            self._respond(500, {"message": "unknown mode"})

    def _respond(self, status, payload, headers=None):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默
        pass


@pytest.fixture()
def mock_receiver():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockReceiverHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def repo():
    return RuleRepository(build_session_factory(build_sqlite_engine(":memory:")))


def _enable_destination(repo, code, base_url):
    repo.upsert_destination(
        code=code, kind="mock", enabled=1, base_url=base_url,
        endpoint="/mock/qc-results", auth_type="none",
        secret_ref="", max_attempts=6, allow_insecure_internal_http=1,
        send_severities_json='["medium","high"]')


def _enqueue(repo, event_id="evt-0001", destination="emr_mock"):
    envelope = build_contract_test_envelope(destination)
    envelope.event_id = event_id
    envelope.idempotency_key = f"sha256:{event_id}"
    return repo.enqueue_outbox(
        event_id=event_id, destination_code=destination,
        payload_json=envelope.model_dump_json(),
        idempotency_key=envelope.idempotency_key)


# ---- SSRF / 签名 ----

def test_target_url_ssrf_guards():
    assert validate_target_url("https://emr.hospital.local", "/api/qc", False) \
        == "https://emr.hospital.local/api/qc"
    with pytest.raises(DestinationError):
        validate_target_url("http://emr.hospital.local", "/api", False)   # http 无开关
    with pytest.raises(DestinationError):
        validate_target_url("http://8.8.8.8", "/api", True)               # http 公网
    with pytest.raises(DestinationError):
        validate_target_url("file:///etc/passwd", "", False)
    with pytest.raises(DestinationError):
        validate_target_url("https://user:pw@host.local", "/x", False)
    # 内网 http + 显式开关允许
    assert validate_target_url("http://127.0.0.1:8601", "/m", True)


def test_hmac_fixed_contract_vector():
    """固定契约向量：签名算法不得静默变更。"""
    sig = build_signature("secret", b'{"a":1}', "1700000000")
    import hashlib
    import hmac as _hmac
    expected = _hmac.new(b"secret", b"1700000000" + b"." + b'{"a":1}',
                         hashlib.sha256).hexdigest()
    assert sig == expected


def test_secret_ref_only_env_form(repo):
    repo.upsert_destination(code="d1", kind="mock", enabled=0,
                            base_url="http://127.0.0.1:1", endpoint="/x",
                            auth_type="hmac_sha256", secret_ref="PLAINTEXT",
                            allow_insecure_internal_http=1)
    with pytest.raises(DestinationError, match="env:"):
        resolve_destination(repo, "d1")


# ---- Outbox 语义 ----

def test_enqueue_idempotent_same_event_destination(repo):
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    a = _enqueue(repo)
    b = _enqueue(repo)
    assert a.id == b.id


def test_disabled_worker_zero_network(repo):
    """result_delivery.enabled=false：dispatch_round 不发一行（零网络）。"""
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    _enqueue(repo)
    calls = []

    def _transport(*args, **kwargs):
        calls.append(args)
        return HttpResponse(status=200)

    worker = DeliveryWorker(repo, transport=_transport, delivery_enabled=False)
    stats = worker.dispatch_round()
    assert stats["claimed"] == 0 and "skipped_reason" in stats
    assert calls == []                      # 零真实调用


def test_delivery_outcomes_over_mock_receiver(repo, mock_receiver):
    base = f"http://127.0.0.1:{mock_receiver.server_address[1]}"
    _enable_destination(repo, "emr_mock", base)
    worker = DeliveryWorker(repo, delivery_enabled=True)

    for mode, event_id, expect_status in (
        ("ok", "evt-ok-1", "sent"),
        ("conflict", "evt-409-1", "sent"),          # 409 幂等成功
        ("throttle", "evt-429-1", "retry"),
        ("server_error", "evt-503-1", "retry"),
        ("bad_ack", "evt-badack-1", "dead"),        # ACK event_id 不一致终态
        ("bad_request", "evt-400-1", "dead"),       # 其他 4xx 终态
    ):
        _MockReceiverHandler.behavior["mode"] = mode
        _enqueue(repo, event_id=event_id)
        stats = worker.dispatch_round(limit=5)
        rows = repo.list_outbox(limit=50)
        target = [r for r in rows if r.event_id == event_id][0]
        assert target.status == expect_status, (mode, target.status)

    # 幂等：sent 行不会重复发送
    _MockReceiverHandler.behavior["mode"] = "ok"
    stats = worker.dispatch_round()
    assert stats["sent"] == 0


def test_timeout_returns_unknown_and_retries(repo):
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")   # 无服务=连接拒绝
    _enqueue(repo, event_id="evt-net-1")
    worker = DeliveryWorker(repo, delivery_enabled=True)
    worker.dispatch_round()
    row = [r for r in repo.list_outbox(limit=10) if r.event_id == "evt-net-1"][0]
    assert row.status == "retry"      # 网络失败按状态未知重试


def test_max_attempts_goes_dead(repo):
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    repo.upsert_destination(code="emr_mock", kind="mock", enabled=1,
                            base_url="http://127.0.0.1:1", endpoint="/x",
                            auth_type="none", secret_ref="",
                            max_attempts=1, allow_insecure_internal_http=1)
    _enqueue(repo, event_id="evt-dead-1")
    worker = DeliveryWorker(repo, delivery_enabled=True)
    worker.dispatch_round()
    row = [r for r in repo.list_outbox(limit=10) if r.event_id == "evt-dead-1"][0]
    assert row.status == "dead"


def test_manual_retry_records_actor(repo):
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    repo.upsert_destination(code="emr_mock", kind="mock", enabled=1,
                            base_url="http://127.0.0.1:1", endpoint="/x",
                            auth_type="none", secret_ref="",
                            max_attempts=1, allow_insecure_internal_http=1)
    _enqueue(repo, event_id="evt-retry-1")
    worker = DeliveryWorker(repo, delivery_enabled=True)
    worker.dispatch_round()
    dead = [r for r in repo.list_outbox(limit=10) if r.event_id == "evt-retry-1"][0]
    assert dead.status == "dead"

    from prearchive.rule_service import Actor
    assert worker.retry_manual(dead.id, Actor(id="op-1", name="运维")) is True
    row = repo.get_outbox(dead.id)
    assert row.status == "pending"
    audits = [a for a in repo.list_audit(action="outbox_retry")]
    assert audits and audits[0].actor_id == "op-1"


def test_claim_atomic_no_double_send(repo):
    """并发 claim：两 worker 各 claim 一批，同一行只被一方拿到。"""
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    for i in range(6):
        _enqueue(repo, event_id=f"evt-race-{i}")
    from prearchive.result_contract import now_cn
    w1 = DeliveryWorker(repo, delivery_enabled=True, worker_id="w1")
    w2 = DeliveryWorker(repo, delivery_enabled=True, worker_id="w2")
    claimed1 = repo.claim_pending(owner="w1", now=now_cn(), limit=10)
    claimed2 = repo.claim_pending(owner="w2", now=now_cn(), limit=10)
    ids1 = {c.id for c in claimed1}
    ids2 = {c.id for c in claimed2}
    assert not (ids1 & ids2), "同一 outbox 行被两个 worker 认领"


def test_reconcile_backfills_missing_outbox(repo):
    _enable_destination(repo, "emr_mock", "http://127.0.0.1:1")
    results = [(1, "P1", "1", "D1", dt("2026-09-02 10:00:00"),
                json.dumps([{"rule_id": "R1", "severity": "high",
                             "message": "m", "name": "n"}], ensure_ascii=False),
                "2026.09.02.1")]
    worker = DeliveryWorker(repo, delivery_enabled=True)
    report = worker.reconcile_results(lambda: results)
    assert report["enqueued"] == 1
    # 再跑一遍幂等
    report2 = worker.reconcile_results(lambda: results)
    assert report2["enqueued"] == 0


def test_severity_filter_respects_send_severities(repo):
    class _D:  # 简化目标对象
        send_severities = ["medium", "high"]
    assert severity_eligible(_D(), "high") is True
    assert severity_eligible(_D(), "low") is False
    _D.send_severities = []
    assert severity_eligible(_D(), "low") is True   # 空列表=不过滤


def test_seed_default_destinations_disabled_by_default(repo):
    seed_default_destinations(repo)
    for code in ("emr_mock", "his_mock"):
        row = repo.get_destination(code)
        assert row is not None and row.enabled == 0    # G2/G3 未确认保持禁用
