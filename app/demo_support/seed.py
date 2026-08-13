"""为隔离 SQLite 生成可被真实页面/API 使用的 12 科室数据。"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func

from app.auth import hash_password
from app.database import SessionLocal, init_db
from app.demo_support.dataset import AUDIT_TYPES, BASE_DATE, DATASET_VERSION, DEPARTMENTS, DEFAULT_SEED, SYNTHETIC_LABEL
from app.models import (
    AuditConclusion,
    AuditDimensionResult,
    Department,
    ExportAuditLog,
    NotifyLog,
    Permission,
    PushAttempt,
    PushExecution,
    PushLog,
    QCAlertFeedback,
    QCFeedback,
    QCFeedbackHistory,
    QCRecordAlertLog,
    Role,
    RoleDepartment,
    RoleMenu,
    RolePermission,
    SchedulerHistory,
    User,
)
from app.routers.menu import MENU_CATALOG
from app.services.alert_token import generate_alert_token


PROFILE_SIZES = {"smoke": 8, "showcase": 100, "performance": 4167}
DEMO_PASSWORD = "Demo-12Dept!2026"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _seed_rbac(db):
    roles = {}
    for name, description in (
        ("admin", "系统管理员（脱敏合成测试）"),
        ("auditor", "质控审计员（脱敏合成测试）"),
        ("dept_manager", "科室主任（脱敏合成测试）"),
        ("clinician", "临床医生（脱敏合成测试）"),
    ):
        role = db.query(Role).filter(Role.name == name).first()
        if role is None:
            role = Role(name=name, description=description)
            db.add(role)
            db.flush()
        else:
            role.description = description
        roles[name] = role

    permission_specs = [
        ("view_dashboard", "查看工作台", "dashboard"),
        ("view_reports", "查看质控报告", "qc_reports"),
        ("export_reports", "导出质控报告", "qc_reports"),
        ("view_feedback", "查看反馈", "feedback"),
        ("create_feedback", "创建反馈", "feedback"),
        ("edit_feedback", "编辑反馈", "feedback"),
        ("approve_feedback", "审批反馈", "feedback"),
        ("manage_users", "管理用户", "admin"),
        ("manage_roles", "管理角色", "admin"),
        ("manage_config", "管理系统配置", "admin"),
        ("view_scheduler", "查看调度器", "scheduler"),
        ("manage_scheduler", "管理调度器", "scheduler"),
    ]
    permissions = {}
    for name, description, module in permission_specs:
        permission = db.query(Permission).filter(Permission.name == name).first()
        if permission is None:
            permission = Permission(name=name, description=description, module=module)
            db.add(permission)
            db.flush()
        else:
            permission.description = description
            permission.module = module
        permissions[name] = permission
    role_permissions = {
        "admin": list(permissions),
        "auditor": ["view_dashboard", "view_reports", "export_reports", "view_feedback", "create_feedback", "edit_feedback"],
        "dept_manager": ["view_dashboard", "view_reports", "export_reports", "view_feedback", "create_feedback", "edit_feedback", "approve_feedback", "view_scheduler"],
        "clinician": ["view_dashboard", "view_reports", "view_feedback", "create_feedback"],
    }
    for role_name, names in role_permissions.items():
        for name in names:
            exists = db.query(RolePermission).filter(RolePermission.role_id == roles[role_name].id, RolePermission.permission_id == permissions[name].id).first()
            if not exists:
                db.add(RolePermission(role_id=roles[role_name].id, permission_id=permissions[name].id))

    departments = []
    for code, name in DEPARTMENTS:
        dept = Department(code=code, name=name)
        db.add(dept)
        db.flush()
        departments.append(dept)

    password_hash = hash_password(DEMO_PASSWORD)
    admin = User(username="demo_admin", password_hash=password_hash, full_name="测试系统管理员", email="demo_admin@example.invalid", role_id=roles["admin"].id, is_active=True)
    auditor = User(username="demo_auditor", password_hash=password_hash, full_name="测试质控审计员", email="demo_auditor@example.invalid", role_id=roles["auditor"].id, is_active=True)
    db.add_all([admin, auditor])
    db.flush()
    managers = {}
    clinicians = {}
    for index, dept in enumerate(departments, start=1):
        suffix = f"d{index:03d}"
        manager = User(username=f"manager_{suffix}", password_hash=password_hash, full_name=f"{dept.name}测试主任", email=f"manager_{suffix}@example.invalid", role_id=roles["dept_manager"].id, dept_id=dept.id, is_active=True)
        clinician = User(username=f"clinician_{suffix}", password_hash=password_hash, full_name=f"{dept.name}测试医生", email=f"clinician_{suffix}@example.invalid", role_id=roles["clinician"].id, dept_id=dept.id, is_active=True)
        db.add_all([manager, clinician])
        db.flush()
        dept.manager_id = manager.id
        managers[dept.id] = manager
        clinicians[dept.id] = clinician

    menu_ids = [str(item["id"]) for item in MENU_CATALOG]
    role_menu_map = {
        "admin": menu_ids,
        "auditor": [item for item in menu_ids if item not in {"users", "roles", "permissions", "departments", "config", "relay-config"}],
        "dept_manager": [item for item in menu_ids if item not in {"users", "roles", "permissions", "departments", "config", "relay-config", "audit-types"}],
        "clinician": [item for item in menu_ids if item in {"dashboard", "patient-qc", "audit", "relay-alert-logs", "feedback"}],
    }
    for role_name, ids in role_menu_map.items():
        for menu_id in ids:
            db.add(RoleMenu(role_id=roles[role_name].id, menu_id=menu_id))
    # auditor 作为跨科室质控角色；主任/医生依靠 User.dept_id 严格限制本科室。
    for dept in departments:
        db.add(RoleDepartment(role_id=roles["auditor"].id, dept_id=dept.id))
    return {"roles": roles, "departments": departments, "admin": admin, "auditor": auditor, "managers": managers, "clinicians": clinicians}


def _dimension_payload(code: str, name: str, severity: str, issue: bool) -> dict:
    return {
        "dimension_code": code,
        "dimension_name": name,
        "status": "fail" if issue else "pass",
        "severity": severity if issue else "low",
        "confidence": 0.93 if issue else 0.88,
        "alert_level": {"high": "red", "medium": "yellow", "low": "blue"}[severity if issue else "low"],
        "closure_hours": 24 if severity == "high" and issue else 72 if issue else 0,
        "push_strategy": "immediate" if severity == "high" and issue else "batch" if issue else "shift_summary",
        "outcome_bucket": "primary" if issue else "none",
        "issue_summary": f"脱敏合成测试发现 {name} 待核实" if issue else f"{name} 未发现测试问题",
        "recommendation": "请完成测试确认、整改与复核。" if issue else "无需处理。",
        "medical_evidence": ["脱敏合成病历证据，不来源于真实患者"],
        "nursing_evidence": ["脱敏合成护理证据，不来源于真实患者"],
    }


def seed_database(profile: str = "showcase", seed: int = DEFAULT_SEED) -> dict:
    if profile not in PROFILE_SIZES:
        raise ValueError(f"unknown profile: {profile}")
    init_db()
    db = SessionLocal()
    try:
        if db.query(Department).count() or db.query(PushLog).count():
            raise RuntimeError("demo database is not empty; use reset instead of reseeding")
        rbac = _seed_rbac(db)
        db.flush()
        admin = rbac["admin"]
        feedback_rows: list[QCFeedback] = []
        alerts: list[QCRecordAlertLog] = []
        per_dept = PROFILE_SIZES[profile]
        feedback_limit = min(20, max(2, per_dept // 4))
        alert_limit = min(12, max(2, per_dept // 5))

        for dept_index, dept in enumerate(rbac["departments"], start=1):
            dept_success_logs: list[PushLog] = []
            for item_index in range(per_dept):
                global_index = (dept_index - 1) * per_dept + item_index + 1
                audit_spec = AUDIT_TYPES[item_index % len(AUDIT_TYPES)]
                bucket = item_index % 20
                if per_dept < 20:
                    status = "skipped" if item_index == per_dept - 1 else "failed" if item_index == per_dept - 2 else "success"
                else:
                    status = "success" if bucket < 17 else "failed" if bucket < 19 else "skipped"
                severity = "high" if item_index < alert_limit or item_index % 10 < 2 else "medium" if item_index % 10 < 6 else "low"
                risk_score = {"high": 86, "medium": 57, "low": 22}[severity]
                push_time = datetime.combine(BASE_DATE, datetime.min.time()) + timedelta(hours=9, minutes=(global_index * 7) % 720, days=-(item_index % 30))
                patient_id = f"SYNTH-{dept_index:02d}-{item_index + 1:04d}"
                patient_name = f"测试患者{global_index:04d}"
                admission_no = f"SYNTH-ZY-{dept_index:02d}{item_index + 1:04d}"
                source_key = f"{patient_id}::1::{audit_spec['code']}::{BASE_DATE.isoformat()}"
                patient_info = {
                    "patient_id": patient_id,
                    "visit_number": "1",
                    "patient_name": patient_name,
                    "admission_no": admission_no,
                    "dept": dept.name,
                    "dept_code": dept.code,
                    "admission_date": (BASE_DATE - timedelta(days=7)).isoformat(),
                    "discharge_date": BASE_DATE.isoformat(),
                    "admission_diagnosis": "测试性症状待查",
                    "discharge_main_diagnosis": "测试性诊断",
                    "admission_dept_name": dept.name,
                    "discharge_dept_name": dept.name,
                    "attending_doctor_userid": rbac["clinicians"][dept.id].username,
                    "attending_doctor_name": rbac["clinicians"][dept.id].full_name,
                    "nurse_head_userid": rbac["managers"][dept.id].username,
                    "nurse_head_name": rbac["managers"][dept.id].full_name,
                }
                parsed = {
                    "version": "2.0",
                    "patient_summary": patient_info,
                    "audit_summary": {
                        "has_inconsistency": severity != "low",
                        "severity": severity,
                        "risk_score": risk_score,
                        "alert_level": {"high": "red", "medium": "yellow", "low": "blue"}[severity],
                        "overall_conclusion": f"{SYNTHETIC_LABEL}：{audit_spec['name']}测试结论。",
                        "overall_qc_summary": "本记录仅用于系统功能、权限、统计和闭环测试。",
                        "focus_items": ["脱敏合成测试问题"],
                    },
                    "dimensions": [_dimension_payload(code, f"测试维度{idx + 1}", severity, idx == 0 and severity != "low") for idx, code in enumerate(audit_spec["dimensions"])],
                }
                log = PushLog(
                    push_time=push_time,
                    trigger_type=["manual", "auto", "retry"][item_index % 3],
                    query_date=(BASE_DATE - timedelta(days=item_index % 30)).isoformat(),
                    patient_id=patient_id,
                    patient_name=patient_name,
                    admission_no=admission_no,
                    visit_number="1",
                    audit_type_code=audit_spec["code"],
                    source_record_key=source_key,
                    dept=dept.name,
                    workflow_run_id=f"demo-wf-{global_index:06d}" if status == "success" else "",
                    task_id=f"demo-task-{global_index:06d}" if status == "success" else "",
                    status=status,
                    pushed_flag=1 if status == "success" else 0,
                    reviewed_flag=1 if status == "success" and item_index % 3 == 0 else 0,
                    reviewed_at=push_time + timedelta(hours=4) if status == "success" and item_index % 3 == 0 else None,
                    reviewed_by="demo_auditor" if status == "success" and item_index % 3 == 0 else "",
                    manual_override=1 if status == "skipped" and item_index % 2 == 0 else 0,
                    skip_reason="unreviewed_pending" if status == "skipped" else "",
                    audit_run_mode="discharge_final" if item_index % 4 == 0 else "daily_increment",
                    inconsistency=1 if status == "success" and severity != "low" else 0,
                    severity=severity if status == "success" else "",
                    elapsed_ms=320 + item_index * 3,
                    retry_count=1 if status == "failed" else 0,
                    parse_status="success" if status == "success" else "failed" if status == "failed" else "",
                    risk_score=risk_score if status == "success" else 0,
                    ai_version="demo-contract-v1",
                    alert_level={"high": "red", "medium": "yellow", "low": "blue"}[severity] if status == "success" else "",
                    ai_result=_json(parsed) if status == "success" else "",
                    error_msg="脱敏合成网络故障场景" if status == "failed" else "",
                    mr_text=f"{SYNTHETIC_LABEL}\n患者：{patient_name}\n测试病历内容，不来源于真实患者。",
                    request_json=_json({"patient_info": patient_info, "demo_meta": {"synthetic": True, "dataset_version": DATASET_VERSION, "seed": seed}}),
                    response_json=_json({"data": {"outputs": {"aa": _json(parsed)}}}) if status == "success" else "",
                    contract_valid=1 if status == "success" else None,
                    contract_errors="",
                )
                db.add(log)
                db.flush()
                if status == "success":
                    dept_success_logs.append(log)
                    for dimension in parsed["dimensions"]:
                        db.add(AuditDimensionResult(
                            push_log_id=log.id,
                            dimension_code=dimension["dimension_code"],
                            dimension=dimension["dimension_name"],
                            status=dimension["status"],
                            severity=dimension["severity"],
                            confidence=dimension["confidence"],
                            alert_level=dimension["alert_level"],
                            closure_hours=dimension["closure_hours"],
                            push_strategy=dimension["push_strategy"],
                            outcome_bucket=dimension["outcome_bucket"],
                            explanation=dimension["issue_summary"],
                            issue_summary=dimension["issue_summary"],
                            recommendation=dimension["recommendation"],
                            medical_evidence_json=_json(dimension["medical_evidence"]),
                            nursing_evidence_json=_json(dimension["nursing_evidence"]),
                            extra_json=_json({"synthetic": True}),
                        ))
                    db.add(AuditConclusion(
                        push_log_id=log.id,
                        has_inconsistency=log.inconsistency,
                        severity=severity,
                        risk_score=risk_score,
                        audit_date=log.query_date,
                        ai_version="demo-contract-v1",
                        alert_level=log.alert_level,
                        closure_hours=24 if severity == "high" else 72 if severity == "medium" else 0,
                        push_strategy="immediate" if severity == "high" else "batch",
                        outcome_bucket="primary" if severity != "low" else "none",
                        overall_conclusion=parsed["audit_summary"]["overall_conclusion"],
                        focus_items=_json(["脱敏合成测试问题"]),
                        reasoning_brief="固定测试规则生成，不构成临床判断。",
                        overall_qc_summary=parsed["audit_summary"]["overall_qc_summary"],
                        extra_json=_json({"synthetic": True}),
                    ))
                identity = hashlib.sha256(f"{source_key}|{log.audit_run_mode}".encode("utf-8")).hexdigest()
                execution = PushExecution(idempotency_key=identity, audit_run_mode=log.audit_run_mode, source_record_key=source_key, audit_type_code=log.audit_type_code, source_version=DATASET_VERSION, status=status, owner_token=f"demo-owner-{global_index}", push_log_id=log.id, reviewed_flag=log.reviewed_flag)
                db.add(execution)
                db.flush()
                db.add(PushAttempt(execution_id=execution.id, attempt_no=1, status=status, target_name="demo-dify-loopback", elapsed_ms=log.elapsed_ms, error_message=log.error_msg, started_at=push_time, finished_at=push_time + timedelta(milliseconds=log.elapsed_ms)))

            for feedback_index, log in enumerate(dept_success_logs[:feedback_limit]):
                status = ["pending", "acknowledged", "rectified", "closed"][feedback_index % 4]
                feedback = QCFeedback(
                    push_log_id=log.id,
                    dept_id=dept.id,
                    severity=log.severity or "medium",
                    status=status,
                    assigned_to=rbac["clinicians"][dept.id].id,
                    feedback_text="脱敏合成测试反馈：请核对测试病历。",
                    is_viewed=feedback_index % 3 != 0,
                    viewed_at=log.push_time + timedelta(hours=1) if feedback_index % 3 != 0 else None,
                    view_count=feedback_index % 4,
                    rectification_clicked=status in {"rectified", "closed"},
                    rectification_clicked_at=log.push_time + timedelta(hours=5) if status in {"rectified", "closed"} else None,
                    suppress_ai_push=status in {"rectified", "closed"},
                    rectification_text="已按测试流程补充脱敏合成病历说明。" if status in {"rectified", "closed"} else "",
                    rectification_date=log.push_time + timedelta(hours=6) if status in {"rectified", "closed"} else None,
                    created_by=admin.id,
                    created_at=log.push_time + timedelta(minutes=5),
                    updated_at=log.push_time + timedelta(hours=6),
                )
                db.add(feedback)
                db.flush()
                feedback_rows.append(feedback)
                db.add(QCFeedbackHistory(feedback_id=feedback.id, old_status="", new_status="pending", changed_by=admin.id, change_reason="创建脱敏合成测试反馈", changed_at=feedback.created_at))
                if status != "pending":
                    db.add(QCFeedbackHistory(feedback_id=feedback.id, old_status="pending", new_status=status, changed_by=rbac["clinicians"][dept.id].id, change_reason="完成测试闭环状态变更", changed_at=feedback.updated_at))

            for alert_index, log in enumerate(dept_success_logs[:alert_limit]):
                alert_status = "success" if alert_index % 6 < 4 else "failed" if alert_index % 6 == 4 else "pending"
                alert = QCRecordAlertLog(
                    push_log_id=log.id,
                    dimension_code=AUDIT_TYPES[alert_index % len(AUDIT_TYPES)]["dimensions"][0],
                    patient_id=log.patient_id,
                    visit_number=log.visit_number,
                    dept=dept.name,
                    severity="high",
                    alert_level="red",
                    status=alert_status,
                    retry_count=1 if alert_status == "failed" else 0,
                    sent_at=log.push_time + timedelta(minutes=2) if alert_status == "success" else None,
                    viewed_flag=1 if alert_index % 3 != 0 else 0,
                    viewed_at=log.push_time + timedelta(hours=1) if alert_index % 3 != 0 else None,
                    last_viewed_at=log.push_time + timedelta(hours=2) if alert_index % 3 != 0 else None,
                    view_count=2 if alert_index % 3 != 0 else 0,
                    viewer_userid=rbac["clinicians"][dept.id].username if alert_index % 3 != 0 else "",
                    viewer_name=rbac["clinicians"][dept.id].full_name if alert_index % 3 != 0 else "",
                    created_at=log.push_time + timedelta(minutes=1),
                    updated_at=log.push_time + timedelta(hours=2),
                    last_error="脱敏合成 Relay 500 场景" if alert_status == "failed" else "",
                )
                db.add(alert)
                db.flush()
                token = generate_alert_token(alert.id, "demo-relay-secret-2026", 720)
                alert.payload_json = _json({
                    "alert_id": alert.id,
                    "synthetic": True,
                    "synthetic_label": SYNTHETIC_LABEL,
                    "patient_id": log.patient_id,
                    "patient_name": log.patient_name,
                    "visit_number": log.visit_number,
                    "dept": dept.name,
                    "dept_code": dept.code,
                    "severity": "high",
                    "evidence_summary": "脱敏合成测试证据，不来源于真实患者",
                    "detail_url": f"http://127.0.0.1:18082/qc-detail/{alert.id}?token={token}",
                })
                alerts.append(alert)
                if alert_index < min(8, alert_limit):
                    action = ["acknowledged", "rectified", "other"][alert_index % 3]
                    db.add(QCAlertFeedback(
                        alert_log_id=alert.id,
                        push_log_id=log.id,
                        dimension_code=alert.dimension_code,
                        action=action,
                        status="submitted",
                        doctor_id=rbac["clinicians"][dept.id].username,
                        doctor_name=rbac["clinicians"][dept.id].full_name,
                        dept=dept.name,
                        reason="已查看脱敏合成测试告警。",
                        rectification_text="已完成测试整改。" if action == "rectified" else "",
                        created_at=log.push_time + timedelta(hours=3),
                        updated_at=log.push_time + timedelta(hours=3),
                    ))

        for day_index in range(30):
            run_time = datetime.combine(BASE_DATE - timedelta(days=day_index), datetime.min.time()) + timedelta(hours=2)
            db.add(SchedulerHistory(run_time=run_time, trigger_type="auto", query_date=(BASE_DATE - timedelta(days=day_index)).isoformat(), audit_type_code=AUDIT_TYPES[day_index % len(AUDIT_TYPES)]["code"], total_records=48, success_count=41, failed_count=5, duration_seconds=36, status="completed", audit_run_mode="daily_increment" if day_index % 2 else "discharge_final", error_code="", error_msg=""))
        for index in range(24):
            db.add(NotifyLog(notify_time=datetime.combine(BASE_DATE, datetime.min.time()) + timedelta(hours=index), channel_type="demo_relay", target="127.0.0.1", patient_id=f"SYNTH-NOTIFY-{index + 1:03d}", status="sent" if index % 5 else "failed", content_summary="脱敏合成测试通知", error_msg="脱敏故障演练" if index % 5 == 0 else ""))
        for dept_index, dept in enumerate(rbac["departments"], start=1):
            db.add(ExportAuditLog(export_time=datetime.combine(BASE_DATE, datetime.min.time()) + timedelta(hours=dept_index), user_id=admin.id, username=admin.username, export_type="push_log", export_format="csv", filter_criteria=_json({"dept": dept.name, "synthetic": True}), record_count=per_dept, ip_address="127.0.0.1", user_agent="demo-seed", status="success"))
        db.commit()
        return build_manifest(db, profile=profile, seed=seed)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_PROJECTION_SPECS = {
    "departments": (Department, ("id", "code", "name", "manager_id")),
    "users": (User, ("id", "username", "dept_id", "role_id", "is_active")),
    "role_permissions": (RolePermission, ("role_id", "permission_id")),
    "role_menus": (RoleMenu, ("role_id", "menu_id")),
    "role_departments": (RoleDepartment, ("role_id", "dept_id")),
    "push_logs": (PushLog, ("id", "source_record_key", "audit_type_code", "audit_run_mode", "patient_id", "dept", "status", "severity", "alert_level", "risk_score", "reviewed_flag", "manual_override", "skip_reason", "superseded_by")),
    "dimensions": (AuditDimensionResult, ("id", "push_log_id", "dimension_code", "status", "severity", "alert_level", "closure_hours", "outcome_bucket")),
    "conclusions": (AuditConclusion, ("id", "push_log_id", "has_inconsistency", "severity", "risk_score", "alert_level", "closure_hours", "outcome_bucket")),
    "qc_feedback": (QCFeedback, ("id", "push_log_id", "dept_id", "severity", "status", "assigned_to", "is_viewed", "view_count", "rectification_clicked", "suppress_ai_push")),
    "qc_feedback_history": (QCFeedbackHistory, ("id", "feedback_id", "old_status", "new_status", "changed_by")),
    "relay_alerts": (QCRecordAlertLog, ("id", "push_log_id", "dimension_code", "patient_id", "dept", "severity", "alert_level", "status", "viewed_flag", "view_count", "retry_count")),
    "h5_feedback": (QCAlertFeedback, ("id", "alert_log_id", "push_log_id", "dimension_code", "action", "status", "dept")),
    "push_executions": (PushExecution, ("id", "push_log_id", "source_record_key", "audit_type_code", "audit_run_mode", "status", "reviewed_flag")),
    "push_attempts": (PushAttempt, ("id", "execution_id", "attempt_no", "status", "target_name")),
}


def build_entity_projections(db=None) -> dict[str, list[str]]:
    """冻结关键业务实体及其关系/状态；排除非确定性的时间戳和密文。"""
    owns_session = db is None
    db = db or SessionLocal()
    try:
        projections: dict[str, list[str]] = {}
        for name, (model, fields) in _PROJECTION_SPECS.items():
            columns = [getattr(model, field) for field in fields]
            rows = db.query(*columns).order_by(*columns).all()
            projections[name] = sorted(_json([value for value in row]) for row in rows)
        return projections
    finally:
        if owns_session:
            db.close()


def build_manifest(db=None, profile: str = "showcase", seed: int = DEFAULT_SEED) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    try:
        model_map = {
            "departments": Department,
            "users": User,
            "roles": Role,
            "permissions": Permission,
            "push_logs": PushLog,
            "dimensions": AuditDimensionResult,
            "conclusions": AuditConclusion,
            "qc_feedback": QCFeedback,
            "qc_feedback_history": QCFeedbackHistory,
            "relay_alerts": QCRecordAlertLog,
            "h5_feedback": QCAlertFeedback,
            "push_executions": PushExecution,
            "push_attempts": PushAttempt,
            "scheduler_history": SchedulerHistory,
            "notify_logs": NotifyLog,
            "export_audit_logs": ExportAuditLog,
        }
        counts = {name: int(db.query(func.count(model.id if hasattr(model, "id") else "*")).scalar() or 0) for name, model in model_map.items()}
        dept_counts = {dept: count for dept, count in db.query(PushLog.dept, func.count(PushLog.id)).group_by(PushLog.dept).order_by(PushLog.dept).all()}
        status_counts = {status: count for status, count in db.query(PushLog.status, func.count(PushLog.id)).group_by(PushLog.status).all()}
        projections = build_entity_projections(db)
        projection_digests = {
            name: hashlib.sha256(_json(rows).encode("utf-8")).hexdigest()
            for name, rows in projections.items()
        }
        stable = {
            "dataset_version": DATASET_VERSION,
            "profile": profile,
            "seed": seed,
            "base_date": BASE_DATE.isoformat(),
            "departments": DEPARTMENTS,
            "audit_types": [item["code"] for item in AUDIT_TYPES],
            "counts": counts,
            "push_logs_by_dept": dept_counts,
            "push_logs_by_status": status_counts,
            "entity_projection_digests": projection_digests,
        }
        digest = hashlib.sha256(_json(stable).encode("utf-8")).hexdigest()
        return {**stable, "dataset_contract_digest": digest, "synthetic": True, "label": SYNTHETIC_LABEL}
    finally:
        if owns_session:
            db.close()
