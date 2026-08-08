"""Push execution 原子 claim 与 attempt 记录（ACTIVE/002）。

网络调用必须在 claim 事务提交之后进行；成功/失败通过 finish_execution 回写。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError

from app.models import PushAttempt, PushExecution, PushLog

DEFAULT_LEASE_SECONDS = 900


def make_idempotency_key(
    source_record_key: str,
    audit_type_code: str,
    audit_run_mode: str,
    source_version: str = "",
) -> str:
    """稳定幂等键：统一跨入口业务互斥身份。

    P1-5: source_version 不参与 key 计算，避免同一业务身份因不同入口 version 分裂。
    source_version 仅保留为审计/attempt 字段。
    """
    raw = "|".join(
        str(v or "").strip()
        for v in (source_record_key, audit_type_code, audit_run_mode)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def claim_execution(
    db,
    source_record_key: str,
    audit_type_code: str,
    audit_run_mode: str,
    source_version: str = "",
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    *,
    force: bool = False,
) -> Tuple[Optional[PushExecution], bool, str]:
    """原子 claim 一次 execution。

    Returns:
        (execution, claimed, reason)
        - claimed=True, reason='claimed'：本 worker 获得 lease，可调用 Dify
        - claimed=False, reason='same_version_reviewed'：同版本已成功且已复核，禁止重复
        - claimed=False, reason='in_flight'：其他 worker 持有未过期 lease
        - claimed=False, reason='force_required'：已有成功结果且未 force（防御性）
    """
    key = make_idempotency_key(source_record_key, audit_type_code, audit_run_mode, source_version)
    now = datetime.now()
    token = secrets.token_hex(16)
    mode = str(audit_run_mode or "daily_increment").strip() or "daily_increment"
    type_code = str(audit_type_code or "").strip()
    source_key = str(source_record_key or "").strip()
    version = str(source_version or "").strip()

    execution = (
        db.query(PushExecution)
        .filter(
            PushExecution.idempotency_key == key,
            PushExecution.audit_run_mode == mode,
        )
        .with_for_update()
        .first()
    )

    if execution is None:
        execution = PushExecution(
            idempotency_key=key,
            audit_run_mode=mode,
            source_record_key=source_key,
            audit_type_code=type_code,
            source_version=version,
            status="running",
            owner_token=token,
            lease_until=now + timedelta(seconds=int(lease_seconds or DEFAULT_LEASE_SECONDS)),
        )
        try:
            # nested savepoint：唯一键冲突时不破坏外层事务
            with db.begin_nested():
                db.add(execution)
                db.flush()
        except IntegrityError:
            execution = (
                db.query(PushExecution)
                .filter(
                    PushExecution.idempotency_key == key,
                    PushExecution.audit_run_mode == mode,
                )
                .with_for_update()
                .first()
            )
            if execution is None:
                raise

    # 同版本已成功且已复核：默认跳过（force=True 用于历史重跑）
    if execution.status == "success" and execution.reviewed_flag and not force:
        return execution, False, "same_version_reviewed"

    if execution.status == "success" and execution.push_log_id and not force:
        prior_log = db.query(PushLog).filter(PushLog.id == execution.push_log_id).first()
        if prior_log and prior_log.reviewed_flag:
            execution.reviewed_flag = 1
            return execution, False, "same_version_reviewed"

    # P1-5: 其他 worker 持有未过期 lease — force 不得绕过有效 in-flight
    if (
        execution.status == "running"
        and execution.owner_token
        and execution.owner_token != token
        and execution.lease_until
        and execution.lease_until > now
    ):
        return execution, False, "in_flight"

    # 接管或首次 claim
    execution.status = "running"
    execution.owner_token = token
    execution.lease_until = now + timedelta(seconds=int(lease_seconds or DEFAULT_LEASE_SECONDS))
    if type_code:
        execution.audit_type_code = type_code
    if source_key:
        execution.source_record_key = source_key
    if version:
        execution.source_version = version

    attempt_no = (
        db.query(PushAttempt).filter(PushAttempt.execution_id == execution.id).count() or 0
    ) + 1
    db.add(
        PushAttempt(
            execution_id=execution.id,
            attempt_no=attempt_no,
            status="started",
        )
    )
    db.flush()
    return execution, True, "claimed"


def finish_execution(
    db,
    execution: PushExecution,
    status: str,
    push_log_id: int | None = None,
    error_message: str = "",
    *,
    target_name: str = "",
    elapsed_ms: int = 0,
    reviewed_flag: int | None = None,
) -> None:
    """回写 execution 与最新 attempt。调用方负责事务提交。"""
    execution.status = str(status or "failed")
    if push_log_id is not None:
        execution.push_log_id = push_log_id
    execution.lease_until = None
    if reviewed_flag is not None:
        execution.reviewed_flag = int(reviewed_flag)

    attempt = (
        db.query(PushAttempt)
        .filter(PushAttempt.execution_id == execution.id)
        .order_by(PushAttempt.attempt_no.desc())
        .first()
    )
    if attempt:
        attempt.status = str(status or "failed")
        attempt.finished_at = datetime.now()
        attempt.error_message = error_message or ""
        if target_name:
            attempt.target_name = target_name
        if elapsed_ms:
            attempt.elapsed_ms = int(elapsed_ms)
    db.flush()


def heartbeat_execution(
    db,
    execution: PushExecution,
    owner_token: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    """延长 lease；owner 不匹配时返回 False。"""
    if not execution or execution.owner_token != owner_token:
        return False
    execution.lease_until = datetime.now() + timedelta(seconds=int(lease_seconds or DEFAULT_LEASE_SECONDS))
    execution.updated_at = datetime.now()
    db.flush()
    return True
