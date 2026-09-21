# -*- coding: utf-8 -*-
"""046 闭环新表模型（同一 Base，SQLite 测试随 build_session_factory 自动建表；
Oracle 走 sql/create_prearchive_closed_loop_oracle_20260910.sql 手工 DDL，
服务启动零自动 DDL——与 RESULT/六表同一纪律）。

表清单（T0 锁定）：
- MED_PREARCHIVE_CATALOG_ITEM    评分目录快照（92 条账本源，保留历史不覆盖）
- MED_PREARCHIVE_COVERAGE_MAP    FID × 原子条款覆盖行（一 FID 多行）
- MED_PREARCHIVE_RUN             检查运行（含 run_revision/trigger_type/trial 标志）
- MED_PREARCHIVE_RULE_EVAL       单规则评估（run+rule+event_instance 唯一，五态）
- MED_PREARCHIVE_ISSUE           缺陷实例（临床问题生命周期内 issue_id 稳定）
- MED_PREARCHIVE_ISSUE_ACTION    人工核查动作（append-only）
- MED_PREARCHIVE_MATCH_TASK      AI 匹配任务
- MED_PREARCHIVE_MATCH_CANDIDATE AI 匹配候选（含用户接受/驳回记录）
- MED_PREARCHIVE_VIEW_TICKET     JHEMR 详情票据 nonce（防重放）

状态口径（046 §3.3）：
- RULE_EVAL.status: pass / fail / unknown / not_applicable / pending
- 排除原因（exclusion_reason）: disabled / dept_excluded / exempt_scene /
  trigger_not_met_with_evidence / rule_scope_empty 等，不计已通过。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from .models import Base
from .rule_models import new_id

# ---- 评估五态 + 排除原因（046 §3.3） ----
EVAL_PASS = "pass"
EVAL_FAIL = "fail"
EVAL_UNKNOWN = "unknown"
EVAL_NOT_APPLICABLE = "not_applicable"
EVAL_PENDING = "pending"
EVAL_STATUSES = (EVAL_PASS, EVAL_FAIL, EVAL_UNKNOWN, EVAL_NOT_APPLICABLE,
                 EVAL_PENDING)

EXCL_DISABLED = "disabled"
EXCL_DEPT_EXCLUDED = "dept_excluded"
EXCL_EXEMPT_SCENE = "exempt_scene"
EXCL_TRIGGER_NOT_MET = "trigger_not_met_with_evidence"
EXCL_RULE_SCOPE_EMPTY = "rule_scope_empty"
EXCLUSION_REASONS = (EXCL_DISABLED, EXCL_DEPT_EXCLUDED, EXCL_EXEMPT_SCENE,
                     EXCL_TRIGGER_NOT_MET, EXCL_RULE_SCOPE_EMPTY)

# ---- 运行触发类型 ----
TRIGGER_PAPERLESS_RPA = "paperless_rpa"
TRIGGER_EMR_SUBMIT = "emr_submit"
TRIGGER_MANUAL_RECHECK = "manual_recheck"
TRIGGER_TRIAL = "trial"
TRIGGER_RECONCILE = "reconcile"
TRIGGER_TYPES = (TRIGGER_PAPERLESS_RPA, TRIGGER_EMR_SUBMIT,
                 TRIGGER_MANUAL_RECHECK, TRIGGER_TRIAL, TRIGGER_RECONCILE)

# ---- 运行状态 ----
RUN_REQUESTED = "requested"     # 已受理未开始（trial 申请即此态，T1b 才执行）
RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_PARTIAL = "partial"         # 部分源失败/部分规则未决
RUN_FAILED = "failed"
RUN_STATUSES = (RUN_REQUESTED, RUN_QUEUED, RUN_RUNNING, RUN_COMPLETED,
                RUN_PARTIAL, RUN_FAILED)

# ---- 缺陷实例状态（人工与自动分离） ----
ISSUE_OPEN = "open"
ISSUE_VIEWED = "viewed"
ISSUE_RECTIFYING = "rectifying"       # 医生已提交整改，待复检
ISSUE_RESOLVED = "resolved"           # 复检通过
ISSUE_FALSE_POSITIVE = "false_positive"
ISSUE_MANUAL_CLOSED = "manual_closed"
ISSUE_STATUSES = (ISSUE_OPEN, ISSUE_VIEWED, ISSUE_RECTIFYING, ISSUE_RESOLVED,
                  ISSUE_FALSE_POSITIVE, ISSUE_MANUAL_CLOSED)

# ---- 匹配任务 ----
MATCH_PENDING = "pending"
MATCH_RUNNING = "running"
MATCH_COMPLETED = "completed"
MATCH_PARTIAL = "partial"             # 部分 FID 失败/超时
MATCH_FAILED = "failed"
MATCH_CANCELLED = "cancelled"
MATCH_STATUSES = (MATCH_PENDING, MATCH_RUNNING, MATCH_COMPLETED,
                  MATCH_PARTIAL, MATCH_FAILED, MATCH_CANCELLED)

# ---- 覆盖行判定方式（046 §4.1） ----
METHOD_DETERMINISTIC = "deterministic"
METHOD_AI_ASSIST = "ai_assist"
METHOD_MANUAL = "manual"
METHOD_DATA_BLOCKED = "data_blocked"
COVERAGE_METHODS = (METHOD_DETERMINISTIC, METHOD_AI_ASSIST, METHOD_MANUAL,
                    METHOD_DATA_BLOCKED)


class CatalogItemRow(Base):
    """评分目录快照行（每次导入一批；历史批次保留不覆盖）。"""

    __tablename__ = "MED_PREARCHIVE_CATALOG_ITEM"

    id = Column(String(32), primary_key=True, default=new_id)
    source_system = Column(String(64), nullable=False, default="paperless_cdms")
    snapshot_id = Column(String(128), nullable=False)
    fid = Column(Integer, nullable=False)
    original_text = Column(Text, nullable=False)
    original_text_sha256 = Column(String(64), nullable=False, default="")
    score = Column(String(16), nullable=False, default="0")
    group_code = Column(String(16), nullable=False, default="")
    group_name = Column(String(64), nullable=False, default="")
    enabled = Column(Integer, nullable=False, default=1)
    collected_at = Column(DateTime(), nullable=True)
    imported_at = Column(DateTime(), nullable=False, default=datetime.now)
    imported_by = Column(String(128), nullable=False, default="")

    __table_args__ = (
        UniqueConstraint("snapshot_id", "fid", name="UQ_PREARCHIVE_CATALOG_SNAP_FID"),
        Index("IX_PREARCHIVE_CATALOG_FID", "fid"),
        {"comment": "046 无纸化评分目录快照（92 条/批，历史保留）"},
    )


class CoverageMapRow(Base):
    """FID × 原子条款覆盖行（账本主体，一 FID 多行）。"""

    __tablename__ = "MED_PREARCHIVE_COVERAGE_MAP"

    id = Column(String(32), primary_key=True, default=new_id)
    fid = Column(Integer, nullable=False, index=True)
    clause_id = Column(String(32), nullable=False)
    clause_text = Column(Text, nullable=False, default="")
    method = Column(String(20), nullable=False, default=METHOD_MANUAL)
    coverage = Column(String(10), nullable=False, default="none")  # full/partial/none
    rule_ids_json = Column(Text, nullable=False, default="[]")
    covered_clauses = Column(Text, nullable=False, default="")
    uncovered_clauses = Column(Text, nullable=False, default="")
    fields_json = Column(Text, nullable=False, default="[]")
    sources_json = Column(Text, nullable=False, default="[]")
    threshold_source = Column(String(255), nullable=False, default="")
    blocked_reason = Column(Text, nullable=False, default="")
    example_positive = Column(Text, nullable=False, default="")
    example_negative = Column(Text, nullable=False, default="")
    severity_suggestion = Column(String(16), nullable=False, default="medium")
    ref_score = Column(String(16), nullable=False, default="0")
    linked_tests_json = Column(Text, nullable=False, default="[]")
    status = Column(String(16), nullable=False, default="draft")  # draft/confirmed
    confirmed_by = Column(String(128), nullable=False, default="")
    confirmed_at = Column(DateTime(), nullable=True)
    verified_at = Column(DateTime(), nullable=True)
    rule_version = Column(String(64), nullable=False, default="")
    owner = Column(String(128), nullable=False, default="")
    next_step = Column(Text, nullable=False, default="")
    updated_at = Column(DateTime(), nullable=False, default=datetime.now,
                        onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("fid", "clause_id", name="UQ_PREARCHIVE_COVERAGE_FID_CLAUSE"),
        Index("IX_PREARCHIVE_COVERAGE_METHOD", "method"),
        {"comment": "046 覆盖账本：FID→原子条款→判定方式/规则/缺口"},
    )


class RunRow(Base):
    """一次检查运行（trigger=轮询/提交/复检/trial；同 anchor 复检=新 revision）。"""

    __tablename__ = "MED_PREARCHIVE_RUN"

    id = Column(String(32), primary_key=True, default=new_id)
    run_revision = Column(Integer, nullable=False, default=1)
    patient_id = Column(String(64), nullable=False)
    visit_number = Column(String(32), nullable=False)
    dept_code = Column(String(64), nullable=False, default="")
    dept_name = Column(String(128), nullable=False, default="")
    trigger_type = Column(String(32), nullable=False, default=TRIGGER_PAPERLESS_RPA)
    trigger_id = Column(String(128), nullable=False, default="")
    submission_id = Column(String(128), nullable=False, default="")
    snapshot_id = Column(String(128), nullable=False, default="")
    ruleset_revision = Column(String(64), nullable=False, default="")
    ruleset_hash = Column(String(64), nullable=False, default="")
    is_trial = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default=RUN_REQUESTED)
    status_detail = Column(String(512), nullable=False, default="")
    requested_by = Column(String(128), nullable=False, default="")
    started_at = Column(DateTime(), nullable=True)
    finished_at = Column(DateTime(), nullable=True)
    checked_at = Column(DateTime(), nullable=True)
    data_snapshot_at = Column(DateTime(), nullable=True)
    summary_json = Column(Text, nullable=False, default="{}")
    source_health_json = Column(Text, nullable=False, default="{}")
    result_id = Column(Integer, nullable=True)      # 关联 MED_PREARCHIVE_RESULT.id
    trial_rules_json = Column(Text, nullable=False, default="{}")   # trial 申请载荷（T1a 契约/T1b 执行）
    trial_scope_json = Column(Text, nullable=False, default="{}")   # trial 观察范围（科室/合成标识）
    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now,
                        onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("patient_id", "visit_number", "run_revision",
                         name="UQ_PREARCHIVE_RUN_REVISION"),
        Index("IX_PREARCHIVE_RUN_TRIGGER", "trigger_type", "status"),
        Index("IX_PREARCHIVE_RUN_TRIAL", "is_trial", "status"),
        {"comment": "046 检查运行（含 trial；同就诊复检递增 run_revision）"},
    )


class RuleEvalRow(Base):
    """单规则 × 事件实例评估行（五态 + 排除原因）。"""

    __tablename__ = "MED_PREARCHIVE_RULE_EVAL"

    id = Column(String(32), primary_key=True, default=new_id)
    run_id = Column(String(32), nullable=False, index=True)
    rule_id = Column(String(128), nullable=False)
    rule_version = Column(String(64), nullable=False, default="")
    event_instance_id = Column(String(64), nullable=False, default="")
    fid = Column(Integer, nullable=True)
    clause_id = Column(String(32), nullable=False, default="")
    status = Column(String(20), nullable=False, default=EVAL_UNKNOWN)
    exclusion_reason = Column(String(48), nullable=False, default="")
    reason_code = Column(String(64), nullable=False, default="")
    evidence_json = Column(Text, nullable=False, default="{}")   # 最小证据
    observed_at = Column(DateTime(), nullable=True)
    deadline_at = Column(DateTime(), nullable=True)              # pending 复查时间
    is_trial = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("run_id", "rule_id", "event_instance_id",
                         name="UQ_PREARCHIVE_EVAL_RUN_RULE_EVENT"),
        Index("IX_PREARCHIVE_EVAL_STATUS", "status"),
        {"comment": "046 逐规则评估（pass/fail/unknown/not_applicable/pending）"},
    )


class IssueRow(Base):
    """缺陷实例：同一临床问题生命周期内 issue_id 稳定（复检不换 ID，状态流转）。"""

    __tablename__ = "MED_PREARCHIVE_ISSUE"

    id = Column(String(32), primary_key=True, default=new_id)
    issue_key = Column(String(128), nullable=False)   # 就诊+规则+事件 的稳定业务键
    patient_id = Column(String(64), nullable=False, index=True)
    visit_number = Column(String(32), nullable=False)
    dept_code = Column(String(64), nullable=False, default="")
    fid = Column(Integer, nullable=True)
    clause_id = Column(String(32), nullable=False, default="")
    rule_id = Column(String(128), nullable=False)
    rule_version = Column(String(64), nullable=False, default="")
    event_instance_id = Column(String(64), nullable=False, default="")
    severity = Column(String(16), nullable=False, default="medium")
    message = Column(Text, nullable=False, default="")
    document_refs_json = Column(Text, nullable=False, default="[]")
    status = Column(String(24), nullable=False, default=ISSUE_OPEN)
    first_seen_run_id = Column(String(32), nullable=False, default="")
    last_seen_run_id = Column(String(32), nullable=False, default="")
    first_seen_at = Column(DateTime(), nullable=False, default=datetime.now)
    last_seen_at = Column(DateTime(), nullable=False, default=datetime.now)
    resolved_run_id = Column(String(32), nullable=False, default="")
    version = Column(Integer, nullable=False, default=1)   # 乐观锁（动作校验）
    is_trial = Column(Integer, nullable=False, default=0)
    delivered_event_id = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now,
                        onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("issue_key", name="UQ_PREARCHIVE_ISSUE_KEY"),
        Index("IX_PREARCHIVE_ISSUE_STATUS", "status"),
        Index("IX_PREARCHIVE_ISSUE_VISIT", "patient_id", "visit_number"),
        {"comment": "046 缺陷实例（稳定生命周期；人工状态与引擎结论分离）"},
    )


class IssueActionRow(Base):
    """人工核查动作（append-only：看过/整改/误报/关闭/复检）。"""

    __tablename__ = "MED_PREARCHIVE_ISSUE_ACTION"

    id = Column(String(32), primary_key=True, default=new_id)
    issue_id = Column(String(32), nullable=False, index=True)
    action = Column(String(32), nullable=False)   # viewed/rectified/false_positive/
    #                                            # manual_closed/recheck_requested/note
    status_from = Column(String(24), nullable=False, default="")
    status_to = Column(String(24), nullable=False, default="")
    reason = Column(Text, nullable=False, default="")
    operator_id = Column(String(128), nullable=False, default="")
    operator_name = Column(String(128), nullable=False, default="")
    issue_version = Column(Integer, nullable=False, default=0)   # 乐观校验
    document_revision = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_ISSUE_ACTION_TIME", "created_at"),
        {"comment": "046 人工核查动作（append-only 审计）"},
    )


class MatchTaskRow(Base):
    """AI 匹配任务（批量 92/选中 FID → 候选）。"""

    __tablename__ = "MED_PREARCHIVE_MATCH_TASK"

    id = Column(String(32), primary_key=True, default=new_id)
    status = Column(String(16), nullable=False, default=MATCH_PENDING)
    fid_filter_json = Column(Text, nullable=False, default="[]")   # 空=全部
    input_hash = Column(String(64), nullable=False, default="")
    model_config_json = Column(Text, nullable=False, default="{}")
    model_name = Column(String(128), nullable=False, default="")
    prompt_version = Column(String(32), nullable=False, default="")
    progress_done = Column(Integer, nullable=False, default=0)
    progress_total = Column(Integer, nullable=False, default=0)
    processed_fids_json = Column(Text, nullable=False, default="[]")  # 断点恢复游标
    failed_fids_json = Column(Text, nullable=False, default="[]")
    duration_ms = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=False, default="")
    created_by = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)
    updated_at = Column(DateTime(), nullable=False, default=datetime.now,
                        onupdate=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_MATCH_STATUS", "status"),
        {"comment": "046 AI 匹配任务（分批/可取消/断点恢复/费用可查）"},
    )


class MatchCandidateRow(Base):
    """AI 匹配候选（含确定性校验结果与用户接受/驳回）。"""

    __tablename__ = "MED_PREARCHIVE_MATCH_CANDIDATE"

    id = Column(String(32), primary_key=True, default=new_id)
    task_id = Column(String(32), nullable=False, index=True)
    fid = Column(Integer, nullable=False)
    clause_id = Column(String(32), nullable=False, default="")
    matched_rule_ids_json = Column(Text, nullable=False, default="[]")
    suggested_dsl_json = Column(Text, nullable=False, default="{}")
    field_refs_json = Column(Text, nullable=False, default="[]")
    covered_clauses = Column(Text, nullable=False, default="")
    uncovered_clauses = Column(Text, nullable=False, default="")
    rationale = Column(Text, nullable=False, default="")
    confidence = Column(String(16), nullable=False, default="")
    blocking_reasons_json = Column(Text, nullable=False, default="[]")
    validation_ok = Column(Integer, nullable=False, default=0)
    validation_errors_json = Column(Text, nullable=False, default="[]")
    decision = Column(String(16), nullable=False, default="pending")  # pending/accepted/rejected
    decided_by = Column(String(128), nullable=False, default="")
    decided_at = Column(DateTime(), nullable=True)
    decided_note = Column(Text, nullable=False, default="")
    exact_match = Column(Integer, nullable=False, default=0)   # 1=精确命中复用（未走模型）
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        Index("IX_PREARCHIVE_MATCH_CAND_FID", "fid", "decision"),
        {"comment": "046 AI 匹配候选（校验不通过不得发布；用户接受/驳回留痕）"},
    )


class TrialFeedbackRow(Base):
    """trial 观察反馈（确认缺陷/误报/待核实——人工结论与引擎结论分开）。"""

    __tablename__ = "MED_PREARCHIVE_TRIAL_FEEDBACK"

    id = Column(String(32), primary_key=True, default=new_id)
    run_id = Column(String(32), nullable=False, index=True)
    rule_id = Column(String(128), nullable=False)
    event_instance_id = Column(String(64), nullable=False, default="")
    fid = Column(Integer, nullable=True)
    verdict = Column(String(24), nullable=False)   # confirmed_defect/false_positive/pending_review
    note = Column(Text, nullable=False, default="")
    operator_id = Column(String(128), nullable=False, default="")
    operator_name = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("run_id", "rule_id", "event_instance_id", "operator_id",
                         name="UQ_PREARCHIVE_TRIAL_FEEDBACK"),
        Index("IX_PREARCHIVE_TRIAL_FEED_VERDICT", "verdict"),
        {"comment": "046 trial 观察反馈（不改变引擎结论；确认后才转正式）"},
    )


class ViewTicketRow(Base):
    """JHEMR 详情票据 nonce（短期一次性；防重放）。"""

    __tablename__ = "MED_PREARCHIVE_VIEW_TICKET"

    id = Column(String(32), primary_key=True, default=new_id)
    nonce = Column(String(128), nullable=False)
    patient_id = Column(String(64), nullable=False)
    visit_number = Column(String(32), nullable=False)
    operator_id = Column(String(128), nullable=False)
    dept_code = Column(String(64), nullable=False, default="")
    scope = Column(String(64), nullable=False, default="issue_view")
    expires_at = Column(DateTime(), nullable=False)
    used_at = Column(DateTime(), nullable=True)
    issued_by = Column(String(128), nullable=False, default="")
    created_at = Column(DateTime(), nullable=False, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("nonce", name="UQ_PREARCHIVE_VIEW_TICKET_NONCE"),
        Index("IX_PREARCHIVE_TICKET_EXPIRE", "expires_at"),
        {"comment": "046 JHEMR 一次性详情票据（nonce 重放防护）"},
    )
