"""
病历时效质控本地表（T2；表名与字段名按主设计文档 §15.2 与任务 T2 固定）。

与 app/models.py 保持同一套约定：
- 表名经 _table_name()：SQLite 为 tl_*；APP_DB_TYPE=oracle 时为 MED_TL_*（大写）；
- 主键经 _id_column()：Oracle 使用 SEQ_MED_TL_* 序列，SQLite 自增；
- 显式索引名一律不超过 30 字符（Oracle 11.2 标识符上限，054 曾触发 ORA-00972）；
- Text/CLOB 列放在所有非 LOB 列之后，否则 Oracle INSERT...RETURNING 报 ORA-24816；
- 可选字符串列以 NULL 表示缺省，不用 default=""（Oracle 空串即 NULL，避免两库口径分叉）；
- tl_action_log.mode 是 Oracle 保留字：SQLAlchemy 自动加引号，物理列为小写 "mode"，
  手写 Oracle SQL 须写作 "mode"。
"""
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text

from app.database import Base

# 复用主模型的表名/外键/主键序列约定，保证与既有表在 SQLite/Oracle 下行为一致。
from app.models import _foreign_key, _id_column, _table_name

# ---- 取值域（§15 T2 固定）；写入校验见 rules_seed.append_rule_version 与后续任务 ----
RULE_CATEGORIES = ("TIMELINESS", "FREQUENCY", "CONTENT")
COMPLETION_BASES = ("FIRST_SIGN", "CREATE")
ACTION_MODES = ("SHADOW", "WARN_ONLY", "LOCK_EMR")
EVENT_STATUSES = (
    "PENDING",
    "WARNING",
    "OVERDUE",
    "APPLYING",
    "APPROVED",
    "COMPLETED_ON_TIME",
    "COMPLETED_LATE",
    "CANCELLED",
    "EXEMPT",
)
ACTION_TYPES = ("NOTIFY", "JHEMR_INSERT_MONITOR", "JHEMR_APPROVE")
ACTION_LOG_MODES = ("DRY_RUN", "EXECUTED", "BLOCKED")
APPROVE_CHANNELS = ("JHEMR_NATIVE", "PC_WEB", "WECOM_H5")


class TLRule(Base):
    """时效规则主表：规则身份与启停；可变口径全部在 tl_rule_version。"""
    __tablename__ = _table_name("tl_rule")

    id = _id_column("tl_rule")
    rule_code = Column(String(64), nullable=False)
    rule_name = Column(String(100), nullable=False)
    category = Column(String(20), nullable=False)                     # TIMELINESS | FREQUENCY | CONTENT
    enabled = Column(Boolean, nullable=False, default=False)
    # 当前生效版本；与 tl_rule_version.rule_id 互指，不建外键以免建表循环依赖
    current_version_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("uq_tl_rule_code", "rule_code", unique=True),
    )


class TLRuleVersion(Base):
    """规则版本表：只追加不修改，每次保存生成新版本；事件记录命中的版本号。"""
    __tablename__ = _table_name("tl_rule_version")

    id = _id_column("tl_rule_version")
    rule_id = Column(Integer, ForeignKey(_foreign_key("tl_rule")), nullable=False)
    version_no = Column(Integer, nullable=False)
    trigger_type = Column(String(32), nullable=False)
    completion_basis = Column(String(16), nullable=False, default="FIRST_SIGN")  # FIRST_SIGN | CREATE
    limit_minutes = Column(Integer, nullable=True)                    # NULL=时限待定
    workday_only = Column(Boolean, nullable=False, default=False)
    warn_before_minutes = Column(Integer, nullable=True)
    action_mode = Column(String(16), nullable=False, default="SHADOW")  # SHADOW | WARN_ONLY | LOCK_EMR
    jhemr_monitor_code = Column(String(32), nullable=True)            # NULL=无 JHEMR 监控码
    penalty_amount = Column(Integer, nullable=True)                   # 单位：元；NULL=未配置
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    trigger_filter_json = Column(Text, default="{}")
    target_json = Column(Text, default="{}")
    channels_json = Column(Text, default="[]")
    dept_scope_json = Column(Text, default="[]")
    note = Column(Text, nullable=True)

    __table_args__ = (
        Index("uq_tl_rule_version_no", "rule_id", "version_no", unique=True),
    )


class TLEvent(Base):
    """时效事件台账：一条规则对一个患者住院次的一次触发。"""
    __tablename__ = _table_name("tl_event")

    id = _id_column("tl_event")
    event_uid = Column(String(128), nullable=False)
    rule_code = Column(String(64), nullable=False)
    rule_version_id = Column(Integer, ForeignKey(_foreign_key("tl_rule_version")), nullable=False)
    patient_id = Column(String(50), nullable=False)
    visit_id = Column(String(20), nullable=False)
    dept_code = Column(String(50), nullable=True)
    responsible_doctor_id = Column(String(64), nullable=True)
    t0 = Column(DateTime, nullable=False)
    deadline = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False, default="PENDING")    # 取值见 EVENT_STATUSES
    matched_file_unique_id = Column(String(100), nullable=True)
    completed_at = Column(DateTime, nullable=True)
    overdue_minutes = Column(Integer, nullable=True)
    warn_sent_at = Column(DateTime, nullable=True)
    last_scan_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    source_ref_json = Column(Text, default="{}")

    __table_args__ = (
        Index("uq_tl_event_uid", "event_uid", unique=True),
        Index("idx_tl_event_pv", "patient_id", "visit_id"),
        Index("idx_tl_event_rule_status", "rule_code", "status"),
        Index("idx_tl_event_status_dl", "status", "deadline"),
    )


class TLEventHistory(Base):
    """事件状态流转历史（只追加）。"""
    __tablename__ = _table_name("tl_event_history")

    id = _id_column("tl_event_history")
    event_id = Column(Integer, ForeignKey(_foreign_key("tl_event")), nullable=False)
    from_status = Column(String(32), nullable=True)                   # 事件新建时为 NULL
    to_status = Column(String(32), nullable=False)
    scan_run_id = Column(Integer, nullable=True)                      # 人工动作产生的历史为 NULL
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    reason = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_tl_event_hist_event", "event_id"),
    )


class TLActionLog(Base):
    """动作审计：通知与 JHEMR 写入一律留痕（默认只生成拟执行 SQL，见 T8）。"""
    __tablename__ = _table_name("tl_action_log")

    id = _id_column("tl_action_log")
    event_id = Column(Integer, ForeignKey(_foreign_key("tl_event")), nullable=True)
    action_type = Column(String(32), nullable=False)                  # NOTIFY | JHEMR_INSERT_MONITOR | JHEMR_APPROVE
    mode = Column(String(16), nullable=False)                         # DRY_RUN | EXECUTED | BLOCKED（Oracle 保留字，自动加引号）
    target = Column(String(200), nullable=True)
    operator = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    sql_text = Column(Text, nullable=True)
    params_json = Column(Text, default="{}")
    result = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_tl_action_log_event", "event_id"),
    )


class TLScanRun(Base):
    """影子扫描批次。"""
    __tablename__ = _table_name("tl_scan_run")

    id = _id_column("tl_scan_run")
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(32), nullable=False)
    patients_scanned = Column(Integer, default=0)
    events_created = Column(Integer, default=0)
    events_updated = Column(Integer, default=0)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    error_text = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_tl_scan_run_started", "started_at"),
    )


class TLApproval(Base):
    """超时申请/审批与扣罚台账（来源 JHEMR jhmr_monitor_limit_log 同步，见 T9）。

    唯一键五列均为 NOT NULL：同步时缺任一键值的源行由同步任务跳过并报告。
    """
    __tablename__ = _table_name("tl_approval")

    id = _id_column("tl_approval")
    patient_id = Column(String(50), nullable=False)
    visit_id = Column(String(20), nullable=False)
    monitor_code = Column(String(32), nullable=False)
    apply_date_time = Column(DateTime, nullable=False)
    type = Column(String(20), nullable=False)
    flag = Column(String(20), nullable=True)                          # JHEMR 原生审批标志（2=审批通过）
    apply_user_id = Column(String(64), nullable=True)
    approve_user_id = Column(String(64), nullable=True)
    approve_date_time = Column(DateTime, nullable=True)
    # 2026-11-12 用户裁定（勘误"10 列"说法）：JHEMR jhmr_monitor_limit_log 共 14 列且
    # hospital_no NOT NULL——模板 B WHERE 条件之一，approve 真实回写必需。
    hospital_no = Column(String(20), nullable=False)
    # 源行科室；approve 真实回写时作为写入器闸门 2（试点科室白名单）依据。
    dept_code = Column(String(50), nullable=True)
    approve_channel = Column(String(32), nullable=True)               # JHEMR_NATIVE | PC_WEB | WECOM_H5
    penalty_amount = Column(Integer, nullable=True)                   # 单位：元
    penalty_exempt = Column(Boolean, nullable=False, default=False)
    synced_at = Column(DateTime, nullable=False, default=datetime.now)
    # Text/CLOB 列必须放在所有非 LOB 列之后（ORA-24816）
    apply_reason = Column(Text, nullable=True)
    exempt_reason = Column(Text, nullable=True)

    __table_args__ = (
        Index(
            "uq_tl_approval_key",
            "patient_id",
            "visit_id",
            "monitor_code",
            "apply_date_time",
            "type",
            unique=True,
        ),
    )


# 供 init_db 自检与测试使用的 7 张表（逻辑名，未加 Oracle 前缀）。
TIMELINESS_TABLE_NAMES = (
    "tl_rule",
    "tl_rule_version",
    "tl_event",
    "tl_event_history",
    "tl_action_log",
    "tl_scan_run",
    "tl_approval",
)
