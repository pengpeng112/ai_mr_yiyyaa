"""规则引擎编排纯函数（病历时效质控 T3）。

evaluate(rule_version, now, data) -> list[EventResult]：
输入患者/文书/手术/会诊/审批日志等字典列表 + 规则版本，输出事件及状态。
不连库、不发消息、不读配置文件（全部输入经参数传入，可重复执行）。

data 约定（全部键可缺省）：
- inpatients: ADMISSION 触发行（含 patient_id/visit_id/dept_code/admission_date_time）
- discharges: DISCHARGE 触发行（discharge_date_time）
- deaths: DEATH 触发行（death_date_time，字段名待真实列核对）
- operations: OPERATION_START / OPERATION_END 触发行（operating_date / 结束时间字段）
- consult_applies: CONSULT_APPLY 触发行（applyid/apply_date_time）
- manual_indicators: MANUAL_OR_INDICATOR 触发行（event_time + source_unique_id/indicator_id）
- external_events: D4 四类外部源事件行（字段固定见 triggers.EXTERNAL_EVENT_FIELDS，
  行需带 trigger_type=触发类型，或 source_system=触发类型小写以区分来源）
- files: jhmr_file_index 文书行（13 列口径见 T1）
- approvals: 审批日志行（patient_id/visit_id/monitor_code/apply_date_time/flag）
- existing_events: 已有事件行（event_uid/status），终态事件状态保持不变
- cancelled_event_uids / exempt_event_uids: 不再适用/豁免的 event_uid 列表
- non_workdays（或 holidays）: 非工作日集合（节假日+周末，D9 待定，调用方传入）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.timeliness.engine.deadline import (
    compute_deadline,
    overdue_minutes,
    to_datetime,
    warn_threshold,
)
from app.timeliness.engine.matchers import (
    COMPLETION_BASIS_CREATE,
    COMPLETION_BASIS_FIRST_SIGN,
    COMPLETION_BASES,
    find_completion,
)
from app.timeliness.engine.state import (
    APPROVED,
    COMPLETED_LATE,
    COMPLETED_ON_TIME,
    OVERDUE,
    derive_status,
    is_terminal,
    normalize_approval_flag,
    transition,
)
from app.timeliness.engine.triggers import (
    EXTERNAL_TRIGGER_TYPES,
    TriggerEvent,
    build_trigger_events,
)

# 触发类型 → data 键候选（按顺序取第一个存在的键）。
TRIGGER_DATA_KEYS: dict[str, tuple[str, ...]] = {
    "ADMISSION": ("inpatients", "admissions"),
    "DISCHARGE": ("discharges",),
    "DEATH": ("deaths",),
    "OPERATION_START": ("operations",),
    "OPERATION_END": ("operations",),
    "CONSULT_APPLY": ("consult_applies",),
    "MANUAL_OR_INDICATOR": ("manual_indicators", "manual_events"),
    "RESCUE_ORDER": ("external_events",),
    "CRITICAL_VALUE": ("external_events",),
    "TRANSFUSION": ("external_events",),
    "ANESTHESIA_END": ("external_events",),
}

# “文书时间 >= t0”默认值：手术结束/危急值/会诊/抢救/输血/麻醉类要求完成
# 发生在触发之后；入院/出院/死亡/手术开始（术前文书本就写在术前）不要求。
# target_json 里显式给 time_ge_t0 时以配置为准。
REQUIRE_TIME_GE_T0_DEFAULTS: dict[str, bool] = {
    "ADMISSION": False,
    "DISCHARGE": False,
    "DEATH": False,
    "OPERATION_START": False,
    "OPERATION_END": True,
    "CONSULT_APPLY": True,
    "RESCUE_ORDER": True,
    "CRITICAL_VALUE": True,
    "TRANSFUSION": True,
    "ANESTHESIA_END": True,
    "MANUAL_OR_INDICATOR": False,
}


@dataclass(frozen=True)
class RuleVersionSpec:
    """evaluate 使用的规则版本口径（从 ORM 对象或 dict 规整而来）。"""

    rule_code: str
    trigger_type: str
    target: dict
    completion_basis: str = COMPLETION_BASIS_FIRST_SIGN
    limit_minutes: int | None = None
    workday_only: bool = False
    warn_before_minutes: int | None = None
    jhemr_monitor_code: str | None = None
    dept_scope: tuple[str, ...] = ()
    trigger_filter: dict | None = None
    rule_version_id: int | None = None


@dataclass(frozen=True)
class EventResult:
    """一次评估产出的事件（字段与 tl_event 台账列对齐，供 T4 直接落库）。"""

    event_uid: str
    rule_code: str
    patient_id: str
    visit_id: str
    t0: datetime
    deadline: datetime | None
    status: str
    status_before: str | None          # None=新事件
    status_changed: bool
    dept_code: str | None = None
    responsible_doctor_id: str | None = None
    matched_file_unique_id: str | None = None
    completed_at: datetime | None = None
    overdue_minutes: int | None = None
    warn_deadline: datetime | None = None
    source_unique_id: str | None = None
    rule_version_id: int | None = None
    context: dict = field(default_factory=dict)


class RuleVersionSpecError(ValueError):
    """规则版本口径非法（缺 rule_code/trigger_type、completion_basis 非法等）。"""


def _load_json_field(value: Any, default: Any) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def normalize_rule_version(rule_version: Any, *, rule_code: str | None = None) -> RuleVersionSpec:
    """把 TLRuleVersion ORM 对象或 dict 规整为 RuleVersionSpec。"""
    if isinstance(rule_version, Mapping):

        def pick(name: str, default: Any = None) -> Any:
            return rule_version.get(name, default)
    else:
        def pick(name: str, default: Any = None) -> Any:
            return getattr(rule_version, name, default)

    code = rule_code or pick("rule_code")
    if not str(code or "").strip():
        raise RuleVersionSpecError("rule_code 不能为空（dict 传入或用 rule_code= 参数补充）")
    trigger_type = str(pick("trigger_type") or "").strip()
    if not trigger_type:
        raise RuleVersionSpecError("trigger_type 不能为空")
    basis = str(pick("completion_basis") or COMPLETION_BASIS_FIRST_SIGN).strip()
    if basis not in COMPLETION_BASES:
        raise RuleVersionSpecError(f"completion_basis 非法: {basis!r}（允许 {', '.join(COMPLETION_BASES)}）")
    dept_scope_raw = _load_json_field(pick("dept_scope_json") or pick("dept_scope"), [])
    trigger_filter_raw = _load_json_field(pick("trigger_filter_json") or pick("trigger_filter"), {})
    target_raw = _load_json_field(pick("target_json") or pick("target"), {})
    monitor_code = pick("jhemr_monitor_code")
    version_id = pick("id") or pick("rule_version_id")
    return RuleVersionSpec(
        rule_code=str(code).strip(),
        trigger_type=trigger_type,
        target=dict(target_raw) if isinstance(target_raw, Mapping) else {},
        completion_basis=basis,
        limit_minutes=pick("limit_minutes"),
        workday_only=bool(pick("workday_only", False)),
        warn_before_minutes=pick("warn_before_minutes"),
        jhemr_monitor_code=str(monitor_code).strip() if monitor_code else None,
        dept_scope=tuple(str(item).strip() for item in dept_scope_raw or () if str(item).strip()),
        trigger_filter=dict(trigger_filter_raw) if isinstance(trigger_filter_raw, Mapping) else {},
        rule_version_id=int(version_id) if version_id else None,
    )


def _collect_rows(data: Mapping[str, Any], trigger_type: str) -> list[Mapping[str, Any]]:
    """按触发类型从 data 取触发行；外部事件行须能对应到该触发类型。"""
    keys = TRIGGER_DATA_KEYS.get(trigger_type)
    if not keys:
        raise RuleVersionSpecError(f"未知触发类型: {trigger_type!r}")
    rows: list[Mapping[str, Any]] = []
    for key in keys:
        value = data.get(key)
        if value:
            rows.extend(value)
            break
    if trigger_type in EXTERNAL_TRIGGER_TYPES:
        expected_source = trigger_type.lower()
        filtered = []
        for row in rows:
            row_type = str(row.get("trigger_type") or "").strip()
            source_system = str(row.get("source_system") or "").strip().lower()
            if row_type == trigger_type or (not row_type and source_system == expected_source):
                filtered.append(row)
        return filtered
    return rows


def _latest_approval_flag(
    approvals: Sequence[Mapping[str, Any]],
    *,
    patient_id: str,
    visit_id: str,
    monitor_code: str | None,
) -> str | None:
    """取该患者+住院次+监控码下最新一条审批日志的 flag（'1'/'2'/None）。"""
    if not monitor_code:
        return None
    matched: list[tuple[datetime, str]] = []
    for row in approvals or ():
        if str(row.get("patient_id") or "").strip() != patient_id:
            continue
        if str(row.get("visit_id") or "").strip() != visit_id:
            continue
        if str(row.get("monitor_code") or "").strip() != monitor_code:
            continue
        flag = normalize_approval_flag(row.get("flag"))
        if flag is None:
            continue
        applied_at = to_datetime(row.get("apply_date_time"))
        matched.append((applied_at or datetime.min, flag))
    if not matched:
        return None
    matched.sort(key=lambda item: item[0])
    return matched[-1][1]


def _files_for_visit(files: Sequence[Mapping[str, Any]], patient_id: str, visit_id: str) -> list[Mapping[str, Any]]:
    result = []
    for file in files or ():
        if str(file.get("patient_id") or "").strip() != patient_id:
            continue
        if str(file.get("visit_id") or "").strip() != visit_id:
            continue
        result.append(file)
    return result


def evaluate(rule_version: Any, now: Any, data: Mapping[str, Any], *, rule_code: str | None = None) -> list[EventResult]:
    """评估一条规则版本在给定数据快照下的事件与状态（纯函数）。

    now 为扫描时刻；data 见模块 docstring。返回结果按 event_uid 去重后的
    触发事件逐条计算：已完成→COMPLETED_*；不再适用→CANCELLED；豁免→EXEMPT；
    有审批→APPLYING/APPROVED；否则按 deadline/warn 推导 PENDING/WARNING/OVERDUE。
    已处终态的既有事件状态保持不变（只刷新上下文类字段）。
    """
    spec = normalize_rule_version(rule_version, rule_code=rule_code)
    current = to_datetime(now)
    if current is None:
        raise ValueError("now 不能为空")
    data = data or {}

    rows = _collect_rows(data, spec.trigger_type)
    trigger_events: list[TriggerEvent] = build_trigger_events(
        spec.rule_code, spec.trigger_type, rows, trigger_filter=spec.trigger_filter
    )

    files = list(data.get("files") or ())
    approvals = list(data.get("approvals") or ())
    non_workdays = data.get("non_workdays")
    if non_workdays is None:
        non_workdays = data.get("holidays")
    cancelled_uids = {str(u).strip() for u in data.get("cancelled_event_uids") or ()}
    exempt_uids = {str(u).strip() for u in data.get("exempt_event_uids") or ()}
    existing_status = {
        str(row.get("event_uid") or "").strip(): str(row.get("status") or "").strip()
        for row in data.get("existing_events") or ()
        if row.get("event_uid")
    }

    require_ge_t0_default = REQUIRE_TIME_GE_T0_DEFAULTS.get(spec.trigger_type, False)
    require_ge_t0 = bool(spec.target.get("time_ge_t0", require_ge_t0_default))

    results: list[EventResult] = []
    for event in trigger_events:
        if spec.dept_scope and (event.dept_code or "") not in spec.dept_scope:
            # 配置了科室范围（试点）：无科室信息或不在范围内的触发行不建事件，
            # 由扫描层负责为触发行补齐科室后再评估。
            continue

        deadline = compute_deadline(
            event.t0, spec.limit_minutes, workday_only=spec.workday_only, non_workdays=non_workdays
        )
        warn_deadline = warn_threshold(deadline, spec.warn_before_minutes)

        completion = find_completion(
            _files_for_visit(files, event.patient_id, event.visit_id),
            target=spec.target,
            completion_basis=spec.completion_basis,
            t0=event.t0,
            require_time_ge_t0=require_ge_t0,
        )
        completed_at = completion.completed_at if completion else None

        status_before = existing_status.get(event.event_uid)
        if status_before and is_terminal(status_before):
            target_status = status_before  # 终态不再改变
        else:
            target_status = derive_status(
                now=current,
                deadline=deadline,
                warn_before_minutes=spec.warn_before_minutes,
                completed_at=completed_at,
                cancelled=event.event_uid in cancelled_uids,
                exempt=event.event_uid in exempt_uids,
                approval_flag=_latest_approval_flag(
                    approvals,
                    patient_id=event.patient_id,
                    visit_id=event.visit_id,
                    monitor_code=spec.jhemr_monitor_code,
                ),
                previous_status=status_before,
            )
            if status_before is not None:
                # 校验转换合法性：非法组合属引擎缺陷，直接抛出（表已覆盖推导可达的全部组合）。
                transition(status_before, target_status, reason=f"event={event.event_uid}")

        computed_overdue: int | None = None
        if target_status == OVERDUE and deadline is not None:
            computed_overdue = overdue_minutes(current, deadline)
        elif target_status == COMPLETED_LATE and completed_at is not None and deadline is not None:
            computed_overdue = overdue_minutes(completed_at, deadline)

        results.append(
            EventResult(
                event_uid=event.event_uid,
                rule_code=spec.rule_code,
                patient_id=event.patient_id,
                visit_id=event.visit_id,
                t0=event.t0,
                deadline=deadline,
                status=target_status,
                status_before=status_before,
                status_changed=status_before != target_status,
                dept_code=event.dept_code,
                responsible_doctor_id=event.responsible_doctor_id,
                matched_file_unique_id=completion.file_unique_id if completion else None,
                completed_at=completed_at,
                overdue_minutes=computed_overdue,
                warn_deadline=warn_deadline,
                source_unique_id=event.source_unique_id,
                rule_version_id=spec.rule_version_id,
                context=event.context,
            )
        )
    return results
