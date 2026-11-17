"""
病历时效质控规则种子与版本写入原语（T2；2026-11-13 返工更新口径）。

- RULE_SEEDS：主设计文档 §15 T2 表格的 18 条规则，全部 enabled=False、action_mode=SHADOW。
  业务意图 action_mode 只写在 note（计划书原文：前 12 项意图 LOCK_EMR、会诊/疑难意图
  WARN_ONLY；DEATH_REC、BLOOD_COURSE、BLOOD_REC 计划书未指定，note 标“待确认”）。
- seed_rules()：幂等——已存在的 rule_code 整条跳过（不改规则行、不碰任何版本），
  重复执行不会覆盖用户后续保存的新版本；对仍处于初始 version_no==1 且
  created_by=system_seed（未被人工改过）的种子规则自动追加升级版本（见
  upgrade_seeded_v1_rules，2026-11-13 返工新增）。
- append_rule_version()：规则“每次保存生成新版本”的写入原语（§14.3 对 T2 的要求）：
  只追加新行、旧版本行不改；执行取值域校验与 D8 红线（§18.1/§18.4）。

2026-11-13 返工口径更新（对齐 2026-11-10~11-12 生产实证）：
- D8 解除 ADM_REC 封锁：生产库 2026-11-10 已完成全院 65 个入院记录模板补码与
  118 条在院监控行销账，JH04.02.001 幽灵行清零并在两科试点正式启用 LOCK_EMR；
  现仅 CHIEF_FIRST_ROUND（JH04.02.008，仍余 251 条幽灵行）受 D8 限制；
- 12 条意图 LOCK_EMR 且带 JHEMR 监控码的种子规则 penalty_amount=200
  （元/次，主方案 §1.2 医疗部口径）；
- ADM_REC target.mr_class 扩充为 EMR09.00.01/02/03；DISCHARGE_REC 扩充为
  EMR12.00 + EMR10.00.13。

2026-11-14 扩围前精度修正（活库 10.10.8.177 近 30 天实证）：
- CONSULT_NORMAL/CONSULT_EMERGENCY 目标由空（通配任意文书，误判）改为
  mr_class=(EMR10.00.08, EMR07.00.08, EMR10.00.02) + title_contains_any=("会诊",)；
- OP_REC 目标 mr_class 扩充 EMR10.00.16（有创操作文书）；
- OP_REC / POSTOP_FIRST_COURSE 种子 trigger_filter 排除床旁/门诊小操作
  operation_type='0'（field_not_in 语法，见 triggers.apply_trigger_filter）。
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

# D8（§18.1/§18.4）：幽灵行原因查清前不得设为 LOCK_EMR。
# 2026-11-13 返工：ADM_REC(JH04.02.001) 已于 2026-11-10 生产销账 118 条幽灵行并
# 在两科试点启用 LOCK_EMR，解除封锁；仅 CHIEF_FIRST_ROUND(JH04.02.008，
# 仍余 251 条幽灵行) 维持限制。
D8_NO_LOCK_RULE_CODES = frozenset({"CHIEF_FIRST_ROUND"})
D8_REJECT_MESSAGE = "D8：幽灵行原因查清前禁止锁定"

# 医疗部默认扣罚（元/次，主方案 §1.2）：12 条意图 LOCK_EMR 且带监控码的种子规则
# 按此写入 penalty_amount；台账统计与审批同步兜底同值。
DEFAULT_PENALTY_AMOUNT = 200

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

_D8_REMARK = "D8：禁止 LOCK_EMR（幽灵行原因查清前只能 SHADOW/WARN_ONLY，主设计文档 §18.1/§18.4；2026-11-10 生产销账后 ADM_REC 已解除，仅本规则维持）"
_D8_REMARK_ADM_REC_CLEARED = "2026-11-10 生产全院 65 模板补码+118 条在院幽灵行销账，D8 封锁解除（两科试点已启用 LOCK_EMR）"
_D4_REMARK = "{source}为独立系统（D4），本期只做 ExternalEventSource 接口桩，种子保留并保持停用（§18.1）"


class RuleVersionError(ValueError):
    """规则版本写入被拒绝：规则不存在、字段非法或触犯 D8 红线。"""


@dataclass(frozen=True)
class RuleSeed:
    """§15 T2 表格一行。target_text 为“目标文书”列原文；intent_action_mode=None 表示计划书未指定。

    penalty_amount：种子扣罚金额（元/次）；2026-11-13 返工起 12 条意图 LOCK_EMR
    且带监控码的规则固定 200（主方案 §1.2），None=未配置。
    trigger_filter：种子 trigger_filter_json（2026-11-14 起手术族排除床旁/门诊
    小操作 operation_type='0'；None=不过滤）。
    """

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
    penalty_amount: int | None = None
    trigger_filter: dict | None = None
    # 2026-11-14 七规则轮（任务书 §2.D）：
    title_excludes_any: tuple[str, ...] = ()      # 标题排除词（术后/交班/有创等）
    require_surgeon_sign: bool = False            # 主刀工号审签校验（OP_REC）
    require_signer_titles: tuple[str, ...] = ()   # 主治及以上审签（ATTENDING）
    preop_exemption: bool = False                 # 术前小结三合一豁免
    require_after_prev_op_end: bool = False       # 连台手术文书时间卡口
    warn_before_minutes: int | None = None        # 种子级预警提前量（PREOP=120）


RULE_SEEDS: tuple[RuleSeed, ...] = (
    RuleSeed(
        "ADM_REC", "入院记录", "ADMISSION", "EMR09.00.01/02/03",
        ("EMR09.00.01", "EMR09.00.02", "EMR09.00.03"), (),
        1440, "JH04.02.001", "LOCK_EMR", _D8_REMARK_ADM_REC_CLEARED,
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "FIRST_COURSE", "首次病程记录", "ADMISSION", "EMR10.00.01",
        ("EMR10.00.01",), (),
        480, "JH04.02.002", "LOCK_EMR",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "ATTENDING_FIRST_ROUND", "主治及以上首次查房", "ADMISSION",
        "EMR10.00.03（审签身份校验，排除术后日常查房）",
        ("EMR10.00.03",), (),
        2880, "JH04.02.003", "LOCK_EMR",
        "2026-11-14：去掉标题职称词硬限制（42 个通用查房模板如 ACS上级查房 不含职称字样），"
        "改 require_signer_titles 审签身份校验（topic_doctor 职称+上级本人审签/上级亲自创建），"
        "title_excludes_any 排除术后日常查房",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
        title_excludes_any=("术后",),
        require_signer_titles=("主治医师", "副主任医师", "主任医师"),
    ),
    RuleSeed(
        "CHIEF_FIRST_ROUND", "主任/副主任首次查房", "ADMISSION", "EMR10.00.03，标题含“主任”",
        ("EMR10.00.03",), ("主任",),
        10080, "JH04.02.008", "LOCK_EMR",
        _D8_REMARK + "；时限 10080 分钟=医疗部 7 天（字典 72h，待 D9）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "RESCUE_REC", "抢救记录", "RESCUE_ORDER", "EMR10.00.08/EMR10.00.02，标题含“抢救”",
        ("EMR10.00.08", "EMR10.00.02"), ("抢救",),
        360, "JH04.02.007", "LOCK_EMR",
        "2026-11-14：触发源接 HIS.ORDERS 抢救医嘱白名单（有效状态 2/3/6+临时，"
        "30 分钟窗口合并同次抢救）；目标=抢救记录类文书（排除有创操作记录）；"
        "完成时间须 >= t0（RESCUE_ORDER 默认）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
        title_excludes_any=("有创",),
    ),
    RuleSeed(
        "OP_REC", "手术记录", "OPERATION_END", "EMR05.01.02/EMR10.00.16（主刀审签）",
        ("EMR05.01.02", "EMR10.00.16"), (),
        1440, "JH04.03.012", "LOCK_EMR",
        "2026-11-14：mr_class 扩充 EMR10.00.16（有创操作文书，活库实证）；"
        "trigger_filter 排除床旁/门诊小操作 operation_type='0'；"
        "require_surgeon_sign=主刀工号审签校验（HIS.SURGEON 6 位工号，空则回退 FIRST_SIGN）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
        trigger_filter={"field_not_in": {"operation_type": ["0"]}},
        require_surgeon_sign=True,
    ),
    RuleSeed(
        "POSTOP_FIRST_COURSE", "术后首次病程", "OPERATION_END", "EMR10.00.12（排除交班/转科/出院）",
        ("EMR10.00.12",), (),
        360, "JH04.02.018", "LOCK_EMR",
        "2026-11-14：去掉过窄的标题词“术后首次”（活库大量模板名 SH术后首程/AR术后首程），"
        "改 mr_class 全类 + title_excludes_any 排除交班/转科/出院类；trigger_filter 排除 "
        "operation_type='0'；完成时间须 >= t0（OPERATION_END 默认）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
        trigger_filter={"field_not_in": {"operation_type": ["0"]}},
        title_excludes_any=("交班", "转科", "出院"),
    ),
    RuleSeed(
        "PREOP_SUMMARY", "术前小结/讨论", "OPERATION_START", "EMR10.00.10（三合一豁免+连台卡口）",
        ("EMR10.00.10",), (),
        0, "JH04.03.001", "LOCK_EMR",
        "时限 0：截止=手术开始；warn 120 分钟=开台前 2h 预警；"
        "2026-11-14：preop_exemption 三合一豁免（急诊/局麻一级小操作/单纯造影，用户拍板）；"
        "require_after_prev_op_end 连台卡口（第 2 台术前文书须晚于上一台结束，首台>=入院）；"
        "手术源优先 HIS.OPERATION_MASTER+SM 排台（未下台取 SCHEDULED_DATE_TIME）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
        preop_exemption=True,
        require_after_prev_op_end=True,
        warn_before_minutes=120,
    ),
    RuleSeed(
        "ANES_REC", "麻醉记录", "ANESTHESIA_END", "待定（不在 JHEMR，D4）",
        (), (),
        1440, None, "LOCK_EMR",
        "目标文书不在 JHEMR（D4），本期只做 ExternalEventSource 接口桩（§18.6）；无 JHEMR 监控码",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "DEATH_DISCUSS", "死亡病例讨论", "DEATH", "EMR10.00.15",
        ("EMR10.00.15",), (),
        5 * 1440, "JH04.02.013", "LOCK_EMR",
        "时限=5 个工作日（limit_minutes=5×1440 且 workday_only=True，按工作日计时由规则引擎实现）",
        workday_only=True,
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "DISCHARGE_REC", "出院记录", "DISCHARGE", "EMR12.00/EMR10.00.13",
        ("EMR12.00", "EMR10.00.13"), (),
        1440, "JH04.02.011", "LOCK_EMR",
        "2026-11-13 返工：mr_class 扩充 EMR10.00.13（日间/24h 出院记录变体）",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "CRITICAL_VALUE_COURSE", "危急值处置病程", "CRITICAL_VALUE", "病程类且标题/监控码为危急值（待 D4）",
        (), (),
        360, "JH04.03.016", "LOCK_EMR",
        _D4_REMARK.format(source="危急值"),
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "DEATH_REC", "死亡记录", "DEATH", "EMR10.00.14/EMR09.00.03",
        ("EMR10.00.14", "EMR09.00.03"), (),
        1440, "JH04.02.012", None,
        "2026-11-14：mr_class 扩充 EMR09.00.03（24h 内入院死亡记录变体）；"
        "死亡触发融合 HIS.ORDERS 死亡/料理医嘱（t0 优先医嘱最早时间）；penalty 200",
        penalty_amount=DEFAULT_PENALTY_AMOUNT,
    ),
    RuleSeed(
        "CONSULT_EMERGENCY", "急会诊", "CONSULT_APPLY", "EMR10.00.08/EMR07.00.08/EMR10.00.02，标题含“会诊”",
        ("EMR10.00.08", "EMR07.00.08", "EMR10.00.02"), ("会诊",),
        10, "JH04.02.020", "WARN_ONLY",
        "2026-11-14：目标 mr_class 按 177 活库近 30 天会诊文书分布实证"
        "（EMR10.00.02 标题含“会诊”3255 份/EMR07.00.08 103 份/EMR10.00.08 95 份），"
        "修复空目标通配误判；无文书时以会诊单处理时间 treat_date_time 回退（evaluate）",
    ),
    RuleSeed(
        "CONSULT_NORMAL", "普通会诊", "CONSULT_APPLY", "EMR10.00.08/EMR07.00.08/EMR10.00.02，标题含“会诊”",
        ("EMR10.00.08", "EMR07.00.08", "EMR10.00.02"), ("会诊",),
        1440, "JH04.02.020", "WARN_ONLY",
        "2026-11-14：目标 mr_class 按 177 活库近 30 天会诊文书分布实证"
        "（EMR10.00.02 标题含“会诊”3255 份/EMR07.00.08 103 份/EMR10.00.08 95 份），"
        "修复空目标通配误判；无文书时以会诊单处理时间 treat_date_time 回退（evaluate）",
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
    target: dict[str, Any] = {
        "description": seed.target_text,
        "mr_class": list(seed.mr_class),
        "title_contains_any": list(seed.title_contains_any),
    }
    if seed.title_excludes_any:
        target["title_excludes_any"] = list(seed.title_excludes_any)
    if seed.require_surgeon_sign:
        target["require_surgeon_sign"] = True
    if seed.require_signer_titles:
        target["require_signer_titles"] = list(seed.require_signer_titles)
    if seed.preop_exemption:
        target["preop_exemption"] = True
    if seed.require_after_prev_op_end:
        target["require_after_prev_op_end"] = True
    return {
        "trigger_type": seed.trigger_type,
        "trigger_filter_json": _dump_json(seed.trigger_filter or {}),
        "target_json": _dump_json(target),
        # 勘误 E13：“已完成”只认 first_mr_sign_date_time IS NOT NULL
        "completion_basis": "FIRST_SIGN",
        "limit_minutes": seed.limit_minutes,
        "workday_only": seed.workday_only,
        "warn_before_minutes": seed.warn_before_minutes,
        "action_mode": "SHADOW",
        "channels_json": _dump_json([]),
        "dept_scope_json": _dump_json([]),
        "jhemr_monitor_code": seed.jhemr_monitor_code,
        "penalty_amount": seed.penalty_amount,
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


def _seed_by_code() -> dict[str, RuleSeed]:
    return {seed.rule_code: seed for seed in RULE_SEEDS}


def upgrade_seeded_v1_rules(
    db: Session, *, created_by: str = "system_seed_upgrade", commit: bool = True
) -> dict[str, list[str]]:
    """把仍处于初始种子版本（version_no==1 且 created_by=system_seed）的规则升级到当前种子口径。

    2026-11-13 返工新增：``seed_rules`` 对老库幂等不覆盖已有版本，生产库（84 容器）
    已种下的 v1 规则需要一个轻量幂等升级通道同步 2026-11-13 口径（ADM_REC/
    DISCHARGE_REC 的 target.mr_class 扩充、12 条可锁定规则 penalty_amount=200、
    ADM_REC 的 D8 解锁备注）。判定"未被人工改过"= 当前版本仍是 version_no==1 且
    created_by==system_seed——用户保存过任何新版本（version_no>=2）的规则不动；
    幂等：升级后当前版本变为 v2，重复执行不再命中。返回 {"upgraded": [...],
    "skipped": [...]}（skipped=不存在/已被人工改过/种子与当前版本内容已一致）。
    """
    upgraded: list[str] = []
    skipped: list[str] = []
    try:
        seeds = _seed_by_code()
        rules = db.query(TLRule).filter(TLRule.rule_code.in_(seeds.keys())).all()
        for rule in rules:
            seed = seeds[rule.rule_code]
            current = db.get(TLRuleVersion, rule.current_version_id) if rule.current_version_id else None
            if current is None or current.rule_id != rule.id:
                skipped.append(rule.rule_code)
                continue
            if current.version_no != 1 or current.created_by != SEED_CREATED_BY:
                skipped.append(rule.rule_code)   # 已被人工改过（或已升级）：不覆盖
                continue
            fields = _seed_version_fields(seed)
            if all(getattr(current, name) == value for name, value in fields.items()):
                skipped.append(rule.rule_code)   # 内容已一致：无需升级
                continue
            append_rule_version(db, rule.rule_code, created_by=created_by, **fields)
            upgraded.append(rule.rule_code)
        if commit:
            db.commit()
        else:
            db.rollback()  # 2026-11-14 补丁 4：--dry-run 真只读（此前内部 commit 使外层回滚无效）
    except Exception:
        db.rollback()
        raise
    return {"upgraded": upgraded, "skipped": skipped}


def seed_rules(db: Session) -> dict[str, list[str]]:
    """幂等写入 18 条规则种子并提交；已存在的 rule_code 整条跳过。

    返回 {"created": [...], "skipped": [...], "upgraded": [...]}；任一步失败整体
    回滚后抛出。upgraded＝仍处于初始 v1 种子版本（未被人工改过）的规则被升级到
    当前种子口径（2026-11-13 返工；见 upgrade_seeded_v1_rules）。
    本函数不在 init_db 中自动调用，由 scripts/timeliness/run_shadow_scan_once.py
    与 upgrade_seed_rules_20261113.py 调用。
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
    # 老库幂等升级（2026-11-13 返工）：v1 初始种子（未被人工改过）同步新口径。
    upgrade = upgrade_seeded_v1_rules(db)
    return {"created": created, "skipped": skipped, "upgraded": upgrade["upgraded"]}


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
