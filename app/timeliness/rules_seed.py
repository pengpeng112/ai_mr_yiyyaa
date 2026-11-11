"""
病历时效质控规则种子与版本写入原语（T2）。

- RULE_SEEDS：主设计文档 §15 T2 表格的 18 条规则，全部 enabled=False、action_mode=SHADOW。
  业务意图 action_mode 只写在 note（计划书原文：前 12 项意图 LOCK_EMR、会诊/疑难意图
  WARN_ONLY；DEATH_REC、BLOOD_COURSE、BLOOD_REC 计划书未指定，note 标“待确认”）。
- seed_rules()：幂等——已存在的 rule_code 整条跳过（不改规则行、不碰任何版本），
  重复执行不会覆盖用户后续保存的新版本。
- append_rule_version()：规则“每次保存生成新版本”的写入原语（§14.3 对 T2 的要求）：
  只追加新行、旧版本行不改；执行取值域校验与 D8 红线
  （ADM_REC / CHIEF_FIRST_ROUND 不得设为 LOCK_EMR，§18.1/§18.4）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.timeliness.models import ACTION_MODES, COMPLETION_BASES, TLRule, TLRuleVersion

SEED_CREATED_BY = "system_seed"
SEED_CATEGORY = "TIMELINESS"

# D8（§18.1/§18.4）：幽灵行原因查清前，这两条规则不得设为 LOCK_EMR。
D8_NO_LOCK_RULE_CODES = frozenset({"ADM_REC", "CHIEF_FIRST_ROUND"})
D8_REJECT_MESSAGE = "D8：幽灵行原因查清前禁止锁定"

# 版本内容字段：新版本从当前版本整体复制，再按本次修改覆盖。
VERSION_FIELDS = (
    "trigger_type",
    "trigger_filter_json",
    "target_json",
    "completion_basis",
    "limit_minutes",
    "workday_only",
    "warn_before_minutes",
    "action_mode",
    "channels_json",
    "dept_scope_json",
    "jhemr_monitor_code",
    "penalty_amount",
    "note",
)
_JSON_FIELDS = frozenset({"trigger_filter_json", "target_json", "channels_json", "dept_scope_json"})
_NON_NEGATIVE_INT_FIELDS = ("limit_minutes", "warn_before_minutes", "penalty_amount")

_D8_REMARK = "D8：禁止 LOCK_EMR（幽灵行原因查清前只能 SHADOW/WARN_ONLY，主设计文档 §18.1/§18.4）"
_D4_REMARK = "{source}为独立系统（D4），本期只做 ExternalEventSource 接口桩，种子保留并保持停用（§18.1）"
_CONSULT_REMARK = "急/普通会诊的区分条件待会诊表真实列核对（T1 待核对项）"


class RuleVersionError(ValueError):
    """规则版本写入被拒绝：规则不存在、字段非法或触犯 D8 红线。"""


@dataclass(frozen=True)
class RuleSeed:
    """§15 T2 表格一行。target_text 为“目标文书”列原文；intent_action_mode=None 表示计划书未指定。"""

    rule_code: str
    rule_name: str
    trigger_type: str
    target_text: str
    mr_class: tuple[str, ...]
    title_contains_any: tuple[str, ...]
    limit_minutes: int | None
    jhemr_monitor_code: str | None
    intent_action_mode: str | None
    remarks: str = ""
    workday_only: bool = False


RULE_SEEDS: tuple[RuleSeed, ...] = (
    RuleSeed(
        "ADM_REC", "入院记录", "ADMISSION", "EMR09.00.01/02/03",
        ("EMR09.00.01", "EMR09.00.02", "EMR09.00.03"), (),
        1440, "JH04.02.001", "LOCK_EMR", _D8_REMARK,
    ),
    RuleSeed(
        "FIRST_COURSE", "首次病程记录", "ADMISSION", "EMR10.00.01",
        ("EMR10.00.01",), (),
        480, "JH04.02.002", "LOCK_EMR",
    ),
    RuleSeed(
        "ATTENDING_FIRST_ROUND", "主治及以上首次查房", "ADMISSION", "EMR10.00.03，标题含“主治/副主任/主任”",
        ("EMR10.00.03",), ("主治", "副主任", "主任"),
        2880, "JH04.02.003", "LOCK_EMR",
    ),
    RuleSeed(
        "CHIEF_FIRST_ROUND", "主任/副主任首次查房", "ADMISSION", "EMR10.00.03，标题含“主任”",
        ("EMR10.00.03",), ("主任",),
        10080, "JH04.02.008", "LOCK_EMR",
        _D8_REMARK + "；时限 10080 分钟=医疗部 7 天（字典 72h，待 D9）",
    ),
    RuleSeed(
        "RESCUE_REC", "抢救记录", "RESCUE_ORDER", "待 D4/D7 确认模板",
        (), (),
        360, "JH04.02.007", "LOCK_EMR",
        "目标模板待 D4/D7 确认；" + _D4_REMARK.format(source="抢救医嘱"),
    ),
    RuleSeed(
        "OP_REC", "手术记录", "OPERATION_END", "EMR05.01.02",
        ("EMR05.01.02",), (),
        1440, "JH04.03.012", "LOCK_EMR",
    ),
    RuleSeed(
        "POSTOP_FIRST_COURSE", "术后首次病程", "OPERATION_END", "EMR10.00.12，标题含“术后首次”",
        ("EMR10.00.12",), ("术后首次",),
        360, "JH04.02.018", "LOCK_EMR",
        "时限 360 分钟待 D9",
    ),
    RuleSeed(
        "PREOP_SUMMARY", "术前小结/讨论", "OPERATION_START", "EMR10.00.10",
        ("EMR10.00.10",), (),
        0, "JH04.03.001", "LOCK_EMR",
        "时限 0：截止=手术开始",
    ),
    RuleSeed(
        "ANES_REC", "麻醉记录", "ANESTHESIA_END", "待定（不在 JHEMR，D4）",
        (), (),
        1440, None, "LOCK_EMR",
        "目标文书不在 JHEMR（D4），本期只做 ExternalEventSource 接口桩（§18.6）；无 JHEMR 监控码",
    ),
    RuleSeed(
        "DEATH_DISCUSS", "死亡病例讨论", "DEATH", "EMR10.00.15",
        ("EMR10.00.15",), (),
        5 * 1440, "JH04.02.013", "LOCK_EMR",
        "时限=5 个工作日（limit_minutes=5×1440 且 workday_only=True，按工作日计时由规则引擎实现）",
        workday_only=True,
    ),
    RuleSeed(
        "DISCHARGE_REC", "出院记录", "DISCHARGE", "EMR12.00",
        ("EMR12.00",), (),
        1440, "JH04.02.011", "LOCK_EMR",
    ),
    RuleSeed(
        "CRITICAL_VALUE_COURSE", "危急值处置病程", "CRITICAL_VALUE", "病程类且标题/监控码为危急值（待 D4）",
        (), (),
        360, "JH04.03.016", "LOCK_EMR",
        _D4_REMARK.format(source="危急值"),
    ),
    RuleSeed(
        "DEATH_REC", "死亡记录", "DEATH", "EMR10.00.14",
        ("EMR10.00.14",), (),
        1440, "JH04.02.012", None,
    ),
    RuleSeed(
        "CONSULT_EMERGENCY", "急会诊", "CONSULT_APPLY", "会诊记录/会诊状态",
        (), (),
        10, "JH04.02.020", "WARN_ONLY",
        _CONSULT_REMARK,
    ),
    RuleSeed(
        "CONSULT_NORMAL", "普通会诊", "CONSULT_APPLY", "会诊记录/会诊状态",
        (), (),
        1440, "JH04.02.020", "WARN_ONLY",
        _CONSULT_REMARK,
    ),
    RuleSeed(
        "DIFFICULT_CASE", "疑难病例讨论", "MANUAL_OR_INDICATOR", "EMR10.00.04",
        ("EMR10.00.04",), (),
        None, None, "WARN_ONLY",
        "时限待定；无 JHEMR 监控码",
    ),
    RuleSeed(
        "BLOOD_COURSE", "输血病程", "TRANSFUSION", "病程类标题含“输血”",
        (), ("输血",),
        1440, "JH04.03.017", None,
        _D4_REMARK.format(source="输血"),
    ),
    RuleSeed(
        "BLOOD_REC", "输血记录", "TRANSFUSION", "EMR05.01.04",
        ("EMR05.01.04",), (),
        1440, "JH04.03.010", None,
        _D4_REMARK.format(source="输血"),
    ),
)

RULE_SEED_CODES = tuple(seed.rule_code for seed in RULE_SEEDS)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _seed_note(seed: RuleSeed) -> str:
    if seed.intent_action_mode is None:
        intent = "业务意图 action_mode：计划书 T2 未指定（仅写明前 12 项 LOCK_EMR、会诊/疑难 WARN_ONLY），待确认"
    elif seed.rule_code in D8_NO_LOCK_RULE_CODES:
        intent = f"业务意图 action_mode={seed.intent_action_mode}（受 D8 约束当前禁止）"
    else:
        intent = f"业务意图 action_mode={seed.intent_action_mode}"
    parts = ["种子来源：主设计文档 §15 T2", intent, "种子实际 action_mode=SHADOW、enabled=False"]
    if seed.remarks:
        parts.append(seed.remarks)
    return "；".join(parts)


def _seed_version_fields(seed: RuleSeed) -> dict[str, Any]:
    return {
        "trigger_type": seed.trigger_type,
        "trigger_filter_json": _dump_json({}),
        "target_json": _dump_json(
            {
                "description": seed.target_text,
                "mr_class": list(seed.mr_class),
                "title_contains_any": list(seed.title_contains_any),
            }
        ),
        # 勘误 E13：“已完成”只认 first_mr_sign_date_time IS NOT NULL
        "completion_basis": "FIRST_SIGN",
        "limit_minutes": seed.limit_minutes,
        "workday_only": seed.workday_only,
        "warn_before_minutes": None,
        "action_mode": "SHADOW",
        "channels_json": _dump_json([]),
        "dept_scope_json": _dump_json([]),
        "jhemr_monitor_code": seed.jhemr_monitor_code,
        "penalty_amount": None,
        "note": _seed_note(seed),
    }


def _normalize_changes(changes: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for name, value in changes.items():
        if name in _JSON_FIELDS and not isinstance(value, str):
            normalized[name] = _dump_json(value)
        else:
            normalized[name] = value
    return normalized


def _validate_version_fields(rule_code: str, fields: dict[str, Any]) -> None:
    if not str(fields.get("trigger_type") or "").strip():
        raise RuleVersionError("trigger_type 不能为空")
    if fields.get("completion_basis") not in COMPLETION_BASES:
        raise RuleVersionError(
            f"completion_basis 非法: {fields.get('completion_basis')!r}（允许 {', '.join(COMPLETION_BASES)}）"
        )
    if fields.get("action_mode") not in ACTION_MODES:
        raise RuleVersionError(
            f"action_mode 非法: {fields.get('action_mode')!r}（允许 {', '.join(ACTION_MODES)}）"
        )
    if not isinstance(fields.get("workday_only"), bool):
        raise RuleVersionError("workday_only 须为布尔值")
    for name in _NON_NEGATIVE_INT_FIELDS:
        value = fields.get(name)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise RuleVersionError(f"{name} 须为非负整数或空: {value!r}")
    for name in _JSON_FIELDS:
        try:
            json.loads(fields.get(name) or "")
        except ValueError as exc:
            raise RuleVersionError(f"{name} 不是合法 JSON") from exc
    if rule_code in D8_NO_LOCK_RULE_CODES and fields.get("action_mode") == "LOCK_EMR":
        raise RuleVersionError(f"{D8_REJECT_MESSAGE}（{rule_code} 不得设为 LOCK_EMR）")


def seed_rules(db: Session) -> dict[str, list[str]]:
    """幂等写入 18 条规则种子并提交；已存在的 rule_code 整条跳过。

    返回 {"created": [...], "skipped": [...]}；任一步失败整体回滚后抛出。
    本函数不在 init_db 中自动调用，由后续任务决定初始化入口。
    """
    created: list[str] = []
    skipped: list[str] = []
    try:
        existing = {code for (code,) in db.query(TLRule.rule_code).all()}
        for seed in RULE_SEEDS:
            if seed.rule_code in existing:
                skipped.append(seed.rule_code)
                continue
            fields = _seed_version_fields(seed)
            _validate_version_fields(seed.rule_code, fields)
            now = datetime.now()
            rule = TLRule(
                rule_code=seed.rule_code,
                rule_name=seed.rule_name,
                category=SEED_CATEGORY,
                enabled=False,
                created_at=now,
                updated_at=now,
            )
            db.add(rule)
            db.flush()
            version = TLRuleVersion(
                rule_id=rule.id,
                version_no=1,
                created_by=SEED_CREATED_BY,
                created_at=now,
                **fields,
            )
            db.add(version)
            db.flush()
            rule.current_version_id = version.id
            created.append(seed.rule_code)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"created": created, "skipped": skipped}


def append_rule_version(db: Session, rule_code: str, *, created_by: str, **changes: Any) -> TLRuleVersion:
    """为规则追加新版本并切换为当前版本；旧版本行保持不变。

    changes 只接受 VERSION_FIELDS 中的字段（*_json 可传 dict/list，自动序列化）。
    本函数只 flush 不提交，由调用方提交或回滚。
    """
    unknown = sorted(set(changes) - set(VERSION_FIELDS))
    if unknown:
        raise RuleVersionError(f"不支持的版本字段: {unknown}")
    if not str(created_by or "").strip():
        raise RuleVersionError("created_by 不能为空")

    rule = db.query(TLRule).filter(TLRule.rule_code == rule_code).one_or_none()
    if rule is None:
        raise RuleVersionError(f"规则不存在: {rule_code}")
    current = db.get(TLRuleVersion, rule.current_version_id) if rule.current_version_id else None
    if current is None or current.rule_id != rule.id:
        raise RuleVersionError(f"规则 {rule_code} 缺少有效的当前版本，拒绝追加")

    fields = {name: getattr(current, name) for name in VERSION_FIELDS}
    fields.update(_normalize_changes(changes))
    _validate_version_fields(rule_code, fields)

    max_no = (
        db.query(func.max(TLRuleVersion.version_no))
        .filter(TLRuleVersion.rule_id == rule.id)
        .scalar()
    )
    now = datetime.now()
    version = TLRuleVersion(
        rule_id=rule.id,
        version_no=int(max_no or 0) + 1,
        created_by=created_by,
        created_at=now,
        **fields,
    )
    db.add(version)
    db.flush()
    rule.current_version_id = version.id
    rule.updated_at = now
    db.flush()
    return version
