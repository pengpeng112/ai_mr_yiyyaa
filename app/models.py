"""
ORM 数据模型 —— push_log / scheduler_history / notify_log / audit_*
"""
import os
import hashlib
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, Index, Float, ForeignKey, Sequence
from app.database import Base


def _use_oracle_prefix() -> bool:
    return (os.getenv("APP_DB_TYPE", "sqlite").strip().lower() == "oracle")


def _table_name(name: str) -> str:
    return f"MED_{name.upper()}" if _use_oracle_prefix() else name


def _foreign_key(table_name: str, column_name: str = "id") -> str:
    return f"{_table_name(table_name)}.{column_name}"


def _oracle_sequence_name(table_name: str) -> str:
    full_name = _table_name(table_name)
    base = f"SEQ_{full_name}"
    if len(base) <= 30:
        return base
    suffix = hashlib.md5(full_name.encode("utf-8")).hexdigest()[:6].upper()
    return f"SEQ_{full_name[:19]}_{suffix}"


def _id_column(table_name: str):
    if _use_oracle_prefix():
        return Column(Integer, Sequence(_oracle_sequence_name(table_name), start=1), primary_key=True)
    return Column(Integer, primary_key=True, autoincrement=True)


class PushLog(Base):
    """推送日志表 - 添加索引优化查询性能"""
    __tablename__ = _table_name("push_log")

    id = _id_column("push_log")
    push_time = Column(DateTime, nullable=False, default=datetime.now, index=True)
    trigger_type = Column(String(20), nullable=False)   # auto | manual | retry
    query_date = Column(String(10), nullable=False, index=True)
    patient_id = Column(String(50), nullable=False, index=True)
    patient_name = Column(String(50), default="")
    admission_no = Column(String(50), default="", index=True)       # 住院号
    visit_number = Column(String(20), default="")                   # 住院次数
    source_record_key = Column(String(255), default="", index=True)
    dept = Column(String(50), default="", index=True)
    workflow_run_id = Column(String(100), default="")
    task_id = Column(String(100), default="")
    status = Column(String(20), nullable=False, index=True)         # success | failed | skipped | pending
    pushed_flag = Column(Integer, default=0, index=True)              # 是否已推送成功（1/0）
    reviewed_flag = Column(Integer, default=0, index=True)            # 是否人工复核（1/0）
    reviewed_at = Column(DateTime, nullable=True)                     # 人工复核时间
    reviewed_by = Column(String(50), default="")                     # 人工复核人
    manual_override = Column(Integer, default=0, index=True)          # 手动覆盖跳过规则（1/0）
    skip_reason = Column(String(200), default="")                    # 跳过原因
    inconsistency = Column(Integer, default=0, index=True)
    severity = Column(String(10), default="")            # high | medium | low
    elapsed_ms = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    parse_status = Column(String(20), default="")
    risk_score = Column(Integer, default=0)
    ai_version = Column(String(20), default="1.0")
    alert_level = Column(String(10), default="")            # red | yellow | blue | gray
    ai_result = Column(Text, default="")
    error_msg = Column(Text, default="")
    mr_text = Column(Text, default="")                   # 推送的原始文本（可选保存）
    request_json = Column(Text, default="")
    response_json = Column(Text, default="")
    parse_error = Column(Text, default="")

    # 复合索引
    __table_args__ = (
        Index('idx_push_status_query_date', 'status', 'query_date'),
        Index('idx_push_dept_query_date', 'dept', 'query_date'),
        Index('idx_push_patient_query_date', 'patient_id', 'query_date'),
    )


class AuditDimensionResult(Base):
    """审计维度结果表 —— 每条推送日志对应多个审计维度"""
    __tablename__ = _table_name("audit_dimension_result")

    id = _id_column("audit_dimension_result")
    push_log_id = Column(Integer, ForeignKey(_foreign_key("push_log")), nullable=False)
    dimension_code = Column(String(64), default="", index=True)
    dimension = Column(String(50), nullable=False)          # 如"诊断一致性"
    status = Column(String(10), nullable=False, default="")  # ✅ ❌ ⚠️ ❓
    severity = Column(String(20), default="")
    confidence = Column(Float, default=0)
    alert_level = Column(String(10), default="")            # red | yellow | blue | gray
    closure_hours = Column(Integer, default=0)               # 闭环时限（小时）
    push_strategy = Column(String(20), default="")           # immediate | batch | shift_summary | review_only
    outcome_bucket = Column(String(20), default="")          # primary | secondary | none
    medical_content = Column(Text, default="")               # 病程记录内容
    nursing_content = Column(Text, default="")               # 护理记录内容
    explanation = Column(Text, default="")                   # 说明
    issue_summary = Column(Text, default="")
    recommendation = Column(Text, default="")
    medical_evidence_json = Column(Text, default="[]")
    nursing_evidence_json = Column(Text, default="[]")

    __table_args__ = (
        Index('idx_audit_dim_log_id', 'push_log_id'),
        Index('idx_audit_dim_dimension', 'dimension'),
    )


class AuditConclusion(Base):
    """审计结论表 —— 每条推送日志对应一条总体结论"""
    __tablename__ = _table_name("audit_conclusion")

    id = _id_column("audit_conclusion")
    push_log_id = Column(Integer, ForeignKey(_foreign_key("push_log")), nullable=False, unique=True)
    has_inconsistency = Column(Integer, default=0)
    severity = Column(String(20), default="")
    risk_score = Column(Integer, default=0)
    audit_date = Column(String(20), default="")             # 核查日期
    ai_version = Column(String(20), default="1.0")
    alert_level = Column(String(10), default="")            # red | yellow | blue | gray
    closure_hours = Column(Integer, default=0)               # 闭环时限（小时）
    push_strategy = Column(String(20), default="")           # immediate | batch | shift_summary | review_only
    outcome_bucket = Column(String(20), default="")          # primary | secondary | none
    overall_conclusion = Column(Text, default="")           # 总体结论
    focus_items = Column(Text, default="")                  # JSON array: 重点关注项
    reasoning_brief = Column(Text, default="")
    overall_qc_summary = Column(Text, default="")           # 整体病历质控结果描述


class SchedulerHistory(Base):
    """调度器历史表 - 添加索引优化查询性能"""
    __tablename__ = _table_name("scheduler_history")

    id = _id_column("scheduler_history")
    run_time = Column(DateTime, nullable=False, default=datetime.now, index=True)
    trigger_type = Column(String(20), nullable=False)
    query_date = Column(String(10), nullable=False, index=True)
    total_records = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    duration_seconds = Column(Integer, default=0)
    status = Column(String(20), nullable=False, index=True)          # completed | failed | cancelled


class NotifyLog(Base):
    """通知日志表 - 添加索引优化查询性能"""
    __tablename__ = _table_name("notify_log")

    id = _id_column("notify_log")
    notify_time = Column(DateTime, nullable=False, default=datetime.now, index=True)
    channel_type = Column(String(20), nullable=False, index=True)    # wechat | dingtalk | email | webhook
    target = Column(String(200), default="")
    patient_id = Column(String(50), default="", index=True)
    status = Column(String(20), nullable=False, index=True)          # sent | failed
    content_summary = Column(Text, default="")
    error_msg = Column(Text, default="")

    # 复合索引
    __table_args__ = (
        Index('idx_notify_channel_status', 'channel_type', 'status'),
        Index('idx_notify_patient_time', 'patient_id', 'notify_time'),
    )


# ============ RBAC 权限管理模型 ============

class Department(Base):
    """科室表"""
    __tablename__ = _table_name("departments")

    id = _id_column("departments")
    name = Column(String(100), unique=True, nullable=False, index=True)
    code = Column(String(20), default="")
    manager_id = Column(Integer, nullable=True)  # 科室主任 ID
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Role(Base):
    """角色表"""
    __tablename__ = _table_name("roles")

    id = _id_column("roles")
    name = Column(String(50), unique=True, nullable=False, index=True)  # admin, dept_manager, clinician, auditor
    description = Column(Text, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Permission(Base):
    """权限表"""
    __tablename__ = _table_name("permissions")

    id = _id_column("permissions")
    name = Column(String(100), unique=True, nullable=False, index=True)  # view_reports, edit_feedback, approve_qc
    description = Column(Text, default="")
    module = Column(String(50), default="")  # dashboard, qc_reports, feedback, admin
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class RolePermission(Base):
    """角色权限关联表"""
    __tablename__ = _table_name("role_permissions")

    role_id = Column(Integer, ForeignKey(_foreign_key("roles")), primary_key=True)
    permission_id = Column(Integer, ForeignKey(_foreign_key("permissions")), primary_key=True)
    # 注意：SQLAlchemy 需要至少一个 autoincrement 列，这里使用复合主键


class RoleMenu(Base):
    """角色菜单关联表"""
    __tablename__ = _table_name("role_menus")

    role_id = Column(Integer, ForeignKey(_foreign_key("roles")), primary_key=True)
    menu_id = Column(String(64), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class RoleDepartment(Base):
    """角色科室关联表"""
    __tablename__ = _table_name("role_departments")

    role_id = Column(Integer, ForeignKey(_foreign_key("roles")), primary_key=True)
    dept_id = Column(Integer, ForeignKey(_foreign_key("departments")), primary_key=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class User(Base):
    """用户表"""
    __tablename__ = _table_name("users")

    id = _id_column("users")
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), default="")
    email = Column(String(100), default="")
    dept_id = Column(Integer, ForeignKey(_foreign_key("departments")), nullable=True)  # 所属科室
    role_id = Column(Integer, ForeignKey(_foreign_key("roles")), nullable=True)  # 角色
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_user_dept_active', 'dept_id', 'is_active'),
    )


# ============ 质控反馈模型 ============

class QCFeedback(Base):
    """质控反馈表"""
    __tablename__ = _table_name("qc_feedback")

    id = _id_column("qc_feedback")
    push_log_id = Column(Integer, ForeignKey(_foreign_key("push_log")), nullable=False, index=True)  # 关联审计日志
    dept_id = Column(Integer, ForeignKey(_foreign_key("departments")), nullable=False, index=True)  # 所属科室
    severity = Column(String(10), nullable=False, default="medium")  # high, medium, low (红黄蓝)
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending, acknowledged, rectified, closed
    assigned_to = Column(Integer, ForeignKey(_foreign_key("users")), nullable=True)  # 分配给谁（user_id）
    feedback_text = Column(Text, default="")  # 反馈内容
    is_viewed = Column(Boolean, default=False, index=True)
    viewed_at = Column(DateTime, nullable=True)
    view_count = Column(Integer, default=0)
    rectification_clicked = Column(Boolean, default=False, index=True)
    rectification_clicked_at = Column(DateTime, nullable=True)
    suppress_ai_push = Column(Boolean, default=False, index=True)
    rectification_text = Column(Text, default="")  # 整改说明
    rectification_date = Column(DateTime, nullable=True)  # 整改完成时间
    created_by = Column(Integer, ForeignKey(_foreign_key("users")), nullable=False)  # 创建人（user_id）
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_qc_dept_status', 'dept_id', 'status'),
        Index('idx_qc_severity_status', 'severity', 'status'),
        Index('idx_qc_assigned_to', 'assigned_to'),
    )


class QCFeedbackHistory(Base):
    """质控反馈历史表"""
    __tablename__ = _table_name("qc_feedback_history")

    id = _id_column("qc_feedback_history")
    feedback_id = Column(Integer, ForeignKey(_foreign_key("qc_feedback")), nullable=False, index=True)
    old_status = Column(String(20), default="")
    new_status = Column(String(20), nullable=False)
    changed_by = Column(Integer, ForeignKey(_foreign_key("users")), nullable=False)  # 变更人（user_id）
    change_reason = Column(Text, default="")
    changed_at = Column(DateTime, nullable=False, default=datetime.now, index=True)
