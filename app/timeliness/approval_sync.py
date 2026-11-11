"""审批同步与扣罚台账（T9；主设计文档 §15 T9）。

只读同步 JHEMR 超时申请/审批日志 ``jhmr_monitor_limit_log`` → 本地 ``tl_approval``，
并驱动对应事件进入 ``APPLYING``（flag=1，已申请解锁）/ ``APPROVED``（flag=2，审批通过）
——状态语义与引擎 state.py 一致（APPLYING 可回退时钟态、APPROVED 粘滞，终态不可转入）。

- **幂等**：``tl_approval`` 唯一键五列（patient_id/visit_id/monitor_code/apply_date_time/
  type）已存在的行整条跳过（不覆盖既有行），重复执行 created=0；
- **去重**：同患者同监控码同一 ``apply_date_time`` 的重复源行按唯一键天然去重；
- 扣罚金额：按事件规则当前版本的 ``penalty_amount`` 回填（缺省 None=未配置，
  台账统计口径为每次解锁按规则扣罚，医疗部默认 200 元由规则配置承载）；
- 事件驱动对新建与既有行都执行（重跑时新事件也能被既有审批推进）；
- 本模块不连接生产库写路径：数据来源为 T1 只读访问层（或测试注入 rows）。

同步触发入口（扫描任务挂接/独立端点）不在 T9 任务书白名单内，由调用方决定；
本函数为纯库内操作，可被扫描器、脚本或后续端点复用。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy.orm import Session

from app.timeliness.engine.state import (
    APPLYING,
    APPROVED,
    IllegalStatusTransition,
    normalize_approval_flag,
    transition,
)
from app.timeliness.models import TLActionLog, TLApproval, TLEvent, TLEventHistory, TLRule, TLRuleVersion
from app.timeliness.rules_seed import SEED_CREATED_BY

# 审批日志 flag → 事件目标状态（state.py 语义：1=已申请解锁 APPLYING，2=审批通过 APPROVED）。
FLAG_TO_EVENT_STATUS = {"1": APPLYING, "2": APPROVED}

# 唯一键五列（缺任一的源行跳过并计数，不写半键行）。
_KEY_FIELDS = ("patient_id", "visit_id", "monitor_code", "apply_date_time", "type")

_HISTORY_REASON_MAX = 400


def _as_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    text = _as_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _monitor_code_rule_map(db: Session) -> dict[str, tuple[str, int | None]]:
    """jhemr_monitor_code → (rule_code, penalty_amount)（按各规则当前版本）。"""
    mapping: dict[str, tuple[str, int | None]] = {}
    rows = (
        db.query(TLRule, TLRuleVersion)
        .join(TLRuleVersion, TLRule.current_version_id == TLRuleVersion.id)
        .all()
    )
    for rule, version in rows:
        code = _as_text(version.jhemr_monitor_code)
        if code:
            mapping.setdefault(code, (rule.rule_code, version.penalty_amount))
    return mapping


def _drive_events(
    db: Session,
    *,
    patient_id: str,
    visit_id: str,
    monitor_code: str,
    target_status: str,
    reason: str,
    rule_map: dict[str, tuple[str, int | None]] | None = None,
) -> dict[str, int]:
    """把该患者该监控码对应规则的未终态事件推进到目标状态（写 tl_event_history）。"""
    mapping = rule_map if rule_map is not None else _monitor_code_rule_map(db)
    rule_code = mapping.get(monitor_code)
    result = {"updated": 0, "unchanged": 0, "skipped": 0}
    if rule_code is None:
        return result
    rule_code, _penalty = rule_code
    events = (
        db.query(TLEvent)
        .filter(
            TLEvent.patient_id == patient_id,
            TLEvent.visit_id == visit_id,
            TLEvent.rule_code == rule_code,
        )
        .all()
    )
    for event in events:
        if event.status == target_status:
            result["unchanged"] += 1
            continue
        try:
            transition(event.status, target_status, reason=reason[:80])
        except IllegalStatusTransition:
            result["skipped"] += 1
            continue
        from_status = event.status
        event.status = target_status
        event.updated_at = datetime.now()
        db.add(
            TLEventHistory(
                event_id=event.id,
                from_status=from_status,
                to_status=target_status,
                reason=reason[:_HISTORY_REASON_MAX],
                scan_run_id=None,
                created_at=datetime.now(),
            )
        )
        result["updated"] += 1
    return result


def sync_approvals(
    db: Session,
    config: dict | None = None,
    *,
    rows: Iterable[Mapping[str, Any]] | None = None,
    fetch_rows: Callable[[Any], list[dict]] | None = None,
    since: Any = None,
    now: Callable[[], datetime] = datetime.now,
) -> dict[str, int]:
    """同步 jhmr_monitor_limit_log → tl_approval 并驱动事件状态。

    - ``rows``（测试/调用方注入假数据）优先；否则用 ``fetch_rows(since)``
      （默认 T1 只读层 ``JhemrModuleReader().list_limit_logs``）；
    - 幂等：唯一键已存在跳过；键五列缺任一跳过；
    - flag=1/2 的行（新建与既有）驱动事件 APPLYING/APPROVED（APPROVED 粘滞，
      非法转换跳过计数）；
    - 单事务：成功 commit，异常回滚后抛出。
    """
    if rows is None:
        if fetch_rows is None:
            from app.timeliness.scanner import JhemrModuleReader

            reader = JhemrModuleReader()
            fetch_rows = reader.list_limit_logs
        rows = fetch_rows(since)

    rule_map = _monitor_code_rule_map(db)
    stats = {
        "created": 0,
        "skipped_existing": 0,
        "skipped_invalid": 0,
        "events_updated": 0,
        "events_unchanged": 0,
        "events_skipped": 0,
    }
    try:
        for row in rows or ():
            key_parts: list[Any] = []
            for name in _KEY_FIELDS:
                value = row.get(name)
                if name == "apply_date_time":
                    value = _to_datetime(value)
                    if value is not None:
                        value = value.replace(microsecond=0)
                if value is None or _as_text(value) == "":
                    break
                key_parts.append(value)
            if len(key_parts) != len(_KEY_FIELDS):
                stats["skipped_invalid"] += 1
                continue
            patient_id, visit_id, monitor_code, apply_dt, limit_type = key_parts

            exists = (
                db.query(TLApproval.id)
                .filter(
                    TLApproval.patient_id == patient_id,
                    TLApproval.visit_id == visit_id,
                    TLApproval.monitor_code == monitor_code,
                    TLApproval.apply_date_time == apply_dt,
                    TLApproval.type == limit_type,
                )
                .first()
            )
            if exists is None:
                rule_code, penalty = rule_map.get(monitor_code, (None, None))
                db.add(
                    TLApproval(
                        patient_id=patient_id,
                        visit_id=visit_id,
                        monitor_code=monitor_code,
                        apply_date_time=apply_dt,
                        type=limit_type,
                        flag=_as_text(row.get("flag")) or None,
                        apply_user_id=_as_text(row.get("apply_user_id")) or None,
                        approve_user_id=_as_text(row.get("approve_user_id")) or None,
                        approve_date_time=_to_datetime(row.get("approve_date_time")),
                        penalty_amount=penalty,
                        synced_at=now(),
                        apply_reason=_as_text(row.get("apply_reason")) or None,
                    )
                )
                stats["created"] += 1
            else:
                stats["skipped_existing"] += 1

            target_status = FLAG_TO_EVENT_STATUS.get(normalize_approval_flag(row.get("flag")) or "")
            if target_status is not None:
                driven = _drive_events(
                    db,
                    patient_id=patient_id,
                    visit_id=visit_id,
                    monitor_code=monitor_code,
                    target_status=target_status,
                    reason=(
                        f"approval sync: jhmr_monitor_limit_log flag="
                        f"{normalize_approval_flag(row.get('flag'))} apply_date_time={apply_dt.isoformat()}"
                    ),
                    rule_map=rule_map,
                )
                stats["events_updated"] += driven["updated"]
                stats["events_unchanged"] += driven["unchanged"]
                stats["events_skipped"] += driven["skipped"]
        db.commit()
    except Exception:
        db.rollback()
        raise
    return stats


def mark_approved_locally(
    db: Session,
    approval: TLApproval,
    *,
    approve_user_id: str,
    approve_date_time: datetime | None = None,
) -> dict[str, int]:
    """writer 模板 B 真实回写成功后，把本地台账与事件对齐（approve 端点复用）。"""
    approval.flag = "2"
    approval.approve_user_id = approve_user_id
    approval.approve_date_time = approve_date_time or datetime.now()
    approval.synced_at = datetime.now()
    driven = _drive_events(
        db,
        patient_id=approval.patient_id,
        visit_id=approval.visit_id,
        monitor_code=approval.monitor_code,
        target_status=APPROVED,
        reason=f"approve via ai_mrzk (tl_approval id={approval.id}, operator={approve_user_id})",
    )
    db.commit()
    return driven
