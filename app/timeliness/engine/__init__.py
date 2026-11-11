"""病历时效质控规则引擎（T3）：纯函数包。

组成（主设计文档 §15 T3）：
- triggers：trigger_type → (event_uid, t0, context)；D4 四类外部源统一接口
  ExternalEventSource / NotConfiguredSource；
- matchers：按 target_json 匹配文书并判定完成（E12/R1/E13 完成时间铁律）；
- deadline：limit_minutes 加法与 workday_only 非工作日跳过；
- state：状态转换表（非法转换抛 IllegalStatusTransition）与状态推导；
- evaluate：evaluate(rule_version, now, data) -> list[EventResult] 纯函数。

本包不连库、不发消息、不 import psycopg2/requests/sqlalchemy（源码扫描
测试在 tests/timeliness/test_engine.py 固化该约束）。
"""
from app.timeliness.engine.deadline import compute_deadline, overdue_minutes, warn_threshold
from app.timeliness.engine.evaluate import EventResult, RuleVersionSpec, RuleVersionSpecError, evaluate
from app.timeliness.engine.matchers import CompletionResult, TargetConfigError, find_completion
from app.timeliness.engine.state import EVENT_STATUSES, IllegalStatusTransition, STATUS_TRANSITIONS, transition
from app.timeliness.engine.triggers import (
    EXTERNAL_EVENT_FIELDS,
    EXTERNAL_TRIGGER_SOURCES,
    EXTERNAL_TRIGGER_TYPES,
    ExternalEventSource,
    NotConfiguredSource,
    TriggerDataError,
    TriggerEvent,
    register_external_source,
)

__all__ = [
    "compute_deadline",
    "overdue_minutes",
    "warn_threshold",
    "evaluate",
    "EventResult",
    "RuleVersionSpec",
    "RuleVersionSpecError",
    "CompletionResult",
    "TargetConfigError",
    "find_completion",
    "EVENT_STATUSES",
    "IllegalStatusTransition",
    "STATUS_TRANSITIONS",
    "transition",
    "EXTERNAL_EVENT_FIELDS",
    "EXTERNAL_TRIGGER_SOURCES",
    "EXTERNAL_TRIGGER_TYPES",
    "ExternalEventSource",
    "NotConfiguredSource",
    "TriggerDataError",
    "TriggerEvent",
    "register_external_source",
]
