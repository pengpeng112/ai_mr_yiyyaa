"""T3：app/timeliness/engine/ 规则引擎纯函数表驱动测试。

覆盖（主设计文档 §15 T3）：deadline 加法与工作日跳过、matchers 完成时间
铁律（E12/R1/E13：签名时间为空即未完成、不用 file_flag）、state 状态转换
表与推导优先级、triggers 各触发类型 event_uid/t0、D4 外部源接口桩
（NotConfiguredSource）、evaluate 端到端（未到期/预警/超时/按时完成/
超时完成/草稿未签/文书早于 t0/多次手术/出院后取消/审批/工作日），
以及源码扫描：engine 下所有文件不得 import psycopg2/requests/sqlalchemy。
测试数据用 §10.1 生产真实编码与标题样例（EMR09.00.01/EMR10.00.01/
EMR10.00.03/EMR12.00、“刘志勇主治医师查房记录”“术后首次病程记录”等）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.timeliness.engine import (
    EXTERNAL_TRIGGER_SOURCES,
    EXTERNAL_TRIGGER_TYPES,
    ExternalEventSource,
    NotConfiguredSource,
    TriggerDataError,
    evaluate,
    register_external_source,
)
from app.timeliness.engine import deadline as deadline_mod
from app.timeliness.engine import matchers as matchers_mod
from app.timeliness.engine import state as state_mod
from app.timeliness.engine import triggers as triggers_mod

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_DIR = REPO_ROOT / "app" / "timeliness" / "engine"

# 2026-11-06 为星期五（测试内断言固化，防止日历假设漂移）。
FRI = datetime(2026, 11, 6, 10, 0)
SAT, SUN = date(2026, 11, 7), date(2026, 11, 8)
T0 = datetime(2026, 11, 3, 8, 0)  # 通用起算时间（星期二 08:00）

FORBIDDEN_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+(psycopg2|requests|sqlalchemy)\b", re.MULTILINE)


# ---------- 通用构造器 ----------

def make_rule(**overrides) -> dict:
    """默认 = FIRST_COURSE 口径（§10.1 真实编码），可按用例覆盖。"""
    rule = {
        "rule_code": "FIRST_COURSE",
        "rule_version_id": 11,
        "trigger_type": "ADMISSION",
        "target_json": {"mr_class": ["EMR10.00.01"]},
        "completion_basis": "FIRST_SIGN",
        "limit_minutes": 480,
        "workday_only": False,
        "warn_before_minutes": 60,
        "jhemr_monitor_code": "JH04.02.002",
        "dept_scope_json": [],
        "trigger_filter_json": {},
    }
    rule.update(overrides)
    return rule


def inpatient(**overrides) -> dict:
    row = {"patient_id": "P1", "visit_id": "1", "dept_code": "D01", "admission_date_time": T0}
    row.update(overrides)
    return row


def file_row(**overrides) -> dict:
    row = {
        "patient_id": "P1",
        "visit_id": "1",
        "file_unique_id": "F-1",
        "mr_class": "EMR10.00.01",
        "topic": "首次病程记录（骨折）",
        "monitor_code": None,
        "file_flag": "1",
        "create_date_time": T0 + timedelta(minutes=30),
        "first_mr_sign_date_time": T0 + timedelta(minutes=300),
        "last_modify_date_time": None,
        "topic_title_name": None,
        "dept_code": "D01",
        "delete_flag": 0,
    }
    row.update(overrides)
    return row


def approval(**overrides) -> dict:
    row = {
        "patient_id": "P1",
        "visit_id": "1",
        "monitor_code": "JH04.02.002",
        "apply_date_time": T0 + timedelta(hours=10),
        "flag": 1,
    }
    row.update(overrides)
    return row


# ---------- deadline.py ----------

class TestDeadline:
    @pytest.mark.parametrize(
        "limit_minutes, expected",
        [
            (480, T0 + timedelta(minutes=480)),
            (0, T0),  # PREOP_SUMMARY：截止=手术开始
            (1440, T0 + timedelta(days=1)),
        ],
    )
    def test_plain_addition(self, limit_minutes, expected):
        assert deadline_mod.compute_deadline(T0, limit_minutes) == expected

    def test_none_limit_returns_none(self):
        assert deadline_mod.compute_deadline(T0, None) is None  # 时限待定

    def test_negative_limit_raises(self):
        with pytest.raises(ValueError):
            deadline_mod.compute_deadline(T0, -1)

    def test_workday_only_skips_weekend(self):
        # 周五 10:00 + 5 个工作日（7200 分钟），跳过周六周日 → 下周五 10:00。
        assert deadline_mod.compute_deadline(FRI, 5 * 1440, workday_only=True, non_workdays=[SAT, SUN]) == FRI + timedelta(days=7)

    def test_workday_only_all_workdays_equals_plain(self):
        assert deadline_mod.compute_deadline(FRI, 2880, workday_only=True, non_workdays=[]) == FRI + timedelta(minutes=2880)

    def test_workday_only_accepts_iso_strings(self):
        got = deadline_mod.compute_deadline(FRI, 1440, workday_only=True, non_workdays=["2026-11-07", "2026-11-08"])
        # 周五耗掉 840 分钟，剩 600 分钟跳过周末后于周一 00:00-10:00 耗尽。
        assert got == datetime(2026, 11, 9, 10, 0)

    def test_workday_only_pathological_set_raises(self):
        every_day = [FRI.date() + timedelta(days=i) for i in range(4000)]
        with pytest.raises(ValueError):
            deadline_mod.compute_deadline(FRI, 1440, workday_only=True, non_workdays=every_day)

    @pytest.mark.parametrize(
        "warn, expected",
        [
            (60, T0 + timedelta(minutes=420)),
            (None, None),
        ],
    )
    def test_warn_threshold(self, warn, expected):
        assert deadline_mod.warn_threshold(T0 + timedelta(minutes=480), warn) == expected

    def test_warn_threshold_invalid_raises(self):
        with pytest.raises(ValueError):
            deadline_mod.warn_threshold(T0, -5)

    @pytest.mark.parametrize(
        "now, limit, expected",
        [
            (T0 + timedelta(minutes=479), 480, 0),
            (T0 + timedelta(minutes=480), 480, 0),  # 恰好到截止不算超时
            (T0 + timedelta(minutes=540), 480, 60),
        ],
    )
    def test_overdue_minutes(self, now, limit, expected):
        assert deadline_mod.overdue_minutes(now, T0 + timedelta(minutes=limit)) == expected

    def test_overdue_minutes_without_deadline(self):
        assert deadline_mod.overdue_minutes(T0, None) == 0


# ---------- matchers.py ----------

class TestMatchers:
    @pytest.mark.parametrize(
        "delete_flag, active",
        [
            (0, True),
            ("0", True),
            ("", True),
            (None, True),
            (1, False),
            ("1", False),
            ("2", False),
        ],
    )
    def test_is_active_file(self, delete_flag, active):
        assert matchers_mod.is_active_file({"delete_flag": delete_flag}) is active

    @pytest.mark.parametrize(
        "target, topic, mr_class, expected",
        [
            ({"mr_class": ["EMR10.00.03"]}, "刘志勇主治医师查房记录", "EMR10.00.03", True),
            ({"mr_class": ["EMR10.00.03"]}, "日常病程记录", "EMR10.00.02", False),
            ({"mr_class": ["EMR09.00.01", "EMR09.00.02", "EMR09.00.03"]}, "胬肉日间出入院", "EMR09.00.02", True),
            ({"title_contains_any": ["主治", "副主任", "主任"]}, "刘志勇主治医师查房记录", "EMR10.00.03", True),
            ({"title_contains_any": ["主任"]}, "刘志勇主治医师查房记录", "EMR10.00.03", False),
            ({"title_contains_any": ["主任"]}, "宋英华主任医师查房记录", "EMR10.00.03", True),
            ({"title_contains_all": ["术后", "首次"]}, "术后首次病程记录", "EMR10.00.12", True),
            ({"title_contains_all": ["术后", "首次"]}, "术后病程记录", "EMR10.00.12", False),
            ({"monitor_code": "JH04.03.016"}, "危急值处置病程记录", "EMR10.00.02", True),
            ({"monitor_code": ["JH04.03.016"]}, "日常病程记录", "EMR10.00.02", False),
            ({}, "任意标题", "EMR10.00.02", True),  # 空条件=不过滤
        ],
    )
    def test_file_matches_target(self, target, topic, mr_class, expected):
        row = file_row(topic=topic, mr_class=mr_class, monitor_code="JH04.03.016" if "危急" in topic else None)
        assert matchers_mod.file_matches_target(row, target) is expected

    def test_target_json_as_string_accepted(self):
        target = '{"mr_class": ["EMR12.00"], "title_contains_any": ["出院"]}'
        assert matchers_mod.file_matches_target(file_row(topic="鼻息肉出院", mr_class="EMR12.00"), matchers_mod.load_target(target))

    def test_completion_time_by_basis(self):
        row = file_row()  # 同时含 create(+30min) 与 sign(+300min)
        assert matchers_mod.completion_time(row, "FIRST_SIGN") == T0 + timedelta(minutes=300)
        assert matchers_mod.completion_time(row, "CREATE") == T0 + timedelta(minutes=30)
        # FIRST_SIGN 只看签名字段：签名为空即未完成，与创建时间无关。
        assert matchers_mod.completion_time(file_row(first_mr_sign_date_time=None), "FIRST_SIGN") is None

    def test_completion_time_unknown_basis_raises(self):
        with pytest.raises(matchers_mod.TargetConfigError):
            matchers_mod.completion_time(file_row(), "WHATEVER")

    def test_find_completion_picks_earliest(self):
        early = file_row(file_unique_id="F-early", first_mr_sign_date_time=T0 + timedelta(minutes=60))
        late = file_row(file_unique_id="F-late", first_mr_sign_date_time=T0 + timedelta(minutes=200))
        result = matchers_mod.find_completion([late, early], target={"mr_class": ["EMR10.00.01"]})
        assert result is not None and result.file_unique_id == "F-early"

    def test_draft_unsigned_is_not_complete(self):
        # R1/E12：草稿 file_flag='T' 且未签名 → 未完成，即使已创建。
        draft = file_row(file_flag="T", first_mr_sign_date_time=None, create_date_time=T0 + timedelta(minutes=10))
        assert matchers_mod.find_completion([draft], target={"mr_class": ["EMR10.00.01"]}) is None

    def test_file_flag_one_without_sign_time_is_not_complete(self):
        # E13：严禁用 file_flag=='1' 判完成；签名时间为空即未完成。
        row = file_row(file_flag="1", first_mr_sign_date_time=None)
        assert matchers_mod.find_completion([row], target={"mr_class": ["EMR10.00.01"]}) is None

    def test_file_flag_variants_with_sign_time_all_complete(self):
        # E13：已签名文书 file_flag 实测有 0/1/2/3——只要签名时间在即为完成。
        for flag in ("0", "1", "2", "3"):
            row = file_row(file_flag=flag, first_mr_sign_date_time=T0 + timedelta(minutes=100))
            result = matchers_mod.find_completion([row], target={"mr_class": ["EMR10.00.01"]})
            assert result is not None and result.completed_at == T0 + timedelta(minutes=100)

    def test_deleted_file_ignored(self):
        deleted = file_row(delete_flag=1, first_mr_sign_date_time=T0 + timedelta(minutes=100))
        assert matchers_mod.find_completion([deleted], target={"mr_class": ["EMR10.00.01"]}) is None

    def test_completion_before_t0_excluded_when_required(self):
        signed_before = file_row(first_mr_sign_date_time=T0 - timedelta(minutes=30))
        assert matchers_mod.find_completion(
            [signed_before], target={"mr_class": ["EMR10.00.01"]}, t0=T0, require_time_ge_t0=True
        ) is None

    def test_completion_exactly_at_t0_counts(self):
        exactly = file_row(first_mr_sign_date_time=T0)
        result = matchers_mod.find_completion([exactly], target={"mr_class": ["EMR10.00.01"]}, t0=T0, require_time_ge_t0=True)
        assert result is not None and result.completed_at == T0

    def test_completion_before_t0_counts_when_not_required(self):
        signed_before = file_row(first_mr_sign_date_time=T0 - timedelta(hours=2))
        result = matchers_mod.find_completion([signed_before], target={"mr_class": ["EMR10.00.01"]}, t0=T0)
        assert result is not None  # 入院类不要求文书时间 ≥ t0

    def test_require_time_ge_t0_without_t0_raises(self):
        with pytest.raises(ValueError):
            matchers_mod.find_completion([file_row()], target={"mr_class": ["EMR10.00.01"]}, require_time_ge_t0=True)


# ---------- state.py ----------

LEGAL_TRANSITIONS = [
    ("PENDING", "WARNING"),
    ("PENDING", "APPLYING"),
    ("WARNING", "OVERDUE"),
    ("OVERDUE", "APPLYING"),
    ("OVERDUE", "COMPLETED_ON_TIME"),  # 截止后发现早已签名：按签名时间判按时
    ("OVERDUE", "COMPLETED_LATE"),
    ("APPLYING", "OVERDUE"),
    ("APPLYING", "PENDING"),  # 申请记录滑出扫描窗口后回退到时钟态
    ("APPLYING", "APPROVED"),
    ("APPROVED", "COMPLETED_LATE"),
    ("PENDING", "EXEMPT"),
    ("WARNING", "CANCELLED"),
]

ILLEGAL_TRANSITIONS = [
    ("COMPLETED_ON_TIME", "OVERDUE"),
    ("COMPLETED_LATE", "APPLYING"),
    ("CANCELLED", "PENDING"),
    ("EXEMPT", "WARNING"),
    ("APPROVED", "OVERDUE"),  # 审批决定不因时钟回退
    ("APPROVED", "PENDING"),
    ("WARNING", "PENDING"),  # 时钟推进单调：进入预警窗后不会回到未预警
]


class TestState:
    @pytest.mark.parametrize("from_status, to_status", LEGAL_TRANSITIONS)
    def test_legal_transition(self, from_status, to_status):
        assert state_mod.transition(from_status, to_status) == to_status

    @pytest.mark.parametrize("from_status, to_status", ILLEGAL_TRANSITIONS)
    def test_illegal_transition_raises(self, from_status, to_status):
        with pytest.raises(state_mod.IllegalStatusTransition):
            state_mod.transition(from_status, to_status)

    def test_same_status_is_noop(self):
        assert state_mod.transition("OVERDUE", "OVERDUE") == "OVERDUE"

    @pytest.mark.parametrize("status", ["BOGUS", ""])
    def test_unknown_status_raises(self, status):
        with pytest.raises(state_mod.IllegalStatusTransition):
            state_mod.transition(status, "PENDING")

    @pytest.mark.parametrize("status", ["COMPLETED_ON_TIME", "COMPLETED_LATE", "CANCELLED", "EXEMPT"])
    def test_terminal_statuses_have_no_outgoing(self, status):
        assert state_mod.is_terminal(status) is True
        assert len(state_mod.STATUS_TRANSITIONS[status]) == 0

    def test_transition_table_covers_all_statuses(self):
        assert set(state_mod.STATUS_TRANSITIONS) == set(state_mod.EVENT_STATUSES)

    @pytest.mark.parametrize(
        "flag, expected",
        [(1, "1"), ("1", "1"), (" 2 ", "2"), (2, "2"), ("2", "2"), ("0", None), (3, None), (None, None), ("", None), ("x", None)],
    )
    def test_normalize_approval_flag(self, flag, expected):
        assert state_mod.normalize_approval_flag(flag) == expected

    @pytest.mark.parametrize(
        "now_offset_min, warn, expected",
        [
            (60, 60, "PENDING"),     # 预警窗前
            (420, 60, "WARNING"),    # 恰进入预警窗（deadline-warn）
            (479, 60, "WARNING"),
            (480, 60, "WARNING"),    # 恰好到截止：未“超过”，仍在预警窗
            (481, 60, "OVERDUE"),
            (481, None, "OVERDUE"),
            (479, None, "PENDING"),  # 未配预警：无 WARNING 态
        ],
    )
    def test_derive_clock_states(self, now_offset_min, warn, expected):
        deadline = T0 + timedelta(minutes=480)
        assert state_mod.derive_status(now=T0 + timedelta(minutes=now_offset_min), deadline=deadline, warn_before_minutes=warn) == expected

    @pytest.mark.parametrize(
        "completed_offset_min, expected",
        [
            (300, "COMPLETED_ON_TIME"),
            (480, "COMPLETED_ON_TIME"),  # 截止时刻完成=按时
            (481, "COMPLETED_LATE"),
        ],
    )
    def test_derive_completion_states(self, completed_offset_min, expected):
        deadline = T0 + timedelta(minutes=480)
        assert state_mod.derive_status(
            now=T0 + timedelta(minutes=600), deadline=deadline, completed_at=T0 + timedelta(minutes=completed_offset_min)
        ) == expected

    def test_derive_completion_without_deadline_is_on_time(self):
        assert state_mod.derive_status(now=T0, deadline=None, completed_at=T0 + timedelta(days=3)) == "COMPLETED_ON_TIME"

    def test_derive_no_deadline_pending(self):
        assert state_mod.derive_status(now=T0 + timedelta(days=30), deadline=None) == "PENDING"

    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({"approval_flag": 1}, "APPLYING"),
            ({"approval_flag": "2"}, "APPROVED"),
            ({"approval_flag": "2", "cancelled": True}, "CANCELLED"),        # 取消优先于审批
            ({"approval_flag": "2", "exempt": True}, "EXEMPT"),              # 豁免优先于审批
            ({"completed_at": T0, "cancelled": True}, "COMPLETED_ON_TIME"),  # 完成优先于取消
            ({"previous_status": "APPROVED"}, "APPROVED"),                   # 审批决定粘滞
            ({"previous_status": "APPROVED", "completed_at": T0 + timedelta(hours=9)}, "COMPLETED_LATE"),
        ],
    )
    def test_derive_precedence(self, kwargs, expected):
        assert state_mod.derive_status(
            now=T0 + timedelta(hours=9), deadline=T0 + timedelta(hours=8), **kwargs
        ) == expected


# ---------- triggers.py ----------

class TestTriggers:
    def test_uid_format(self):
        assert triggers_mod.make_event_uid("FIRST_COURSE", " P1 ", "1", "1") == "FIRST_COURSE:P1:1:1"

    @pytest.mark.parametrize("part", [None, "", "  "])
    def test_uid_empty_part_raises(self, part):
        with pytest.raises(TriggerDataError):
            triggers_mod.make_event_uid("R", "P1", part, "1")

    @pytest.mark.parametrize(
        "rule_code, trigger_type, row, expected_uid, expected_t0",
        [
            ("ADM_REC", "ADMISSION", inpatient(), "ADM_REC:P1:1:1", T0),
            ("DISCHARGE_REC", "DISCHARGE", {"patient_id": "P1", "visit_id": "1", "discharge_date_time": T0}, "DISCHARGE_REC:P1:1:1", T0),
            ("DEATH_REC", "DEATH", {"patient_id": "P9", "visit_id": "2", "death_date_time": T0}, "DEATH_REC:P9:2:2", T0),
            (
                "OP_REC",
                "OPERATION_END",
                {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-7", "operating_end_date": T0},
                "OP_REC:P1:1:OP-7",
                T0,
            ),
            (
                "PREOP_SUMMARY",
                "OPERATION_START",
                {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-7", "operating_date": T0},
                "PREOP_SUMMARY:P1:1:OP-7",
                T0,
            ),
            (
                "CONSULT_EMERGENCY",
                "CONSULT_APPLY",
                {"patient_id": "P1", "visit_id": "1", "applyid": "AP-77", "apply_date_time": T0},
                "CONSULT_EMERGENCY:P1:1:AP-77",
                T0,
            ),
            (
                "CRITICAL_VALUE_COURSE",
                "CRITICAL_VALUE",
                {"trigger_type": "CRITICAL_VALUE", "source_event_id": "CV-001", "patient_id": "P1", "visit_id": "1", "event_time": T0},
                "CRITICAL_VALUE_COURSE:P1:1:CV-001",
                T0,
            ),
            (
                "DIFFICULT_CASE",
                "MANUAL_OR_INDICATOR",
                {"patient_id": "P1", "visit_id": "1", "event_time": T0, "indicator_id": "IND-3"},
                "DIFFICULT_CASE:P1:1:IND-3",
                T0,
            ),
        ],
    )
    def test_uid_and_t0_per_trigger_type(self, rule_code, trigger_type, row, expected_uid, expected_t0):
        events = triggers_mod.build_trigger_events(rule_code, trigger_type, [row])
        assert len(events) == 1
        assert events[0].event_uid == expected_uid
        assert events[0].t0 == expected_t0

    def test_operation_end_time_uses_verified_column(self):
        # 2026-11-10 实证：operation 表唯一结束时间列 = operating_end_date。
        row = {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-1", "operating_end_date": T0}
        events = triggers_mod.build_trigger_events("OP_REC", "OPERATION_END", [row])
        assert events[0].t0 == T0
        # 旧候选名（未实证存在）不再生效：只给 operation_end_date_time 时不产出事件。
        stale = {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-1", "operation_end_date_time": T0}
        assert triggers_mod.build_trigger_events("OP_REC", "OPERATION_END", [stale]) == []

    def test_operation_row_without_end_time_skipped(self):
        row = {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-1", "operating_date": T0}
        assert triggers_mod.build_trigger_events("OP_REC", "OPERATION_END", [row]) == []

    def test_row_without_patient_skipped_not_raised(self):
        bad = {"visit_id": "1", "admission_date_time": T0}
        assert triggers_mod.build_trigger_events("ADM_REC", "ADMISSION", [bad]) == []

    @pytest.mark.parametrize("missing", ["source_event_id", "patient_id", "visit_id", "event_time"])
    def test_validate_external_event_missing_field_raises(self, missing):
        row = {"source_system": "LIS", "source_event_id": "CV-1", "patient_id": "P1", "visit_id": "1", "event_time": T0}
        row.pop(missing)
        with pytest.raises(TriggerDataError):
            triggers_mod.validate_external_event(row)

    def test_validate_external_event_bad_time_raises(self):
        row = {"source_event_id": "CV-1", "patient_id": "P1", "visit_id": "1", "event_time": "not-a-time"}
        with pytest.raises(ValueError):
            triggers_mod.validate_external_event(row)

    @pytest.mark.parametrize(
        "trigger_filter, expected",
        [
            (None, True),
            ({}, True),
            ({"apply_type": "1"}, True),
            ({"apply_type": "2"}, False),
            ({"apply_type": ["1", "3"]}, True),
            ({"apply_type": ["2"]}, False),
            ({"consult_class": "急"}, False),  # 字段缺失视为不匹配
        ],
    )
    def test_apply_trigger_filter(self, trigger_filter, expected):
        row = {"patient_id": "P1", "visit_id": "1", "applyid": "A1", "apply_date_time": T0, "apply_type": "1"}
        assert triggers_mod.apply_trigger_filter(row, trigger_filter) is expected

    def test_duplicate_uid_deduped(self):
        row = inpatient()
        events = triggers_mod.build_trigger_events("ADM_REC", "ADMISSION", [row, dict(row)])
        assert len(events) == 1

    def test_unknown_trigger_type_raises(self):
        with pytest.raises(ValueError):
            triggers_mod.build_trigger_events("R", "NO_SUCH", [inpatient()])


class TestExternalSources:
    def test_not_configured_source_returns_empty_and_marks_status(self):
        source = NotConfiguredSource()
        assert source.fetch_events(T0, T0 + timedelta(days=1)) == []
        assert source.status == "NOT_CONFIGURED"

    def test_registry_defaults_all_not_configured(self):
        assert set(EXTERNAL_TRIGGER_SOURCES) == set(EXTERNAL_TRIGGER_TYPES)
        for trigger_type, source in EXTERNAL_TRIGGER_SOURCES.items():
            assert isinstance(source, NotConfiguredSource)
            assert source.status == "NOT_CONFIGURED"

    def test_register_and_restore_external_source(self):
        class FakeSource(ExternalEventSource):
            source_system = "fake_lis"

            def fetch_events(self, since, until):
                return [{
                    "source_system": "fake_lis", "source_event_id": "CV-9", "patient_id": "P1",
                    "visit_id": "1", "event_time": T0, "dept_code": "D01", "doctor_id": "DOC1", "detail": {},
                }]

        original = EXTERNAL_TRIGGER_SOURCES["CRITICAL_VALUE"]
        try:
            register_external_source("CRITICAL_VALUE", FakeSource())
            registered = EXTERNAL_TRIGGER_SOURCES["CRITICAL_VALUE"]
            assert registered.status == "READY"
            assert registered.fetch_events(T0, T0)[0]["source_event_id"] == "CV-9"
        finally:
            register_external_source("CRITICAL_VALUE", original)

    def test_register_rejects_unknown_type_and_bad_source(self):
        with pytest.raises(ValueError):
            register_external_source("NO_SUCH_TYPE", NotConfiguredSource())
        with pytest.raises(TypeError):
            register_external_source("TRANSFUSION", object())


# ---------- evaluate.py 端到端 ----------

class TestEvaluateAdmissionRule:
    @pytest.mark.parametrize(
        "now_offset_min, files, expected",
        [
            (60, [], "PENDING"),                       # 未到期
            (430, [], "WARNING"),                      # 进入预警窗（deadline-60=420）
            (480, [], "WARNING"),                      # 恰好到截止未超过
            (481, [], "OVERDUE"),                      # 超过截止
            (300, [file_row()], "COMPLETED_ON_TIME"),  # 按时完成（签名 300min）
            (600, [file_row(first_mr_sign_date_time=T0 + timedelta(minutes=500))], "COMPLETED_LATE"),  # 超时完成
        ],
    )
    def test_clock_and_completion_states(self, now_offset_min, files, expected):
        results = evaluate(make_rule(), T0 + timedelta(minutes=now_offset_min), {"inpatients": [inpatient()], "files": files})
        assert [r.status for r in results] == [expected]

    def test_overdue_minutes_reported(self):
        results = evaluate(make_rule(), T0 + timedelta(minutes=540), {"inpatients": [inpatient()]})
        assert results[0].status == "OVERDUE"
        assert results[0].overdue_minutes == 60

    def test_late_completion_overdue_minutes_from_completed_at(self):
        signed = file_row(first_mr_sign_date_time=T0 + timedelta(minutes=500))
        results = evaluate(make_rule(), T0 + timedelta(minutes=900), {"inpatients": [inpatient()], "files": [signed]})
        assert results[0].status == "COMPLETED_LATE"
        assert results[0].overdue_minutes == 20

    @pytest.mark.parametrize(
        "draft, expected",
        [
            (file_row(file_flag="T", first_mr_sign_date_time=None), "PENDING"),   # 只有草稿：未完成
            (file_row(file_flag="T", first_mr_sign_date_time=None), "OVERDUE"),  # 草稿且已超时
        ],
    )
    def test_draft_only_is_not_complete(self, draft, expected):
        now_offset = 100 if expected == "PENDING" else 600
        results = evaluate(make_rule(), T0 + timedelta(minutes=now_offset), {"inpatients": [inpatient()], "files": [draft]})
        assert results[0].status == expected
        assert results[0].completed_at is None

    def test_result_fields_align_with_ledger(self):
        results = evaluate(make_rule(), T0 + timedelta(minutes=60), {"inpatients": [inpatient()]})
        (r,) = results
        assert r.event_uid == "FIRST_COURSE:P1:1:1"
        assert r.rule_code == "FIRST_COURSE"
        assert r.t0 == T0
        assert r.deadline == T0 + timedelta(minutes=480)
        assert r.warn_deadline == T0 + timedelta(minutes=420)
        assert r.status_before is None and r.status_changed is True
        assert r.rule_version_id == 11
        assert r.dept_code == "D01"

    def test_completion_before_admission_counts_for_admission_rule(self):
        # 入院类不要求文书时间 ≥ t0：入院前已签的记录也认。
        signed_before = file_row(first_mr_sign_date_time=T0 - timedelta(hours=1))
        results = evaluate(make_rule(), T0 + timedelta(minutes=60), {"inpatients": [inpatient()], "files": [signed_before]})
        assert results[0].status == "COMPLETED_ON_TIME"

    def test_files_of_other_visits_ignored(self):
        other_visit = file_row(patient_id="P2", visit_id="9")
        results = evaluate(make_rule(), T0 + timedelta(minutes=60), {"inpatients": [inpatient()], "files": [other_visit]})
        assert results[0].status == "PENDING"


class TestEvaluateOperationRule:
    def make_op_rule(self) -> dict:
        return make_rule(
            rule_code="OP_REC",
            trigger_type="OPERATION_END",
            target_json={"mr_class": ["EMR05.01.02"]},
            jhemr_monitor_code="JH04.03.012",
            limit_minutes=1440,
        )

    def op_row(self, **overrides) -> dict:
        row = {"patient_id": "P1", "visit_id": "1", "operation_no": "OP-1", "operating_end_date": T0}
        row.update(overrides)
        return row

    def op_file(self, **overrides) -> dict:
        return file_row(mr_class="EMR05.01.02", topic="鼻骨折闭合性复位术手术记录", **overrides)

    def test_doc_signed_before_operation_end_not_counted(self):
        # 文书早于 t0 不算（手术类要求完成发生在触发之后）。
        signed_before = self.op_file(first_mr_sign_date_time=T0 - timedelta(hours=2))
        results = evaluate(
            self.make_op_rule(), T0 + timedelta(hours=30),
            {"operations": [self.op_row()], "files": [signed_before]},
        )
        assert results[0].status == "OVERDUE"

    def test_doc_signed_after_operation_end_counted(self):
        signed = self.op_file(first_mr_sign_date_time=T0 + timedelta(hours=10))
        results = evaluate(
            self.make_op_rule(), T0 + timedelta(hours=30),
            {"operations": [self.op_row()], "files": [signed]},
        )
        assert results[0].status == "COMPLETED_ON_TIME"

    def test_multiple_operations_timed_separately(self):
        # 多次手术各自计时：两台手术分别建事件、各自 deadline/状态。
        op1 = self.op_row(operation_no="OP-1", operating_end_date=datetime(2026, 11, 2, 8, 0))
        op2 = self.op_row(operation_no="OP-2", operating_end_date=datetime(2026, 11, 3, 9, 0))
        files = [self.op_file(file_unique_id="F-OP1", first_mr_sign_date_time=datetime(2026, 11, 2, 20, 0))]
        results = evaluate(self.make_op_rule(), datetime(2026, 11, 4, 8, 30), {"operations": [op1, op2], "files": files})
        by_uid = {r.source_unique_id: r for r in results}
        assert set(by_uid) == {"OP-1", "OP-2"}
        assert by_uid["OP-1"].status == "COMPLETED_ON_TIME"      # 当天 20:00 已签
        assert by_uid["OP-2"].status == "WARNING"                # 截止 09:00 未到，08:00 起已进预警窗（warn=60）
        assert by_uid["OP-1"].deadline == datetime(2026, 11, 3, 8, 0)
        assert by_uid["OP-2"].deadline == datetime(2026, 11, 4, 9, 0)

    def test_target_time_ge_t0_override_false(self):
        # target_json 显式 time_ge_t0=false 覆盖默认：术前签名也算。
        rule = self.make_op_rule()
        rule["target_json"] = {"mr_class": ["EMR05.01.02"], "time_ge_t0": False}
        signed_before = self.op_file(first_mr_sign_date_time=T0 - timedelta(hours=2))
        results = evaluate(rule, T0 + timedelta(hours=30), {"operations": [self.op_row()], "files": [signed_before]})
        assert results[0].status == "COMPLETED_ON_TIME"


class TestEvaluateConsultRule:
    def make_consult_rule(self, limit: int) -> dict:
        return make_rule(
            rule_code="CONSULT_EMERGENCY",
            trigger_type="CONSULT_APPLY",
            target_json={"mr_class": ["EMR10.00.08", "EMR07.00.08"], "title_contains_any": ["会诊"]},
            jhemr_monitor_code="JH04.02.020",
            limit_minutes=limit,
            warn_before_minutes=None,
        )

    def consult_row(self, **overrides) -> dict:
        row = {"patient_id": "P1", "visit_id": "1", "applyid": "AP-77", "apply_date_time": T0, "apply_type": "1"}
        row.update(overrides)
        return row

    def test_emergency_consult_completed_within_10min(self):
        signed = file_row(mr_class="EMR10.00.08", topic="麻醉科会诊记录", first_mr_sign_date_time=T0 + timedelta(minutes=5))
        results = evaluate(self.make_consult_rule(10), T0 + timedelta(hours=1), {"consult_applies": [self.consult_row()], "files": [signed]})
        assert results[0].status == "COMPLETED_ON_TIME"

    def test_emergency_consult_overdue(self):
        results = evaluate(self.make_consult_rule(10), T0 + timedelta(minutes=11), {"consult_applies": [self.consult_row()]})
        assert results[0].status == "OVERDUE"
        assert results[0].overdue_minutes == 1

    def test_consult_doc_before_apply_not_counted(self):
        signed_before = file_row(mr_class="EMR10.00.08", topic="麻醉科会诊记录", first_mr_sign_date_time=T0 - timedelta(minutes=5))
        results = evaluate(
            self.make_consult_rule(10), T0 + timedelta(minutes=11),
            {"consult_applies": [self.consult_row()], "files": [signed_before]},
        )
        assert results[0].status == "OVERDUE"

    def test_trigger_filter_selects_apply_type(self):
        rule = self.make_consult_rule(10)
        rule["trigger_filter_json"] = {"apply_type": "2"}  # 只要普通会诊申请
        results = evaluate(rule, T0, {"consult_applies": [self.consult_row(apply_type="1"), self.consult_row(applyid="AP-78", apply_type="2")]})
        assert [r.source_unique_id for r in results] == ["AP-78"]


class TestEvaluateExternalRules:
    def make_cv_rule(self) -> dict:
        return make_rule(
            rule_code="CRITICAL_VALUE_COURSE",
            trigger_type="CRITICAL_VALUE",
            target_json={"mr_class": ["EMR10.00.02"], "title_contains_any": ["危急值"]},
            jhemr_monitor_code="JH04.03.016",
            limit_minutes=360,
        )

    def cv_event(self, **overrides) -> dict:
        row = {
            "trigger_type": "CRITICAL_VALUE", "source_system": "LIS", "source_event_id": "CV-001",
            "patient_id": "P1", "visit_id": "1", "event_time": T0, "dept_code": "D01", "doctor_id": "DOC1", "detail": {},
        }
        row.update(overrides)
        return row

    def test_external_event_produces_event(self):
        signed = file_row(mr_class="EMR10.00.02", topic="危急值处置病程记录", first_mr_sign_date_time=T0 + timedelta(minutes=120))
        results = evaluate(self.make_cv_rule(), T0 + timedelta(minutes=300), {"external_events": [self.cv_event()], "files": [signed]})
        (r,) = results
        assert r.event_uid == "CRITICAL_VALUE_COURSE:P1:1:CV-001"
        assert r.status == "COMPLETED_ON_TIME"
        assert r.responsible_doctor_id == "DOC1"

    def test_external_event_matched_by_source_system_lowercase(self):
        row = self.cv_event()
        row.pop("trigger_type")
        row["source_system"] = "critical_value"
        results = evaluate(self.make_cv_rule(), T0 + timedelta(minutes=10), {"external_events": [row]})
        assert len(results) == 1

    def test_external_event_of_other_system_not_matched(self):
        row = self.cv_event(trigger_type="TRANSFUSION")
        assert evaluate(self.make_cv_rule(), T0, {"external_events": [row]}) == []

    def test_external_rule_without_data_yields_no_events(self):
        # D4：NotConfiguredSource 恒返回空 → 评估无事件（扫描层另行记录 NOT_CONFIGURED）。
        assert EXTERNAL_TRIGGER_SOURCES["CRITICAL_VALUE"].fetch_events(T0, T0) == []
        assert evaluate(self.make_cv_rule(), T0, {}) == []

    def test_external_row_missing_required_field_skipped(self):
        bad = self.cv_event()
        bad.pop("event_time")
        assert evaluate(self.make_cv_rule(), T0, {"external_events": [bad]}) == []


class TestEvaluateCancellationAndApprovals:
    def test_cancelled_after_discharge(self):
        # 出院/删除/转出导致不再适用 → CANCELLED（调用方标记 event_uid）。
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "cancelled_event_uids": ["FIRST_COURSE:P1:1:1"]},
        )
        assert results[0].status == "CANCELLED"

    def test_cancelled_from_existing_overdue(self):
        existing = [{"event_uid": "FIRST_COURSE:P1:1:1", "status": "OVERDUE"}]
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "existing_events": existing, "cancelled_event_uids": ["FIRST_COURSE:P1:1:1"]},
        )
        assert results[0].status == "CANCELLED" and results[0].status_changed is True

    def test_exemption_marks_exempt(self):
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "exempt_event_uids": ["FIRST_COURSE:P1:1:1"]},
        )
        assert results[0].status == "EXEMPT"

    def test_approval_flag1_applying(self):
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "approvals": [approval(flag=1)]},
        )
        assert results[0].status == "APPLYING"

    def test_approval_flag2_approved(self):
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "approvals": [approval(flag=2)]},
        )
        assert results[0].status == "APPROVED"

    def test_latest_approval_wins(self):
        approvals = [
            approval(flag=1, apply_date_time=T0 + timedelta(hours=9)),
            approval(flag=2, apply_date_time=T0 + timedelta(hours=12)),
        ]
        results = evaluate(make_rule(), T0 + timedelta(hours=13), {"inpatients": [inpatient()], "approvals": approvals})
        assert results[0].status == "APPROVED"

    def test_approval_of_other_monitor_code_ignored(self):
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "approvals": [approval(monitor_code="JH04.02.001", flag=1)]},
        )
        assert results[0].status == "OVERDUE"  # 首程监控码不匹配入院监控码

    def test_existing_applying_regresses_to_clock_state(self):
        existing = [{"event_uid": "FIRST_COURSE:P1:1:1", "status": "APPLYING"}]
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "existing_events": existing},  # 申请日志已不在窗口
        )
        assert results[0].status == "OVERDUE"

    def test_existing_approved_stays_approved(self):
        existing = [{"event_uid": "FIRST_COURSE:P1:1:1", "status": "APPROVED"}]
        results = evaluate(
            make_rule(), T0 + timedelta(hours=20),
            {"inpatients": [inpatient()], "existing_events": existing},
        )
        assert results[0].status == "APPROVED" and results[0].status_changed is False

    @pytest.mark.parametrize("terminal", ["COMPLETED_ON_TIME", "COMPLETED_LATE", "CANCELLED", "EXEMPT"])
    def test_terminal_status_never_changes(self, terminal):
        existing = [{"event_uid": "FIRST_COURSE:P1:1:1", "status": terminal}]
        results = evaluate(
            make_rule(), T0 + timedelta(days=3),
            {"inpatients": [inpatient()], "existing_events": existing,
             "cancelled_event_uids": ["FIRST_COURSE:P1:1:1"]},
        )
        assert results[0].status == terminal and results[0].status_changed is False

    def test_existing_overdue_becomes_applying(self):
        existing = [{"event_uid": "FIRST_COURSE:P1:1:1", "status": "OVERDUE"}]
        results = evaluate(
            make_rule(), T0 + timedelta(minutes=600),
            {"inpatients": [inpatient()], "existing_events": existing, "approvals": [approval(flag=1)]},
        )
        assert results[0].status == "APPLYING" and results[0].status_changed is True


class TestEvaluateMisc:
    def test_attending_first_round_with_real_titles(self):
        # §10.1 真实标题样例：EMR10.00.03 + 标题含“主治/副主任/主任”。
        rule = make_rule(
            rule_code="ATTENDING_FIRST_ROUND",
            target_json={"mr_class": ["EMR10.00.03"], "title_contains_any": ["主治", "副主任", "主任"]},
            limit_minutes=2880,
        )
        signed = file_row(mr_class="EMR10.00.03", topic="刘志勇主治医师查房记录", first_mr_sign_date_time=T0 + timedelta(hours=24))
        results = evaluate(rule, T0 + timedelta(hours=30), {"inpatients": [inpatient()], "files": [signed]})
        assert results[0].status == "COMPLETED_ON_TIME"

    def test_chief_round_requires_chief_keyword(self):
        # “主任”关键词：主治查房标题不含“主任”，不满足主任/副主任首次查房。
        rule = make_rule(
            rule_code="CHIEF_FIRST_ROUND",
            target_json={"mr_class": ["EMR10.00.03"], "title_contains_any": ["主任"]},
            limit_minutes=10080,
        )
        attending_doc = file_row(mr_class="EMR10.00.03", topic="刘志勇主治医师查房记录", first_mr_sign_date_time=T0 + timedelta(hours=24))
        chief_doc = file_row(file_unique_id="F-2", mr_class="EMR10.00.03", topic="宋英华主任医师查房记录", first_mr_sign_date_time=T0 + timedelta(hours=200))
        results = evaluate(rule, T0 + timedelta(hours=300), {"inpatients": [inpatient()], "files": [attending_doc, chief_doc]})
        assert results[0].matched_file_unique_id == "F-2"

    def test_workday_only_death_discuss_end_to_end(self):
        # 死亡讨论 5 个工作日：周五 10:00 死亡，跳过周末 → 下周五 10:00 截止。
        rule = make_rule(
            rule_code="DEATH_DISCUSS",
            trigger_type="DEATH",
            target_json={"mr_class": ["EMR10.00.15"]},
            limit_minutes=5 * 1440,
            workday_only=True,
            warn_before_minutes=1440,
        )
        deaths = [{"patient_id": "P1", "visit_id": "3", "death_date_time": FRI}]
        deadline = FRI + timedelta(days=7)
        pending = evaluate(rule, datetime(2026, 11, 12, 9, 0), {"deaths": deaths, "non_workdays": [SAT, SUN]})
        warning = evaluate(rule, datetime(2026, 11, 12, 10, 0), {"deaths": deaths, "non_workdays": [SAT, SUN]})
        still = evaluate(rule, deadline, {"deaths": deaths, "non_workdays": [SAT, SUN]})
        overdue = evaluate(rule, deadline + timedelta(minutes=1), {"deaths": deaths, "non_workdays": [SAT, SUN]})
        assert [r.status for r in (pending[0], warning[0], still[0], overdue[0])] == ["PENDING", "WARNING", "WARNING", "OVERDUE"]
        assert pending[0].deadline == deadline

    def test_create_basis_uses_create_time(self):
        # CREATE 口径：只看 create_date_time（未签名也算完成）。
        rule = make_rule(completion_basis="CREATE")
        draft = file_row(file_flag="T", first_mr_sign_date_time=None, create_date_time=T0 + timedelta(minutes=200))
        results = evaluate(rule, T0 + timedelta(minutes=300), {"inpatients": [inpatient()], "files": [draft]})
        assert results[0].status == "COMPLETED_ON_TIME"

    def test_no_limit_stays_pending(self):
        rule = make_rule(limit_minutes=None)
        results = evaluate(rule, T0 + timedelta(days=30), {"inpatients": [inpatient()]})
        assert results[0].status == "PENDING" and results[0].deadline is None

    def test_dept_scope_filters_rows(self):
        rule = make_rule(dept_scope_json=["D01"])
        in_scope = inpatient()
        out_scope = inpatient(patient_id="P2", dept_code="D99")
        results = evaluate(rule, T0, {"inpatients": [in_scope, out_scope]})
        assert [r.patient_id for r in results] == ["P1"]

    def test_dept_scope_drops_rows_without_dept(self):
        rule = make_rule(dept_scope_json=["D01"])
        no_dept = inpatient(dept_code=None)
        assert evaluate(rule, T0, {"inpatients": [no_dept]}) == []

    def test_rule_version_orm_like_object(self):
        # TLRuleVersion ORM 对象风格：*_json 为字符串、rule_code 由参数补充。
        version = SimpleNamespace(
            id=99,
            trigger_type="ADMISSION",
            target_json='{"mr_class": ["EMR10.00.01"]}',
            completion_basis="FIRST_SIGN",
            limit_minutes=480,
            workday_only=False,
            warn_before_minutes=60,
            jhemr_monitor_code="JH04.02.002",
            dept_scope_json="[]",
            trigger_filter_json="{}",
        )
        results = evaluate(version, T0, {"inpatients": [inpatient()]}, rule_code="FIRST_COURSE")
        assert results[0].rule_version_id == 99
        assert results[0].deadline == T0 + timedelta(minutes=480)

    def test_missing_rule_code_raises(self):
        with pytest.raises(ValueError):
            evaluate({"trigger_type": "ADMISSION"}, T0, {})

    def test_unknown_trigger_type_raises(self):
        with pytest.raises(ValueError):
            evaluate(make_rule(trigger_type="NO_SUCH"), T0, {})

    def test_empty_data_yields_no_events(self):
        assert evaluate(make_rule(), T0, {}) == []


# ---------- 同步与源码门禁 ----------

class TestSyncAndSourceGuards:
    def test_statuses_match_models(self):
        from app.timeliness.models import EVENT_STATUSES as MODEL_STATUSES

        assert set(state_mod.EVENT_STATUSES) == set(MODEL_STATUSES)

    def test_trigger_types_match_seeds(self):
        from app.timeliness.rules_seed import RULE_SEEDS

        assert set(triggers_mod.TRIGGER_TYPES) == {seed.trigger_type for seed in RULE_SEEDS}

    def test_engine_source_no_forbidden_imports(self):
        files = sorted(ENGINE_DIR.glob("*.py"))
        assert files, f"engine 目录不存在: {ENGINE_DIR}"
        for path in files:
            source = path.read_text(encoding="utf-8")
            assert not FORBIDDEN_IMPORT_RE.search(source), f"{path.name} 引入了禁用依赖（psycopg2/requests/sqlalchemy）"

    def test_engine_import_purity_subprocess(self):
        # 子进程独立验证：import engine 不会连带加载 psycopg2/requests/sqlalchemy。
        code = (
            "import sys\n"
            "import app.timeliness.engine\n"
            "bad = [m for m in ('psycopg2', 'requests', 'sqlalchemy') if m in sys.modules]\n"
            "print(','.join(bad))\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=str(REPO_ROOT), capture_output=True, text=True, encoding="utf-8"
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == "", f"engine 连带加载了禁用模块: {proc.stdout.strip()}"
