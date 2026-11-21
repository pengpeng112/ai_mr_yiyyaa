"""病历时效质控 API 路由（T5；主设计文档 §15 T5 / §10.1 字典 / §18.1 D8）。

- 前缀 /api/timeliness（app/main.py 只追加一次 include_router）；
- 权限：timeliness_view / timeliness_rule_edit / timeliness_approve（T9 使用）/
  timeliness_export / timeliness_admin（§15.2 统一命名，种子仅 admin）；
- D8 强制防呆（§18.1/§18.6）：幽灵监控行原因查清前，CHIEF_FIRST_ROUND(JH04.02.008)
  严禁设为 LOCK_EMR——即使 jhemr_write.enabled=true 且操作人具备 timeliness_admin
  也必须 400；ADM_REC(JH04.02.001) 已于 2026-11-10 生产销账后解除封锁（65 模板补码+
  118 幽灵行清零，两科试点启用）；其余规则需 timeliness_admin + jhemr_write.enabled；
- LOCK_EMR 其余要求：操作人具备 timeliness_admin 且 timeliness.jhemr_write.enabled
  ==true，否则 400；
- 保存新版本走 rules_seed.append_rule_version（只追加不覆盖，旧版本完整保留）；
- dry-run 用待保存版本对当前数据试算，只返回统计与前 50 条样例，绝不写库；
- 事件列表/详情/月度统计/导出受 dept_visibility 科室可见性约束；
- 导出必须调用 record_export_audit()（AGENTS.md 回归红线）。
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import false as sql_false

from app.config import load_config
from app.database import get_db
from app.models import Department, Role, User
from app.permissions import get_user_permissions, require_permission
from app.services.timeliness_access import timeliness_department_options, timeliness_visibility
from app.services.export_audit_service import record_export_audit
from app.timeliness.approval_sync import mark_approved_locally, sync_approvals
from app.timeliness.config import TimelinessNotConfigured, TimelinessPermissionMissing
from app.timeliness.engine import evaluate
from app.timeliness.engine.state import TERMINAL_STATUSES
from app.timeliness.engine.triggers import TRIGGER_TYPES
from app.timeliness.jhemr_writer import (
    JhemrWriteError,
    JhemrWriter,
    JhemrWriteRowCountError,
)
from app.timeliness.models import (
    ACTION_MODES,
    COMPLETION_BASES,
    EVENT_STATUSES,
    TLActionLog,
    TLApproval,
    TLEvent,
    TLEventHistory,
    TLRule,
    TLRuleVersion,
    TLScanRun,
)
from app.timeliness.rules_seed import (
    D8_NO_LOCK_RULE_CODES,
    RuleVersionError,
    VERSION_FIELDS,
    append_rule_version,
)
from app.timeliness.schemas import (
    MessageResponse,
    RuleDryRunRequest,
    RuleToggleRequest,
    RuleVersionCreateRequest,
)
from app.timeliness.scanner import JhemrModuleReader, fetch_scan_snapshot

logger = logging.getLogger(__name__)
router = APIRouter()

PERM_VIEW = "timeliness_view"
PERM_EDIT = "timeliness_rule_edit"
PERM_APPROVE = "timeliness_approve"   # T9 审批端点启用；本文件先声明占用
PERM_EXPORT = "timeliness_export"
PERM_ADMIN = "timeliness_admin"

# D8（§18.1/§18.4）：幽灵行原因查清前仅受限规则禁止 LOCK_EMR。
# 2026-11-13 返工：生产 2026-11-10 已完成全院 65 个入院记录模板补码与 118 条在院
# 监控行销账（JH04.02.001 幽灵行清零，两科试点启用 LOCK_EMR），ADM_REC 解除封锁；
# 仅 CHIEF_FIRST_ROUND(JH04.02.008，余 251 条幽灵行) 维持限制。
D8_ONLY_LOCK_HINT = (
    "D8 restriction: LOCK_EMR is not allowed for CHIEF_FIRST_ROUND(JH04.02.008) "
    "until its remaining ghost monitor rows (251) are cleared; "
    "ADM_REC(JH04.02.001) was unlocked on 2026-11-10 after production remediation "
    "(65 templates recoded, 118 ghost rows settled) and may enable locking "
    "with timeliness_admin + jhemr_write.enabled"
)

DRY_RUN_SAMPLE_LIMIT = 50

# ---- 字典（§10.1 生产实测；来源=主设计文档 2026-11-09 只读影子验证） ----

# mr_class：编码 → 说明（含样例标题）。
MR_CLASS_DICT: list[dict[str, str]] = [
    {"code": "EMR09.00.01", "label": "入院记录（普通）", "sample_topic": "鼻骨骨折"},
    {"code": "EMR09.00.02", "label": "入院记录（日间入出院）", "sample_topic": "胬肉日间出入院"},
    {"code": "EMR09.00.03", "label": "入院记录（24h入院死亡）", "sample_topic": ""},
    {"code": "EMR10.00.01", "label": "首次病程记录", "sample_topic": "首次病程记录（骨折）"},
    {"code": "EMR10.00.02", "label": "日常病程记录（抢救/危急值/输血/术后病程载体）", "sample_topic": ""},
    {"code": "EMR10.00.03", "label": "查房记录（主治/副主任/主任）", "sample_topic": "刘志勇主治医师查房记录"},
    {"code": "EMR10.00.04", "label": "疑难病例讨论", "sample_topic": ""},
    {"code": "EMR10.00.06", "label": "转科记录（转出/转入）", "sample_topic": "转科记录"},
    {"code": "EMR10.00.07", "label": "阶段小结", "sample_topic": "阶段小结"},
    {"code": "EMR10.00.08", "label": "会诊记录", "sample_topic": "会诊记录"},
    {"code": "EMR10.00.10", "label": "术前小结及术前讨论", "sample_topic": "术前小结及讨论"},
    {"code": "EMR10.00.12", "label": "术后首次病程记录", "sample_topic": "术后首次病程记录"},
    {"code": "EMR10.00.14", "label": "死亡记录", "sample_topic": "死亡记录"},
    {"code": "EMR10.00.15", "label": "死亡病例讨论", "sample_topic": "死亡病例讨论结论记录"},
    {"code": "EMR10.00.16", "label": "有创操作记录", "sample_topic": ""},
    {"code": "EMR12.00", "label": "出院记录", "sample_topic": "鼻息肉出院"},
    {"code": "EMR05.01.02", "label": "手术记录", "sample_topic": "鼻骨折闭合性复位术手术记录"},
    {"code": "EMR05.01.04", "label": "输血记录", "sample_topic": "输血记录"},
    {"code": "EMR07.00.01", "label": "手术知情同意书", "sample_topic": "鼻窦炎手术知情"},
    {"code": "EMR07.00.04", "label": "输血知情同意书", "sample_topic": "输血知情同意书"},
    {"code": "EMR07.00.08", "label": "会诊记录（同意书类）", "sample_topic": "麻醉科会诊记录"},
]

# 监控项字典：§10.1 实测编码子集（27 项）。完整 35 项以生产表
# jhemr.jhinpat_mr_monitor_items 为准（需只读授权后拉取，§18.2）；
# jhemr_generated=JHEMR 后台是否自动生成监控行（实证 R2：仅 4 类自动生成）。
MONITOR_ITEM_DICT: list[dict[str, Any]] = [
    {"code": "JH04.02.001", "label": "住院病历（入院记录）", "limit": "24h", "jhemr_generated": True},
    {"code": "JH04.03.013", "label": "24h入出院记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.002", "label": "首次病程记录", "limit": "8h（测试期24h）", "jhemr_generated": True},
    {"code": "JH04.02.003", "label": "首次上级查房", "limit": "48h", "jhemr_generated": False},
    {"code": "JH04.03.007", "label": "上级常规查房", "limit": "", "jhemr_generated": False},
    {"code": "JH04.02.008", "label": "首次主任或副主任查房", "limit": "72h（医疗部7天）", "jhemr_generated": True},
    {"code": "JH04.02.004", "label": "转出记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.005", "label": "转入记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.006", "label": "阶段小结", "limit": "30天", "jhemr_generated": True},
    {"code": "JH04.02.007", "label": "抢救记录", "limit": "6h", "jhemr_generated": False},
    {"code": "JH04.03.001", "label": "术前小结", "limit": "手术前", "jhemr_generated": False},
    {"code": "JH04.03.002", "label": "术前讨论记录", "limit": "手术前", "jhemr_generated": False},
    {"code": "JH04.03.011", "label": "手术同意书", "limit": "手术前", "jhemr_generated": False},
    {"code": "JH04.03.012", "label": "手术记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.018", "label": "术后首次病程", "limit": "24h（医疗部即时/6h）", "jhemr_generated": False},
    {"code": "JH04.02.015", "label": "术后1天病程及查房", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.016", "label": "术后2天病程及查房", "limit": "48h", "jhemr_generated": False},
    {"code": "JH04.02.017", "label": "术后3天病程及查房", "limit": "72h", "jhemr_generated": False},
    {"code": "JH04.02.019", "label": "术后上级查房", "limit": "", "jhemr_generated": False},
    {"code": "JH04.03.016", "label": "危急值病程", "limit": "6h（可调8h）", "jhemr_generated": False},
    {"code": "JH04.03.010", "label": "输血记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.03.017", "label": "输血病程", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.03.018", "label": "输血同意书", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.020", "label": "会诊记录", "limit": "急10min / 普24h", "jhemr_generated": False},
    # 2026-11-13 返工：出院记录已于 2026-11-10 在生产 jhinpat_mr_monitor_order 配置
    # JH07.01.0004 原生自动触发 → jhemr_generated=True（外插拦截见 NATIVE_GENERATED_CODES）。
    {"code": "JH04.02.011", "label": "出院记录", "limit": "24h", "jhemr_generated": True},
    {"code": "JH04.02.012", "label": "死亡记录", "limit": "24h", "jhemr_generated": False},
    {"code": "JH04.02.013", "label": "死亡病例讨论", "limit": "168h（5个工作日）", "jhemr_generated": False},
]

TRIGGER_TYPE_LABELS: dict[str, str] = {
    "ADMISSION": "患者入院",
    "DISCHARGE": "出院",
    "DEATH": "死亡",
    "OPERATION_START": "手术开始",
    "OPERATION_END": "手术结束",
    "CONSULT_APPLY": "会诊申请",
    "MANUAL_OR_INDICATOR": "人工/指标",
    "RESCUE_ORDER": "抢救医嘱（外部源，D4）",
    "CRITICAL_VALUE": "危急值（外部源，D4）",
    "TRANSFUSION": "输血（外部源，D4）",
    "ANESTHESIA_END": "麻醉结束（外部源，D4）",
}


# ---- 内部工具 ----


def _user_has_permission(db: Session, current_user: User, permission: str) -> bool:
    """与 require_permission 同语义：admin 角色全通过，其余查角色权限。"""
    if not current_user.role_id:
        return False
    role = db.query(Role).filter(Role.id == current_user.role_id).first()
    if role and role.name == "admin":
        return True
    return permission in get_user_permissions(current_user.id, db)


def _jhemr_write_enabled(config: dict | None = None) -> bool:
    cfg = config if config is not None else load_config()
    section = (cfg or {}).get("timeliness") or {}
    write_cfg = section.get("jhemr_write") or {}
    return bool(isinstance(write_cfg, dict) and write_cfg.get("enabled"))


def _notify_mode(config: dict | None = None) -> str:
    """timeliness.notify_mode 现值（默认 LOG_ONLY；D6 闸门展示用）。"""
    from app.timeliness.notifier import resolve_notify_mode

    cfg = config if config is not None else load_config()
    try:
        mode, _reason = resolve_notify_mode(cfg)
    except Exception:
        mode = "LOG_ONLY"
    return mode


def _get_rule(db: Session, rule_code: str) -> TLRule:
    rule = db.query(TLRule).filter(TLRule.rule_code == rule_code).first()
    if rule is None:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_code}")
    return rule


def _get_current_version(db: Session, rule: TLRule) -> TLRuleVersion:
    version = db.get(TLRuleVersion, rule.current_version_id) if rule.current_version_id else None
    if version is None:
        raise HTTPException(status_code=404, detail=f"rule has no current version: {rule.rule_code}")
    return version


def _rule_dict(rule: TLRule, version: TLRuleVersion | None) -> dict[str, Any]:
    return {
        "id": rule.id,
        "rule_code": rule.rule_code,
        "rule_name": rule.rule_name,
        "category": rule.category,
        "enabled": bool(rule.enabled),
        "current_version_id": rule.current_version_id,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        "current_version": _version_dict(version) if version else None,
    }


def _version_dict(version: TLRuleVersion) -> dict[str, Any]:
    return {
        "id": version.id,
        "rule_id": version.rule_id,
        "version_no": version.version_no,
        "trigger_type": version.trigger_type,
        "trigger_filter_json": version.trigger_filter_json,
        "target_json": version.target_json,
        "completion_basis": version.completion_basis,
        "limit_minutes": version.limit_minutes,
        "workday_only": bool(version.workday_only),
        "warn_before_minutes": version.warn_before_minutes,
        "action_mode": version.action_mode,
        "channels_json": version.channels_json,
        "dept_scope_json": version.dept_scope_json,
        "jhemr_monitor_code": version.jhemr_monitor_code,
        "penalty_amount": version.penalty_amount,
        "note": version.note,
        "created_by": version.created_by,
        "created_at": version.created_at.isoformat() if version.created_at else None,
    }


def _display_maps(db: Session) -> dict[str, dict[str, str]]:
    """台账中文化展示映射（2026-11-14 P0 轮；2026-11-15 审批台账补齐）：

    - dept_names：应用库 Department.code → name；
    - staff_names：HIS.STAFF_DICT 工号→姓名（TTL 缓存；Oracle 不可用降级空表）；
    - rule_names：TLRule.rule_code → rule_name；
    - monitor_rule_names：JHEMR 监控码 → rule_name（审批台账按 monitor_code 关联规则名，
      取规则当前版本 jhemr_monitor_code 反查；一码多规则时取 rule_code 字典序首个）。
    均为只读展示用途，失败不阻断请求。
    """
    dept_names = {
        (row.code or ""): (row.name or "")
        for row in db.query(Department).all()
        if row.code
    }
    rule_names = {
        rule.rule_code: rule.rule_name or ""
        for rule in db.query(TLRule.rule_code, TLRule.rule_name).all()
    }
    monitor_rule_names: dict[str, str] = {}
    try:
        rows = (
            db.query(TLRuleVersion.jhemr_monitor_code, TLRule.rule_code, TLRule.rule_name)
            .join(TLRule, TLRule.current_version_id == TLRuleVersion.id)
            .filter(TLRuleVersion.jhemr_monitor_code.isnot(None))
            .all()
        )
        for monitor_code, rule_code, rule_name in rows:
            code = str(monitor_code or "").strip()
            if code and code not in monitor_rule_names:
                monitor_rule_names[code] = rule_name or rule_code or ""
    except Exception:
        pass  # 规则版本关联异常：监控码中文名留空（展示降级，不影响数据）
    staff_names: dict[str, str] = {}
    try:
        from app.timeliness.his_oracle_reader import get_staff_name_map

        staff_names = get_staff_name_map() or {}
    except Exception:
        pass  # HIS 不可用：姓名留空（展示降级，不影响数据）
    return {
        "dept": dept_names,
        "staff": staff_names,
        "rule": rule_names,
        "monitor_rule": monitor_rule_names,
    }


def _patient_name_map(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """当页 (patient_id, visit_id) → 患者真实姓名（2026-11-15 P0-3）。

    - 复用 his_oracle_reader.fetch_patient_visit_meta 的 V_QYBR 授权查询与
      1 小时进程内 TTL 缓存（每批 ≤200 对、未缓存键 600 查库封顶）；
    - pairs 去重后为空直接返回 {}（零连接零开销）；
    - HIS/Oracle 配置不可用或查询异常时静默降级 {}（与 _display_maps 里
      get_staff_name_map 同款容错，绝不拖慢/拖垮离线单测与台账主链路）。
    """
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pid, vid in pairs or ():
        key = (str(pid or "").strip(), str(vid or "").strip())
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            unique.append(key)
    if not unique:
        return {}
    try:
        from app.timeliness.his_oracle_reader import fetch_patient_visit_meta

        meta = fetch_patient_visit_meta(unique) or {}
    except Exception:
        # 离线/无权限/驱动缺失：姓名留空（键保留空串），前端回退 patient_id
        return {pair: "" for pair in unique}
    return {
        pair: str((meta.get(pair) or {}).get("patient_name") or "")
        for pair in unique
    }


def _patient_meta_map(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dict]:
    """WP04：当页 (patient_id, visit_id) → V_QYBR 临床元信息（姓名+住院号/性别/年龄/
    入院日期/入院诊断/护理级别等，一次批量查询）。

    与 _patient_name_map 同款规范化与静默降级：空 pairs 返回 {}；HIS/Oracle 不可用
    或查询异常时返回 {}（页面回退既有编码展示，绝不拖垮台账主链路）。
    """
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for pid, vid in pairs or ():
        key = (str(pid or "").strip(), str(vid or "").strip())
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            unique.append(key)
    if not unique:
        return {}
    try:
        from app.timeliness.his_oracle_reader import fetch_patient_visit_meta

        return fetch_patient_visit_meta(unique) or {}
    except Exception:
        return {}


def _rule_monitor_map(db: Session) -> dict[str, str]:
    """WP04：rule_code → 监控码（规则当前版本 jhemr_monitor_code）。

    事件 latest_approval 的「同规则优先」与审批行回联 TLEvent 共用；查询异常降级
    空表（latest_approval 退同患者口径，展示层不受影响）。
    """
    mapping: dict[str, str] = {}
    try:
        rows = (
            db.query(TLRule.rule_code, TLRuleVersion.jhemr_monitor_code)
            .join(TLRule, TLRule.current_version_id == TLRuleVersion.id)
            .filter(TLRuleVersion.jhemr_monitor_code.isnot(None))
            .all()
        )
        for rule_code, monitor_code in rows:
            code = str(monitor_code or "").strip()
            if rule_code and code:
                mapping.setdefault(str(rule_code), code)
    except Exception:
        pass
    return mapping


def _doctor_filter_ids(db: Session, doctor: str | None) -> list[str]:
    """WP04：把「工号或姓名」筛选值解析为责任医生/申请人工号集合。

    工号精确值始终纳入；STAFF_DICT 姓名映射（TTL 缓存）中姓名包含该文本的工号一并
    纳入（姓名模糊→工号集合）。HIS 不可用时降级为仅工号精确匹配。
    """
    text = str(doctor or "").strip()
    if not text:
        return []
    ids = {text}
    try:
        from app.timeliness.his_oracle_reader import get_staff_name_map

        staff = get_staff_name_map() or {}
    except Exception:
        staff = {}
    for emp_no, name in staff.items():
        if name and text in str(name):
            ids.add(emp_no)
    return sorted(ids)


def _remaining_minutes(event: TLEvent) -> int | None:
    """WP04：未进入终态事件距截止的整分钟（正=剩余，负=已超时）；终态/无截止为 None。"""
    if event.status in TERMINAL_STATUSES or event.deadline is None:
        return None
    return int((event.deadline - datetime.now()).total_seconds() // 60)


def _latest_approval_map(
    db: Session, events: list[TLEvent], rule_monitor: dict[str, str]
) -> dict[tuple[str, str], dict[str, Any] | None]:
    """WP04：按当页 (patient_id, visit_id) 一次查询 TLApproval，给出每条事件的
    最近解锁申请摘要。

    - 优先匹配「同患者同住院次且监控码与事件规则对应」的最新一条（match="rule"，
      经规则当前版本 jhemr_monitor_code 关联）；
    - 找不到则取同患者（不限住院次）最新一条并标 match="patient"；
    - 患者无任何申请 → None；查询异常降级全 None（不阻断台账主链路）。
    """
    if not events:
        return {}
    pids = sorted({str(e.patient_id or "").strip() for e in events if e.patient_id})
    if not pids:
        return {}
    approvals_by_patient: dict[str, list[TLApproval]] = {}
    try:
        rows = (
            db.query(TLApproval)
            .filter(TLApproval.patient_id.in_(pids))
            .order_by(TLApproval.apply_date_time.desc(), TLApproval.id.desc())
            .all()
        )
    except Exception:
        rows = []
    for approval in rows:
        approvals_by_patient.setdefault(str(approval.patient_id or "").strip(), []).append(approval)

    def _summary(approval: TLApproval | None, match: str | None) -> dict[str, Any] | None:
        if approval is None:
            return None
        return {
            "id": approval.id,
            "flag": approval.flag,
            "apply_date_time": (
                approval.apply_date_time.isoformat() if approval.apply_date_time else None
            ),
            "approve_date_time": (
                approval.approve_date_time.isoformat() if approval.approve_date_time else None
            ),
            "penalty_exempt": bool(approval.penalty_exempt),
            "match": match,
        }

    result: dict[tuple[str, str], dict[str, Any] | None] = {}
    for event in events:
        pid = str(event.patient_id or "").strip()
        vid = str(event.visit_id or "").strip()
        monitor_code = rule_monitor.get(event.rule_code or "", "")
        rule_hit: TLApproval | None = None
        if monitor_code:
            for approval in approvals_by_patient.get(pid, ()):  # 已按申请时间倒序
                if (
                    str(approval.visit_id or "").strip() == vid
                    and str(approval.monitor_code or "").strip() == monitor_code
                ):
                    rule_hit = approval
                    break
        if rule_hit is not None:
            result[(pid, vid)] = _summary(rule_hit, "rule")
        else:
            patient_rows = approvals_by_patient.get(pid) or []
            result[(pid, vid)] = _summary(patient_rows[0] if patient_rows else None, "patient")
    return result


def _event_overdue_map(
    db: Session, approvals: list[TLApproval], rule_monitor: dict[str, str]
) -> dict[int, dict[str, Any] | None]:
    """WP04：审批行 → 同患者同规则最近 TLEvent 的截止/超时分钟（monitor_code 经
    当前版本反查 rule_code；找不到对应事件为 None；查询异常降级全 None）。"""
    if not approvals:
        return {}
    monitor_to_rule = {code: rule for rule, code in rule_monitor.items()}
    pids = sorted({str(a.patient_id or "").strip() for a in approvals if a.patient_id})
    if not pids:
        return {}
    event_map: dict[tuple[str, str, str], TLEvent] = {}
    try:
        rows = (
            db.query(TLEvent)
            .filter(TLEvent.patient_id.in_(pids))
            .order_by(TLEvent.id.desc())
            .all()
        )
    except Exception:
        rows = []
    for event in rows:
        key = (
            str(event.patient_id or "").strip(),
            str(event.visit_id or "").strip(),
            str(event.rule_code or ""),
        )
        existing = event_map.get(key)
        if existing is None:
            event_map[key] = event  # id 倒序 → 首条即最新
        elif existing.overdue_minutes is None and event.overdue_minutes is not None:
            # 最新事件可能是 PENDING（无超时数据）——保留最近一条带超时口径的行
            event_map[key] = event

    result: dict[int, dict[str, Any] | None] = {}
    for approval in approvals:
        rule_code = monitor_to_rule.get(str(approval.monitor_code or "").strip(), "")
        event = event_map.get(
            (
                str(approval.patient_id or "").strip(),
                str(approval.visit_id or "").strip(),
                rule_code,
            )
        ) if rule_code else None
        result[approval.id] = {
            "event_deadline": (
                event.deadline.isoformat() if event is not None and event.deadline else None
            ),
            "event_overdue_minutes": event.overdue_minutes if event is not None else None,
        }
    return result


def _event_dict(event: TLEvent, display: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    data = {
        "id": event.id,
        "event_uid": event.event_uid,
        "rule_code": event.rule_code,
        "rule_version_id": event.rule_version_id,
        "patient_id": event.patient_id,
        "visit_id": event.visit_id,
        "dept_code": event.dept_code,
        "responsible_doctor_id": event.responsible_doctor_id,
        "t0": event.t0.isoformat() if event.t0 else None,
        "deadline": event.deadline.isoformat() if event.deadline else None,
        "status": event.status,
        "matched_file_unique_id": event.matched_file_unique_id,
        "completed_at": event.completed_at.isoformat() if event.completed_at else None,
        "overdue_minutes": event.overdue_minutes,
        "warn_sent_at": event.warn_sent_at.isoformat() if event.warn_sent_at else None,
        "last_scan_at": event.last_scan_at.isoformat() if event.last_scan_at else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
        "updated_at": event.updated_at.isoformat() if event.updated_at else None,
    }
    if display is not None:
        # 2026-11-14 P0：只读中文展示字段（长 uid 前端收折，导出脱敏口径不变）。
        data["dept_name"] = (display["dept"] or {}).get(event.dept_code or "", "")
        data["responsible_doctor_name"] = (display["staff"] or {}).get(
            event.responsible_doctor_id or "", "")
        data["rule_name"] = (display["rule"] or {}).get(event.rule_code, "")
        # 2026-11-15 P0-3：患者真实姓名（V_QYBR TTL 缓存按当页 pairs 批量补齐；
        # 查不到时留空，前端回退 patient_id + 住院次）。inp_no 暂无授权字段，
        # patient_id 即住院号（051xxxx 口径）。
        data["patient_name"] = (display.get("patient") or {}).get(
            (event.patient_id or "", str(event.visit_id or "")), "")
        data["inp_no"] = ""
    return data


def _resolve_dept_filter(db: Session, dept_param: str | None, user: User | None = None) -> list[str]:
    """把科室过滤参数（编码或名称）解析为科室编码列表。"""
    text = str(dept_param or "").strip()
    if not text:
        return []
    if getattr(user, "his_virtual", False):
        code = user.his_dept_code
        return [code] if code and text in (code, user.his_dept_name) else []
    rows = db.query(Department).filter(
        (Department.code == text) | (Department.name == text)
    ).all()
    return [row.code or row.name for row in rows if (row.code or row.name)]


def _filter_dept(query, column, db, current_user, dept):
    if not (dept or "").strip():
        return query
    codes = _resolve_dept_filter(db, dept, current_user)
    return query.filter(column.in_(codes) if codes else sql_false())


def _parse_day_bound(value: str, *, end: bool = False) -> datetime:
    """解析日期过滤参数：非法值 → 400（修订 2026-11-11：此前未捕获 ValueError 变 500）。

    date_to 传纯日期（YYYY-MM-DD，无时间部分）时取当天 23:59:59.999999 含当日全天
    （修订 2026-11-11：此前解析为零点，整个目标日被静默排除）。
    """
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid datetime filter: {value!r}") from exc
    if end and len(text) <= 10 and parsed.time() == datetime.min.time():
        parsed = parsed.replace(hour=23, minute=59, second=59, microsecond=999999)
    return parsed


# ---- 字典与规则 ----


@router.get("/dicts", summary="时效质控字典（触发源/MR_CLASS/监控项/枚举/写开关状态）")
def get_dicts(current_user: User = Depends(require_permission(PERM_VIEW)), db: Session = Depends(get_db)):
    return {
        **timeliness_department_options(db, current_user),
        "trigger_types": [
            {"code": code, "label": TRIGGER_TYPE_LABELS.get(code, code)}
            for code in TRIGGER_TYPES
        ],
        "mr_class": MR_CLASS_DICT,
        "monitor_items": {
            "source": "主设计文档 §10.1 生产实测编码子集（27 项）",
            "full_dictionary": "jhemr.jhinpat_mr_monitor_items（35 项，需只读授权后拉取）",
            "items": MONITOR_ITEM_DICT,
        },
        "completion_bases": list(COMPLETION_BASES),
        "action_modes": list(ACTION_MODES),
        "event_statuses": list(EVENT_STATUSES),
        "d8_no_lock_rule_codes": sorted(D8_NO_LOCK_RULE_CODES),
        "d8_note": D8_ONLY_LOCK_HINT,
        # T9 追加（前端 LOCK_EMR 判定与 approve 可用性提示）：后端 JHEMR 写开关现值
        "jhemr_write_enabled": _jhemr_write_enabled(),
        # 2026-11-14 P0：通知模式透传（D6 闸门现值，前端抽屉禁用状态对齐后端）。
        "notify_mode": _notify_mode(),
    }


@router.get("/rules", summary="规则列表（含当前版本）")
def list_rules(current_user: User = Depends(require_permission(PERM_VIEW)),
               db: Session = Depends(get_db)):
    rules = db.query(TLRule).order_by(TLRule.rule_code).all()
    return {
        "total": len(rules),
        "items": [_rule_dict(rule, _get_current_version(db, rule)) for rule in rules],
    }


@router.get("/rules/{rule_code}/versions", summary="规则版本历史（旧版本不覆盖）")
def list_rule_versions(rule_code: str,
                       current_user: User = Depends(require_permission(PERM_VIEW)),
                       db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_code)
    versions = (
        db.query(TLRuleVersion)
        .filter(TLRuleVersion.rule_id == rule.id)
        .order_by(TLRuleVersion.version_no.asc())
        .all()
    )
    return {"total": len(versions), "items": [_version_dict(v) for v in versions]}


@router.post("/rules/{rule_code}/versions", summary="保存新版本（不覆盖旧版本）")
def create_rule_version(rule_code: str, body: RuleVersionCreateRequest,
                        current_user: User = Depends(require_permission(PERM_EDIT)),
                        db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_code)  # 404 先于权限细节
    changes = body.changes_dict()
    created_by = str(changes.pop("created_by", None) or current_user.username or "api")

    # D8 强制防呆（§18.1/§18.6）：两规则严禁 LOCK_EMR，优先于其余校验。
    if str(changes.get("action_mode") or "").strip() == "LOCK_EMR" \
            and rule.rule_code in D8_NO_LOCK_RULE_CODES:
        raise HTTPException(status_code=400, detail=D8_ONLY_LOCK_HINT)
    # 其余规则的 LOCK_EMR：timeliness_admin + jhemr_write.enabled 双闸门。
    if str(changes.get("action_mode") or "").strip() == "LOCK_EMR":
        if not _user_has_permission(db, current_user, PERM_ADMIN):
            raise HTTPException(
                status_code=400,
                detail="LOCK_EMR requires timeliness_admin permission",
            )
        if not _jhemr_write_enabled():
            raise HTTPException(
                status_code=400,
                detail="LOCK_EMR requires timeliness.jhemr_write.enabled == true",
            )

    try:
        version = append_rule_version(db, rule.rule_code, created_by=created_by, **changes)
        db.commit()
    except RuleVersionError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "rule version saved",
        "rule_code": rule.rule_code,
        "version": _version_dict(version),
    }


@router.post("/rules/{rule_code}/toggle", summary="启停规则")
def toggle_rule(rule_code: str, body: RuleToggleRequest,
                current_user: User = Depends(require_permission(PERM_EDIT)),
                db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_code)
    rule.enabled = bool(body.enabled)
    rule.updated_at = datetime.now()
    db.commit()
    return MessageResponse(
        message="规则启停已更新",
        data={"rule_code": rule.rule_code, "enabled": bool(rule.enabled)},
    )


@router.post("/rules/{rule_code}/dry-run", summary="试算待保存版本（绝不写库）")
def dry_run_rule(rule_code: str, body: RuleDryRunRequest,
                 current_user: User = Depends(require_permission(PERM_VIEW)),
                 db: Session = Depends(get_db)):
    rule = _get_rule(db, rule_code)
    version = _get_current_version(db, rule)
    changes = body.changes_dict()

    # D8/LOCK_EMR 校验与保存口径一致（试算也不允许演练被禁用的锁定口径）。
    if str(changes.get("action_mode") or "").strip() == "LOCK_EMR" \
            and rule.rule_code in D8_NO_LOCK_RULE_CODES:
        raise HTTPException(status_code=400, detail=D8_ONLY_LOCK_HINT)

    # 候选版本 = 当前版本字段 + 本次改动（不落库，id 置空）。
    candidate: dict[str, Any] = {field: getattr(version, field) for field in VERSION_FIELDS}
    for key, value in changes.items():
        if key in ("trigger_filter_json", "target_json", "channels_json", "dept_scope_json") \
                and not isinstance(value, str):
            candidate[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            candidate[key] = value
    candidate["id"] = None

    data_source = "jhemr_readonly"
    source_note = ""
    try:
        snapshot = fetch_scan_snapshot(JhemrModuleReader(), now=datetime.now())
        data = {
            "inpatients": snapshot["inpatients"],
            "discharges": snapshot["discharges"],
            "deaths": snapshot.get("deaths") or [],
            "operations": snapshot["operations"],
            "consult_applies": snapshot["consult_applies"],
            "files": snapshot["files"],
            "approvals": snapshot["approvals"],
            "existing_events": [
                {"event_uid": uid, "status": status}
                for uid, status in db.query(TLEvent.event_uid, TLEvent.status)
                .filter(TLEvent.rule_code == rule.rule_code).all()
            ],
        }
    except (TimelinessNotConfigured, TimelinessPermissionMissing, ImportError) as exc:
        # 未配置只读源/缺权限/驱动不可用（本机 psycopg2 DLL 缺失等）：对空数据试算
        # （统计口径注明 data_source=unavailable；真实环境无此分支）。
        snapshot = {"patients_scanned": 0}
        data = {"existing_events": [
            {"event_uid": uid, "status": status}
            for uid, status in db.query(TLEvent.event_uid, TLEvent.status)
            .filter(TLEvent.rule_code == rule.rule_code).all()
        ]}
        data_source = "unavailable"
        source_note = str(exc)

    visibility = timeliness_visibility(db, current_user)
    results = [result for result in evaluate(candidate, now=datetime.now(), data=data, rule_code=rule.rule_code)
               if visibility.allows(result.dept_code)]
    existing_uids = {row["event_uid"] for row in data["existing_events"]}
    histogram: dict[str, int] = {}
    would_create = would_update = 0
    for result in results:
        histogram[result.status] = histogram.get(result.status, 0) + 1
        if result.event_uid in existing_uids:
            would_update += 1
        else:
            would_create += 1
    samples = [
        {
            "event_uid": r.event_uid,
            "patient_id": r.patient_id,
            "visit_id": r.visit_id,
            "dept_code": r.dept_code,
            "t0": r.t0.isoformat(),
            "deadline": r.deadline.isoformat() if r.deadline else None,
            "status": r.status,
        }
        for r in results[:DRY_RUN_SAMPLE_LIMIT]
    ]
    return {
        "rule_code": rule.rule_code,
        "base_version_no": version.version_no,
        "dry_run": True,
        "data_source": data_source,
        "source_note": source_note,
        "patients_scanned": snapshot.get("patients_scanned", 0) if visibility.codes is None else None,
        "stats": {
            "events": len(results),
            "would_create": would_create,
            "would_update": would_update,
            "status_histogram": histogram,
        },
        "samples": samples,
        "sample_truncated": len(results) > DRY_RUN_SAMPLE_LIMIT,
    }


# ---- 事件台账 ----


@router.get("/events", summary="事件台账（分页+过滤，受科室可见性约束）")
def list_events(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=500),
                dept: str | None = None, rule_code: str | None = None,
                status: str | None = None, patient_id: str | None = None,
                date_from: str | None = None, date_to: str | None = None,
                doctor: str | None = None,
                current_user: User = Depends(require_permission(PERM_VIEW)),
                db: Session = Depends(get_db)):
    query = db.query(TLEvent)
    query = timeliness_visibility(db, current_user).apply(query, TLEvent.dept_code)
    if rule_code:
        query = query.filter(TLEvent.rule_code == rule_code.strip())
    if status:
        text = status.strip()
        if text not in EVENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status: {text}")
        query = query.filter(TLEvent.status == text)
    if patient_id:
        query = query.filter(TLEvent.patient_id == patient_id.strip())
    doctor_ids = _doctor_filter_ids(db, doctor)
    if doctor is not None and str(doctor).strip():
        if not doctor_ids:
            return {"total": 0, "page": page, "limit": limit, "items": []}
        query = query.filter(TLEvent.responsible_doctor_id.in_(doctor_ids))
    dept_codes = _resolve_dept_filter(db, dept)
    if dept is not None and str(dept).strip():
        if not dept_codes:
            return {"total": 0, "page": page, "limit": limit, "items": []}
        query = query.filter(TLEvent.dept_code.in_(dept_codes))
    if date_from:
        query = query.filter(TLEvent.t0 >= _parse_day_bound(date_from))
    if date_to:
        query = query.filter(TLEvent.t0 <= _parse_day_bound(date_to, end=True))

    total = query.count()
    rows = (
        query.order_by(TLEvent.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    display = _display_maps(db)
    # 2026-11-15 P0-3：按当页 pairs 批量补患者姓名（V_QYBR TTL 缓存；保留既有
    # monkeypatch 契约）。WP04：临床元信息（住院号/性别/年龄/入院日期/入院诊断/护理级别）
    # 经 _patient_meta_map 批量取——同 pairs 二次调用命中进程内缓存，零额外查库。
    display["patient"] = _patient_name_map([(e.patient_id, str(e.visit_id)) for e in rows])
    meta = _patient_meta_map([(e.patient_id, str(e.visit_id)) for e in rows])
    # WP04：最近解锁申请摘要（同规则优先经规则当前版本监控码关联，退同患者最新）。
    rule_monitor = _rule_monitor_map(db)
    latest_approvals = _latest_approval_map(db, rows, rule_monitor)
    items: list[dict[str, Any]] = []
    for event in rows:
        item = _event_dict(event, display)
        info = meta.get(
            (str(event.patient_id or "").strip(), str(event.visit_id or "").strip())
        ) or {}
        item.update({
            # _event_dict 已置 inp_no=""，此处在 V_QYBR 命中时覆盖为真实住院号
            "inp_no": str(info.get("inp_no") or ""),
            "sex": str(info.get("sex") or ""),
            "age": str(info.get("age") or ""),
            "admission_date": info.get("admission_date"),
            "admission_diagnosis": str(info.get("admission_diagnosis") or ""),
            "nursing_level": str(info.get("nursing_level") or ""),
            "remaining_minutes": _remaining_minutes(event),
            "latest_approval": latest_approvals.get(
                (str(event.patient_id or "").strip(), str(event.visit_id or "").strip())
            ),
        })
        items.append(item)
    return {"total": total, "page": page, "limit": limit, "items": items}


@router.get("/events/{event_id}", summary="事件详情（含状态历史与动作日志）")
def get_event(event_id: int,
              current_user: User = Depends(require_permission(PERM_VIEW)),
              db: Session = Depends(get_db)):
    event = db.query(TLEvent).filter(TLEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    if not timeliness_visibility(db, current_user).allows(event.dept_code):
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    display = _display_maps(db)
    display["patient"] = _patient_name_map([(event.patient_id, str(event.visit_id))])
    histories = (
        db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id)
        .order_by(TLEventHistory.id.asc()).all()
    )
    actions = (
        db.query(TLActionLog).filter(TLActionLog.event_id == event.id)
        .order_by(TLActionLog.id.asc()).all()
    )
    return {
        **_event_dict(event, display),
        "history": [
            {
                "id": h.id, "from_status": h.from_status, "to_status": h.to_status,
                "reason": h.reason, "scan_run_id": h.scan_run_id,
                "created_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in histories
        ],
        "action_logs": [
            {
                "id": a.id, "action_type": a.action_type, "mode": a.mode,
                "target": a.target, "operator": a.operator, "result": a.result,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
    }


# ---- 事件人工豁免（2026-11-15 P0-2：在院未锁事件直接终态化，不再跳空审批表） ----

# 完成类/取消类终态不可豁免（EXEMPT 自身走幂等重入分支）。
_EVENT_EXEMPT_BLOCKED_STATUSES = ("COMPLETED_ON_TIME", "COMPLETED_LATE", "CANCELLED")


class EventExemptRequest(BaseModel):
    """POST /events/{id}/exempt：事件人工豁免（原因必填，终态化并写 History+ActionLog）。"""

    exempt_reason: str = Field(..., min_length=1, max_length=500,
                               description="豁免原因（必填，入审计）")


@router.post("/events/{event_id}/exempt",
             summary="事件人工豁免（需 timeliness_admin，原因必填；终态化不再预警/锁定）")
def exempt_event(event_id: int, body: EventExemptRequest,
                 current_user: User = Depends(require_permission(PERM_ADMIN)),
                 db: Session = Depends(get_db)):
    event = db.query(TLEvent).filter(TLEvent.id == event_id).first()
    if event is None or not timeliness_visibility(db, current_user, for_write=True).allows(event.dept_code):
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    reason = body.exempt_reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="exempt_reason is required")
    if event.status == "EXEMPT":
        # 幂等重入：已豁免事件直接返回现状，不重复写 History/ActionLog。
        return MessageResponse(
            message="event already exempted",
            data={"event_id": event.id, "status": "EXEMPT"},
        )
    if event.status in _EVENT_EXEMPT_BLOCKED_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"cannot exempt terminal event in status {event.status}",
        )
    # 状态机校验（PENDING/WARNING/OVERDUE/APPLYING/APPROVED → EXEMPT 均为合法出边；
    # 非法组合由 transition 抛 IllegalStatusTransition 直接失败，不落半截写）。
    from app.timeliness.engine.state import transition

    now = datetime.now()
    old_status = event.status
    new_status = transition(old_status, "EXEMPT", reason=f"manual_exempt event={event.id}")
    event.status = new_status
    event.updated_at = now
    db.add(TLEventHistory(
        event_id=event.id, from_status=old_status, to_status="EXEMPT",
        reason=f"manual_exempt: {reason[:180]}", scan_run_id=None, created_at=now,
    ))
    # ACTION_TYPES 常量为信息性清单（无 DB 枚举校验，T9 APPROVAL_EXEMPT 同先例），
    # EVENT_EXEMPT 直接写入；历史动作日志/时间线前端按 actionTypeLabel 中文化。
    db.add(TLActionLog(
        event_id=event.id, action_type="EVENT_EXEMPT", mode="EXECUTED",
        target=f"tl_event:{event.id}", operator=current_user.username or "api",
        created_at=now, result=reason[:200], params_json="{}",
    ))
    db.commit()
    return MessageResponse(
        message="event exempted",
        data={"event_id": event.id, "status": "EXEMPT", "exempt_reason": reason},
    )


# ---- 统计与导出 ----


# 月度统计行的全部字段（事件口径 8 列 + 2026-11-13 返工新增扣罚口径 4 列）。
_MONTHLY_EVENT_FIELDS = (
    "total", "completed_on_time", "completed_late",
    "overdue", "pending", "warning", "other",
)
_MONTHLY_APPROVAL_FIELDS = (
    "approval_count", "approved_unlock_count", "exempt_count", "penalty_amount_total",
)


def _resolve_period(
    month: str | None, date_from: str | None, date_to: str | None
) -> tuple[datetime, datetime, str, str]:
    """WP04：解析统计区间为 [start, end_exclusive) 与展示标签。

    - 优先 date_from/date_to（YYYY-MM-DD，闭区间；内部转 end+1 天排他上界）；
      两参必须同时提供；
    - 否则 month（YYYY-MM）；都没有 → 本月 1 日 ~ 下月 1 日；
    - 非法日期、倒序、跨度 > 366 天 → 400（英文 detail）；
    - 返回 (start, end_exclusive, label, month_key)：label 用于页头/文件名展示
      （month 模式即 YYYY-MM），month_key 保持旧 month 字段兼容（区间模式取
      起始日所在月份 YYYY-MM）。
    """
    from datetime import timedelta

    if date_from or date_to:
        if not (date_from and date_to):
            raise HTTPException(status_code=400,
                                detail="date_from and date_to must be provided together")
        try:
            start = datetime.strptime(str(date_from).strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"invalid date_from (expect YYYY-MM-DD): {date_from}") from exc
        try:
            end_day = datetime.strptime(str(date_to).strip(), "%Y-%m-%d")
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"invalid date_to (expect YYYY-MM-DD): {date_to}") from exc
        if start.date() > end_day.date():
            raise HTTPException(status_code=400, detail="date_from cannot be after date_to")
        if (end_day.date() - start.date()).days > 366:
            raise HTTPException(status_code=400, detail="date range exceeds 366 days")
        label = f"{start:%Y-%m-%d}~{end_day:%Y-%m-%d}"
        return start, end_day + timedelta(days=1), label, start.strftime("%Y-%m")
    month_text = str(month or "").strip() or datetime.now().strftime("%Y-%m")
    try:
        month_start = datetime.strptime(month_text, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid month (expect YYYY-MM): {month}") from exc
    if month_start.month == 12:
        month_end = datetime(month_start.year + 1, 1, 1)
    else:
        month_end = datetime(month_start.year, month_start.month + 1, 1)
    return month_start, month_end, month_text, month_text


def _period_rows(
    db: Session, current_user: User, start: datetime, end: datetime,
    dept: str | None = None, doctor_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """WP04：按科室×责任医生聚合任意区间 [start, end) 的事件与审批口径（SQL 聚合版）。

    与旧循环实现（test_wp04 中 legacy 对照）逐行一致：
    - 事件按 (dept_code, responsible_doctor_id) SUM(CASE status) 聚合（t0 落区间）；
    - 审批按 (dept_code, apply_user_id) 聚合（apply_date_time 落区间）；
      penalty_amount_total＝flag=='2' 且未豁免的 COALESCE(penalty_amount, 200) 合计；
    - Python 端按同键合并；新增计算字段 on_time_rate＝按时/(按时+超时完成)×100
      （1 位小数，分母 0 → 0.0）；行序保持 (dept_code, responsible_doctor_id)。
    """
    def _blank_row(dept_code: str, doctor_id: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "dept_code": dept_code, "responsible_doctor_id": doctor_id,
        }
        for name in _MONTHLY_EVENT_FIELDS:
            row[name] = 0
        for name in _MONTHLY_APPROVAL_FIELDS:
            row[name] = 0
        return row

    grouped: dict[tuple[str, str], dict[str, Any]] = {}

    event_query = db.query(TLEvent).filter(TLEvent.t0 >= start, TLEvent.t0 < end)
    visibility = timeliness_visibility(db, current_user)
    event_query = visibility.apply(event_query, TLEvent.dept_code)
    event_query = _filter_dept(event_query, TLEvent.dept_code, db, current_user, dept)
    if doctor_ids:
        event_query = event_query.filter(TLEvent.responsible_doctor_id.in_(doctor_ids))
    event_agg = event_query.with_entities(
        TLEvent.dept_code,
        TLEvent.responsible_doctor_id,
        func.count(TLEvent.id).label("total"),
        func.sum(case((TLEvent.status == "COMPLETED_ON_TIME", 1), else_=0)).label("on_time"),
        func.sum(case((TLEvent.status == "COMPLETED_LATE", 1), else_=0)).label("late"),
        func.sum(case((TLEvent.status == "OVERDUE", 1), else_=0)).label("overdue"),
        func.sum(case((TLEvent.status == "PENDING", 1), else_=0)).label("pending"),
        func.sum(case((TLEvent.status == "WARNING", 1), else_=0)).label("warning"),
    ).group_by(TLEvent.dept_code, TLEvent.responsible_doctor_id).all()
    for dept_code, doctor_id, total, on_time, late, overdue, pending, warning in event_agg:
        key = (dept_code or "", doctor_id or "")
        row = grouped.setdefault(key, _blank_row(*key))
        row["total"] = int(total or 0)
        row["completed_on_time"] = int(on_time or 0)
        row["completed_late"] = int(late or 0)
        row["overdue"] = int(overdue or 0)
        row["pending"] = int(pending or 0)
        row["warning"] = int(warning or 0)
        # other = 其余状态（EXEMPT/APPLYING/APPROVED/CANCELLED…）之和
        row["other"] = row["total"] - (
            row["completed_on_time"] + row["completed_late"]
            + row["overdue"] + row["pending"] + row["warning"]
        )

    approval_query = db.query(TLApproval).filter(
        TLApproval.apply_date_time >= start, TLApproval.apply_date_time < end
    )
    approval_query = visibility.apply(approval_query, TLApproval.dept_code)
    approval_query = _filter_dept(approval_query, TLApproval.dept_code, db, current_user, dept)
    if doctor_ids:
        approval_query = approval_query.filter(TLApproval.apply_user_id.in_(doctor_ids))
    approval_agg = approval_query.with_entities(
        TLApproval.dept_code,
        TLApproval.apply_user_id,
        func.count(TLApproval.id).label("approval_count"),
        func.sum(case((TLApproval.flag == "2", 1), else_=0)).label("approved_unlock"),
        func.sum(case((TLApproval.penalty_exempt == True, 1), else_=0)).label("exempted"),  # noqa: E712
        func.sum(case(
            ((TLApproval.flag == "2") & (TLApproval.penalty_exempt != True),  # noqa: E712
             func.coalesce(TLApproval.penalty_amount, 200)),
            else_=0,
        )).label("penalty_total"),
    ).group_by(TLApproval.dept_code, TLApproval.apply_user_id).all()
    for dept_code, apply_user_id, count, approved_unlock, exempted, penalty_total in approval_agg:
        key = (dept_code or "", apply_user_id or "")
        row = grouped.setdefault(key, _blank_row(*key))
        row["approval_count"] = int(count or 0)
        row["approved_unlock_count"] = int(approved_unlock or 0)
        row["exempt_count"] = int(exempted or 0)
        row["penalty_amount_total"] = int(penalty_total or 0)

    for row in grouped.values():
        denom = row["completed_on_time"] + row["completed_late"]
        row["on_time_rate"] = (
            round(row["completed_on_time"] / denom * 100, 1) if denom else 0.0
        )
    return sorted(grouped.values(), key=lambda r: (r["dept_code"], r["responsible_doctor_id"]))


def _monthly_rows(db: Session, current_user: User, month: str, dept: str | None = None) -> list[dict[str, Any]]:
    """按科室×责任医生聚合当月事件 + 当月超时申请/扣罚台账（2026-11-13 返工）。

    事件口径：t0 落在月份内，按 (dept_code, responsible_doctor_id) 聚合，受可见性约束；
    扣罚口径：tl_approval.apply_date_time 落在月份内，按 (dept_code, apply_user_id)
    聚合（与事件行同键合并；无对应事件行的医生单独成行），受同套可见性约束：
    - approval_count＝超时申请总次数；
    - approved_unlock_count＝flag=='2' 解锁通过次数；
    - exempt_count＝penalty_exempt==True 豁免次数；
    - penalty_amount_total＝flag=='2' 且未豁免的 COALESCE(penalty_amount, 200) 合计（元）。

    WP04：实现改为 _period_rows 的 SQL 聚合薄包装（口径与旧循环版逐行一致，
    见 test_wp04 新旧实现对照用例）；行内新增计算字段 on_time_rate。
    """
    month_start, month_end, _label, _key = _resolve_period(month, None, None)
    return _period_rows(db, current_user, month_start, month_end, dept)


@router.get("/stats/analytics", summary="时效统计分析（科室/医生锁定排名、规则分布、每日趋势；WP03）")
def stats_analytics(
    date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD（默认本月 1 日）"),
    date_to: str | None = Query(None, description="结束日期 YYYY-MM-DD（默认今天，闭区间含当日）"),
    dept: str | None = Query(None, description="科室编码或名称（可选下钻）"),
    top_n: int = Query(15, ge=5, le=50, description="科室排名返回条数"),
    current_user: User = Depends(require_permission(PERM_VIEW)),
    db: Session = Depends(get_db),
):
    """统计分析聚合（口径与 stats/monthly 一致；数据范围隔离；全 SQL 聚合）。"""
    from datetime import date as _date, timedelta as _timedelta
    from app.timeliness.stats_service import compute_timeliness_analytics

    today = datetime.now().date()
    if date_from:
        try:
            parsed_from = datetime.strptime(str(date_from).strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"invalid date_from (expect YYYY-MM-DD): {date_from}") from exc
    else:
        parsed_from = today.replace(day=1)
    if date_to:
        try:
            parsed_to = datetime.strptime(str(date_to).strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(status_code=400,
                                detail=f"invalid date_to (expect YYYY-MM-DD): {date_to}") from exc
    else:
        parsed_to = today
    if parsed_from > parsed_to:
        raise HTTPException(status_code=400, detail="date_from cannot be after date_to")
    if (parsed_to - parsed_from).days > 366:
        raise HTTPException(status_code=400, detail="date range exceeds 366 days")

    return compute_timeliness_analytics(
        db, current_user=current_user,
        date_from=parsed_from, date_to=parsed_to,
        dept_code=str(dept).strip() if dept and str(dept).strip() else None,
        top_n=top_n,
    )


@router.get("/stats/monthly", summary="科室/个人考核统计（月度或任意日期区间；事件口径+超时申请/扣罚口径）")
def stats_monthly(month: str | None = Query(None, description="月份 YYYY-MM（默认当月；与 date_from/date_to 二选一，区间优先）"),
                  date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD（WP04：与 date_to 同时提供时优先于 month）"),
                  date_to: str | None = Query(None, description="结束日期 YYYY-MM-DD（闭区间含当日）"),
                  page: int | None = Query(None, ge=1, description="页码（不传返回全量，结构与旧版一致）"),
                  limit: int = Query(20, ge=1, le=200, description="每页行数（传 page 时生效，≤200）"),
                  doctor: str | None = Query(None, description="责任医生（工号精确或姓名模糊）"),
                  current_user: User = Depends(require_permission(PERM_VIEW)),
                  db: Session = Depends(get_db), dept: str | None = None):
    start, end, label, month_key = _resolve_period(month, date_from, date_to)
    # WP04：医生筛选（工号精确 ∪ 姓名模糊→工号集合；解析失败视为无匹配行而非 400）。
    doctor_ids = _doctor_filter_ids(db, doctor) if doctor and str(doctor).strip() else []
    if doctor and str(doctor).strip() and not doctor_ids:
        rows: list[dict[str, Any]] = []
    else:
        rows = _period_rows(db, current_user, start, end, dept, doctor_ids)
    # 2026-11-14 P0：聚合行补中文展示（科室名/医生姓名，CSV 导出口径不变）。
    display = _display_maps(db)
    for row in rows:
        row["dept_name"] = (display["dept"] or {}).get(row.get("dept_code") or "", "")
        row["responsible_doctor_name"] = (display["staff"] or {}).get(
            row.get("responsible_doctor_id") or "", "")
    # WP04：totals 始终为全量合计（分页切片不影响）。
    totals = {
        "total": sum(r["total"] for r in rows),
        "completed_on_time": sum(r["completed_on_time"] for r in rows),
        "completed_late": sum(r["completed_late"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "pending": sum(r["pending"] for r in rows),
        "warning": sum(r["warning"] for r in rows),
        "other": sum(r["other"] for r in rows),
        # 2026-11-13 返工：当月超时申请/扣罚口径（tl_approval，向后兼容新增字段）。
        "approval_count": sum(r["approval_count"] for r in rows),
        "approved_unlock_count": sum(r["approved_unlock_count"] for r in rows),
        "exempt_count": sum(r["exempt_count"] for r in rows),
        "penalty_amount_total": sum(r["penalty_amount_total"] for r in rows),
    }
    from datetime import timedelta

    response: dict[str, Any] = {
        # month 键保持旧契约（区间模式回退起始日所在月份 YYYY-MM）；label 供页头展示。
        "month": month_key,
        "period_label": label,
        "totals": totals,
        "rows": rows,
        "date_from": start.strftime("%Y-%m-%d"),
        "date_to": (end - timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    if page is not None:
        response["rows"] = rows[(page - 1) * limit: page * limit]
        response["total_rows"] = len(rows)
        response["page"] = page
        response["limit"] = limit
    return response


@router.get("/export/monthly", summary="导出考核统计（CSV 默认；format=xlsx 为真 Excel，写导出审计）")
def export_monthly(month: str | None = Query(None, description="月份 YYYY-MM（与 date_from/date_to 二选一，区间优先）"),
                   date_from: str | None = Query(None, description="起始日期 YYYY-MM-DD（WP04）"),
                   date_to: str | None = Query(None, description="结束日期 YYYY-MM-DD（闭区间含当日）"),
                   doctor: str | None = Query(None, description="责任医生（工号精确或姓名模糊）"),
                   export_format: str = Query("csv", alias="format", pattern="^(csv|xlsx)$",
                                              description="导出格式：csv（默认，兼容旧调用）或 xlsx"),
                   request: Request = None,
                   current_user: User = Depends(require_permission(PERM_EXPORT)),
                   db: Session = Depends(get_db), dept: str | None = None):
    from datetime import timedelta
    from urllib.parse import quote

    start, end, label, month_key = _resolve_period(month, date_from, date_to)
    end_day = (end - timedelta(days=1)).strftime("%Y-%m-%d")
    doctor_ids = _doctor_filter_ids(db, doctor) if doctor and str(doctor).strip() else []
    if doctor and str(doctor).strip() and not doctor_ids:
        rows: list[dict[str, Any]] = []
    else:
        rows = _period_rows(db, current_user, start, end, dept, doctor_ids)
    display = _display_maps(db)
    for row in rows:
        row["dept_name"] = (display["dept"] or {}).get(row.get("dept_code") or "", "")
        row["responsible_doctor_name"] = (display["staff"] or {}).get(
            row.get("responsible_doctor_id") or "", "")
    totals = {
        "total": sum(r["total"] for r in rows),
        "completed_on_time": sum(r["completed_on_time"] for r in rows),
        "completed_late": sum(r["completed_late"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "pending": sum(r["pending"] for r in rows),
        "warning": sum(r["warning"] for r in rows),
        "other": sum(r["other"] for r in rows),
        "approval_count": sum(r["approval_count"] for r in rows),
        "approved_unlock_count": sum(r["approved_unlock_count"] for r in rows),
        "exempt_count": sum(r["exempt_count"] for r in rows),
        "penalty_amount_total": sum(r["penalty_amount_total"] for r in rows),
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_stem = "".join(ch for ch in label if ch.isdigit()) or month_key.replace("-", "")
    filter_criteria = {
        "date_from": start.strftime("%Y-%m-%d"),
        "date_to": end_day,
        "dept": dept,
        "doctor": doctor,
        "rows": len(rows),
    }

    if export_format == "xlsx":
        # WP04：真二进制 Excel（openpyxl），固定表头 + 冻结前 2 行与左侧科室/医生列。
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        headers = [
            "科室名称", "科室编码", "责任医生", "工号", "事件总数", "按时完成",
            "超时完成", "超时未完成", "预警中", "未到期", "按时率",
            "锁定(超时申请)次数", "解锁通过次数", "豁免次数", "应扣金额(元)",
        ]
        wb = Workbook()
        ws = wb.active
        ws.title = "时效考核统计"
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        title_cell = ws.cell(
            row=1, column=1,
            value=f"病历时效考核统计表（{start.strftime('%Y-%m-%d')} 至 {end_day}）",
        )
        title_cell.font = Font(size=14, bold=True)
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        thin = Side(style="thin")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        header_fill = PatternFill("solid", fgColor="DBEAFE")
        for col, name in enumerate(headers, 1):
            cell = ws.cell(row=2, column=col, value=name)
            cell.font = Font(bold=True)
            cell.fill = header_fill
            cell.border = border
            ws.column_dimensions[get_column_letter(col)].width = max(
                12, min(28, int(len(name) * 2.2)),
            )
        for idx, row in enumerate(rows):
            values = [
                row.get("dept_name") or row.get("dept_code") or "",
                row.get("dept_code") or "",
                row.get("responsible_doctor_name") or "",
                row.get("responsible_doctor_id") or "",
                row["total"], row["completed_on_time"], row["completed_late"],
                row["overdue"], row["warning"], row["pending"],
                round((row.get("on_time_rate") or 0) / 100.0, 4),
                row["approval_count"], row["approved_unlock_count"],
                row["exempt_count"], row["penalty_amount_total"],
            ]
            excel_row = idx + 3
            for col, value in enumerate(values, 1):
                cell = ws.cell(row=excel_row, column=col, value=value)
                cell.border = border
                if col == 11:  # 按时率：小数 + 百分比格式
                    cell.number_format = "0.0%"
        sum_row = len(rows) + 3
        sum_rate_denom = totals["completed_on_time"] + totals["completed_late"]
        sum_rate = (
            round(totals["completed_on_time"] / sum_rate_denom, 4) if sum_rate_denom else 0.0
        )
        sum_values = [
            "合计", "", "", "",
            totals["total"], totals["completed_on_time"], totals["completed_late"],
            totals["overdue"], totals["warning"], totals["pending"], sum_rate,
            totals["approval_count"], totals["approved_unlock_count"],
            totals["exempt_count"], totals["penalty_amount_total"],
        ]
        for col, value in enumerate(sum_values, 1):
            cell = ws.cell(row=sum_row, column=col, value=value)
            cell.font = Font(bold=True)
            cell.border = border
            if col == 11:
                cell.number_format = "0.0%"
        ws.freeze_panes = "E3"
        buf = io.BytesIO()
        wb.save(buf)
        filename = f"时效考核统计_{file_stem}_{stamp}.xlsx"
        audit_format = "xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        payload: Any = buf.getvalue()
        headers_out = {
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        }
    else:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["月份", "科室编码", "责任医生", "事件总数", "按时完成", "超时完成",
                         "超时未完成", "未到期", "预警中", "其他状态",
                         "超时申请次数", "解锁通过次数", "豁免次数", "应扣金额(元)"])
        for row in rows:
            writer.writerow([label, row["dept_code"], row["responsible_doctor_id"],
                             row["total"], row["completed_on_time"], row["completed_late"],
                             row["overdue"], row["pending"], row["warning"], row["other"],
                             row["approval_count"], row["approved_unlock_count"],
                             row["exempt_count"], row["penalty_amount_total"]])
        filename = f"timeliness_monthly_{file_stem}_{stamp}.csv"
        audit_format = "csv"
        media_type = "text/csv"
        payload = output.getvalue()
        headers_out = {"Content-Disposition": f"attachment; filename={filename}"}

    # AGENTS.md 红线：新导出端点必须调用 record_export_audit()
    try:
        record_export_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username or "",
            export_type="timeliness_monthly",
            export_format=audit_format,
            filter_criteria=filter_criteria,
            record_count=len(rows),
            status="success",
            request=request,
        )
    except Exception:
        logger.exception("时效月度导出审计记录失败")

    return StreamingResponse([payload], media_type=media_type, headers=headers_out)


# ---- 扫描记录（admin） ----


@router.get("/scan-runs", summary="影子扫描运行记录（admin）")
def list_scan_runs(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200),
                   current_user: User = Depends(require_permission(PERM_ADMIN)),
                   db: Session = Depends(get_db)):
    query = db.query(TLScanRun)
    total = query.count()
    runs = (
        query.order_by(TLScanRun.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            {
                "id": r.id,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "patients_scanned": r.patients_scanned,
                "events_created": r.events_created,
                "events_updated": r.events_updated,
                "error_text": r.error_text,
            }
            for r in runs
        ],
    }


# ---- 审批同步与扣罚台账（T9） ----


class ApprovalExemptRequest(BaseModel):
    """POST /approvals/{id}/exempt：豁免/取消豁免扣罚（原因必填，留痕）。

    2026-11-13 返工：``cancel=true`` 取消豁免（清除 penalty_exempt/exempt_reason，
    留 APPROVAL_EXEMPT_CANCEL 审计）；缺省 false=设置豁免。
    """

    exempt_reason: str = Field(..., min_length=1, description="豁免/取消豁免原因（必填，入审计）")
    cancel: bool = Field(default=False, description="true=取消豁免；false=设置豁免")


class ApprovalApproveRequest(BaseModel):
    """POST /approvals/{id}/approve：审批通过回写（默认演练，显式 dry_run=false 才真实执行）。"""

    dry_run: bool = Field(default=True, description="true=演练留痕不连库；false=真实回写 JHEMR")


def _approval_dict(
    approval: TLApproval, display: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    item = {
        "id": approval.id,
        "patient_id": approval.patient_id,
        "visit_id": approval.visit_id,
        "monitor_code": approval.monitor_code,
        "apply_date_time": approval.apply_date_time.isoformat() if approval.apply_date_time else None,
        "type": approval.type,
        "flag": approval.flag,
        "apply_user_id": approval.apply_user_id,
        "apply_reason": approval.apply_reason,
        "approve_user_id": approval.approve_user_id,
        "approve_date_time": approval.approve_date_time.isoformat() if approval.approve_date_time else None,
        "approve_channel": approval.approve_channel,
        "dept_code": approval.dept_code,
        "penalty_amount": approval.penalty_amount,
        "penalty_exempt": bool(approval.penalty_exempt),
        "exempt_reason": approval.exempt_reason,
        "synced_at": approval.synced_at.isoformat() if approval.synced_at else None,
    }
    if display is not None:
        # 2026-11-14 P0：审批台账中文化（申请人姓名/科室名）。
        item["apply_user_name"] = (display["staff"] or {}).get(approval.apply_user_id or "", "")
        # WP04：审批人姓名（STAFF_DICT 同款映射，未审批/未知为空串）。
        item["approve_user_name"] = (display["staff"] or {}).get(
            approval.approve_user_id or "", "")
        item["dept_name"] = (display["dept"] or {}).get(approval.dept_code or "", "")
        # 2026-11-15：监控码→规则中文名（审批台账不存 rule_code，经当前版本反查）；
        # 患者姓名经 V_QYBR TTL 缓存按当页 pairs 补齐（查不到回退 patient_id）。
        item["rule_name"] = (display.get("monitor_rule") or {}).get(
            str(approval.monitor_code or "").strip(), "")
        item["patient_name"] = (display.get("patient") or {}).get(
            (approval.patient_id or "", str(approval.visit_id or "")), "")
        item["inp_no"] = ""
    return item


def _approval_status_counts(query) -> dict[str, int]:
    """WP04：审批状态汇总（同样筛选但不含 flag 下的 1 条 SUM(CASE) 聚合）。

    pending=flag=='1'（锁定待审批）；approved=flag=='2'（已解锁）；
    exempted=penalty_exempt==True（豁免，可与已解锁重叠）。
    """
    row = (
        query.with_entities(
            func.count(TLApproval.id).label("total"),
            func.sum(case((TLApproval.flag == "1", 1), else_=0)).label("pending"),
            func.sum(case((TLApproval.flag == "2", 1), else_=0)).label("approved"),
            func.sum(case((TLApproval.penalty_exempt == True, 1), else_=0)).label("exempted"),  # noqa: E712
        ).first()
    )
    if row is None:
        return {"total": 0, "pending": 0, "approved": 0, "exempted": 0}
    return {
        "total": int(row.total or 0),
        "pending": int(row.pending or 0),
        "approved": int(row.approved or 0),
        "exempted": int(row.exempted or 0),
    }


def _get_approval(db: Session, approval_id: int, current_user: User) -> TLApproval:
    approval = db.query(TLApproval).filter(TLApproval.id == approval_id).first()
    if approval is None or not timeliness_visibility(db, current_user, for_write=True).allows(approval.dept_code):
        raise HTTPException(status_code=404, detail=f"approval not found: {approval_id}")
    return approval


@router.get("/approvals", summary="超时审批/扣罚台账（分页+过滤，支持科室/监控码/状态/申请日期/申请人）")
def list_approvals(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=500),
                   patient_id: str | None = None, monitor_code: str | None = None,
                   flag: str | None = None, dept: str | None = None,
                   apply_date_from: str | None = None, apply_date_to: str | None = None,
                   applicant: str | None = None,
                   current_user: User = Depends(require_permission(PERM_VIEW)),
                   db: Session = Depends(get_db)):
    query = timeliness_visibility(db, current_user).apply(db.query(TLApproval), TLApproval.dept_code)
    if patient_id:
        query = query.filter(TLApproval.patient_id == patient_id.strip())
    if monitor_code:
        query = query.filter(TLApproval.monitor_code == monitor_code.strip())
    if applicant is not None and str(applicant).strip():
        # WP04：申请人筛选（工号精确或姓名模糊→工号集合，解析口径与责任医生一致）。
        applicant_ids = _doctor_filter_ids(db, applicant)
        if not applicant_ids:
            return {"total": 0, "page": page, "limit": limit, "status_counts":
                    {"total": 0, "pending": 0, "approved": 0, "exempted": 0},
                    "items": []}
        query = query.filter(TLApproval.apply_user_id.in_(applicant_ids))
    if apply_date_from:
        # WP04：申请日期闭区间（纯日期 date_to 含当日全天，口径同事件列表）。
        query = query.filter(TLApproval.apply_date_time >= _parse_day_bound(apply_date_from))
    if apply_date_to:
        query = query.filter(TLApproval.apply_date_time <= _parse_day_bound(apply_date_to, end=True))
    if dept is not None and str(dept).strip():
        # 2026-11-13 返工：科室筛选（编码或名称，解析口径与事件列表一致）。
        dept_codes = _resolve_dept_filter(db, dept)
        if not dept_codes:
            return {"total": 0, "page": page, "limit": limit, "status_counts":
                    {"total": 0, "pending": 0, "approved": 0, "exempted": 0},
                    "items": []}
        query = query.filter(TLApproval.dept_code.in_(dept_codes))
    # WP04：状态汇总卡（同样筛选但不含 flag，换页/切状态都不变）。
    status_counts = _approval_status_counts(query)
    if flag:
        query = query.filter(TLApproval.flag == flag.strip())
    total = query.count()
    rows = (
        query.order_by(TLApproval.apply_date_time.desc(), TLApproval.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    display = _display_maps(db)
    # 2026-11-15 P0-3：按当页 pairs 批量补患者姓名（保留既有 monkeypatch 契约）。
    # WP04：临床元信息（住院号/入院日期/入院诊断）经 _patient_meta_map（同 pairs
    # 二次调用命中进程内缓存，零额外查库）。
    display["patient"] = _patient_name_map([(a.patient_id, str(a.visit_id)) for a in rows])
    meta = _patient_meta_map([(a.patient_id, str(a.visit_id)) for a in rows])
    # WP04：同患者同规则最近 TLEvent 的截止/超时分钟（监控码经当前版本反查规则）。
    rule_monitor = _rule_monitor_map(db)
    event_links = _event_overdue_map(db, rows, rule_monitor)
    items: list[dict[str, Any]] = []
    for approval in rows:
        item = _approval_dict(approval, display)
        info = meta.get(
            (str(approval.patient_id or "").strip(), str(approval.visit_id or "").strip())
        ) or {}
        link = event_links.get(approval.id) or {}
        item.update({
            "inp_no": str(info.get("inp_no") or ""),
            "admission_date": info.get("admission_date"),
            "admission_diagnosis": str(info.get("admission_diagnosis") or ""),
            "event_deadline": link.get("event_deadline"),
            "event_overdue_minutes": link.get("event_overdue_minutes"),
        })
        items.append(item)
    return {"total": total, "page": page, "limit": limit,
            "status_counts": status_counts, "items": items}


@router.post("/approvals/{approval_id}/exempt", summary="豁免/取消豁免扣罚（需 timeliness_admin，原因必填，写审计）")
def exempt_approval(approval_id: int, body: ApprovalExemptRequest,
                    current_user: User = Depends(require_permission(PERM_ADMIN)),
                    db: Session = Depends(get_db)):
    approval = _get_approval(db, approval_id, current_user)
    reason = body.exempt_reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="exempt_reason is required")
    if bool(body.cancel):
        # 取消豁免：未豁免时幂等返回；取消后清除原因并留 APPROVAL_EXEMPT_CANCEL 审计。
        if not approval.penalty_exempt:
            return MessageResponse(
                message="approval not exempted",
                data={"approval_id": approval.id, "penalty_exempt": False},
            )
        approval.penalty_exempt = False
        approval.exempt_reason = None
        db.add(TLActionLog(
            action_type="APPROVAL_EXEMPT_CANCEL", mode="EXECUTED",
            target=f"tl_approval:{approval.id}", operator=current_user.username or "api",
            created_at=datetime.now(), result=f"cancel: {reason[:180]}",
            params_json="{}",
        ))
        db.commit()
        return MessageResponse(
            message="penalty exemption cancelled",
            data={"approval_id": approval.id, "penalty_exempt": False,
                  "cancel_reason": reason},
        )
    if approval.penalty_exempt:
        return MessageResponse(
            message="approval already exempted",
            data={"approval_id": approval.id, "exempt_reason": approval.exempt_reason},
        )
    approval.penalty_exempt = True
    approval.exempt_reason = reason
    db.add(TLActionLog(
        action_type="APPROVAL_EXEMPT", mode="EXECUTED",
        target=f"tl_approval:{approval.id}", operator=current_user.username or "api",
        created_at=datetime.now(), result=reason[:200],
        params_json="{}",
    ))
    db.commit()
    return MessageResponse(
        message="penalty exempted",
        data={"approval_id": approval.id, "penalty_amount": approval.penalty_amount,
              "exempt_reason": reason},
    )


@router.post("/approvals/{approval_id}/approve", summary="审批通过回写 JHEMR（写开关关闭 409；默认演练）")
def approve_approval(approval_id: int, body: ApprovalApproveRequest,
                     current_user: User = Depends(require_permission(PERM_ADMIN)),
                     db: Session = Depends(get_db)):
    approval = _get_approval(db, approval_id, current_user)
    operator = current_user.username or "api"

    # 幂等：JHEMR 侧已审批通过（flag=2）则不再回写。
    if str(approval.flag or "").strip() == "2":
        return MessageResponse(
            message="approval already approved (flag=2)",
            data={"approval_id": approval.id, "flag": approval.flag},
        )

    # 写开关关闭 → 409（不连库、不构造 writer），留 BLOCKED 审计后提示走 JHEMR 原生画布。
    if not _jhemr_write_enabled():
        db.add(TLActionLog(
            action_type="JHEMR_APPROVE", mode="BLOCKED",
            target=f"tl_approval:{approval.id}", operator=operator,
            created_at=datetime.now(),
            result="blocked: timeliness.jhemr_write.enabled is not true",
            params_json="{}",
        ))
        db.commit()
        raise HTTPException(
            status_code=409,
            detail=(
                "JHEMR write switch is off (timeliness.jhemr_write.enabled=false); "
                "approve this limit log in JHEMR native [超时审批] canvas instead"
            ),
        )

    writer = JhemrWriter(db, load_config())
    try:
        outcome = writer.approve_limit_log(
            patient_id=approval.patient_id,
            visit_id=approval.visit_id,
            dept_code=approval.dept_code,       # 闸门 2 白名单依据；同步时自源行 dept_code 映射
            monitor_code=approval.monitor_code,
            apply_date_time=approval.apply_date_time,
            limit_type=approval.type,
            hospital_no=approval.hospital_no,   # 2026-11-12 用户裁定+T1 两份实证：jhmr_monitor_limit_log
            approve_user_id=operator,           # 共 14 列且 hospital_no NOT NULL（原"10 列"判断有误，见 T9 报告裁定节）
            dry_run=bool(body.dry_run),
            operator=operator,
            event_id=None,
        )
    except JhemrWriteRowCountError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JhemrWriteError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mode = str(outcome.get("mode") or "")
    if mode == "EXECUTED" and outcome.get("executed"):
        driven = mark_approved_locally(
            db, approval, approve_user_id=operator,
            approve_date_time=datetime.now(),
        )
        return MessageResponse(
            message="approved and written back to JHEMR",
            data={"approval_id": approval.id, "mode": mode,
                  "action_log_id": outcome.get("action_log_id"),
                  "events_updated": driven["updated"],
                  "events_skipped": driven["skipped"]},
        )
    # DRY_RUN / BLOCKED（writer 已留痕）：如实回传，不改动本地台账。
    return MessageResponse(
        message="approval write attempted (not executed)" if mode == "BLOCKED"
        else "dry-run recorded (nothing written)",
        data={"approval_id": approval.id, "mode": mode,
              "action_log_id": outcome.get("action_log_id"),
              "reason": outcome.get("reason") or ""},
    )


@router.post("/approvals/sync", summary="只读同步 jhmr_monitor_limit_log → tl_approval 并驱动事件（幂等）")
def sync_approvals_endpoint(since: str | None = Query(None, description="同步窗口起点 ISO 时间；缺省=只读层全量窗口"),
                            current_user: User = Depends(require_permission(PERM_ADMIN)),
                            db: Session = Depends(get_db)):
    """同步为只读操作（数据源=T1 只读访问层），结果幂等可重跑；需要 timeliness_admin。

    since 缺省时由只读层决定取数窗口；本机未配置只读源时返回 503（不伪造数据）。
    """
    if timeliness_visibility(db, current_user, for_write=True).codes is not None:
        raise HTTPException(403, "Hospital-wide operational scope required")
    try:
        stats = sync_approvals(db, load_config(), since=since)
    except (TimelinessNotConfigured, TimelinessPermissionMissing) as exc:
        raise HTTPException(status_code=503, detail=f"readonly source unavailable: {exc}") from exc
    return MessageResponse(message="approval sync finished", data=dict(stats))
