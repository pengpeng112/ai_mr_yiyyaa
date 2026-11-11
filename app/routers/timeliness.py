"""病历时效质控 API 路由（T5；主设计文档 §15 T5 / §10.1 字典 / §18.1 D8）。

- 前缀 /api/timeliness（app/main.py 只追加一次 include_router）；
- 权限：timeliness_view / timeliness_rule_edit / timeliness_approve（T9 使用）/
  timeliness_export / timeliness_admin（§15.2 统一命名，种子仅 admin）；
- D8 强制防呆（§18.1/§18.6）：幽灵监控行原因查清前，ADM_REC(JH04.02.001) 与
  CHIEF_FIRST_ROUND(JH04.02.008) 严禁设为 LOCK_EMR——即使 jhemr_write.enabled=true
  且操作人具备 timeliness_admin 也必须 400；仅 FIRST_COURSE(002) 可开锁定；
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
from sqlalchemy.orm import Session
from sqlalchemy.sql.expression import false as sql_false

from app.config import load_config
from app.database import get_db
from app.models import Department, Role, User
from app.permissions import get_user_permissions, require_permission
from app.services.dept_visibility import visible_dept_names
from app.services.export_audit_service import record_export_audit
from app.timeliness.config import TimelinessNotConfigured, TimelinessPermissionMissing
from app.timeliness.engine import evaluate
from app.timeliness.engine.triggers import TRIGGER_TYPES
from app.timeliness.models import (
    ACTION_MODES,
    COMPLETION_BASES,
    EVENT_STATUSES,
    TLActionLog,
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

# D8（§18.1/§18.4）：幽灵行原因查清前仅 FIRST_COURSE(002) 允许 LOCK_EMR。
D8_ONLY_LOCK_HINT = (
    "D8 restriction: LOCK_EMR is not allowed for ADM_REC(JH04.02.001) or "
    "CHIEF_FIRST_ROUND(JH04.02.008) until ghost monitor rows are explained; "
    "only FIRST_COURSE(JH04.02.002) may enable locking"
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
    {"code": "JH04.02.011", "label": "出院记录", "limit": "24h", "jhemr_generated": False},
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


def _event_dict(event: TLEvent) -> dict[str, Any]:
    return {
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


def _resolve_dept_filter(db: Session, dept_param: str | None) -> list[str]:
    """把科室过滤参数（编码或名称）解析为科室编码列表。"""
    text = str(dept_param or "").strip()
    if not text:
        return []
    rows = db.query(Department).filter(
        (Department.code == text) | (Department.name == text)
    ).all()
    return [row.code or row.name for row in rows if (row.code or row.name)]


def _apply_visibility(query, db: Session, current_user: User):
    """admin 全院；普通用户按可见科室（名称→编码）过滤；无可见科室→空集。"""
    names = visible_dept_names(db, current_user)
    if names is None:
        return query
    codes = [
        row.code or row.name
        for row in db.query(Department).filter(Department.name.in_(names)).all()
        if (row.code or row.name)
    ]
    if not codes:
        return query.filter(sql_false())
    return query.filter(TLEvent.dept_code.in_(codes))


def _event_can_see(db: Session, current_user: User, event: TLEvent) -> bool:
    names = visible_dept_names(db, current_user)
    if names is None:
        return True
    codes = {
        row.code or row.name
        for row in db.query(Department).filter(Department.name.in_(names)).all()
        if (row.code or row.name)
    }
    return (event.dept_code or "") in codes


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


@router.get("/dicts", summary="时效质控字典（触发源/MR_CLASS/监控项/枚举）")
def get_dicts(current_user: User = Depends(require_permission(PERM_VIEW))):
    return {
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

    results = evaluate(candidate, now=datetime.now(), data=data, rule_code=rule.rule_code)
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
        "patients_scanned": snapshot.get("patients_scanned", 0),
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
                current_user: User = Depends(require_permission(PERM_VIEW)),
                db: Session = Depends(get_db)):
    query = db.query(TLEvent)
    query = _apply_visibility(query, db, current_user)
    if rule_code:
        query = query.filter(TLEvent.rule_code == rule_code.strip())
    if status:
        text = status.strip()
        if text not in EVENT_STATUSES:
            raise HTTPException(status_code=400, detail=f"invalid status: {text}")
        query = query.filter(TLEvent.status == text)
    if patient_id:
        query = query.filter(TLEvent.patient_id == patient_id.strip())
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
    return {"total": total, "page": page, "limit": limit,
            "items": [_event_dict(e) for e in rows]}


@router.get("/events/{event_id}", summary="事件详情（含状态历史与动作日志）")
def get_event(event_id: int,
              current_user: User = Depends(require_permission(PERM_VIEW)),
              db: Session = Depends(get_db)):
    event = db.query(TLEvent).filter(TLEvent.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    if not _event_can_see(db, current_user, event):
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    histories = (
        db.query(TLEventHistory).filter(TLEventHistory.event_id == event.id)
        .order_by(TLEventHistory.id.asc()).all()
    )
    actions = (
        db.query(TLActionLog).filter(TLActionLog.event_id == event.id)
        .order_by(TLActionLog.id.asc()).all()
    )
    return {
        **_event_dict(event),
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


# ---- 统计与导出 ----


def _monthly_rows(db: Session, current_user: User, month: str) -> list[dict[str, Any]]:
    """按科室×责任医生聚合当月（t0 落在月份内）事件；口径与列表一致受可见性约束。"""
    try:
        month_start = datetime.strptime(month, "%Y-%m")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid month (expect YYYY-MM): {month}") from exc
    if month_start.month == 12:
        month_end = datetime(month_start.year + 1, 1, 1)
    else:
        month_end = datetime(month_start.year, month_start.month + 1, 1)

    query = db.query(TLEvent).filter(TLEvent.t0 >= month_start, TLEvent.t0 < month_end)
    query = _apply_visibility(query, db, current_user)
    events = query.all()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        key = (event.dept_code or "", event.responsible_doctor_id or "")
        row = grouped.setdefault(key, {
            "dept_code": key[0], "responsible_doctor_id": key[1],
            "total": 0, "completed_on_time": 0, "completed_late": 0,
            "overdue": 0, "pending": 0, "warning": 0, "other": 0,
        })
        row["total"] += 1
        if event.status == "COMPLETED_ON_TIME":
            row["completed_on_time"] += 1
        elif event.status == "COMPLETED_LATE":
            row["completed_late"] += 1
        elif event.status == "OVERDUE":
            row["overdue"] += 1
        elif event.status == "PENDING":
            row["pending"] += 1
        elif event.status == "WARNING":
            row["warning"] += 1
        else:
            row["other"] += 1
    return sorted(grouped.values(), key=lambda r: (r["dept_code"], r["responsible_doctor_id"]))


@router.get("/stats/monthly", summary="科室/个人月度统计")
def stats_monthly(month: str | None = Query(None, description="月份 YYYY-MM，默认当月"),
                  current_user: User = Depends(require_permission(PERM_VIEW)),
                  db: Session = Depends(get_db)):
    month = str(month or "").strip() or datetime.now().strftime("%Y-%m")
    rows = _monthly_rows(db, current_user, month)
    totals = {
        "total": sum(r["total"] for r in rows),
        "completed_on_time": sum(r["completed_on_time"] for r in rows),
        "completed_late": sum(r["completed_late"] for r in rows),
        "overdue": sum(r["overdue"] for r in rows),
        "pending": sum(r["pending"] for r in rows),
        "warning": sum(r["warning"] for r in rows),
        "other": sum(r["other"] for r in rows),
    }
    return {"month": month.strip(), "totals": totals, "rows": rows}


@router.get("/export/monthly", summary="导出月度统计 CSV（写导出审计）")
def export_monthly(month: str = Query(..., description="月份 YYYY-MM"),
                   request: Request = None,
                   current_user: User = Depends(require_permission(PERM_EXPORT)),
                   db: Session = Depends(get_db)):
    rows = _monthly_rows(db, current_user, month.strip())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["月份", "科室编码", "责任医生", "事件总数", "按时完成", "超时完成",
                     "超时未完成", "未到期", "预警中", "其他状态"])
    for row in rows:
        writer.writerow([month.strip(), row["dept_code"], row["responsible_doctor_id"],
                         row["total"], row["completed_on_time"], row["completed_late"],
                         row["overdue"], row["pending"], row["warning"], row["other"]])
    filename = f"timeliness_monthly_{month.strip().replace('-', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    # AGENTS.md 红线：新导出端点必须调用 record_export_audit()
    try:
        record_export_audit(
            db=db,
            user_id=current_user.id,
            username=current_user.username or "",
            export_type="timeliness_monthly",
            export_format="csv",
            filter_criteria={"month": month.strip(), "rows": len(rows)},
            record_count=len(rows),
            status="success",
            request=request,
        )
    except Exception:
        logger.exception("时效月度导出审计记录失败")

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


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
