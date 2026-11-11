"""触发器（病历时效质控 T3）：trigger_type → (event_uid, t0, context)。

- event_uid 规则：{rule_code}:{patient_id}:{visit_id}:{源唯一号}；
  源唯一号：入院/出院/死亡类用 visit_id，手术用 operation_no，
  会诊用 applyid，危急值/抢救/输血/麻醉用来源流水号（source_event_id）。
- D4（主设计文档 §18.1/§18.5）：RESCUE_ORDER、CRITICAL_VALUE、TRANSFUSION、
  ANESTHESIA_END 四类触发源是独立外部系统，本期只提供统一抽象接口
  ExternalEventSource 与空实现 NotConfiguredSource（返回空列表、状态
  NOT_CONFIGURED）；不得猜测或连接任何外部系统。后期每接一个系统，
  新增一个 ExternalEventSource 实现并经 register_external_source 登记。
- 手术结束时间/死亡时间字段名已于 2026-11-10 实证回填（单一常量入口，见
  OPERATION_END_TIME_FIELDS / DEATH_TIME_FIELDS；证据 T1_columns.json）。
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from app.timeliness.engine.deadline import to_datetime

logger = logging.getLogger(__name__)

# ---- 触发类型（与 rules_seed.RULE_SEEDS 一致，由测试保证同步） ----
TRIGGER_TYPES = (
    "ADMISSION",
    "DISCHARGE",
    "DEATH",
    "OPERATION_START",
    "OPERATION_END",
    "CONSULT_APPLY",
    "MANUAL_OR_INDICATOR",
    # D4 外部独立系统触发源（本期仅接口桩）
    "RESCUE_ORDER",
    "CRITICAL_VALUE",
    "TRANSFUSION",
    "ANESTHESIA_END",
)
EXTERNAL_TRIGGER_TYPES = ("RESCUE_ORDER", "CRITICAL_VALUE", "TRANSFUSION", "ANESTHESIA_END")

# ---- D4：外部事件源统一接口 ----

# fetch_events 返回行的固定字段（主设计文档 §15 T3 / §18.5）。
EXTERNAL_EVENT_FIELDS = (
    "source_system",
    "source_event_id",
    "patient_id",
    "visit_id",
    "event_time",
    "dept_code",
    "doctor_id",
    "detail",
)
_EXTERNAL_REQUIRED_FIELDS = ("source_event_id", "patient_id", "visit_id", "event_time")

SOURCE_STATUS_READY = "READY"
SOURCE_STATUS_NOT_CONFIGURED = "NOT_CONFIGURED"


class TriggerDataError(ValueError):
    """触发行数据不完整/不合法（缺患者号、缺事件时间、外部事件缺固定字段等）。"""


class ExternalEventSource(abc.ABC):
    """外部独立系统事件源统一接口（D4）。

    实现方只做一件事：在 fetch_events(since, until) 时间窗内拉取该系统的
    事件列表，每行字段固定为 EXTERNAL_EVENT_FIELDS；引擎与扫描任务不关心
    来源系统是 LIS、HIS 还是输血系统。除字段映射外不得引入其他契约。
    """

    source_system: str = ""

    @abc.abstractmethod
    def fetch_events(self, since: Any, until: Any) -> list[dict]:
        """拉取 [since, until] 窗口内的事件（字典字段固定，见 EXTERNAL_EVENT_FIELDS）。"""

    @property
    def status(self) -> str:
        """READY=已配置可用；NOT_CONFIGURED=未配置（扫描任务应记录并跳过）。"""
        return SOURCE_STATUS_READY


class NotConfiguredSource(ExternalEventSource):
    """未配置的空实现：fetch_events 恒返回空列表，状态标记 NOT_CONFIGURED。"""

    source_system = ""

    def fetch_events(self, since: Any, until: Any) -> list[dict]:
        return []

    @property
    def status(self) -> str:
        return SOURCE_STATUS_NOT_CONFIGURED


# 四类外部触发的默认登记：全部 NotConfiguredSource（D4：本期不接任何外部系统）。
EXTERNAL_TRIGGER_SOURCES: dict[str, ExternalEventSource] = {
    trigger_type: NotConfiguredSource() for trigger_type in EXTERNAL_TRIGGER_TYPES
}


def register_external_source(trigger_type: str, source: ExternalEventSource) -> None:
    """登记一个外部事件源实现（后期接入新系统时由配置/接入任务调用）。"""
    if trigger_type not in EXTERNAL_TRIGGER_TYPES:
        raise ValueError(f"未知外部触发类型: {trigger_type!r}（允许 {', '.join(EXTERNAL_TRIGGER_TYPES)}）")
    if not isinstance(source, ExternalEventSource):
        raise TypeError("source 必须是 ExternalEventSource 实现")
    EXTERNAL_TRIGGER_SOURCES[trigger_type] = source


def validate_external_event(row: Mapping[str, Any]) -> dict:
    """校验外部事件行：必填字段齐全且 event_time 可解析，返回规整后的 dict。"""
    missing = [name for name in _EXTERNAL_REQUIRED_FIELDS if row.get(name) in (None, "")]
    if missing:
        raise TriggerDataError(f"外部事件缺固定字段: {missing}（行={dict(row)!r}）")
    event_time = to_datetime(row.get("event_time"))
    if event_time is None:
        raise TriggerDataError(f"外部事件 event_time 无法解析: {row.get('event_time')!r}")
    normalized = {name: row.get(name) for name in EXTERNAL_EVENT_FIELDS}
    normalized["event_time"] = event_time
    return normalized


# ---- 触发事件 ----


@dataclass(frozen=True)
class TriggerEvent:
    """一次触发：event_uid + 起算时间 t0 + 上下文。"""

    event_uid: str
    t0: datetime
    patient_id: str
    visit_id: str
    source_unique_id: str
    dept_code: str | None = None
    responsible_doctor_id: str | None = None
    context: dict = field(default_factory=dict)


def make_event_uid(rule_code: str, patient_id: Any, visit_id: Any, source_unique_id: Any) -> str:
    """拼接 event_uid：{rule_code}:{patient_id}:{visit_id}:{源唯一号}。"""
    parts = [rule_code, patient_id, visit_id, source_unique_id]
    if any(p is None or str(p).strip() == "" for p in parts):
        raise TriggerDataError(f"event_uid 组成部分不能为空: {parts!r}")
    return ":".join(str(p).strip() for p in parts)


def _row_patient_visit(row: Mapping[str, Any]) -> tuple[str, str] | None:
    pid = str(row.get("patient_id") or "").strip()
    vid = str(row.get("visit_id") or "").strip()
    if not pid or not vid:
        return None
    return pid, vid


def _first_time(row: Mapping[str, Any], candidates: Sequence[str]) -> datetime | None:
    for name in candidates:
        if name in row and row.get(name) not in (None, ""):
            return to_datetime(row.get(name))
    return None


def _simple_trigger(
    rule_code: str,
    row: Mapping[str, Any],
    *,
    time_fields: Sequence[str],
    source_field: str | None = None,
) -> TriggerEvent | None:
    """通用触发构造：t0 取候选字段第一个非空；源唯一号默认 visit_id。"""
    identity = _row_patient_visit(row)
    if identity is None:
        raise TriggerDataError(f"触发行缺 patient_id/visit_id: {dict(row)!r}")
    pid, vid = identity
    t0 = _first_time(row, time_fields)
    if t0 is None:
        return None  # 时间字段为空：该行无法起算，由调用方记录跳过
    source_unique_id = vid if source_field is None else str(row.get(source_field) or "").strip() or vid
    return TriggerEvent(
        event_uid=make_event_uid(rule_code, pid, vid, source_unique_id),
        t0=t0,
        patient_id=pid,
        visit_id=vid,
        source_unique_id=source_unique_id,
        dept_code=_optional_str(row.get("dept_code")),
        responsible_doctor_id=_optional_str(row.get("doctor_id")) or _optional_str(row.get("responsible_doctor_id")),
        context=dict(row),
    )


def _optional_str(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


# 各触发类型 t0 候选字段（首个非空生效）。
# 2026-11-10 §18.2 授权后经 sjzc 只读实证（review/timeliness/T1_columns.json）：
# operation 表时间类列只有 operating_date / operating_end_date（无
# operation_end_date_time 等旧候选名）；pat_visit 存在 death_date_time。
ADMISSION_TIME_FIELDS = ("admission_date_time",)
DISCHARGE_TIME_FIELDS = ("discharge_date_time",)
DEATH_TIME_FIELDS = ("death_date_time",)  # pat_visit 实证存在
OPERATION_START_TIME_FIELDS = ("operating_date",)
OPERATION_END_TIME_FIELDS = ("operating_end_date",)  # operation 表唯一结束时间列（实证）
CONSULT_TIME_FIELDS = ("apply_date_time",)
MANUAL_TIME_FIELDS = ("event_time", "indicator_time", "trigger_time")


def admission_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """入院触发：t0=入院时间，源唯一号=visit_id。"""
    return _simple_trigger(rule_code, row, time_fields=ADMISSION_TIME_FIELDS)


def discharge_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """出院触发：t0=出院时间，源唯一号=visit_id。"""
    return _simple_trigger(rule_code, row, time_fields=DISCHARGE_TIME_FIELDS)


def death_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """死亡触发：t0=死亡时间，源唯一号=visit_id。"""
    return _simple_trigger(rule_code, row, time_fields=DEATH_TIME_FIELDS)


def operation_start_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """手术开始触发：t0=手术开始时间，源唯一号=operation_no。"""
    return _simple_trigger(rule_code, row, time_fields=OPERATION_START_TIME_FIELDS, source_field="operation_no")


def operation_end_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """手术结束触发：t0=手术结束时间，源唯一号=operation_no。

    结束时间字段缺失的手术行返回 None（跳过）：用开始时间顶替会把截止
    整体提前、造成误报，宁可漏报待扫描层单独统计（见 T1 待核对项）。
    """
    event = _simple_trigger(rule_code, row, time_fields=OPERATION_END_TIME_FIELDS, source_field="operation_no")
    if event is None:
        logger.warning("手术行缺结束时间字段 %s，跳过（rule=%s patient=%s visit=%s operation_no=%s）",
                       list(OPERATION_END_TIME_FIELDS), rule_code,
                       row.get("patient_id"), row.get("visit_id"), row.get("operation_no"))
    return event


def consult_apply_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """会诊申请触发：t0=申请时间，源唯一号=applyid。"""
    return _simple_trigger(rule_code, row, time_fields=CONSULT_TIME_FIELDS, source_field="applyid")


def manual_indicator_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
    """人工/指标触发（如疑难病例讨论）：源唯一号取 source_unique_id/indicator_id，缺省 visit_id。"""
    event = _simple_trigger(rule_code, row, time_fields=MANUAL_TIME_FIELDS, source_field="source_unique_id")
    if event is not None and event.source_unique_id == str(row.get("visit_id")).strip():
        indicator = _optional_str(row.get("indicator_id"))
        if indicator:
            event = TriggerEvent(
                event_uid=make_event_uid(rule_code, event.patient_id, event.visit_id, indicator),
                t0=event.t0,
                patient_id=event.patient_id,
                visit_id=event.visit_id,
                source_unique_id=indicator,
                dept_code=event.dept_code,
                responsible_doctor_id=event.responsible_doctor_id,
                context=event.context,
            )
    return event


def _make_external_handler(trigger_type: str) -> Callable[[str, Mapping[str, Any]], TriggerEvent | None]:
    def external_trigger(rule_code: str, row: Mapping[str, Any]) -> TriggerEvent | None:
        normalized = validate_external_event(row)
        t0 = normalized["event_time"]
        pid = str(normalized["patient_id"]).strip()
        vid = str(normalized["visit_id"]).strip()
        source_unique_id = str(normalized["source_event_id"]).strip()
        return TriggerEvent(
            event_uid=make_event_uid(rule_code, pid, vid, source_unique_id),
            t0=t0,
            patient_id=pid,
            visit_id=vid,
            source_unique_id=source_unique_id,
            dept_code=_optional_str(normalized.get("dept_code")),
            responsible_doctor_id=_optional_str(normalized.get("doctor_id")),
            context=normalized,
        )

    return external_trigger


# 触发类型 → 处理函数注册表。
TRIGGER_HANDLERS: dict[str, Callable[[str, Mapping[str, Any]], TriggerEvent | None]] = {
    "ADMISSION": admission_trigger,
    "DISCHARGE": discharge_trigger,
    "DEATH": death_trigger,
    "OPERATION_START": operation_start_trigger,
    "OPERATION_END": operation_end_trigger,
    "CONSULT_APPLY": consult_apply_trigger,
    "MANUAL_OR_INDICATOR": manual_indicator_trigger,
    "RESCUE_ORDER": _make_external_handler("RESCUE_ORDER"),
    "CRITICAL_VALUE": _make_external_handler("CRITICAL_VALUE"),
    "TRANSFUSION": _make_external_handler("TRANSFUSION"),
    "ANESTHESIA_END": _make_external_handler("ANESTHESIA_END"),
}


def apply_trigger_filter(row: Mapping[str, Any], trigger_filter: Mapping[str, Any] | None) -> bool:
    """按 trigger_filter_json 过滤触发行：标量相等、列表任一命中（均按字符串比较）。"""
    if not trigger_filter:
        return True
    for key, expected in trigger_filter.items():
        actual = row.get(key)
        if isinstance(expected, (list, tuple, set)):
            allowed = {str(item).strip() for item in expected}
            if str(actual).strip() not in allowed:
                return False
        elif str(actual).strip() != str(expected).strip():
            return False
    return True


def build_trigger_events(
    rule_code: str,
    trigger_type: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    trigger_filter: Mapping[str, Any] | None = None,
) -> list[TriggerEvent]:
    """把触发行列表转换为去重后的 TriggerEvent 列表。

    - 先过 trigger_filter，再构造事件；
    - 缺起算时间的行跳过并记 warning（如手术行缺结束时间）；
    - 数据不完整（缺患者号/visit、外部事件缺固定字段）跳过并记 warning，
      不让单行坏数据中断整批；
    - event_uid 重复时保留首行。
    """
    handler = TRIGGER_HANDLERS.get(trigger_type)
    if handler is None:
        raise ValueError(f"未知触发类型: {trigger_type!r}（允许 {', '.join(TRIGGER_TYPES)}）")
    events: list[TriggerEvent] = []
    seen_uids: set[str] = set()
    skipped = 0
    for row in rows or ():
        if not apply_trigger_filter(row, trigger_filter):
            continue
        try:
            event = handler(rule_code, row)
        except TriggerDataError as exc:
            skipped += 1
            logger.warning("触发行数据不完整，跳过（rule=%s trigger=%s）: %s", rule_code, trigger_type, exc)
            continue
        if event is None:
            skipped += 1
            continue
        if event.event_uid in seen_uids:
            continue
        seen_uids.add(event.event_uid)
        events.append(event)
    if skipped:
        logger.warning("触发类型 %s（规则 %s）共跳过 %d 行无法起算/数据不完整的触发行", trigger_type, rule_code, skipped)
    return events
