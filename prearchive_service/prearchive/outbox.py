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
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, List, Optional

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

# WP07：受控中间表投递（staging_table）——与 HTTP 同一 Outbox 重试/死信框架。
# 表名白名单正则（任务书 §3.4）：防注入，拒绝任何非 [A-Za-z][A-Za-z0-9_]{0,29}
# （可选 schema 前缀）的表名；写入一律参数化 + 幂等 NOT EXISTS 门。
STAGING_TABLE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]{0,29}(\.[A-Za-z][A-Za-z0-9_]{0,29})?$")
STAGING_IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,29}$")


def build_staging_insert_sql(table: str, idempotency_column: str) -> str:
    """构造 Oracle 参数化幂等写入 SQL（表/列名经白名单正则校验后拼接）。"""
    if not STAGING_TABLE_PATTERN.match(table or ""):
        raise DestinationError(f"staging table name rejected by allowlist: {table!r}")
    if not STAGING_IDEMPOTENCY_PATTERN.match(idempotency_column or ""):
        raise DestinationError(
            f"staging idempotency_column rejected by allowlist: {idempotency_column!r}")
    return (
        f"INSERT INTO {table} ({idempotency_column}, PAYLOAD_JSON, CREATED_AT) "
        f"SELECT :idempotency_key, :payload_json, SYSDATE FROM dual "
        f"WHERE NOT EXISTS (SELECT 1 FROM {table} "
        f"WHERE {idempotency_column} = :idempotency_key)"
    )


def default_staging_connect(dsn_env: str):
    """真实中间表连接（DSN 只从环境变量读；未设置抛 DestinationError）。"""
    dsn = os.environ.get(dsn_env or "", "").strip()
    if not dsn:
        raise DestinationError(f"staging dsn env not set: {dsn_env!r}")
    from .destinations import resolve_secret  # env: 前缀共用

    try:
        import oracledb  # type: ignore
        return oracledb.connect(dsn=dsn)
    except ImportError:
        import cx_Oracle  # type: ignore
        return cx_Oracle.connect(dsn=dsn)


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


def compute_next_retry(attempts: int, retry_after: Optional[int] = None,
                       now: Optional[datetime] = None) -> datetime:
    """计算下次重试时间；now 可注入（046 ST-003：时序测试不依赖真实时钟/短 Retry-After）。"""
    base = now if now is not None else now_cn()
    if retry_after and retry_after > 0:
        return base + timedelta(seconds=min(retry_after, MAX_BACKOFF_SECONDS))
    backoff = min(BASE_BACKOFF_SECONDS * (2 ** max(0, attempts - 1)),
                  MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, backoff * 0.3)
    return base + timedelta(seconds=backoff + jitter)


class DeliveryWorker:
    def __init__(self, repository: RuleRepository, *,
                 transport: Callable[..., HttpResponse] = default_http_post,
                 delivery_enabled: bool = False, worker_id: str = "worker-1",
                 clock: Callable[[], datetime] = now_cn,
                 staging_connect: Callable[..., Any] | None = None,
                 staging_config: dict | None = None):
        self.repository = repository
        self.transport = transport
        self.delivery_enabled = delivery_enabled
        self.worker_id = worker_id
        # 046 ST-003：时钟可注入——重试到期前后的判定在测试中用可控时钟推进，
        # 不再依赖真实 sleep 或缩短 Retry-After 凑时序
        self.clock = clock
        # WP07：中间表连接工厂（默认 default_staging_connect；测试注入假连接，
        # 未启用 staging 目的地时零连接）。
        self.staging_connect = staging_connect or default_staging_connect
        # WP07：destination_code → {dsn_env, table, idempotency_column}（由装配层
        # 从 config.result_delivery.staging_table + destinations 表组装传入）
        self.staging_config = dict(staging_config or {})

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
            owner=self.worker_id, now=self.clock(), limit=limit)
        stats = {"claimed": len(claimed), "sent": 0, "retried": 0, "dead": 0}
        for outbox in claimed:
            self._send_one(outbox, stats)
        return stats

    def _send_one(self, outbox, stats: dict) -> None:
        attempts = int(outbox.attempts or 0) + 1
        # WP07：staging_table 目的地分流（与 HTTP 同一重试/死信状态机；不改 destinations.py）
        destination_row = self.repository.get_destination(outbox.destination_code)
        if destination_row is not None and str(destination_row.kind) == "staging_table":
            self._send_staging_table(outbox, destination_row, stats, attempts)
            return
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
            next_at = compute_next_retry(attempts, response.retry_after_seconds,
                                         now=self.clock())
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

    def _send_staging_table(self, outbox, destination_row, stats: dict,
                            attempts: int) -> None:
        """staging_table 传输：参数化幂等 INSERT，与 HTTP 共用重试/死信状态机。

        - 目的地未启用 → disabled（同 HTTP 语义）；
        - 配置缺/表名非法 → terminal dead（人工修配置后 retry）；
        - DSN 环境变量未设/连接失败/执行失败 → retryable（走既有退避）；
        - rowcount=0 → 幂等命中（duplicate）→ sent。
        """
        if not destination_row.enabled:
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_DISABLED,
                error="destination disabled", attempts=attempts)
            return
        cfg = (self.staging_config or {}).get(outbox.destination_code) or {}
        dsn_env = str(cfg.get("dsn_env") or "")
        table = str(cfg.get("table") or "")
        idem_col = str(cfg.get("idempotency_column") or "IDEMPOTENCY_KEY")
        try:
            sql = build_staging_insert_sql(table, idem_col)
        except DestinationError as exc:
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_DEAD, error=str(exc), attempts=attempts)
            self.repository.append_delivery_log(
                outbox_id=outbox.id, event_id=outbox.event_id,
                destination_code=outbox.destination_code, attempt=attempts,
                http_status=None, outcome=DeliveryOutcome.TERMINAL, detail=str(exc))
            stats["dead"] += 1
            return

        idempotency_key = str(outbox.idempotency_key or outbox.event_id)
        payload_json = str(outbox.payload_json or "{}")
        outcome = DeliveryOutcome.RETRYABLE
        detail = ""
        http_status = None
        conn = None
        try:
            conn = self.staging_connect(dsn_env)
            cur = conn.cursor()
            try:
                cur.execute(sql, {
                    "idempotency_key": idempotency_key,
                    "payload_json": payload_json,
                })
                inserted = int(getattr(cur, "rowcount", 0) or 0)
            finally:
                cur.close()
            conn.commit()
            if inserted > 0:
                outcome = DeliveryOutcome.SENT
                detail = f"staging insert ok ({table})"
            else:
                outcome = DeliveryOutcome.DUPLICATE
                detail = f"staging idempotency hit ({idem_col}={idempotency_key})"
        except DestinationError as exc:
            # DSN 环境变量未设置：环境可修复 → retryable
            outcome = DeliveryOutcome.RETRYABLE
            detail = str(exc)
        except Exception as exc:  # noqa: BLE001
            outcome = DeliveryOutcome.RETRYABLE
            detail = f"{type(exc).__name__}: {exc}"
        finally:
            close = getattr(conn, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001
                    pass

        self.repository.append_delivery_log(
            outbox_id=outbox.id, event_id=outbox.event_id,
            destination_code=outbox.destination_code, attempt=attempts,
            http_status=http_status, outcome=outcome, detail=detail)
        logger.info("delivery %s -> %s staging outcome=%s table=%s",
                    outbox.event_id, outbox.destination_code, outcome, table)

        if outcome in (DeliveryOutcome.SENT, DeliveryOutcome.DUPLICATE):
            self.repository.finish_outbox(
                outbox.id, status=OUTBOX_SENT, attempts=attempts)
            stats["sent"] += 1
            return
        # retryable：复用同一退避计算
        next_at = compute_next_retry(attempts, None, now=self.clock())
        self.repository.finish_outbox(
            outbox.id, status=OUTBOX_RETRY, error=detail,
            next_retry_at=next_at, attempts=attempts)
        stats["retried"] += 1

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
