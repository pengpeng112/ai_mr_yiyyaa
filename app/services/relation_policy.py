"""
012 P2 草案：六类质控 RelationPolicy（只读、版本化）。

第一版只表达当前行为，不顺带修订临床口径（012 §6）：
- 关联键、时间字段、required/anchor 角色全部复刻现行 SQL/Builder 行为；
- daily/discharge 语义不得合并；
- syssvsscbc 必须含 operation_date；surgery_chain 不得被强加 operation_date。

本模块为只读策略定义，未接入 loader/builder 调度。
"""
from __future__ import annotations

from dataclasses import dataclass, field

RELATION_POLICY_VERSION_V1 = "relation-policy-v1-20260808"

#: 运行模式
RUN_MODE_DAILY = "daily"
RUN_MODE_DISCHARGE = "discharge"


@dataclass(frozen=True)
class RelationPolicy:
    """单类质控在单一运行模式下的不可变关联策略。"""

    audit_type_code: str
    run_mode: str
    version: str
    anchor_keys: tuple[str, ...]                    # 分组/锚定键
    required_sources: tuple[str, ...]               # 必需源：缺失则整 bundle fail-closed
    context_sources: tuple[str, ...] = ()           # 上下文/可缺源（LEFT 语义）
    anchor_sources: tuple[str, ...] = ()            # 可创建 bundle 的锚点源
    time_rules: dict[str, str] = field(default_factory=dict)  # 源 -> 冻结的时间口径
    relation_edges: tuple[str, ...] = ()            # 关系边标注（如 same_audit_day）
    notes: str = ""


#: 六类 × 运行模式的 V1 策略表；键为 (audit_type_code, run_mode)。
#: 口径逐条复刻 012 §6 表格，禁止在实施中改写。
_RELATION_POLICIES_V1: dict[tuple[str, str], RelationPolicy] = {}


def _register(policy: RelationPolicy) -> None:
    key = (policy.audit_type_code, policy.run_mode)
    if key in _RELATION_POLICIES_V1:
        raise ValueError(f"重复注册 RelationPolicy: {key}")
    _RELATION_POLICIES_V1[key] = policy


_register(RelationPolicy(
    audit_type_code="progress_vs_nursing",
    run_mode=RUN_MODE_DAILY,
    version=RELATION_POLICY_VERSION_V1,
    anchor_keys=("patient_id", "visit_number"),
    required_sources=("progress", "nursing"),   # 现行内连接：两侧均存在才进入
    time_rules={
        "progress": "event_time(caption_date_time) 位于 query_date",
        "nursing": "form_time 位于同一 query_date",
    },
    relation_edges=("same_audit_day",),
    notes="当日在院锚点；candidate policy 要求两侧存在",
))
_register(RelationPolicy(
    audit_type_code="progress_vs_nursing",
    run_mode=RUN_MODE_DISCHARGE,
    version=RELATION_POLICY_VERSION_V1,
    anchor_keys=("patient_id", "visit_number"),
    required_sources=("progress",),
    context_sources=("nursing",),               # 现行 LEFT JOIN：缺护理不删病程 candidate
    time_rules={
        "progress": "event_time 位于入院至出院+1",
        "nursing": "created_date 与每条病程完成时间同日（隐式复合键关联）",
    },
    relation_edges=("same_calendar_day",),
    notes="出院日期=query_date；保留住院全程病程",
))
for _mode in (RUN_MODE_DAILY, RUN_MODE_DISCHARGE):
    _register(RelationPolicy(
        audit_type_code="jyjc_vs_bcnursing",
        run_mode=_mode,
        version=RELATION_POLICY_VERSION_V1,
        anchor_keys=("patient_id", "visit_number"),
        required_sources=("lab_or_exam",),
        context_sources=("progress", "nursing"),
        anchor_sources=("lab", "exam"),
        time_rules={
            "lab_exam": "按结果/报告日期",
            "nursing": "patient+visit 定向 fanout，配置时间窗",
        },
        notes="lab/exam 为可替代锚点；progress/nursing 为上下文",
    ))
_register(RelationPolicy(
    audit_type_code="syssvsscbc",
    run_mode=RUN_MODE_DISCHARGE,
    version=RELATION_POLICY_VERSION_V1,
    anchor_keys=("patient_id", "visit_number", "operation_date"),
    required_sources=("frontpage_surgery", "postop_first_progress"),
    time_rules={"postop_first_progress": "病历日期=手术日期"},
    relation_edges=("operation_date",),
    notes="首页每台手术展开；禁止退化为仅 patient+visit",
))
for _mode in (RUN_MODE_DAILY, RUN_MODE_DISCHARGE):
    _register(RelationPolicy(
        audit_type_code="admission_vs_first_progress",
        run_mode=_mode,
        version=RELATION_POLICY_VERSION_V1,
        anchor_keys=("patient_id", "visit_number"),
        required_sources=("admission_record", "first_progress"),
        notes="入院记录与首次病程均必需（Vastbase 分类）；visit_id/inp_no 映射待 P0 确认",
    ))
    _register(RelationPolicy(
        audit_type_code="surgery_chain",
        run_mode=_mode,
        version=RELATION_POLICY_VERSION_V1,
        anchor_keys=("patient_id", "visit_number"),
        required_sources=("preop_summary", "operation_record", "postop_first_progress"),
        notes="同一住院次三亚型按时间排序；不引入 operation_date 新键",
    ))
_register(RelationPolicy(
    audit_type_code="discharge_vs_frontpage",
    run_mode=RUN_MODE_DISCHARGE,
    version=RELATION_POLICY_VERSION_V1,
    anchor_keys=("patient_id", "visit_number"),
    required_sources=("discharge_record", "frontpage"),
    notes="出院记录与首次病程均必需，按出院日期锚定",
))


def get_relation_policy(
    audit_type_code: str,
    run_mode: str,
    version: str = RELATION_POLICY_VERSION_V1,
) -> RelationPolicy:
    """按类型+模式取策略；未知组合 fail-closed（KeyError）。"""
    if version != RELATION_POLICY_VERSION_V1:
        raise KeyError(f"未知 RelationPolicy 版本: {version}")
    key = (str(audit_type_code or "").strip(), str(run_mode or "").strip())
    if key not in _RELATION_POLICIES_V1:
        raise KeyError(f"未定义 RelationPolicy: {key}")
    return _RELATION_POLICIES_V1[key]


def list_relation_policies() -> list[RelationPolicy]:
    """返回全部已注册策略（只读副本）。"""
    return list(_RELATION_POLICIES_V1.values())


def validate_required_sources(
    policy: RelationPolicy,
    available_sources: set[str],
    failed_sources: set[str],
) -> list[str]:
    """按策略校验源可用性，返回违规列表（空 = 通过）。

    - required 源查询失败：整 bundle fail-closed（012 §8.2.5）；
    - required 源真实缺失（0 行）：daily 内连接语义下判为不满足候选；
    - context 源缺失不构成违规。
    """
    violations: list[str] = []
    for source in policy.required_sources:
        if source in failed_sources:
            violations.append(f"required 源 {source} 查询失败，fail-closed")
        elif source not in available_sources:
            violations.append(f"required 源 {source} 缺失")
    return violations
