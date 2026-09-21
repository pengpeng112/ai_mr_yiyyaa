# -*- coding: utf-8 -*-
"""046 T9b 运维诊断聚合：引擎版本/最后成功采集/源故障/任务与 Outbox 积压/compare 差异。

只读、无 PHI、无密钥：全部为计数/时间戳/状态短键（日志与响应都不携带病历正文、
患者标识或拼接 SQL 参数）。挂在 /healthz（additive `diagnostics` 块）与
/api/admin/diagnostics（admin 鉴权，含更细的源健康明细）。
"""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, select

from .closed_loop_models import RUN_QUEUED, RunRow

# 执行中状态（积压口径：queued/running）
RUN_OPEN_STATUSES = (RUN_QUEUED, "running")
from .rule_models import (
    OUTBOX_DEAD,
    OUTBOX_PENDING,
    OUTBOX_RETRY,
    DeliveryLogRow,
    OutboxRow,
)


def _iso(value) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def build_diagnostics(session_factory, heartbeat=None,
                      engine=None, watermark: str = None) -> dict:
    """聚合运维诊断面（全部只读、脱敏）。"""
    with session_factory() as session:
        # 引擎版本 = 最近一次 run 的规则集版本（无 run=未知，不编造）
        latest_run = session.execute(
            select(RunRow).order_by(RunRow.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        engine_version = latest_run.ruleset_revision if latest_run else ""

        # 最后成功采集：最近 completed/partial run 的 checked_at（心跳另列）
        last_ok = session.execute(
            select(RunRow).where(RunRow.status.in_(("completed", "partial")))
            .order_by(RunRow.checked_at.desc()).limit(1)
        ).scalar_one_or_none()

        # 源故障：最近 run 的 source_health 里 status=error 的短键（不含 detail 正文）
        source_faults: list[str] = []
        source_health: dict = {}
        if latest_run is not None and latest_run.source_health_json:
            health = json.loads(latest_run.source_health_json or "{}")
            source_health = {
                key: {"status": value.get("status", "unknown")}
                for key, value in health.items()}
            source_faults = sorted(
                key for key, value in health.items()
                if str(value.get("status")) == "error")

        # 任务积压：queued/running 的 run 数 + 最老任务时间
        backlog_rows = session.execute(
            select(RunRow.created_at, func.count())
            .where(RunRow.status.in_(RUN_OPEN_STATUSES))
            .group_by(RunRow.created_at)
            .order_by(RunRow.created_at)).all()
        task_backlog = sum(count for _ts, count in backlog_rows)
        oldest_task = backlog_rows[0][0] if backlog_rows else None

        # Outbox：积压（pending+retry）/最老事件/死信
        outbox_status = dict(session.execute(
            select(OutboxRow.status, func.count())
            .group_by(OutboxRow.status)).all())
        outbox_backlog = (outbox_status.get(OUTBOX_PENDING, 0)
                          + outbox_status.get(OUTBOX_RETRY, 0))
        dead = outbox_status.get(OUTBOX_DEAD, 0)
        oldest_outbox = session.execute(
            select(func.min(OutboxRow.created_at)).where(
                OutboxRow.status.in_((OUTBOX_PENDING, OUTBOX_RETRY)))
        ).scalar_one_or_none()

        # 连续失败：按事件×目标分组，取最近一次尝试 outcome 非 sent 的连续次数最大值
        recent_logs = session.execute(
            select(DeliveryLogRow.outbox_id, DeliveryLogRow.outcome)
            .order_by(DeliveryLogRow.created_at.desc()).limit(500)).all()
        consecutive: dict[str, int] = {}
        for outbox_id, outcome in recent_logs:
            if outbox_id not in consecutive:
                consecutive[outbox_id] = 0 if outcome == "sent" else 1
        max_consecutive_failure = max(consecutive.values(), default=0)

    heartbeat_record = None
    if heartbeat is not None:
        try:
            heartbeat_record = heartbeat.read()
        except Exception:  # noqa: BLE001 —— 心跳读取失败不阻断诊断
            heartbeat_record = None

    # compare 影子差异计数（仅 compare 模式引擎有该属性）
    diff_count = getattr(engine, "diff_count", None)

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "engine_version": engine_version or "unknown",
        "last_successful_check_at": _iso(last_ok.checked_at)
        if last_ok else None,
        "heartbeat": {
            "alive": bool(heartbeat_record),
            "watermark": watermark or (heartbeat_record or {}).get("watermark"),
            "processed_total": (heartbeat_record or {}).get("processed_total"),
        },
        "source_faults": source_faults,
        "source_health": source_health,
        "task_backlog": {"count": task_backlog, "oldest_at": _iso(oldest_task)},
        "outbox": {
            "backlog": outbox_backlog,
            "oldest_pending_at": _iso(oldest_outbox),
            "dead": dead,
            "status_counts": outbox_status,
            "max_consecutive_failures": max_consecutive_failure,
        },
        "compare_diff_count": diff_count,
    }
