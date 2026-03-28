"""
ORM 数据模型 —— push_log / scheduler_history / notify_log / audit_dimension_result / audit_conclusion
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from app.database import Base


class PushLog(Base):
    __tablename__ = "push_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    push_time = Column(DateTime, nullable=False, default=datetime.now)
    trigger_type = Column(String(20), nullable=False)   # auto | manual | retry
    query_date = Column(String(10), nullable=False)
    patient_id = Column(String(50), nullable=False)
    patient_name = Column(String(50), default="")
    dept = Column(String(50), default="")
    admission_no = Column(String(50), default="", index=True)   # 住院号
    visit_number = Column(String(20), default="")               # 次数
    workflow_run_id = Column(String(100), default="")
    task_id = Column(String(100), default="")
    status = Column(String(20), nullable=False)         # success | failed | skipped | pending
    ai_result = Column(Text, default="")
    inconsistency = Column(Integer, default=0)
    severity = Column(String(10), default="")            # high | medium | low
    error_msg = Column(Text, default="")
    elapsed_ms = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    mr_text = Column(Text, default="")                   # 推送的原始文本（可选保存）


class AuditDimensionResult(Base):
    __tablename__ = "audit_dimension_result"

    id = Column(Integer, primary_key=True, autoincrement=True)
    push_log_id = Column(Integer, nullable=False, index=True)   # 关联 push_log.id
    dimension = Column(String(50), nullable=False)              # 如"诊断一致性"
    status = Column(String(10), nullable=False)                 # ✅❌⚠️❓
    medical_content = Column(Text, default="")                  # 病程记录内容
    nursing_content = Column(Text, default="")                  # 护理记录内容
    explanation = Column(Text, default="")                      # 说明


class AuditConclusion(Base):
    __tablename__ = "audit_conclusion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    push_log_id = Column(Integer, nullable=False, unique=True, index=True)
    overall_conclusion = Column(Text, default="")               # 总体结论
    focus_items = Column(Text, default="")                      # JSON array: 重点关注项
    audit_date = Column(String(20), default="")                 # 核查日期


class SchedulerHistory(Base):
    __tablename__ = "scheduler_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_time = Column(DateTime, nullable=False, default=datetime.now)
    trigger_type = Column(String(20), nullable=False)
    query_date = Column(String(10), nullable=False)
    total_records = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    duration_seconds = Column(Integer, default=0)
    status = Column(String(20), nullable=False)          # completed | failed | cancelled


class NotifyLog(Base):
    __tablename__ = "notify_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    notify_time = Column(DateTime, nullable=False, default=datetime.now)
    channel_type = Column(String(20), nullable=False)    # wechat | dingtalk | email | webhook
    target = Column(String(200), default="")
    patient_id = Column(String(50), default="")
    content_summary = Column(Text, default="")
    status = Column(String(20), nullable=False)          # sent | failed
    error_msg = Column(Text, default="")
