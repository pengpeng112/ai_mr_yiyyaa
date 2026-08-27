# -*- coding: utf-8 -*-
"""结果存储单测：复检语义/幂等/推送状态（SQLite 内存库）。"""

from datetime import datetime

import pytest

from prearchive.models import (
    PUSH_FAILED,
    PUSH_PENDING,
    PUSH_SENT,
    PUSH_SKIPPED,
    build_session_factory,
    build_sqlite_engine,
)
from prearchive.receivers import Receiver
from prearchive.store import ResultRepository

from helpers import dt


@pytest.fixture()
def repo():
    factory = build_session_factory(build_sqlite_engine(":memory:"))
    return ResultRepository(factory)


PROBLEMS = [
    {"rule_id": "R1", "severity": "medium"},
    {"rule_id": "R2", "severity": "low"},
]


def test_upsert_and_current(repo):
    row = repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=PROBLEMS, rule_version="v1", dept_code="D1", dept_name="普外科",
        patient_name="测试甲",
        receiver=Receiver(user_id="U1", doctor_id="DOC1", doctor_name="甲"))
    assert row.id is not None
    assert row.current == 1
    assert row.problem_count == 2
    assert row.severity_top == "medium"
    assert row.push_wecom_status == PUSH_PENDING
    assert row.problems()[0]["rule_id"] == "R1"
    assert repo.get_current("P1", "1").id == row.id


def test_recheck_semantics_new_finished_new_row_current(repo):
    """A1 复检语义：同 patient+visit、finished 更新 → 新行 current，旧行保留。"""
    old = repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=PROBLEMS, rule_version="v1")
    new = repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 15:00:00"),
        problems=[], rule_version="v1")
    assert new.id != old.id
    assert new.current == 1
    history = repo.list_history("P1", "1")
    assert len(history) == 2                      # 旧行保留
    currents = [r for r in history if r.current == 1]
    assert len(currents) == 1 and currents[0].id == new.id
    assert repo.get_current("P1", "1").id == new.id


def test_same_check_key_idempotent_update(repo):
    """同一检查键重跑：原位更新，不产生新行。"""
    first = repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=PROBLEMS, rule_version="v1")
    second = repo.upsert_result(
        patient_id="P1", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=[], rule_version="v2")
    assert second.id == first.id
    assert repo.list_history("P1", "1") .__len__() == 1
    assert second.rule_version == "v2" and second.problem_count == 0


def test_recheck_back_then_forward_unique_keys(repo):
    """完成时间先更新到 15:00 再回写 12:00（迟到同步）：三行三键、current=最新逻辑。"""
    repo.upsert_result(patient_id="P2", visit_id="1",
                       finished_date_time=dt("2026-08-26 10:00:00"),
                       problems=[], rule_version="v")
    repo.upsert_result(patient_id="P2", visit_id="1",
                       finished_date_time=dt("2026-08-26 15:00:00"),
                       problems=[], rule_version="v")
    repo.upsert_result(patient_id="P2", visit_id="1",
                       finished_date_time=dt("2026-08-26 12:00:00"),
                       problems=[], rule_version="v")
    history = repo.list_history("P2", "1")
    assert len(history) == 3
    assert repo.get_current("P2", "1").finished_date_time == dt("2026-08-26 12:00:00")


def test_push_status_channels_independent(repo):
    row = repo.upsert_result(
        patient_id="P3", visit_id="1", finished_date_time=dt("2026-08-26 10:00:00"),
        problems=PROBLEMS, rule_version="v")

    assert repo.set_push_status(row.id, "wecom", PUSH_SENT, "HTTP 200")
    assert repo.set_push_status(row.id, "agent", PUSH_SENT, "popup shown")

    fresh = repo.get_current("P3", "1")
    assert fresh.push_wecom_status == PUSH_SENT
    assert fresh.push_wecom_at is not None
    assert fresh.push_agent_status == PUSH_SENT

    # sent 后不允许回退（去重纪律）
    assert repo.set_push_status(row.id, "wecom", PUSH_FAILED, "late error") is False
    assert repo.get_current("P3", "1").push_wecom_status == PUSH_SENT

    with pytest.raises(ValueError):
        repo.set_push_status(row.id, "sms", PUSH_SKIPPED)


def test_get_current_missing_returns_none(repo):
    assert repo.get_current("NO", "9") is None
    assert isinstance(datetime.now(), datetime)   # sanity
