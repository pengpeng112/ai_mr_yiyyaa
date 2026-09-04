# -*- coding: utf-8 -*-
"""规则中心领域模型（039 T1）：六张独立前缀表，全部挂在与 MED_PREARCHIVE_RESULT
同一个 Base 上（SQLite 测试经 build_session_factory 自动建表；Oracle 走
sql/create_prearchive_rule_center_oracle.sql 手工 DDL，服务启动零自动 DDL）。

设计要点：
- 规则版本不可变：draft 可编辑（乐观锁 DRAFT_EDIT_VERSION），validated 之后内容
  只读；published 版本只能被新版本取代，不能改写；
- 发布指针按 (DOMAIN, TRACK, RULE_KEY) 粒度（039 §5.4"每域指针"的执行细化：
  域内每条规则一指针，回滚即把指针指回旧版本）；POINTER_VERSION 乐观号防并发覆盖；
- 审计 append-only：任何状态迁移都落 RULE_AUDIT（操作者/时间/原因/前后版本/request_id）；
- Destination 只存 secret_ref（env:NAME），明文密钥永不落库；
- Outbox 唯一键 (EVENT_ID, DESTINATION_CODE)；DELIVERY_LOG 只存脱敏回执摘要。

ID 统一为应用侧生成的 hex 字符串（uuid4().hex[:32]），SQLite/Oracle 行为一致，
不依赖 Oracle 序列（与既有 RESULT 表的数值自增策略不同的原因：六表全为低频管理写）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from .models import Base

RULE_STATUS_DRAFT = "draft"
RULE_STATUS_VALIDATED = "validated"
RULE_STATUS_APPROVED = "approved"
RULE_STATUS_PUBLISHED = "published"
RULE_STATUS_RETIRED = "retired"
RULE_STATUSES = (
    RULE_STATUS_DRAFT, RULE_STATUS_VALIDATED, RULE_STATUS_APPROVED,
    RULE_STATUS_PUBLISHED, RULE_STATUS_RETIRED,
)

RULE_DOMAINS = ("medical_record", "medical_quality", "insurance", "system_push")
RULE_ORIGINS = (
    "paperless_t_mark_item", "hospital_policy", "system_push", "opendrg", "manual",
)

AUDIT_ACTIONS = (
    "create_draft", "update_draft", "validate", "approve", "reject",
    "publish", "rollback", "retire", "import", "config_update",
    "outbox_retry", "contract_test",
)

OUTBOX_PENDING = "pending"
OUTBOX_SENDING = "sending"
OUTBOX_SENT = "sent"
OUTBOX_RETRY = "retry"
OUTBOX_DEAD = "dead"
OUTBOX_DISABLED = "disabled"
OUTBOX_STATUSES = (
    OUTBOX_PENDING, OUTBOX_SENDING, OUTBOX_SENT, OUTBOX_RETRY,
    OUTBOX_DEAD, OUTBOX_DISABLED,
)

DEST_KINDS = ("emr", "his", "mock")
DEST_AUTH_TYPES = ("hmac_sha256", "mtls", "none")


def new_id() -> str:
    import uuid
    return uuid.uuid4().hex[:32]


def canonical_json(rule_dict: dict) -> str:
    """canonical 序列化：键排序 + 无空白，供 SHA-256 与零差异比对。"""
    import json
    return json.dumps(rule_dict, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_sha256(rule_dict: dict) -> str:
    import hashlib
    return hashlib.sha256(canonical_json(rule_dict).encode("utf-8")).hexdigest()


class RuleVersionRow(Base):
    """不可变规则版本（draft 行可编辑内容，validated 后内容冻结）。"""

    __tablename__ = "MED_PREARCHIVE_RULE_VERSION"

    id = Column(String(32), primary_key=True, default=new_id)
    rule_key = Column(String(128), nullable=False)
    domain = Column(String(32), nullable=False, default="medical_record")
    track = Column(String(32), nullable=False, default="main")
    origin = Column(String(64), nullable=False, default="manual")
    rule_version = Column(String(64), nullable=False)          # 规则自身版本（如 2026.09.02.1）
    set_version = Column(String(64), nullable=False, default="")   # 所属规则集快照（导入用）
    status = Column(String(16), nullable=False, default=RULE_STATUS_DRAFT)
    content_json = Column(Text, nullable=False)                 # canonical 规则 DSL JSON
    content_sha256 = Column(String(64), nullable=False)
    draft_edit_version = Column(Integer, nullable=False, default=1)  # 乐观锁（仅 draft 态有效）
    based_on_version = Column(String(64), nullable=False, default="")
    approved_by = Column(String(128), nullable=False, default="")
    approved_at = Column(DateTime(), nullable=True)
    published_at = Column(DateTime(), nullable=True)
    retired_at = Column(DateTime(), nullable=True)
    created_by = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("rule_key", "rule_version", name="UQ_PREARCHIVE_RULE_KEY_VERSION"),
        Index("IX_PREARCHIVE_RULE_KEY_STATUS", "rule_key", "status"),
        Index("IX_PREARCH_RULE_DOMAIN_TRACK", "domain", "track"),
        {"comment": "039 规则中心：不可变规则版本（draft 可编辑，validated+ 内容冻结）"},
    )


class RulePointerRow(Base):
    """发布指针：域内每条规则当前生效的已发布版本。"""

    __tablename__ = "MED_PREARCHIVE_RULE_POINTER"

    id = Column(String(32), primary_key=True, default=new_id)
    domain = Column(String(32), nullable=False)
    track = Column(String(32), nullable=False, default="main")
    rule_key = Column(String(128), nullable=False)
    published_version = Column(String(64), nullable=False)
    pointer_version = Column(Integer, nullable=False, default=1)   # 乐观锁
    updated_by = Column(String(128), nullable=False, default="")
    updated_at = Column(DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("domain", "track", "rule_key", name="UQ_PREARCHIVE_RULE_POINTER"),
        {"comment": "039 规则中心：发布指针（registry 模式运行时唯一读取入口）"},
    )


class RuleAuditRow(Base):
    """管理审计（append-only，禁 UPDATE/DELETE）。"""

    __tablename__ = "MED_PREARCHIVE_RULE_AUDIT"

    id = Column(String(32), primary_key=True, default=new_id)
    action = Column(String(32), nullable=False)
    rule_key = Column(String(128), nullable=False, default="")
    version_from = Column(String(64), nullable=False, default="")
    version_to = Column(String(64), nullable=False, default="")
    actor_id = Column(String(128), nullable=False, default="")
    actor_name = Column(String(128), nullable=False, default="")
    reason = Column(String(512), nullable=False, default="")
    request_id = Column(String(64), nullable=False, default="")
    detail_json = Column(Text, nullable=False, default="{}")     # 脱敏详情（不含密钥/PHI）
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_RULE_AUDIT_KEY", "rule_key", "created_at"),
        Index("IX_PREARCHIVE_RULE_AUDIT_TIME", "created_at"),
        {"comment": "039 规则中心：编辑/校验/审批/发布/回滚审计（append-only）"},
    )


class DestinationRow(Base):
    """EMR/HIS 等投递目标配置（非敏感；密钥只存 secret_ref 引用）。"""

    __tablename__ = "MED_PREARCHIVE_DESTINATION"

    code = Column(String(64), primary_key=True)
    kind = Column(String(16), nullable=False, default="emr")
    enabled = Column(Integer, nullable=False, default=0)
    base_url = Column(String(512), nullable=False, default="")
    endpoint = Column(String(255), nullable=False, default="")
    auth_type = Column(String(32), nullable=False, default="hmac_sha256")
    secret_ref = Column(String(255), nullable=False, default="")   # env:VAR_NAME，永不存明文
    schema_version = Column(String(16), nullable=False, default="1.0.0")
    timeout_seconds = Column(Integer, nullable=False, default=5)
    max_attempts = Column(Integer, nullable=False, default=6)
    send_severities_json = Column(Text, nullable=False, default='["medium","high"]')
    allow_insecure_internal_http = Column(Integer, nullable=False, default=0)
    config_version = Column(Integer, nullable=False, default=1)    # 目标配置修改审计用
    updated_by = Column(String(128), nullable=False, default="")
    updated_at = Column(DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_DEST_KIND", "kind"),
        {"comment": "039 规则中心：投递目标配置（密钥经 env secret_ref 引用）"},
    )

    def send_severities(self) -> list:
        import json
        try:
            data = json.loads(self.send_severities_json or "[]")
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def to_public_dict(self) -> dict:
        """API/UI 返回体：不含任何密钥材料。"""
        return {
            "code": self.code,
            "kind": self.kind,
            "enabled": bool(self.enabled),
            "base_url": self.base_url,
            "endpoint": self.endpoint,
            "auth_type": self.auth_type,
            "secret_ref": self.secret_ref,
            "secret_configured": bool(self.secret_ref),
            "schema_version": self.schema_version,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.max_attempts,
            "send_severities": self.send_severities(),
            "allow_insecure_internal_http": bool(self.allow_insecure_internal_http),
            "config_version": self.config_version,
            "updated_at": self.updated_at.isoformat(timespec="seconds") if self.updated_at else None,
        }


class OutboxRow(Base):
    """每事件 × 每目标的可靠投递任务。"""

    __tablename__ = "MED_PREARCHIVE_OUTBOX"

    id = Column(String(32), primary_key=True, default=new_id)
    event_id = Column(String(64), nullable=False)
    destination_code = Column(String(64), nullable=False)
    idempotency_key = Column(String(128), nullable=False, default="")
    status = Column(String(16), nullable=False, default=OUTBOX_PENDING)
    attempts = Column(Integer, nullable=False, default=0)
    next_retry_at = Column(DateTime(), nullable=True)
    lease_until = Column(DateTime(), nullable=True)
    lease_owner = Column(String(128), nullable=False, default="")
    last_http_status = Column(Integer, nullable=True)
    last_error = Column(String(512), nullable=False, default="")
    payload_json = Column(Text, nullable=False, default="{}")     # QC Result JSON v1（最小患者字段）
    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("event_id", "destination_code", name="UQ_PREARCHIVE_OUTBOX"),
        Index("IX_PREARCHIVE_OUTBOX_STATUS", "status", "next_retry_at"),
        {"comment": "039 规则中心：EMR/HIS 投递 Outbox（唯一键 event+destination）"},
    )


class DeliveryLogRow(Base):
    """每次投递尝试与脱敏回执（append-only，不存患者正文/密钥）。"""

    __tablename__ = "MED_PREARCHIVE_DELIVERY_LOG"

    id = Column(String(32), primary_key=True, default=new_id)
    outbox_id = Column(String(32), nullable=False, default="")
    event_id = Column(String(64), nullable=False)
    destination_code = Column(String(64), nullable=False)
    attempt = Column(Integer, nullable=False, default=1)
    http_status = Column(Integer, nullable=True)
    outcome = Column(String(16), nullable=False, default="")     # sent/duplicate/retryable/terminal/unknown
    ack_event_id = Column(String(64), nullable=False, default="")
    receiver_reference = Column(String(255), nullable=False, default="")
    detail = Column(String(512), nullable=False, default="")     # 脱敏摘要
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_DELIVERY_EVENT", "event_id", "destination_code"),
        Index("IX_PREARCHIVE_DELIVERY_TIME", "created_at"),
        {"comment": "039 规则中心：投递尝试日志（脱敏，append-only）"},
    )
