# -*- coding: utf-8 -*-
"""Outbox 投递 Worker（039 §7.2）。

可靠性语义：
- 结果事务提交后入队；enqueue 失败可由 reconcile_results 补齐；
- 原子 claim（仓储层条件 UPDATE），多 worker 不重复发送；
- 指数退避 + jitter，尊重 Retry-After（秒级）；
- lease 超时可回收（worker 崩溃自愈）；sent 永不自动回退；
- result_delivery.enabled=false 时 dispatch_round 一行也不发（零网络），
  只允许 dry-run preview（构造 envelope 不发送）。
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from .destinations import (
    DestinationError,
    build_delivery_headers,
    mask_url_for_log,
    resolve_destination,
)
from .result_contract import (
    DeliveryOutcome,
    QCResultEnvelope,
    build_idempotency_key,
    classify_delivery,
    now_cn,
)
from .rule_models import (
    OUTBOX_DEAD,
    OUTBOX_DISABLED,
    OUTBOX_RETRY,
    OUTBOX_SENT,
)
from .rule_repository import RuleRepository

logger = logging.getLogger("prearchive.delivery")

BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 3600


@dataclass
class HttpResponse:
    """传输层抽象：真实 HTTP 或测试注入。"""

    status: Optional[int]
    body: Optional[dict] = None
    error: Optional[str] = None
    retry_after_seconds: Optional[int] = None


def default_http_post(url: str, headers: dict, body: bytes,
                      timeout_seconds: int) -> HttpResponse:
    """真实传输（httpx，已是预检服务依赖）；测试注入 transport 替换。"""
    import httpx

    try:
        response = httpx.post(url, headers=headers, content=body,
                              timeout=timeout_seconds)
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:200]}
        retry_after = response.headers.get("Retry-After")
        return HttpResponse(
            status=response.status_code,
            body=payload,
            retry_after_seconds=int(retry_after) if retry_after and retry_after.isdigit() else None,
        )
    except httpx.TimeoutException as exc:
        return HttpResponse(status=None, error=f"timeout: {exc}")
    except Exception as exc:  # noqa: BLE001
        return HttpResponse(status=None, error=f"{type(exc).__name__}: {exc}")


def compute_next_retry(attempts: int, retry_after: Optional[int] = None) -> datetime:
    if retry_after and retry_after > 0:
        return now_cn() + timedelta(seconds=min(retry_after, MAX_BACKOFF_SECONDS))
    backoff = min(BASE_BACKOFF_SECONDS * (2 ** max(0, attempts - 1)),
                  MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, backoff * 0.3)
    return now_cn() + timedelta(seconds=backoff + jitter)


class DeliveryWorker:
    def __init__(self, repository: RuleRepository, *,
                 transport: Callable[..., HttpResponse] = default_http_post,
                 delivery_enabled: bool = False, worker_id: str = "worker-1"):
        self.repository = repository
        self.transport = transport
        self.delivery_enabled = delivery_enabled
        self.worker_id = worker_id

    # ---- 入队 ----

    def enqueue_for_result(self, envelope: QCResultEnvelope,
                           destinations: Optional[List[str]] = None) -> List[dict]:
        """按目标生成 Outbox 行（结果事务后调用；幂等）。"""
        created = []
        for row in self.repository.list_destinations():
            if destinations is not None and row.code not in destinations:
                continue
            if not row.enabled:
                continue
            envelope.idempotency_key = build_idempotency_key(
                envelope.event_id, row.code)
            outbox = self.repository.enqueue_outbox(
                event_id=envelope.event_id,
                destination_code=row.code,
                payload_json=envelope.model_dump_json(),
                idempotency_key=envelope.idempotency_key,
            )
            created.append({"event_id": envelope.event_id,
                            "destination_code": row.code,
                            "outbox_id": outbox.id,
                            "status": outbox.status})
        return created

    # ---- 发送 ----

    def dispatch_round(self, limit: int = 20) -> dict:
        if not self.delivery_enabled:
            return {"claimed": 0, "sent": 0, "retried": 0, "dead": 0,
                    "skipped_reason": "result_delivery.enabled=false"}
        claimed = self.repository.claim_pending(
            owner=self.worker_id, now=now_cn(), limit=limit)
        stats = {"claimed": len(claimed), "sent": 0, "retried": 0, "dead": 0}
        for outbox in claimed:
            self._send_one(outbox, stats)
        return stats

    def _send_one(self, outbox, stats: dict) -> None:
        attempts = int(outbox.attempts or 0) + 1
        try:
            destination = resolve_destination(self.repository, outbox.destination_code)
        except DestinationError as exc:
            # 目标配置坏（SSRF 校验失败/密钥缺）：终态 dead，人工修配置后 retry
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_DEAD, error=str(exc), attempts=attempts)
            self.repository.append_delivery_log(
                outbox_id=outbox.id, event_id=outbox.event_id,
                destination_code=outbox.destination_code, attempt=attempts,
                http_status=None, outcome=DeliveryOutcome.TERMINAL, detail=str(exc))
            stats["dead"] += 1
            return

        if not destination.enabled:
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_DISABLED,
                error="destination disabled", attempts=attempts)
            return

        body = (outbox.payload_json or "{}").encode("utf-8")
        try:
            headers = build_delivery_headers(destination, body)
        except DestinationError as exc:
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_DEAD, error=str(exc), attempts=attempts)
            stats["dead"] += 1
            return

        response = self.transport(
            destination.url, headers, body, destination.timeout_seconds)
        outcome, ack, detail = classify_delivery(
            response.status, response.error, outbox.event_id, response.body)

        self.repository.append_delivery_log(
            outbox_id=outbox.id, event_id=outbox.event_id,
            destination_code=outbox.destination_code, attempt=attempts,
            http_status=response.status, outcome=outcome,
            ack_event_id=getattr(ack, "event_id", "") or "",
            receiver_reference=str(getattr(ack, "receiver_reference", "") or ""),
            detail=detail,
        )
        logger.info("delivery %s -> %s outcome=%s status=%s url=%s",
                    outbox.event_id, outbox.destination_code, outcome,
                    response.status, mask_url_for_log(destination.url))

        if outcome in (DeliveryOutcome.SENT, DeliveryOutcome.DUPLICATE):
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_SENT, http_status=response.status,
                attempts=attempts)
            stats["sent"] += 1
            return

        if outcome in (DeliveryOutcome.RETRYABLE, DeliveryOutcome.UNKNOWN):
            if attempts >= destination.max_attempts:
                self.repository.finish_outbox(
                    outbox.id, status=OUTBOX_DEAD, http_status=response.status,
                    error=detail, attempts=attempts)
                stats["dead"] += 1
                return
            next_at = compute_next_retry(attempts, response.retry_after_seconds)
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_RETRY, http_status=response.status,
                error=detail, next_retry_at=next_at, attempts=attempts)
            stats["retried"] += 1
            return

        # terminal：其他 4xx / 坏 ACK / event_id 不一致——停自动重试，等人工
        self.repository.finish_outbox(
            outbox.id, status=OUTBOX_DEAD, http_status=response.status,
            error=detail, attempts=attempts)
        stats["dead"] += 1

    def retry_manual(self, outbox_id: str, actor) -> bool:
        """人工重试：只允许 dead/disabled → pending，必须记录操作者。"""
        outbox = self.repository.get_outbox(outbox_id)
        if outbox is None:
            return False
        if outbox.status not in (OUTBOX_DEAD, OUTBOX_DISABLED, OUTBOX_RETRY):
            return False
        ok = self.repository.finish_outbox(outbox_id, status="pending", error="")
        if ok:
            self.repository.append_audit(
                action="outbox_retry", actor_id=actor.id, actor_name=actor.name,
                reason=f"manual retry outbox {outbox_id}",
                detail={"event_id": outbox.event_id,
                        "destination_code": outbox.destination_code})
        return ok

    # ---- 对账 ----

    def reconcile_results(self, results_provider: Callable[[], list]) -> dict:
        """补齐缺失 Outbox：遍历已提交结果，比对既有 event 行。

        results_provider 返回 [(result_id, patient_id, visit_id, dept_code,
        finished_at, problems_json, rule_version), ...]——调用方保证只读。
        """
        report = {"checked": 0, "enqueued": 0, "missing_results": []}
        existing = {(row.event_id, row.destination_code)
                    for row in self.repository.list_outbox(limit=100000)}
        for result in results_provider():
            report["checked"] += 1
            event_id = _event_id_for_result(result)
            if event_id is None:
                report["missing_results"].append({
                    "result_id": str(result[0]),
                    "reason": "cannot derive event id (missing finished_at)"})
                continue
            for row in self.repository.list_destinations():
                if not row.enabled:
                    continue
                if (event_id, row.code) in existing:
                    continue
                envelope = build_envelope_for_reconcile(result, event_id, row.code)
                self.repository.enqueue_outbox(
                    event_id=event_id, destination_code=row.code,
                    payload_json=envelope.model_dump_json(),
                    idempotency_key=envelope.idempotency_key)
                report["enqueued"] += 1
        return report


def _event_id_for_result(result) -> Optional[str]:
    """结果行 → 确定性 event_id（同一结果重跑不产生新事件）。"""
    result_id, patient_id, visit_id, _dept, finished_at = result[0], result[1], result[2], result[3], result[4]
    if not finished_at:
        return None
    import hashlib
    digest = hashlib.sha256(
        f"prearchive-result:{result_id}:{patient_id}:{visit_id}:{finished_at.isoformat()}"
        .encode("utf-8")).hexdigest()[:32]
    return f"res-{digest}"


def build_envelope_for_reconcile(result, event_id: str, destination_code: str):
    from .result_contract import serialize_result

    _result_id, patient_id, visit_id, dept_code, finished_at, problems_json, rule_version = \
        result[0], result[1], result[2], result[3], result[4], result[5], result[6]
    problems = json.loads(problems_json or "[]")
    envelope = serialize_result(
        result_id=_result_id,
        patient_id=patient_id,
        visit_number=visit_id,
        dept_code=dept_code,
        trigger_mode="reconcile",
        checked_at=finished_at,
        problems=problems,
        rule_version=rule_version,
        event_id=event_id,
    )
    envelope.idempotency_key = build_idempotency_key(event_id, destination_code)
    return envelope
