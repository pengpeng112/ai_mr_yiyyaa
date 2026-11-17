"""T2：app/timeliness/models.py 与 rules_seed.py 单元测试。

覆盖：SQLite 内存库建出 7 张表且字段名与计划书一致；取值域与默认值；唯一约束；
18 条种子逐条对照计划书 T2 表格、幂等、全部 enabled=False 且 action_mode=SHADOW、
note 写明业务意图与 D8；追加新版本后旧版本完整保留、种子重跑不覆盖；D8 红线与
取值域校验；Oracle 标识符 ≤30、LOB 列置后、保留字 mode 加引号；
_verify_required_schema 纳入 7 表；临时隔离目录跑一次 init_db() 建出 7 张表。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import Text, create_engine, inspect, text
from sqlalchemy.dialects import oracle
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex, CreateTable

from app import database
from app.database import Base
from app.models import _oracle_sequence_name, _table_name
from app.timeliness.models import (
    ACTION_LOG_MODES,
    ACTION_MODES,
    ACTION_TYPES,
    APPROVE_CHANNELS,
    COMPLETION_BASES,
    EVENT_STATUSES,
    RULE_CATEGORIES,
    TIMELINESS_TABLE_NAMES,
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
    D8_REJECT_MESSAGE,
    RULE_SEED_CODES,
    RuleVersionError,
    append_rule_version,
    seed_rules,
    upgrade_seeded_v1_rules,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

TL_MODELS = (TLRule, TLRuleVersion, TLEvent, TLEventHistory, TLActionLog, TLScanRun, TLApproval)

# 计划书 §15 T2 固定字段（含 id）
EXPECTED_COLUMNS = {
    "tl_rule": {
        "id", "rule_code", "rule_name", "category", "enabled", "current_version_id",
        "created_at", "updated_at",
    },
    "tl_rule_version": {
        "id", "rule_id", "version_no", "trigger_type", "trigger_filter_json", "target_json",
        "completion_basis", "limit_minutes", "workday_only", "warn_before_minutes", "action_mode",
        "channels_json", "dept_scope_json", "jhemr_monitor_code", "penalty_amount", "note",
        "created_by", "created_at",
    },
    "tl_event": {
        "id", "event_uid", "rule_code", "rule_version_id", "patient_id", "visit_id", "dept_code",
        "responsible_doctor_id", "t0", "deadline", "status", "matched_file_unique_id", "completed_at",
        "overdue_minutes", "warn_sent_at", "last_scan_at", "source_ref_json", "created_at", "updated_at",
    },
    "tl_event_history": {"id", "event_id", "from_status", "to_status", "reason", "scan_run_id", "created_at"},
    "tl_action_log": {
        "id", "event_id", "action_type", "mode", "target", "sql_text", "params_json", "result",
        "operator", "created_at",
    },
    "tl_scan_run": {
        "id", "started_at", "finished_at", "status", "patients_scanned", "events_created",
        "events_updated", "error_text",
    },
    "tl_approval": {
        "id", "patient_id", "visit_id", "monitor_code", "apply_date_time", "type", "flag",
        "apply_user_id", "apply_reason", "approve_user_id", "approve_date_time", "approve_channel",
        "penalty_amount", "penalty_exempt", "exempt_reason", "synced_at",
        "hospital_no", "dept_code",
    },
}

# 计划书 §15 T2 种子表格（顺序即表格顺序）：rule_code -> (名称, trigger_type, mr_class, 时限分钟, 监控码)
EXPECTED_SEEDS = {
    "ADM_REC": ("入院记录", "ADMISSION", ["EMR09.00.01", "EMR09.00.02", "EMR09.00.03"], 1440, "JH04.02.001"),
    "FIRST_COURSE": ("首次病程记录", "ADMISSION", ["EMR10.00.01"], 480, "JH04.02.002"),
    # 2026-11-14 七规则轮：去掉标题职称词，改 require_signer_titles 审签校验。
    "ATTENDING_FIRST_ROUND": ("主治及以上首次查房", "ADMISSION", ["EMR10.00.03"], 2880, "JH04.02.003"),
    "CHIEF_FIRST_ROUND": ("主任/副主任首次查房", "ADMISSION", ["EMR10.00.03"], 10080, "JH04.02.008"),
    # 2026-11-14 七规则轮：接 HIS.ORDERS 抢救医嘱白名单，目标=抢救记录类。
    "RESCUE_REC": ("抢救记录", "RESCUE_ORDER", ["EMR10.00.08", "EMR10.00.02"], 360, "JH04.02.007"),
    "OP_REC": ("手术记录", "OPERATION_END", ["EMR05.01.02", "EMR10.00.16"], 1440, "JH04.03.012"),
    "POSTOP_FIRST_COURSE": ("术后首次病程", "OPERATION_END", ["EMR10.00.12"], 360, "JH04.02.018"),
    "PREOP_SUMMARY": ("术前小结/讨论", "OPERATION_START", ["EMR10.00.10"], 0, "JH04.03.001"),
    "ANES_REC": ("麻醉记录", "ANESTHESIA_END", [], 1440, None),
    "DEATH_DISCUSS": ("死亡病例讨论", "DEATH", ["EMR10.00.15"], 7200, "JH04.02.013"),
    # 2026-11-13 返工：mr_class 扩充 EMR10.00.13（日间/24h 出院记录变体）
    "DISCHARGE_REC": ("出院记录", "DISCHARGE", ["EMR12.00", "EMR10.00.13"], 1440, "JH04.02.011"),
    "CRITICAL_VALUE_COURSE": ("危急值处置病程", "CRITICAL_VALUE", [], 360, "JH04.03.016"),
    # 2026-11-14 七规则轮：mr_class 扩充 EMR09.00.03（24h 内入院死亡记录）。
    "DEATH_REC": ("死亡记录", "DEATH", ["EMR10.00.14", "EMR09.00.03"], 1440, "JH04.02.012"),
    # 2026-11-14 扩围精度修正：会诊目标三 mr_class（活库近 30 天会诊文书分布实证），
    # 不再为空（空目标在 matchers 防呆下不再通配，且会误判任意签名文书为完成）。
    "CONSULT_EMERGENCY": ("急会诊", "CONSULT_APPLY", ["EMR10.00.08", "EMR07.00.08", "EMR10.00.02"], 10, "JH04.02.020"),
    "CONSULT_NORMAL": ("普通会诊", "CONSULT_APPLY", ["EMR10.00.08", "EMR07.00.08", "EMR10.00.02"], 1440, "JH04.02.020"),
    "DIFFICULT_CASE": ("疑难病例讨论", "MANUAL_OR_INDICATOR", ["EMR10.00.04"], None, None),
    "BLOOD_COURSE": ("输血病程", "TRANSFUSION", [], 1440, "JH04.03.017"),
    "BLOOD_REC": ("输血记录", "TRANSFUSION", ["EMR05.01.04"], 1440, "JH04.03.010"),
}
INTENT_LOCK_EMR = tuple(EXPECTED_SEEDS)[:12]  # 计划书：前 12 项意图 LOCK_EMR
INTENT_WARN_ONLY = ("CONSULT_EMERGENCY", "CONSULT_NORMAL", "DIFFICULT_CASE")
INTENT_UNSPECIFIED = ("DEATH_REC", "BLOOD_COURSE", "BLOOD_REC")


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng, tables=[model.__table__ for model in TL_MODELS])
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    session = sessionmaker(bind=engine, autoflush=False)()
    yield session
    session.close()


def _snapshot(obj) -> dict:
    return {column.name: getattr(obj, column.name) for column in obj.__table__.columns}


def _current_version(db, rule_code: str) -> TLRuleVersion:
    rule = db.query(TLRule).filter(TLRule.rule_code == rule_code).one()
    return db.get(TLRuleVersion, rule.current_version_id)


# ---------- 表结构 ----------


def test_seven_tables_created_in_sqlite_memory(engine):
    inspector = inspect(engine)
    assert set(inspector.get_table_names()) == set(TIMELINESS_TABLE_NAMES)
    for table in TIMELINESS_TABLE_NAMES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        assert columns == EXPECTED_COLUMNS[table], table


def test_table_names_fixed_by_plan():
    assert TIMELINESS_TABLE_NAMES == (
        "tl_rule", "tl_rule_version", "tl_event", "tl_event_history",
        "tl_action_log", "tl_scan_run", "tl_approval",
    )
    assert tuple(model.__tablename__ for model in TL_MODELS) == TIMELINESS_TABLE_NAMES


def test_value_domains_match_plan():
    assert RULE_CATEGORIES == ("TIMELINESS", "FREQUENCY", "CONTENT")
    assert COMPLETION_BASES == ("FIRST_SIGN", "CREATE")
    assert ACTION_MODES == ("SHADOW", "WARN_ONLY", "LOCK_EMR")
    assert EVENT_STATUSES == (
        "PENDING", "WARNING", "OVERDUE", "APPLYING", "APPROVED",
        "COMPLETED_ON_TIME", "COMPLETED_LATE", "CANCELLED", "EXEMPT",
    )
    assert ACTION_TYPES == ("NOTIFY", "JHEMR_INSERT_MONITOR", "JHEMR_APPROVE")
    assert ACTION_LOG_MODES == ("DRY_RUN", "EXECUTED", "BLOCKED")
    assert APPROVE_CHANNELS == ("JHEMR_NATIVE", "PC_WEB", "WECOM_H5")


def test_column_defaults(db):
    rule = TLRule(rule_code="R1", rule_name="测试规则", category="TIMELINESS")
    db.add(rule)
    db.flush()
    version = TLRuleVersion(rule_id=rule.id, version_no=1, trigger_type="ADMISSION")
    db.add(version)
    db.flush()
    event = TLEvent(
        event_uid="uid-1", rule_code="R1", rule_version_id=version.id,
        patient_id="P1", visit_id="1", t0=datetime(2026, 11, 10, 8, 0, 0),
    )
    approval = TLApproval(
        patient_id="P1", visit_id="1", monitor_code="JH04.02.002",
        apply_date_time=datetime(2026, 11, 10, 9, 0, 0), type="1",
        hospital_no="49557032X",
    )
    db.add_all([event, approval])
    db.commit()

    assert rule.enabled is False
    assert rule.created_at is not None and rule.updated_at is not None
    assert version.action_mode == "SHADOW"
    assert version.completion_basis == "FIRST_SIGN"
    assert version.workday_only is False
    assert (version.trigger_filter_json, version.target_json) == ("{}", "{}")
    assert (version.channels_json, version.dept_scope_json) == ("[]", "[]")
    assert event.status == "PENDING"
    assert approval.penalty_exempt is False
    assert approval.synced_at is not None


def test_action_log_mode_must_be_explicit(db):
    db.add(TLActionLog(action_type="NOTIFY"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_rule_code(db):
    db.add(TLRule(rule_code="DUP", rule_name="a", category="TIMELINESS"))
    db.commit()
    db.add(TLRule(rule_code="DUP", rule_name="b", category="TIMELINESS"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_version_no_per_rule(db):
    rule = TLRule(rule_code="R1", rule_name="a", category="TIMELINESS")
    db.add(rule)
    db.flush()
    db.add(TLRuleVersion(rule_id=rule.id, version_no=1, trigger_type="ADMISSION"))
    db.commit()
    db.add(TLRuleVersion(rule_id=rule.id, version_no=1, trigger_type="ADMISSION"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_event_uid(db):
    t0 = datetime(2026, 11, 10, 8, 0, 0)
    db.add(TLEvent(event_uid="E1", rule_code="R1", rule_version_id=1, patient_id="P1", visit_id="1", t0=t0))
    db.commit()
    db.add(TLEvent(event_uid="E1", rule_code="R1", rule_version_id=1, patient_id="P2", visit_id="1", t0=t0))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_unique_approval_five_column_key(db):
    key = dict(
        patient_id="P1", visit_id="1", monitor_code="JH04.02.002",
        apply_date_time=datetime(2026, 11, 10, 9, 0, 0), type="1",
        hospital_no="49557032X",
    )
    db.add(TLApproval(**key))
    db.commit()
    db.add(TLApproval(**{**key, "type": "2"}))  # 键不同（type）允许
    db.commit()
    db.add(TLApproval(**key))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ---------- 种子 ----------


def test_seed_creates_18_rules_all_disabled_and_shadow(db):
    result = seed_rules(db)
    # 2026-11-13 返工：返回值多 upgraded 键（全新库种子即最新口径，无需升级）。
    assert result == {"created": list(EXPECTED_SEEDS), "skipped": [], "upgraded": []}
    assert RULE_SEED_CODES == tuple(EXPECTED_SEEDS)

    rules = db.query(TLRule).all()
    assert len(rules) == 18
    for rule in rules:
        assert rule.enabled is False, rule.rule_code
        assert rule.category == "TIMELINESS"
        versions = db.query(TLRuleVersion).filter(TLRuleVersion.rule_id == rule.id).all()
        assert len(versions) == 1, rule.rule_code
        version = versions[0]
        assert version.version_no == 1
        assert rule.current_version_id == version.id
        assert version.action_mode == "SHADOW", rule.rule_code
        assert version.completion_basis == "FIRST_SIGN"
        assert version.created_by == "system_seed"
    assert {v.action_mode for v in db.query(TLRuleVersion).all()} == {"SHADOW"}


def test_seed_matches_plan_table(db):
    seed_rules(db)
    # 2026-11-14 扩围：手术族种子 trigger_filter 排除床旁/门诊小操作（operation_type='0'），
    # 其余种子仍为空过滤。
    OPERATION_SEED_FILTER = {"field_not_in": {"operation_type": ["0"]}}
    for code, (name, trigger_type, mr_class, limit_minutes, monitor_code) in EXPECTED_SEEDS.items():
        rule = db.query(TLRule).filter(TLRule.rule_code == code).one()
        version = db.get(TLRuleVersion, rule.current_version_id)
        assert rule.rule_name == name, code
        assert version.trigger_type == trigger_type, code
        assert version.limit_minutes == limit_minutes, code
        assert version.jhemr_monitor_code == monitor_code, code
        target = json.loads(version.target_json)
        assert target["mr_class"] == mr_class, code
        assert target["description"], code
        expected_filter = OPERATION_SEED_FILTER if code in ("OP_REC", "POSTOP_FIRST_COURSE") else {}
        assert json.loads(version.trigger_filter_json) == expected_filter, code
        assert json.loads(version.channels_json) == []
        assert json.loads(version.dept_scope_json) == []
        # 2026-11-14 七规则轮：PREOP_SUMMARY 种子带开台前 2h 预警，其余 None。
        assert version.warn_before_minutes == (120 if code == "PREOP_SUMMARY" else None), code
        # 2026-11-13 返工：12 条意图 LOCK_EMR 的可锁定规则种子扣罚 200 元/次；
        # 2026-11-14：DEATH_REC 计划书未指定意图但按任务书补 200。
        expected_penalty = 200 if (code in INTENT_LOCK_EMR or code == "DEATH_REC") else None
        assert version.penalty_amount == expected_penalty, code
        assert version.workday_only is (code == "DEATH_DISCUSS"), code

    def title_keywords(code):
        return json.loads(_current_version(db, code).target_json)["title_contains_any"]

    assert title_keywords("CHIEF_FIRST_ROUND") == ["主任"]
    assert title_keywords("BLOOD_COURSE") == ["输血"]
    # 2026-11-14：会诊规则目标关键词（空目标通配 Bug 修复回归锚）。
    assert title_keywords("CONSULT_NORMAL") == ["会诊"]
    assert title_keywords("CONSULT_EMERGENCY") == ["会诊"]
    assert title_keywords("RESCUE_REC") == ["抢救"]
    # 2026-11-14 七规则轮回归锚：去掉过窄标题词 + 新声明式审签约束。
    assert title_keywords("ATTENDING_FIRST_ROUND") == []
    assert title_keywords("POSTOP_FIRST_COURSE") == []
    attending = json.loads(_current_version(db, "ATTENDING_FIRST_ROUND").target_json)
    assert attending["require_signer_titles"] == ["主治医师", "副主任医师", "主任医师"]
    assert attending["title_excludes_any"] == ["术后"]
    op_rec = json.loads(_current_version(db, "OP_REC").target_json)
    assert op_rec["require_surgeon_sign"] is True
    postop = json.loads(_current_version(db, "POSTOP_FIRST_COURSE").target_json)
    assert postop["title_excludes_any"] == ["交班", "转科", "出院"]
    rescue = json.loads(_current_version(db, "RESCUE_REC").target_json)
    assert rescue["title_excludes_any"] == ["有创"]
    preop = json.loads(_current_version(db, "PREOP_SUMMARY").target_json)
    assert preop["preop_exemption"] is True
    assert preop["require_after_prev_op_end"] is True


def test_seed_is_idempotent(db):
    seed_rules(db)
    before = sorted((_snapshot(r) for r in db.query(TLRule).all()), key=lambda s: s["id"])
    before_versions = sorted((_snapshot(v) for v in db.query(TLRuleVersion).all()), key=lambda s: s["id"])

    second = seed_rules(db)
    third = seed_rules(db)
    # 2026-11-13 返工：返回值多 upgraded 键；新种子的 v1 与当前种子口径一致 → 不升级。
    assert second == {"created": [], "skipped": list(EXPECTED_SEEDS), "upgraded": []}
    assert third == second
    db.expire_all()
    assert db.query(TLRule).count() == 18
    assert db.query(TLRuleVersion).count() == 18
    assert sorted((_snapshot(r) for r in db.query(TLRule).all()), key=lambda s: s["id"]) == before
    assert sorted((_snapshot(v) for v in db.query(TLRuleVersion).all()), key=lambda s: s["id"]) == before_versions


def test_seed_note_records_intent_and_d8(db):
    seed_rules(db)
    notes = {code: _current_version(db, code).note for code in EXPECTED_SEEDS}
    for code in INTENT_LOCK_EMR:
        assert "业务意图 action_mode=LOCK_EMR" in notes[code], code
    for code in INTENT_WARN_ONLY:
        assert "业务意图 action_mode=WARN_ONLY" in notes[code], code
    for code in INTENT_UNSPECIFIED:
        assert "未指定" in notes[code] and "待确认" in notes[code], code
    # 2026-11-13 返工：ADM_REC 的 D8 封锁已解除（生产销账），仅 CHIEF_FIRST_ROUND 维持。
    assert "D8：禁止 LOCK_EMR" in notes["CHIEF_FIRST_ROUND"]
    for code in set(EXPECTED_SEEDS) - {"CHIEF_FIRST_ROUND"}:
        assert "D8：禁止 LOCK_EMR" not in notes[code], code
    assert "2026-11-10" in notes["ADM_REC"] and "解除" in notes["ADM_REC"]
    for code, note in notes.items():
        assert "种子实际 action_mode=SHADOW" in note, code


# ---------- 种子 v1 幂等升级（2026-11-13 返工） ----------


def _make_old_v1_rule(db, rule_code: str, *, created_by: str = "system_seed",
                      penalty_amount=None, target_json=None) -> None:
    """手工构造"老口径 v1 种子"规则行（模拟 84 容器生产库 T2 时期的种子）。"""
    now = datetime.now()
    rule = TLRule(rule_code=rule_code, rule_name=rule_code, category="TIMELINESS",
                  enabled=False, created_at=now, updated_at=now)
    db.add(rule)
    db.flush()
    version = TLRuleVersion(
        rule_id=rule.id, version_no=1, trigger_type="ADMISSION",
        completion_basis="FIRST_SIGN", limit_minutes=1440, workday_only=False,
        warn_before_minutes=None, action_mode="SHADOW", jhemr_monitor_code=None,
        penalty_amount=penalty_amount, created_by=created_by, created_at=now,
        trigger_filter_json="{}",
        target_json=target_json or json.dumps(
            {"description": "old", "mr_class": [], "title_contains_any": []}, ensure_ascii=False),
        channels_json="[]", dept_scope_json="[]", note="old v1 seed",
    )
    db.add(version)
    db.flush()
    rule.current_version_id = version.id
    db.commit()


def test_upgrade_seeded_v1_rules_updates_unmodified_v1(db):
    """仍处于初始 v1（created_by=system_seed）的老口径种子 → 升级到当前种子口径。"""
    _make_old_v1_rule(db, "DISCHARGE_REC", penalty_amount=None,
                      target_json=json.dumps({"description": "出院记录", "mr_class": ["EMR12.00"],
                                              "title_contains_any": []}, ensure_ascii=False))
    _make_old_v1_rule(db, "OP_REC", penalty_amount=None)
    _make_old_v1_rule(db, "CONSULT_NORMAL", penalty_amount=None)

    result = upgrade_seeded_v1_rules(db)
    assert set(result["upgraded"]) == {"DISCHARGE_REC", "OP_REC", "CONSULT_NORMAL"}
    # 升级 = 追加 v2 并切换 current；v1 原样保留（旧版本不可变）。
    rule = db.query(TLRule).filter(TLRule.rule_code == "DISCHARGE_REC").one()
    versions = db.query(TLRuleVersion).filter(TLRuleVersion.rule_id == rule.id).order_by(TLRuleVersion.version_no).all()
    assert [v.version_no for v in versions] == [1, 2]
    current = db.get(TLRuleVersion, rule.current_version_id)
    assert current.version_no == 2 and current.created_by == "system_seed_upgrade"
    assert json.loads(current.target_json)["mr_class"] == ["EMR12.00", "EMR10.00.13"]
    assert current.penalty_amount == 200
    assert json.loads(versions[0].target_json)["mr_class"] == ["EMR12.00"]  # v1 不动
    # 2026-11-14 扩围：OP_REC 升级后带床旁小操作排除过滤；CONSULT_NORMAL 目标
    # 从空（旧口径）升级为三 mr_class + “会诊”关键词（空目标通配 Bug 修复）。
    op_current = db.get(TLRuleVersion, db.query(TLRule).filter(TLRule.rule_code == "OP_REC").one().current_version_id)
    assert json.loads(op_current.trigger_filter_json) == {"field_not_in": {"operation_type": ["0"]}}
    assert json.loads(op_current.target_json)["mr_class"] == ["EMR05.01.02", "EMR10.00.16"]
    consult_current = db.get(TLRuleVersion, db.query(TLRule).filter(TLRule.rule_code == "CONSULT_NORMAL").one().current_version_id)
    assert json.loads(consult_current.target_json)["mr_class"] == ["EMR10.00.08", "EMR07.00.08", "EMR10.00.02"]
    assert json.loads(consult_current.target_json)["title_contains_any"] == ["会诊"]
    # 幂等：重跑不再命中（当前版本已是 v2）
    again = upgrade_seeded_v1_rules(db)
    assert again["upgraded"] == [] and set(again["skipped"]) >= {"DISCHARGE_REC", "OP_REC", "CONSULT_NORMAL"}


def test_upgrade_skips_rules_modified_by_human(db):
    """已被人工保存过新版本（version_no>=2 或 created_by 非 system_seed）的规则不升级。"""
    _make_old_v1_rule(db, "OP_REC", created_by="qc_admin")          # v1 但人工创建
    _make_old_v1_rule(db, "FIRST_COURSE")
    append_rule_version(db, "FIRST_COURSE", created_by="qc_admin", limit_minutes=999)
    db.commit()

    result = upgrade_seeded_v1_rules(db)
    assert result["upgraded"] == []
    assert set(result["skipped"]) == {"OP_REC", "FIRST_COURSE"}
    rule = db.query(TLRule).filter(TLRule.rule_code == "FIRST_COURSE").one()
    current = db.get(TLRuleVersion, rule.current_version_id)
    assert current.limit_minutes == 999  # 人工口径不被覆盖


def test_seed_rules_upgrades_old_v1_automatically(db):
    """seed_rules 集成：老库（旧口径 v1 已存在）重跑自动升级（2026-11-13 返工）。"""
    _make_old_v1_rule(db, "ADM_REC", penalty_amount=None)
    result = seed_rules(db)
    assert result["created"] and "ADM_REC" in result["skipped"] and result["upgraded"] == ["ADM_REC"]
    current = _current_version(db, "ADM_REC")
    assert current.version_no == 2 and current.penalty_amount == 200
    assert json.loads(current.target_json)["mr_class"] == ["EMR09.00.01", "EMR09.00.02", "EMR09.00.03"]


# ---------- 版本化 ----------


def test_new_version_keeps_old_versions_and_reseed_does_not_override(db):
    seed_rules(db)
    v1 = _current_version(db, "FIRST_COURSE")
    v1_before = _snapshot(v1)

    v2 = append_rule_version(
        db, "FIRST_COURSE", created_by="qc_admin",
        limit_minutes=1440, warn_before_minutes=60, action_mode="WARN_ONLY",
        channels_json=["WECOM"],
    )
    db.commit()
    v2_before = _snapshot(v2)
    v3 = append_rule_version(db, "FIRST_COURSE", created_by="qc_admin", limit_minutes=720)
    db.commit()
    db.expire_all()

    rule = db.query(TLRule).filter(TLRule.rule_code == "FIRST_COURSE").one()
    versions = (
        db.query(TLRuleVersion)
        .filter(TLRuleVersion.rule_id == rule.id)
        .order_by(TLRuleVersion.version_no)
        .all()
    )
    assert [v.version_no for v in versions] == [1, 2, 3]
    assert _snapshot(versions[0]) == v1_before  # 旧版本完整保留
    assert _snapshot(versions[1]) == v2_before
    assert rule.current_version_id == v3.id
    assert rule.enabled is False  # 追加版本不改启停

    new = versions[1]
    assert (new.limit_minutes, new.warn_before_minutes, new.action_mode) == (1440, 60, "WARN_ONLY")
    assert json.loads(new.channels_json) == ["WECOM"]
    assert new.created_by == "qc_admin"
    for name in ("trigger_type", "trigger_filter_json", "target_json", "completion_basis",
                 "workday_only", "dept_scope_json", "jhemr_monitor_code", "penalty_amount", "note"):
        assert getattr(new, name) == v1_before[name], name
    assert (versions[2].limit_minutes, versions[2].action_mode) == (720, "WARN_ONLY")  # 基于 v2 复制

    # 种子重跑不覆盖用户保存的新版本
    result = seed_rules(db)
    assert result["created"] == [] and "FIRST_COURSE" in result["skipped"]
    db.expire_all()
    rule = db.query(TLRule).filter(TLRule.rule_code == "FIRST_COURSE").one()
    assert rule.current_version_id == v3.id
    assert db.query(TLRuleVersion).filter(TLRuleVersion.rule_id == rule.id).count() == 3
    assert _snapshot(db.get(TLRuleVersion, v1_before["id"])) == v1_before


@pytest.mark.parametrize("rule_code", ["CHIEF_FIRST_ROUND"])
def test_d8_rules_reject_lock_emr(db, rule_code):
    seed_rules(db)
    before = db.query(TLRuleVersion).count()
    with pytest.raises(RuleVersionError, match="D8"):
        append_rule_version(db, rule_code, created_by="qc_admin", action_mode="LOCK_EMR")
    db.rollback()
    assert db.query(TLRuleVersion).count() == before

    allowed = append_rule_version(db, rule_code, created_by="qc_admin", action_mode="WARN_ONLY")
    db.commit()
    assert allowed.version_no == 2


def test_adm_rec_lock_emr_allowed_after_20261113_rework(db):
    """2026-11-13 返工：ADM_REC 的 D8 封锁解除（生产 2026-11-10 销账），允许 LOCK_EMR。"""
    seed_rules(db)
    version = append_rule_version(db, "ADM_REC", created_by="qc_admin", action_mode="LOCK_EMR")
    db.commit()
    assert version.action_mode == "LOCK_EMR"


def test_d8_constants_fixed():
    # 2026-11-13 返工：仅 CHIEF_FIRST_ROUND（JH04.02.008，余 251 条幽灵行）维持 D8。
    assert D8_NO_LOCK_RULE_CODES == frozenset({"CHIEF_FIRST_ROUND"})


@pytest.mark.parametrize(
    "changes",
    [
        {"action_mode": "LOCK"},
        {"completion_basis": "SIGN"},
        {"limit_minutes": -1},
        {"limit_minutes": "60"},
        {"warn_before_minutes": True},
        {"workday_only": "yes"},
        {"target_json": "{not json"},
        {"trigger_type": ""},
        {"enabled": True},  # 启停不属于版本字段
    ],
)
def test_append_version_rejects_invalid_changes(db, changes):
    seed_rules(db)
    with pytest.raises(RuleVersionError):
        append_rule_version(db, "FIRST_COURSE", created_by="qc_admin", **changes)
    db.rollback()
    assert db.query(TLRuleVersion).count() == 18


def test_append_version_requires_rule_and_operator(db):
    seed_rules(db)
    with pytest.raises(RuleVersionError):
        append_rule_version(db, "NO_SUCH_RULE", created_by="qc_admin")
    with pytest.raises(RuleVersionError):
        append_rule_version(db, "FIRST_COURSE", created_by="", limit_minutes=60)
    db.rollback()
    assert db.query(TLRuleVersion).count() == 18


# ---------- Oracle 兼容（离线） ----------


def test_oracle_physical_identifiers_within_30(monkeypatch):
    monkeypatch.setenv("APP_DB_TYPE", "oracle")
    for name in TIMELINESS_TABLE_NAMES:
        physical = _table_name(name)
        assert physical == f"MED_{name.upper()}"
        assert len(physical) <= 30
        sequence = _oracle_sequence_name(name)
        assert sequence == f"SEQ_MED_{name.upper()}"  # 未触发哈希截断
        assert len(sequence) <= 30
    for model in TL_MODELS:
        for column in model.__table__.columns:
            assert len(column.name) <= 30, column.name
        for index in model.__table__.indexes:
            assert len(index.name) <= 30, index.name


def test_oracle_ddl_compiles_under_30_char_limit():
    dialect = oracle.dialect()
    dialect.max_identifier_length = 30  # 生产应用库 Oracle 11.2
    for model in TL_MODELS:
        str(CreateTable(model.__table__).compile(dialect=dialect))
        for index in model.__table__.indexes:
            str(CreateIndex(index).compile(dialect=dialect))  # 超长显式名会抛 IdentifierError
    action_ddl = str(CreateTable(TLActionLog.__table__).compile(dialect=dialect))
    assert '"mode" VARCHAR2(16 CHAR) NOT NULL' in action_ddl  # Oracle 保留字自动加引号
    rule_ddl = str(CreateTable(TLRule.__table__).compile(dialect=dialect))
    assert "enabled SMALLINT NOT NULL" in rule_ddl


def test_lob_columns_placed_after_non_lob_columns():
    """Oracle INSERT...RETURNING 要求 CLOB 绑定位于所有非 LOB 绑定之后（ORA-24816）。"""
    for model in TL_MODELS:
        is_lob = [isinstance(column.type, Text) for column in model.__table__.columns]
        if True in is_lob:
            first_lob = is_lob.index(True)
            assert all(is_lob[first_lob:]), model.__tablename__


# ---------- 与 app/database.py 的集成 ----------


def test_verify_required_schema_covers_tl_tables(monkeypatch, tmp_path):
    schema_engine = create_engine(f"sqlite:///{tmp_path / 'schema.db'}")
    try:
        Base.metadata.create_all(schema_engine)
        monkeypatch.setattr(database, "engine", schema_engine)
        database._verify_required_schema()  # 主表 + tl_* 表齐全时通过

        with schema_engine.begin() as conn:
            conn.execute(text("DROP TABLE tl_approval"))
        with pytest.raises(RuntimeError, match="tl_approval"):
            database._verify_required_schema()
    finally:
        schema_engine.dispose()


def test_init_db_in_isolated_tmp_workspace_creates_tl_tables(tmp_path):
    """T2 验收：临时隔离目录用 SQLite 跑一次 init_db() 建出 7 张表（TEST_ISOLATED_MODE，不碰 data/）。"""
    run_id = "t2-timeliness"
    env = os.environ.copy()
    env.pop("DEMO_MODE", None)
    env.update(
        {
            "TEST_ISOLATED_MODE": "1",
            "DEMO_RUN_ID": run_id,
            "DEMO_WORKSPACE_ROOT": str(tmp_path),
            "DATA_DIR": str(tmp_path / "data" / "demo" / run_id),
            "CONFIG_DIR": str(tmp_path / "config" / "demo" / run_id),
            "LOG_DIR": str(tmp_path / "logs" / "demo" / run_id),
            "APP_DB_TYPE": "sqlite",
            "ENABLE_SCHEDULER": "false",
            "ENVIRONMENT": "development",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    code = textwrap.dedent(
        """
        import json, sqlite3
        from app import config
        from app.database import SessionLocal, init_db

        init_db()  # 7 张表只能经 init_db 内的导入注册后建出

        from app.timeliness.rules_seed import seed_rules

        db = SessionLocal()
        try:
            first = seed_rules(db)
            second = seed_rules(db)
        finally:
            db.close()
        conn = sqlite3.connect(config.DB_PATH)
        try:
            names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            tables = sorted(n for n in names if n.startswith("tl_"))
            columns = {t: sorted(r[1] for r in conn.execute(f"PRAGMA table_info({t})")) for t in tables}
            rule_count = conn.execute("SELECT COUNT(*) FROM tl_rule").fetchone()[0]
        finally:
            conn.close()
        print("T2_RESULT=" + json.dumps({
            "db_path": config.DB_PATH,
            "tables": tables,
            "columns": columns,
            "first_created": len(first["created"]),
            "second_created": len(second["created"]),
            "second_skipped": len(second["skipped"]),
            "rule_count": rule_count,
        }))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    line = next(item for item in proc.stdout.splitlines() if item.startswith("T2_RESULT="))
    result = json.loads(line[len("T2_RESULT="):])

    assert Path(result["db_path"]).resolve().is_relative_to(tmp_path.resolve())
    assert result["tables"] == sorted(TIMELINESS_TABLE_NAMES)
    for table in TIMELINESS_TABLE_NAMES:
        assert set(result["columns"][table]) == EXPECTED_COLUMNS[table], table
    assert (result["first_created"], result["second_created"], result["second_skipped"]) == (18, 0, 18)
    assert result["rule_count"] == 18
