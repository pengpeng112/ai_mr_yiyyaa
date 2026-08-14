"""
患者质控总览 API
以 patient_id + visit_number + dept 为中心，聚合展示该患者本次住院的所有质控结果。
"""
import json
import logging
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.database import get_db, engine as _db_engine
from app.security_utils import public_error_message
from app.models import (
    PushLog, AuditConclusion, AuditDimensionResult,
    QCFeedback, QCFeedbackHistory, User, Department,
)
from app.services.patient_snapshot import extract_patient_snapshot
from app.services.export_audit_service import record_export_audit
from app.permissions import require_role, require_permission, get_user_role
from app.auth import get_current_user
from app.schemas import QuickActionRequest, MessageResponse
from app.services.dept_visibility import apply_push_log_visibility, visible_dept_names

logger = logging.getLogger(__name__)
router = APIRouter()

# 严重度排序
_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1, "": 0, None: 0}
_SEVERITY_RANK_MAP = {"high": 3, "medium": 2, "low": 1}
_VALID_SEVERITIES = frozenset(_SEVERITY_RANK_MAP.keys())
_VALID_FEEDBACK_STATUSES = frozenset({"pending", "rectified", "closed"})

# 问题维度判断
_ISSUE_STATUSES = {"fail", "warning", "risk"}

# 患者标识类筛选：审计中不得写原文
_SENSITIVE_FILTER_KEYS = frozenset({
    "patient_id", "patient_name", "admission_no", "visit_number",
})


def _safe_json_loads(value, default=None):
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return default or {}
    try:
        return json.loads(text)
    except Exception:
        return default or {}


def _format_dt(dt: Optional[datetime]) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""


# 病历正文（mr_text）字段回退解析：结构化字段缺失时按常见文书标签正则提取
_MR_TEXT_FIELD_LABELS = {
    "admission_date": ("入院日期", "入院时间"),
    "discharge_date": ("出院日期", "出院时间"),
    "admission_diagnosis": ("入院诊断", "初步诊断"),
    "discharge_main_diagnosis": ("出院主诊断", "出院诊断"),
    "admission_dept_name": ("入院科室",),
    "discharge_dept_name": ("出院科室",),
}

# 文书常见表头词：捕获值恰为表头词时说明该字段实为空白（如「出院日期：\n出院科室」），不得误取
_MR_TEXT_HEADER_WORDS = {
    "患者姓名", "姓名", "性别", "年龄", "科室", "病区", "住院号", "床号",
    "记录时间", "入院日期", "入院时间", "出院日期", "出院时间",
    "入院科室", "出院科室", "入院诊断", "出院诊断", "初步诊断", "出院主诊断",
}


def _extract_from_mr_text(mr_text: str) -> dict:
    """从病历正文文本中提取患者关键字段（值为标签后同行的非空内容）。"""
    out: dict[str, str] = {}
    if not mr_text:
        return out
    for field, labels in _MR_TEXT_FIELD_LABELS.items():
        for label in labels:
            m = re.search(re.escape(label) + r"\s*[:：]\s*[\r\n]*\s*([^\r\n]+)", mr_text)
            if m:
                value = m.group(1).strip().strip("：:")
                if value and value not in _MR_TEXT_HEADER_WORDS:
                    out[field] = value
                    break
    return out


def _extract_evidence_summary(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
        return payload.get("evidence_summary") or payload.get("evidence_title") or ""
    except Exception:
        return ""


# 【MOCK-20260813】演示展示需要：列表暴露 payload 内主管医师姓名，恢复见项目根目录 需要修改回去的说明.md
def _extract_payload_doctor_name(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
        return payload.get("doctor_name") or ""
    except Exception:
        return ""


def _get_snapshot_info(log: PushLog) -> dict:
    """从 push_log 的 request_json 中提取患者快照。"""
    return extract_patient_snapshot(log)


def _is_issue(dim: AuditDimensionResult) -> bool:
    """判断一个维度是否为问题。"""
    return (
        dim.status in _ISSUE_STATUSES
        or (dim.severity or "") in {"high", "medium"}
        or bool((dim.issue_summary or "").strip())
    )


def _alert_level_for_severity(severity: str) -> str:
    return {"high": "red", "medium": "yellow", "low": "blue"}.get(severity, "")


def _clean_filter_text(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    return text or None


def _parse_patient_qc_date(value: Optional[str], *, end_of_day: bool = False, strict: bool = False):
    """解析 YYYY-MM-DD。strict=True 时非法日期抛出 ValueError。"""
    text = _clean_filter_text(value)
    if not text:
        return None
    try:
        dt = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        if strict:
            raise ValueError(f"invalid date format: {text}")
        return None
    if end_of_day:
        return dt.replace(hour=23, minute=59, second=59)
    return dt


def normalize_patient_qc_filters(
    *,
    patient_id: Optional[str] = None,
    patient_name: Optional[str] = None,
    admission_no: Optional[str] = None,
    visit_number: Optional[str] = None,
    dept: Optional[str] = None,
    discharge_dept_name: Optional[str] = None,
    severity: Optional[str] = None,
    audit_type_code: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    strict: bool = False,
) -> dict:
    """规范化患者质控筛选。

    strict=True（导出）：非法日期/枚举抛 ValueError，由路由转为 422。
    strict=False（列表）：非法日期忽略，非法 severity 不生效，status 原样参与查询。
    """
    severity_val = _clean_filter_text(severity)
    status_val = _clean_filter_text(status)
    if strict:
        if severity_val and severity_val not in _VALID_SEVERITIES:
            raise ValueError(f"invalid severity: {severity_val}")
        if status_val and status_val not in _VALID_FEEDBACK_STATUSES:
            raise ValueError(f"invalid status: {status_val}")
    elif severity_val and severity_val not in _VALID_SEVERITIES:
        severity_val = None

    return {
        "patient_id": _clean_filter_text(patient_id),
        "patient_name": _clean_filter_text(patient_name),
        "admission_no": _clean_filter_text(admission_no),
        "visit_number": _clean_filter_text(visit_number),
        "dept": _clean_filter_text(dept),
        "discharge_dept_name": _clean_filter_text(discharge_dept_name),
        "severity": severity_val,
        "audit_type_code": _clean_filter_text(audit_type_code),
        "status": status_val,
        "date_from": _parse_patient_qc_date(date_from, strict=strict),
        "date_to": _parse_patient_qc_date(date_to, end_of_day=True, strict=strict),
        "date_from_raw": _clean_filter_text(date_from),
        "date_to_raw": _clean_filter_text(date_to),
    }


def build_patient_qc_base_filters(
    filters: dict,
    *,
    visible_depts: Optional[list] = None,
    enforce_dept_scope: bool = False,
) -> list:
    """构造与列表一致的当前结果 + 文本/日期/科室筛选条件（列表与导出共用）。

    enforce_dept_scope=True 时：
    - visible_depts is None：管理员全院（不加科室过滤）
    - visible_depts=[]：无可见科室，返回空结果
    - 非空列表：仅这些科室名称
    """
    from sqlalchemy import or_
    from sqlalchemy.sql.expression import false as sql_false

    base_filters = [
        PushLog.status == "success",
        PushLog.superseded_by.is_(None),
        or_(PushLog.contract_valid.is_(None), PushLog.contract_valid == 1),
    ]
    if filters.get("date_from") is not None:
        base_filters.append(PushLog.push_time >= filters["date_from"])
    if filters.get("date_to") is not None:
        base_filters.append(PushLog.push_time <= filters["date_to"])
    if filters.get("audit_type_code"):
        base_filters.append(PushLog.audit_type_code == filters["audit_type_code"])
    if filters.get("patient_id"):
        base_filters.append(PushLog.patient_id.like(f"%{filters['patient_id']}%"))
    if filters.get("patient_name"):
        base_filters.append(PushLog.patient_name.like(f"%{filters['patient_name']}%"))
    if filters.get("admission_no"):
        base_filters.append(PushLog.admission_no.like(f"%{filters['admission_no']}%"))
    if filters.get("visit_number"):
        base_filters.append(PushLog.visit_number == filters["visit_number"])
    if filters.get("dept"):
        base_filters.append(PushLog.dept.like(f"%{filters['dept']}%"))
    if filters.get("discharge_dept_name"):
        # discharge_dept_name 仅存在于 request_json（CLOB），PushLog 无独立列。
        # Oracle 下对 CLOB 直接 LIKE 会 ORA-00932: inconsistent datatypes，
        # 需用 dbms_lob.instr；SQLite/Postgres 用 LIKE。与 logs._filter_discharge_dept 保持一致。
        dept_name = filters["discharge_dept_name"]
        if _db_engine.dialect.name == "oracle":
            pattern = f'"discharge_dept_name": "{dept_name}"'
            base_filters.append(or_(
                PushLog.dept == dept_name,
                text("dbms_lob.instr(request_json, :pattern) > 0").bindparams(pattern=pattern),
            ))
        else:
            base_filters.append(or_(
                PushLog.dept == dept_name,
                PushLog.request_json.like(f'%discharge_dept_name%{dept_name}%'),
            ))
    if enforce_dept_scope:
        if visible_depts is None:
            pass  # admin 全院
        elif not visible_depts:
            base_filters.append(sql_false())
        else:
            base_filters.append(PushLog.dept.in_(list(visible_depts)))
    return base_filters


def build_patient_qc_grouped_query(
    db: Session,
    filters: dict,
    *,
    current_user: Optional[User] = None,
):
    """按 patient_id + visit_number + dept 分组的聚合查询（列表与导出共用）。"""
    from sqlalchemy import func, case

    if current_user is not None:
        base_filters = build_patient_qc_base_filters(
            filters,
            visible_depts=visible_dept_names(db, current_user),
            enforce_dept_scope=True,
        )
    else:
        base_filters = build_patient_qc_base_filters(filters)
    severity = filters.get("severity")
    status = filters.get("status")

    severity_rank_expr = case(
        (AuditDimensionResult.severity == "high", 3),
        (AuditDimensionResult.severity == "medium", 2),
        (AuditDimensionResult.severity == "low", 1),
        else_=0,
    )

    base = db.query(
        PushLog.patient_id.label("pid"),
        PushLog.visit_number.label("vn"),
        PushLog.dept.label("dp"),
        func.count(PushLog.id).label("push_log_count"),
        func.max(PushLog.push_time).label("latest_push_time"),
        func.count(func.distinct(PushLog.audit_type_code)).label("audit_type_count"),
    ).filter(*base_filters)

    if severity in _SEVERITY_RANK_MAP:
        severity_subq = db.query(
            PushLog.patient_id.label("pid"),
            PushLog.visit_number.label("vn"),
            PushLog.dept.label("dp"),
            func.max(severity_rank_expr).label("severity_rank"),
        ).join(
            AuditDimensionResult, AuditDimensionResult.push_log_id == PushLog.id
        ).filter(*base_filters).group_by(
            PushLog.patient_id, PushLog.visit_number, PushLog.dept
        ).subquery()
        base = base.join(
            severity_subq,
            (PushLog.patient_id == severity_subq.c.pid)
            & (PushLog.visit_number == severity_subq.c.vn)
            & (PushLog.dept == severity_subq.c.dp),
        ).filter(severity_subq.c.severity_rank == _SEVERITY_RANK_MAP[severity])

    if status:
        feedback_subq = db.query(
            PushLog.patient_id.label("pid"),
            PushLog.visit_number.label("vn"),
            PushLog.dept.label("dp"),
            func.sum(case((QCFeedback.status == status, 1), else_=0)).label("status_count"),
        ).join(
            QCFeedback, QCFeedback.push_log_id == PushLog.id
        ).filter(*base_filters).group_by(
            PushLog.patient_id, PushLog.visit_number, PushLog.dept
        ).subquery()
        base = base.join(
            feedback_subq,
            (PushLog.patient_id == feedback_subq.c.pid)
            & (PushLog.visit_number == feedback_subq.c.vn)
            & (PushLog.dept == feedback_subq.c.dp),
        ).filter(feedback_subq.c.status_count > 0)

    return base.group_by(
        PushLog.patient_id, PushLog.visit_number, PushLog.dept
    )


def query_patient_qc_visit_keys(
    db: Session,
    filters: dict,
    *,
    current_user: Optional[User] = None,
) -> set[tuple[str, str]]:
    """返回筛选命中的全部患者住院次 (patient_id, visit_number)，跨科室去重。"""
    groups = build_patient_qc_grouped_query(db, filters, current_user=current_user).all()
    keys: set[tuple[str, str]] = set()
    for g in groups:
        pid = str(g.pid or "").strip()
        vn = str(g.vn or "").strip()
        if pid:
            keys.add((pid, vn))
    return keys


def build_export_audit_criteria(filters: dict) -> dict:
    """导出审计筛选摘要：非敏感条件原文，患者标识仅记“已提供”。"""
    criteria = {
        "source": "TEMP_PAT_VISIT_LIST",
        "scope": "filtered_all_pages",
    }
    for key in (
        "severity", "status", "dept", "discharge_dept_name", "audit_type_code",
    ):
        if filters.get(key):
            criteria[key] = filters[key]
    if filters.get("date_from_raw"):
        criteria["date_from"] = filters["date_from_raw"]
    if filters.get("date_to_raw"):
        criteria["date_to"] = filters["date_to_raw"]
    for key in _SENSITIVE_FILTER_KEYS:
        if filters.get(key):
            criteria[key] = "已提供"
    return criteria


@router.get("/patients", summary="患者质控总览 - 患者聚合列表")
def list_patient_qc_patients(
    patient_id: Optional[str] = Query(None),
    patient_name: Optional[str] = Query(None),
    admission_no: Optional[str] = Query(None),
    visit_number: Optional[str] = Query(None),
    dept: Optional[str] = Query(None),
    discharge_dept_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    """查询患者质控聚合列表（SQL 聚合 + 分页，避免全量加载）。"""
    from sqlalchemy import func, literal_column

    filters = normalize_patient_qc_filters(
        patient_id=patient_id,
        patient_name=patient_name,
        admission_no=admission_no,
        visit_number=visit_number,
        dept=dept,
        discharge_dept_name=discharge_dept_name,
        severity=severity,
        audit_type_code=audit_type_code,
        status=status,
        date_from=date_from,
        date_to=date_to,
        strict=False,
    )

    # ---- Step 1: SQL 聚合分组（与导出共用构造器；含科室可见性）----
    grouped_query = build_patient_qc_grouped_query(db, filters, current_user=current_user)
    grouped_subq = grouped_query.subquery()

    # 总数
    total = db.query(func.count(literal_column("*"))).select_from(grouped_subq).scalar() or 0

    # 分页查询分组
    offset = (page - 1) * limit
    groups = db.query(grouped_subq).order_by(
        grouped_subq.c.latest_push_time.desc()
    ).offset(offset).limit(limit).all()

    if not groups:
        return {"total": total, "items": []}

    # ---- Step 2: 只对当前页的分组查询维度和反馈统计 ----
    # 构建 OR 条件匹配 (patient_id, visit_number, dept)
    page_conditions = []
    for g in groups:
        page_conditions.append(
            (PushLog.patient_id == g.pid)
            & (PushLog.visit_number == g.vn)
            & (PushLog.dept == g.dp)
        )
    page_logs = db.query(PushLog).filter(
        PushLog.status == "success", or_(*page_conditions)
    ).all()
    page_log_ids = [l.id for l in page_logs]

    # 按分组 key 索引 log
    logs_by_group: dict[str, list] = {}
    for l in page_logs:
        k = f"{l.patient_id}::{l.visit_number}::{l.dept}"
        logs_by_group.setdefault(k, []).append(l)

    # 批量加载维度和反馈（仅当前页的 log IDs）
    dims_by_log: dict[int, list] = {}
    fb_by_log: dict[int, list] = {}
    if page_log_ids:
        for d in db.query(AuditDimensionResult).filter(
            AuditDimensionResult.push_log_id.in_(page_log_ids)
        ).all():
            dims_by_log.setdefault(d.push_log_id, []).append(d)
        for f in db.query(QCFeedback).filter(
            QCFeedback.push_log_id.in_(page_log_ids)
        ).all():
            fb_by_log.setdefault(f.push_log_id, []).append(f)

    # ---- Step 3: 组装结果 ----
    result_items = []
    for g in groups:
        gkey = f"{g.pid}::{g.vn}::{g.dp}"
        g_logs = logs_by_group.get(gkey, [])
        if not g_logs:
            continue

        g_dims = [d for lid in [l.id for l in g_logs] for d in dims_by_log.get(lid, [])]
        g_fbs = [f for lid in [l.id for l in g_logs] for f in fb_by_log.get(lid, [])]

        high_count = sum(1 for d in g_dims if d.severity == "high")
        medium_count = sum(1 for d in g_dims if d.severity == "medium")
        low_count = sum(1 for d in g_dims if d.severity == "low")
        issue_count = sum(1 for d in g_dims if _is_issue(d))
        pending_count = sum(1 for f in g_fbs if f.status == "pending")
        resolved_count = sum(1 for f in g_fbs if f.status in {"rectified", "closed"})

        all_severities = [d.severity for d in g_dims if d.severity]
        highest = max(all_severities, key=lambda s: _SEVERITY_RANK.get(s, 0)) if all_severities else ""

        # 患者姓名：只对当前页的记录解析 request_json
        first_log = g_logs[0]
        snapshot = _get_snapshot_info(first_log)

        result_items.append({
            "patient_id": g.pid,
            "visit_number": g.vn,
            "patient_name": snapshot.get("patient_name") or first_log.patient_name or "",
            "admission_no": snapshot.get("admission_no") or first_log.admission_no or "",
            "dept": g.dp or first_log.dept or "",
            "admission_dept_name": snapshot.get("admission_dept_name") or "",
            "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
            "latest_push_time": _format_dt(g.latest_push_time),
            "audit_type_count": int(g.audit_type_count or 0),
            "push_log_count": int(g.push_log_count or 0),
            "issue_count": issue_count,
            "high_count": high_count,
            "medium_count": medium_count,
            "low_count": low_count,
            "pending_count": pending_count,
            "resolved_count": resolved_count,
            "highest_severity": highest,
            "alert_level": _alert_level_for_severity(highest),
        })

    return {"total": total, "items": result_items}


@router.get("/patient-detail", summary="患者质控总览 - 患者详情")
def get_patient_qc_detail(
    patient_id: str = Query(...),
    visit_number: str = Query(...),
    dept: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_reports")),
):
    """查询某患者本次住院的完整质控详情。"""
    q = db.query(PushLog).filter(
        PushLog.patient_id == patient_id,
        PushLog.visit_number == visit_number,
        PushLog.status == "success",
    )
    if dept:
        q = q.filter(PushLog.dept == dept)
    q = apply_push_log_visibility(q, current_user, db)
    logs = q.order_by(PushLog.push_time.desc()).all()

    if not logs:
        raise HTTPException(status_code=404, detail="no records found for this patient")

    # 患者信息：跨推送日志逐字段合并（不同审计类型/批次的 payload 字段完整性不同，
    # 仅取最新一条会导致入院日期/诊断等字段为空）；结构化字段仍缺失时从 mr_text 病历正文回退解析
    first_log = logs[0]
    snapshot: dict = {}
    attending_doctor = ""
    nurse_head = ""
    _MR_FALLBACK_FIELDS = ("admission_date", "discharge_date", "admission_diagnosis", "discharge_main_diagnosis")
    for log in logs:
        other = _get_snapshot_info(log)
        for k, v in other.items():
            if not snapshot.get(k) and v:
                snapshot[k] = v
        request_json = _safe_json_loads(getattr(log, "request_json", "") or "")
        pi = request_json.get("patient_info", {}) if isinstance(request_json.get("patient_info"), dict) else {}
        if not attending_doctor:
            attending_doctor = str(pi.get("attending_doctor_name") or pi.get("管床医师") or "")
        if not nurse_head:
            nurse_head = str(pi.get("nurse_head_name") or "")
        mr_fields = _extract_from_mr_text(str(request_json.get("mr_text") or ""))
        for k, v in mr_fields.items():
            if not snapshot.get(k) and v:
                snapshot[k] = v
        if all(snapshot.get(k) for k in _MR_FALLBACK_FIELDS) and attending_doctor and nurse_head:
            break

    patient = {
        "patient_id": patient_id,
        "visit_number": visit_number,
        "patient_name": snapshot.get("patient_name") or first_log.patient_name or "",
        "admission_no": snapshot.get("admission_no") or first_log.admission_no or "",
        "dept": snapshot.get("dept_name") or first_log.dept or "",
        "admission_date": snapshot.get("admission_date") or "",
        "discharge_date": snapshot.get("discharge_date") or "",
        "admission_diagnosis": snapshot.get("admission_diagnosis") or "",
        "discharge_main_diagnosis": snapshot.get("discharge_main_diagnosis") or "",
        "admission_dept_name": snapshot.get("admission_dept_name") or "",
        "discharge_dept_name": snapshot.get("discharge_dept_name") or "",
        "surgery": snapshot.get("surgery") or "",
        "attending_doctor_name": attending_doctor,
        "nurse_head_name": nurse_head,
    }

    # 按审计类型分组
    log_ids = [l.id for l in logs]
    all_dimensions = db.query(AuditDimensionResult).filter(
        AuditDimensionResult.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    all_conclusions = db.query(AuditConclusion).filter(
        AuditConclusion.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    all_feedbacks = db.query(QCFeedback).filter(
        QCFeedback.push_log_id.in_(log_ids)
    ).all() if log_ids else []

    # 用户映射
    user_ids = set()
    for fb in all_feedbacks:
        if fb.assigned_to:
            user_ids.add(fb.assigned_to)
    users = {}
    if user_ids:
        for u in db.query(User).filter(User.id.in_(user_ids)).all():
            users[u.id] = u.full_name or u.username

    # 构建审计分组
    conclusion_map = {c.push_log_id: c for c in all_conclusions}
    dim_map: dict[int, list[AuditDimensionResult]] = {}
    for d in all_dimensions:
        dim_map.setdefault(d.push_log_id, []).append(d)
    feedback_map: dict[int, list[QCFeedback]] = {}
    for f in all_feedbacks:
        feedback_map.setdefault(f.push_log_id, []).append(f)

    # 审计类型编码 → 中文名称（注册表读取 config；未知编码回退为编码本身）
    from app.services.audit_type_registry import AuditTypeRegistry
    try:
        audit_type_names = {t.code: t.name for t in AuditTypeRegistry().list_all()}
    except Exception:
        audit_type_names = {}

    audit_groups_dict: dict[str, dict] = {}
    for log in logs:
        code = log.audit_type_code or "unknown"
        if code not in audit_groups_dict:
            audit_groups_dict[code] = {
                "audit_type_code": code,
                "audit_type_name": audit_type_names.get(code) or code,
                "latest_push_time": _format_dt(log.push_time),
                "overall_conclusion": "",
                "overall_qc_summary": "",
                "severity": "",
                "alert_level": "",
                "logs": [],
            }

        conclusion = conclusion_map.get(log.id)
        dims = dim_map.get(log.id, [])
        fbs = feedback_map.get(log.id, [])

        # 填充总体结论（取最新）
        if conclusion and not audit_groups_dict[code]["overall_conclusion"]:
            audit_groups_dict[code]["overall_conclusion"] = conclusion.overall_conclusion or ""
            audit_groups_dict[code]["overall_qc_summary"] = conclusion.overall_qc_summary or ""
            audit_groups_dict[code]["severity"] = conclusion.severity or ""
            audit_groups_dict[code]["alert_level"] = conclusion.alert_level or ""

        # 维度
        dimensions_list = []
        for dim in dims:
            dimensions_list.append({
                "dimension_code": dim.dimension_code or "",
                "dimension_name": dim.dimension or "",
                "status": dim.status or "",
                "severity": dim.severity or "",
                "alert_level": dim.alert_level or "",
                "issue_summary": dim.issue_summary or "",
                "medical_evidence": _safe_json_loads(dim.medical_evidence_json, []),
                "nursing_evidence": _safe_json_loads(dim.nursing_evidence_json, []),
                "recommendation": dim.recommendation or "",
                "explanation": dim.explanation or "",
            })

        # 反馈
        fb_info = {"status": "pending", "feedback_text": "", "assigned_to_name": ""}
        if fbs:
            fb = fbs[0]
            fb_info["status"] = fb.status or "pending"
            fb_info["feedback_text"] = fb.feedback_text or ""
            fb_info["assigned_to_name"] = users.get(fb.assigned_to, "") if fb.assigned_to else ""

        audit_groups_dict[code]["logs"].append({
            "push_log_id": log.id,
            "push_time": _format_dt(log.push_time),
            "status": log.status or "",
            "parse_status": log.parse_status or "",
            "parse_error": log.parse_error or "",
            "overall_conclusion": (conclusion.overall_conclusion or "") if conclusion else "",
            "overall_qc_summary": (conclusion.overall_qc_summary or "") if conclusion else "",
            "severity": log.severity or "",
            "alert_level": log.alert_level or "",
            "inconsistency": bool(log.inconsistency),
            "risk_score": log.risk_score or 0,
            "dimensions": dimensions_list,
            "feedback": fb_info,
        })

    audit_groups = list(audit_groups_dict.values())

    # 汇总统计
    all_dims = all_dimensions
    high_count = sum(1 for d in all_dims if d.severity == "high")
    medium_count = sum(1 for d in all_dims if d.severity == "medium")
    low_count = sum(1 for d in all_dims if d.severity == "low")
    issue_count = sum(1 for d in all_dims if _is_issue(d))
    pending_count = sum(1 for f in all_feedbacks if f.status == "pending")
    resolved_count = sum(1 for f in all_feedbacks if f.status in {"rectified", "closed"})

    all_severities = [d.severity for d in all_dims if d.severity]
    highest = max(all_severities, key=lambda s: _SEVERITY_RANK.get(s, 0)) if all_severities else ""

    summary = {
        "audit_type_count": len(audit_groups),
        "push_log_count": len(logs),
        "issue_count": issue_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "pending_count": pending_count,
        "resolved_count": resolved_count,
        "highest_severity": highest,
    }

    return {"patient": patient, "summary": summary, "audit_groups": audit_groups}


@router.get("/relay-alert/logs", summary="前置机推送日志查询")
def list_relay_alert_logs(
    patient_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    viewed_flag: Optional[int] = Query(None, description="查看状态 1=已查看 0=未查看"),
    dept: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询前置机推送日志。"""
    from app.models import QCRecordAlertLog, QCAlertFeedback

    q = db.query(QCRecordAlertLog)
    if patient_id:
        q = q.filter(QCRecordAlertLog.patient_id.like(f"%{patient_id}%"))
    if status:
        q = q.filter(QCRecordAlertLog.status == status)
    if viewed_flag is not None:
        q = q.filter(QCRecordAlertLog.viewed_flag == viewed_flag)
    if dept:
        q = q.filter(QCRecordAlertLog.dept.like(f"%{dept}%"))
    if severity:
        q = q.filter(QCRecordAlertLog.severity == severity)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(QCRecordAlertLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            q = q.filter(QCRecordAlertLog.created_at <= dt_to)
        except ValueError:
            pass

    total = q.count()
    items = q.order_by(QCRecordAlertLog.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    _alert_ids = [item.id for item in items]
    _feedback_map = {}
    if _alert_ids:
        _feedbacks = db.query(QCAlertFeedback).filter(QCAlertFeedback.alert_log_id.in_(_alert_ids)).all()
        _feedback_map = {f.alert_log_id: f for f in _feedbacks}

    result_items = []
    for item in items:
        fb = _feedback_map.get(item.id)
        result_items.append({
            "id": item.id,
            "push_log_id": item.push_log_id,
            "dimension_code": item.dimension_code,
            "patient_id": item.patient_id,
            "dept": item.dept,
            "severity": item.severity,
            "alert_level": item.alert_level,
            "status": item.status,
            "retry_count": item.retry_count,
            "last_error": item.last_error,
            "sent_at": _format_dt(item.sent_at),
            "created_at": _format_dt(item.created_at),
            "viewed_flag": int(getattr(item, "viewed_flag", 0) or 0),
            "viewed_at": _format_dt(getattr(item, "viewed_at", None)),
            "last_viewed_at": _format_dt(getattr(item, "last_viewed_at", None)),
            "view_count": int(getattr(item, "view_count", 0) or 0),
            "viewer_name": getattr(item, "viewer_name", "") or "",
            "viewer_userid": getattr(item, "viewer_userid", "") or "",
            "evidence_summary": _extract_evidence_summary(getattr(item, "payload_json", "")),
            "doctor_name": _extract_payload_doctor_name(getattr(item, "payload_json", "")),  # 【MOCK-20260813】演示展示用，恢复见 需要修改回去的说明.md
            "feedback_action": fb.action if fb else "",
            "feedback_doctor_name": fb.doctor_name if fb else "",
            "feedback_dept": fb.dept if fb else "",
            "feedback_reason": fb.reason if fb else "",
            "feedback_rectification_text": fb.rectification_text if fb else "",
            "feedback_created_at": _format_dt(fb.created_at) if fb else "",
        })

    return {"total": total, "items": result_items}


@router.get("/alert-status-report", summary="高危与告警状态账实报告（003-E）")
def alert_status_report(
    query_date: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    audit_run_mode: Optional[str] = Query(None, pattern=r"^(daily_increment|discharge_final)$"),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    from app.services.alert_status_stats import build_alert_status_report
    from app.config import load_config

    report = build_alert_status_report(
        db, query_date=query_date, audit_run_mode=audit_run_mode
    )
    relay_cfg = (load_config().get("relay_alert") or {})
    report["alert_dept_filter"] = list(relay_cfg.get("alert_dept_filter") or [])
    report["relay_enabled"] = bool(relay_cfg.get("enabled"))
    # 不暴露 secret
    report["has_secret"] = bool(relay_cfg.get("secret_key_enc") or relay_cfg.get("secret_key"))
    return report


@router.get("/relay-alert/summary", summary="前置机推送日志统计")
def relay_alert_summary(
    patient_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    viewed_flag: Optional[int] = Query(None),
    dept: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """查询前置机推送日志统计（全量口径，用于首页 KPI）。"""
    from app.models import QCRecordAlertLog

    q = db.query(QCRecordAlertLog)
    if patient_id:
        q = q.filter(QCRecordAlertLog.patient_id.like(f"%{patient_id}%"))
    if status:
        q = q.filter(QCRecordAlertLog.status == status)
    if viewed_flag is not None:
        q = q.filter(QCRecordAlertLog.viewed_flag == viewed_flag)
    if dept:
        q = q.filter(QCRecordAlertLog.dept.like(f"%{dept}%"))
    if severity:
        q = q.filter(QCRecordAlertLog.severity == severity)
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(QCRecordAlertLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
            q = q.filter(QCRecordAlertLog.created_at <= dt_to)
        except ValueError:
            pass

    total = q.count()
    success = q.filter(QCRecordAlertLog.status == "success").count()
    failed = q.filter(QCRecordAlertLog.status == "failed").count()
    pending = q.filter(QCRecordAlertLog.status == "pending").count()
    suppressed = q.filter(QCRecordAlertLog.status == "suppressed").count()
    dept_filtered = q.filter(QCRecordAlertLog.status == "dept_filtered").count()
    sending = q.filter(QCRecordAlertLog.status == "sending").count()
    viewed = q.filter(QCRecordAlertLog.viewed_flag == 1).count()
    unviewed = q.filter(QCRecordAlertLog.viewed_flag == 0, QCRecordAlertLog.status != "suppressed").count()
    from sqlalchemy import or_ as _or
    empty_dept = q.filter(
        _or(QCRecordAlertLog.dept.is_(None), QCRecordAlertLog.dept == "")
    ).count()

    # 003-E：显式区分过滤与发送成功，避免页面把 dept_filtered 当成无高危
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "pending": pending,
        "sending": sending,
        "suppressed": suppressed,
        "dept_filtered": dept_filtered,
        "empty_dept": empty_dept,
        "viewed": viewed,
        "unviewed": unviewed,
        "success_rate": round(success * 100 / total, 2) if total else None,
        "view_rate": round(viewed * 100 / total, 2) if total else None,
        "status_legend": {
            "success": "已成功送达前置机",
            "dept_filtered": "科室白名单过滤（非发送成功，也非系统无高危）",
            "pending": "待发送",
            "sending": "发送中",
            "failed": "发送失败",
            "suppressed": "业务抑制",
        },
    }


@router.post("/relay-alert/retry/{alert_id}", summary="重试前置机推送")
def retry_relay_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_role("admin")),
):
    """重试一条失败的前置机推送记录。"""
    from app.models import QCRecordAlertLog
    from app.services.relay_alert_service import RelayAlertService
    from app.config import load_config

    alert = db.query(QCRecordAlertLog).filter(QCRecordAlertLog.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status == "success":
        return {"message": "already sent", "status": "success"}
    if alert.status == "suppressed":
        raise HTTPException(status_code=400, detail="suppressed alert cannot be retried")
    if alert.status not in ("failed", "pending"):
        raise HTTPException(status_code=400, detail="only failed or pending alerts can be retried")

    config = load_config()
    service = RelayAlertService(db, config)
    ok = service.send_one(alert)
    db.commit()

    return {"message": "sent" if ok else "failed", "status": alert.status, "last_error": alert.last_error}


@router.post("/feedback/quick-action", response_model=MessageResponse, summary="医生快捷操作")
def feedback_quick_action(
    body: QuickActionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """医生快捷操作：已整改/未处理/其他原因。"""
    if body.action == "other" and not (body.reason or "").strip():
        raise HTTPException(status_code=400, detail="其他原因需要填写说明")

    # 查找 PushLog
    log = db.query(PushLog).filter(PushLog.id == body.push_log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="push log not found")

    from app.routers.qc_feedback import (
        _check_feedback_permission,
        _resolve_confirm_dept_id,
        _resolve_department_by_name,
    )

    # 查找或创建 QCFeedback
    feedback = db.query(QCFeedback).filter(
        QCFeedback.push_log_id == body.push_log_id,
        QCFeedback.status != "deleted",
    ).order_by(QCFeedback.id.desc()).first()

    if feedback:
        _check_feedback_permission(feedback, current_user, db)

    now = datetime.now()

    if not feedback:
        # 首次操作，自动创建 feedback
        role_name = get_user_role(current_user.id, db) or ""
        dept_ref = _resolve_department_by_name(db, log.dept)
        dept_id = _resolve_confirm_dept_id(role_name, current_user.dept_id, dept_ref, feedback)
        feedback = QCFeedback(
            push_log_id=log.id,
            dept_id=dept_id,
            severity=log.severity or "medium",
            status="pending",
            is_viewed=False,
            view_count=0,
            created_by=current_user.id,
        )
        db.add(feedback)
        db.flush()

    old_status = feedback.status

    if body.action == "rectified":
        feedback.status = "rectified"
        feedback.suppress_ai_push = True
        feedback.rectification_text = body.reason or "已整改"
        feedback.rectification_date = now
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now
        db.add(QCFeedbackHistory(
            feedback_id=feedback.id,
            old_status=old_status,
            new_status="rectified",
            changed_by=current_user.id,
            change_reason="医生快捷操作：已整改",
        ))

    elif body.action == "pending":
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now

    elif body.action == "other":
        feedback.status = "closed"
        feedback.suppress_ai_push = False
        feedback.feedback_text = (body.reason or "").strip()
        feedback.is_viewed = True
        feedback.viewed_at = now
        feedback.view_count = (feedback.view_count or 0) + 1
        feedback.updated_at = now
        db.add(QCFeedbackHistory(
            feedback_id=feedback.id,
            old_status=old_status,
            new_status="closed",
            changed_by=current_user.id,
            change_reason=f"医生快捷操作：其他原因 - {body.reason}",
        ))

    db.commit()
    return MessageResponse(message=f"操作成功：{body.action}")


@router.get("/export/patient-visit-summary", summary="导出患者就诊数据汇总")
def export_patient_visit_summary(
    request: Request,
    patient_id: Optional[str] = Query(None),
    patient_name: Optional[str] = Query(None),
    admission_no: Optional[str] = Query(None),
    visit_number: Optional[str] = Query(None),
    dept: Optional[str] = Query(None),
    discharge_dept_name: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    audit_type_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("export_reports")),
):
    """导出当前筛选条件下全部匹配患者住院次（与列表筛选同源，不限页）。

    结果与 TEMP_PAT_VISIT_LIST 取交集；筛选无结果时返回仅表头 Excel。
    """
    from fastapi.responses import Response
    from app.services.patient_visit_export_service import export_patient_visit_summary as _export

    try:
        filters = normalize_patient_qc_filters(
            patient_id=patient_id,
            patient_name=patient_name,
            admission_no=admission_no,
            visit_number=visit_number,
            dept=dept,
            discharge_dept_name=discharge_dept_name,
            severity=severity,
            audit_type_code=audit_type_code,
            status=status,
            date_from=date_from,
            date_to=date_to,
            strict=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    audit_criteria = build_export_audit_criteria(filters)
    try:
        visit_keys = query_patient_qc_visit_keys(db, filters, current_user=current_user)
        if not visit_keys:
            raise ValueError(
                "当前筛选条件下没有命中任何患者，无法导出。请调整筛选后重试。"
            )
        xlsx_bytes, fmt, record_count = _export(db, patient_keys=visit_keys)
        if record_count == 0:
            raise ValueError(
                f"筛选命中 {len(visit_keys)} 位患者，但均不在当前就诊名单"
                "(TEMP_PAT_VISIT_LIST)中，无法导出其临床数据。"
                "历史出院患者的文书数据不在导出数据源内；"
                "建议清除筛选后导出当前就诊名单，或调整筛选范围。"
            )
    except ValueError as exc:
        try:
            record_export_audit(
                db=db, user_id=current_user.id, username=current_user.username or "",
                export_type="patient_visit", export_format="excel",
                filter_criteria=audit_criteria, record_count=0, status="failed",
                error_msg=public_error_message(exc, "导出参数无效"), request=request,
            )
        except Exception as audit_exc:
            logger.error("患者就诊导出失败审计记录失败: %s", audit_exc, exc_info=True)
        raise HTTPException(status_code=400, detail=public_error_message(exc, "导出参数无效"))
    except RuntimeError as exc:
        try:
            record_export_audit(
                db=db, user_id=current_user.id, username=current_user.username or "",
                export_type="patient_visit", export_format="excel",
                filter_criteria=audit_criteria, record_count=0, status="failed",
                error_msg=public_error_message(exc, "患者就诊数据导出失败"), request=request,
            )
        except Exception as audit_exc:
            logger.error("患者就诊导出失败审计记录失败: %s", audit_exc, exc_info=True)
        raise HTTPException(status_code=500, detail=public_error_message(exc, "患者就诊数据导出失败"))
    except Exception as exc:
        generic_export_error = "患者就诊数据导出失败"
        try:
            record_export_audit(
                db=db, user_id=current_user.id, username=current_user.username or "",
                export_type="patient_visit", export_format="excel",
                filter_criteria=audit_criteria, record_count=0, status="failed",
                error_msg=generic_export_error, request=request,
            )
        except Exception as audit_exc:
            logger.error("患者就诊导出未知失败审计记录失败: %s", audit_exc, exc_info=True)
        logger.error("患者就诊导出未知异常: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=generic_export_error)

    try:
        record_export_audit(
            db=db, user_id=current_user.id, username=current_user.username or "",
            export_type="patient_visit", export_format="excel",
            filter_criteria=audit_criteria, record_count=record_count,
            status="success", request=request,
        )
    except Exception as audit_exc:
        logger.error("患者就诊导出成功审计记录失败: %s", audit_exc, exc_info=True)

    filename = f"patient_visit_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
