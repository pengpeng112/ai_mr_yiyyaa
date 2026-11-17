"""审批同步与扣罚台账（T9；主设计文档 §15 T9）。

只读同步 JHEMR 超时申请/审批日志 ``jhmr_monitor_limit_log`` → 本地 ``tl_approval``，
并驱动对应事件进入 ``APPLYING``（flag=1，已申请解锁）/ ``APPROVED``（flag=2，审批通过）
——状态语义与引擎 state.py 一致（APPLYING 可回退时钟态、APPROVED 粘滞，终态不可转入）。

- **幂等**：``tl_approval`` 唯一键五列（patient_id/visit_id/monitor_code/apply_date_time/
  type）已存在且源行无变化的行跳过（``skipped_existing``），重复执行 created=0；
- **既有行状态更新**（2026-11-13 返工）：JHEMR 原生【超时审批】通过后会**原地 UPDATE**
  同一五元组行（flag 1→2、approve_user_id、approve_date_time）；此前"已存在即跳过"
  会让本地 ``flag`` 永久卡在 '1'。现在已存在时比对源行与本地行的 ``flag`` /
  ``approve_user_id`` / ``approve_date_time`` / ``dept_code`` / ``apply_reason``，任一
  变化即更新这些列 + ``synced_at`` 并计入 ``updated``；本地已人工设置的
  ``penalty_exempt`` / ``exempt_reason`` 与已有 ``PC_WEB`` / ``WECOM_H5`` 渠道标记
  **不被覆盖**（``approve_channel`` 为空且源行 flag='2' 时补 ``JHEMR_NATIVE``）；
- **去重**：同患者同监控码同一 ``apply_date_time`` 的重复源行按唯一键天然去重；
- ``hospital_no``（模板 B 条件列，NOT NULL）与 ``dept_code``（科室白名单依据）随源行
  映射入库；``hospital_no`` 缺失的源行按无效跳过（approve 真实回写必需）；
- 扣罚金额：新建或更新时若 ``penalty_amount`` 为空，按对应监控码关联规则当前版本的
  ``penalty_amount`` 回填（仍为空则按医疗部口径默认 200 元）；
- 事件驱动对新建与既有行都执行（重跑时新事件也能被既有审批推进）；
- 本模块不连接生产库写路径：数据来源为 T1 只读访问层（或测试注入 rows）。

同步触发入口：``run_scan()``（扫描任务自动挂接，2026-11-13 返工）或
``POST /api/timeliness/approvals/sync``（独立端点）。
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

# 扣罚金额兜底默认（元/次）：医疗部《住院病历时效节点信息化锁定管理规定》200 元/次
# （主方案 §1.2；规则版本未配置 penalty_amount 时按此回填）。
DEFAULT_PENALTY_AMOUNT = 200

# 唯一键五列（缺任一的源行跳过并计数，不写半键行）。
_KEY_FIELDS = ("patient_id", "visit_id", "monitor_code", "apply_date_time", "type")

# hospital_no 为 tl_approval NOT NULL 列（T1 实证 14 列 + 用户 2026-11-12 答复裁定；
# 模板 B WHERE 条件之一），源行缺失同样按无效跳过。
_REQUIRED_NON_KEY_FIELD = "hospital_no"

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


def _norm_dt(value: Any) -> datetime | None:
    """比较用时间归一：转 datetime 并截去微秒（与唯一键 apply_date_time 归一口径一致）。"""
    parsed = value if isinstance(value, datetime) else _to_datetime(value)
    return parsed.replace(microsecond=0) if parsed is not None else None


def _approval_row_changed(approval: TLApproval, *, flag: str | None,
                          approve_user_id: str | None, approve_date_time: datetime | None,
                          dept_code: str | None, apply_reason: str | None) -> bool:
    """源行与本地行五列比对（flag/approve_user_id/approve_date_time/dept_code/apply_reason）。

    任一列不同即视为 JHEMR 侧发生了原地 UPDATE（典型：flag '1'→'2' 医务科审批通过）。
    """
    if (approval.flag or None) != (flag or None):
        return True
    if (approval.approve_user_id or None) != (approve_user_id or None):
        return True
    if _norm_dt(approval.approve_date_time) != _norm_dt(approve_date_time):
        return True
    if (approval.dept_code or None) != (dept_code or None):
        return True
    if (approval.apply_reason or None) != (apply_reason or None):
        return True
    return False


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
    - 幂等：唯一键已存在且源行无变化跳过（skipped_existing）；源行变化（典型
      JHEMR 原生审批通过 flag 1→2）则更新既有行并计 ``updated``（保留本地人工
      penalty_exempt/exempt_reason 与 PC_WEB/WECOM_H5 渠道标记）；键五列缺任一跳过；
    - flag=1/2 的行（新建与既有）驱动事件 APPLYING/APPROVED（APPROVED 粘滞，
      非法转换跳过计数）；
    - 新建或更新时 penalty_amount 为空 → 按规则当前版本回填，仍为空默认 200 元；
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
        "updated": 0,
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
            hospital_no = _as_text(row.get(_REQUIRED_NON_KEY_FIELD))
            if not hospital_no:
                stats["skipped_invalid"] += 1
                continue
            patient_id, visit_id, monitor_code, apply_dt, limit_type = key_parts

            exists = (
                db.query(TLApproval)
                .filter(
                    TLApproval.patient_id == patient_id,
                    TLApproval.visit_id == visit_id,
                    TLApproval.monitor_code == monitor_code,
                    TLApproval.apply_date_time == apply_dt,
                    TLApproval.type == limit_type,
                )
                .first()
            )
            _rule_code, rule_penalty = rule_map.get(monitor_code, (None, None))
            effective_penalty = rule_penalty if rule_penalty is not None else DEFAULT_PENALTY_AMOUNT
            incoming_flag = _as_text(row.get("flag")) or None
            incoming_approve_user = _as_text(row.get("approve_user_id")) or None
            incoming_approve_dt = _to_datetime(row.get("approve_date_time"))
            incoming_dept = _as_text(row.get("dept_code")) or None
            incoming_reason = _as_text(row.get("apply_reason")) or None
            if exists is None:
                db.add(
                    TLApproval(
                        patient_id=patient_id,
                        visit_id=visit_id,
                        monitor_code=monitor_code,
                        apply_date_time=apply_dt,
                        type=limit_type,
                        flag=incoming_flag,
                        apply_user_id=_as_text(row.get("apply_user_id")) or None,
                        approve_user_id=incoming_approve_user,
                        approve_date_time=incoming_approve_dt,
                        hospital_no=hospital_no,
                        dept_code=incoming_dept,
                        penalty_amount=effective_penalty,
                        synced_at=now(),
                        apply_reason=incoming_reason,
                    )
                )
                stats["created"] += 1
            elif _approval_row_changed(
                exists,
                flag=incoming_flag,
                approve_user_id=incoming_approve_user,
                approve_date_time=incoming_approve_dt,
                dept_code=incoming_dept,
                apply_reason=incoming_reason,
            ):
                # JHEMR 原生【超时审批】通过后原地 UPDATE 同一五元组行（flag 1→2 等）：
                # 跟随源行更新，但保留本地人工设置与既有渠道标记。
                exists.flag = incoming_flag
                exists.approve_user_id = incoming_approve_user
                exists.approve_date_time = incoming_approve_dt
                exists.dept_code = incoming_dept
                exists.apply_reason = incoming_reason
                exists.synced_at = now()
                if not (exists.approve_channel or "").strip() and incoming_flag == "2":
                    exists.approve_channel = "JHEMR_NATIVE"
                if exists.penalty_amount is None:
                    exists.penalty_amount = effective_penalty
                stats["updated"] += 1
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
