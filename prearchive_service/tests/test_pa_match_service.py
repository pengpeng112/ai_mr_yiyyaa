# -*- coding: utf-8 -*-
"""046 T1a AI 匹配服务测试（stub 通道全流程 + 确定性校验器 + 任务生命周期）。"""

import json

import pytest

from prearchive.coverage import build_coverage_records, load_snapshot_items
from prearchive.match_service import (
    StubMatchModel,
    MatchService,
    build_match_input,
    input_hash_for,
    validate_model_output,
)
from prearchive.match_service import CoverageRepository
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_service import Actor

ADMIN = Actor(id="admin-1", name="管理员", permissions=["*"])


@pytest.fixture()
def stack():
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    coverage = CoverageRepository(session_factory)
    coverage.import_snapshot(build_coverage_records(load_snapshot_items()),
                             apply=True, actor_id="admin-1")
    svc = MatchService(session_factory)
    return svc, session_factory, coverage


def _full_run(svc, model=None, fids=None):
    task = svc.create_task(fids=fids, actor_id="admin-1")
    task = svc.run_task(task.id, model_client=model)
    return svc.get_task(task.id)


# ---------------------------------------------------------------- 输入契约


def test_match_input_has_no_phi_and_stable_hash(stack):
    svc, _sf, _cov = stack
    record = next(r for r in svc.coverage_records() if r["fid"] == 38)
    text = build_match_input(record, [])
    assert "patient_name" not in text and "病历原文" not in text
    h1 = input_hash_for([record], [])
    h2 = input_hash_for([record], [])
    assert h1 == h2 and len(h1) == 32


# ---------------------------------------------------------------- stub 全流程


def test_stub_match_full_flow_completed(stack):
    svc, _sf, _cov = stack
    task = _full_run(svc, model=StubMatchModel(), fids=[38, 57, 59])
    assert task.status == "completed"
    assert task.progress_done == 3 and task.progress_total == 3
    candidates = svc.list_candidates(task.id)
    assert candidates, "38/57/59 应产出候选"
    fids_seen = {c.fid for c in candidates}
    assert fids_seen == {38, 57, 59}
    # FID38 的 48h 时限候选应是合法 DSL（校验通过）
    fid38 = [c for c in candidates if c.fid == 38 and c.clause_id == "FID38-C1"]
    assert fid38 and fid38[0].validation_ok == 1
    dsl = json.loads(fid38[0].suggested_dsl_json)
    assert dsl["type"] == "time_limit" and dsl["threshold_hours"] == 48


def test_exact_match_reuses_confirmed_and_skips_model(stack):
    svc, _sf, cov = stack
    cov.confirm_fid(14, ADMIN)
    calls = []

    class CountingStub(StubMatchModel):
        def complete(self, prompt):
            calls.append(json.loads(prompt)["fid"])
            return super().complete(prompt)

    task = _full_run(svc, model=CountingStub(), fids=[14, 34])
    assert task.status == "completed"
    assert 14 not in calls, "已确认 FID 必须精确命中复用，不经模型"
    assert 34 in calls
    exact = [c for c in svc.list_candidates(task.id) if c.fid == 14]
    assert exact and all(c.exact_match == 1 for c in exact)
    assert all("exact match" in c.rationale for c in exact)


def test_fabricated_field_blocked_not_acceptable(stack):
    svc, _sf, _cov = stack
    task = svc.create_task(fids=[38], actor_id="admin-1")
    svc.run_task(task.id, model_client=StubMatchModel(overrides={38: "fabricate"}))
    candidates = svc.list_candidates(task.id)
    assert candidates
    blocked = [c for c in candidates
               if any("totally_made_up_field" in e
                      for e in json.loads(c.blocking_reasons_json or "[]"))]
    assert blocked, "编造字段必须进入 blocked"
    with pytest.raises(ValueError):
        svc.decide_candidate(blocked[0].id, "accepted", ADMIN)


def test_dangerous_dsl_blocked(stack):
    svc, _sf, _cov = stack
    task = svc.create_task(fids=[38], actor_id="admin-1")
    svc.run_task(task.id, model_client=StubMatchModel(overrides={38: "bad_dsl"}))
    candidates = svc.list_candidates(task.id)
    target = [c for c in candidates if c.clause_id == "FID38-C1"][0]
    assert target.validation_ok == 0
    reasons = json.loads(target.blocking_reasons_json)
    assert any("sql" in r.lower() or "forbidden" in r.lower() for r in reasons)
    assert json.loads(target.suggested_dsl_json) == {}, "非法 DSL 不得保留"


def test_model_timeout_marks_partial(stack):
    svc, _sf, _cov = stack
    task = svc.create_task(fids=[38, 41], actor_id="admin-1")
    svc.run_task(task.id, model_client=StubMatchModel(overrides={41: "timeout"}),
                 per_call_timeout=1)
    task = svc.get_task(task.id)
    assert task.status == "partial"
    failed = json.loads(task.failed_fids_json)
    assert failed and failed[0]["fid"] == 41 and "timeout" in failed[0]["error"]


def test_bad_json_marks_partial_with_retry(stack):
    svc, _sf, _cov = stack
    task = svc.create_task(fids=[41], actor_id="admin-1")
    svc.run_task(task.id, model_client=StubMatchModel(overrides={41: "badjson"}))
    task = svc.get_task(task.id)
    assert task.status == "partial"
    failed = json.loads(task.failed_fids_json)
    assert "invalid json" in failed[0]["error"]
    assert task.attempts >= 2, "坏响应应重试一次后再判失败"


def test_resume_from_processed_cursor(stack):
    svc, _sf, _cov = stack
    task = svc.create_task(fids=[38, 41, 48], actor_id="admin-1")
    # 模拟中断：FID38 已处理入库游标
    with _sf() as session:
        from prearchive.closed_loop_models import MatchTaskRow
        row = session.get(MatchTaskRow, task.id)
        row.processed_fids_json = json.dumps([38])
        row.progress_done = 1
        session.commit()
    calls = []

    class CountingStub(StubMatchModel):
        def complete(self, prompt):
            calls.append(json.loads(prompt)["fid"])
            return super().complete(prompt)

    task = svc.run_task(task.id, model_client=CountingStub())
    assert task.status == "completed" and task.progress_done == 3
    assert 38 not in calls, "断点恢复：已处理 FID 不重复调用模型"


def test_same_input_reuses_task(stack):
    svc, _sf, _cov = stack
    t1 = svc.create_task(fids=[38], actor_id="a-1")
    t2 = svc.create_task(fids=[38], actor_id="a-2")
    assert t1.id == t2.id, "相同输入必须复用任务（费用控制）"


def test_cancel_during_run(stack):
    svc, _sf, _cov = stack

    class CancelStub:
        name = "cancel-stub"

        def complete(self, prompt):
            fid = json.loads(prompt)["fid"]
            if fid == 41:
                svc.cancel_task(task_id_holder["id"], actor_id="admin-1")
                # 取消后仍返回合法结果，服务层在下一 FID 前检查取消
            return StubMatchModel().complete(prompt)

    task_id_holder = {}
    task = svc.create_task(fids=[38, 41, 48], actor_id="admin-1")
    task_id_holder["id"] = task.id
    result = svc.run_task(task.id, model_client=CancelStub())
    assert result.status == "cancelled"
    assert result.progress_done < 3 or json.loads(result.processed_fids_json) != [38, 41, 48]


def test_accept_reject_records_actor(stack):
    svc, _sf, _cov = stack
    task = _full_run(svc, model=StubMatchModel(), fids=[38])
    candidate = [c for c in svc.list_candidates(task.id)
                 if c.validation_ok == 1][0]
    accepted = svc.decide_candidate(candidate.id, "accepted", ADMIN, note="ok")
    assert accepted.decision == "accepted" and accepted.decided_by == "admin-1"
    with pytest.raises(ValueError):
        svc.decide_candidate(candidate.id, "rejected", ADMIN)   # 已决策不可重复
    other = [c for c in svc.list_candidates(task.id) if c.validation_ok == 1
             and c.id != candidate.id][0]
    rejected = svc.decide_candidate(other.id, "rejected", ADMIN, note="语义不符")
    assert rejected.decision == "rejected" and rejected.decided_note == "语义不符"


def test_unknown_fid_rejected_at_validation():
    candidates, errors = validate_model_output({"fid": 999, "clauses": []},
                                               known_fids={1}, published_rule_ids=set())
    assert candidates == [] and errors and "unknown fid" in errors[0]


def test_non_publishable_field_blocks_promotion():
    """candidate 状态字段（如 firstpage.allergy_drug）不得成为可发布确定性候选。"""
    parsed = {"fid": 11, "clauses": [{
        "clause_id": "FID11-C2", "matched_rule_ids": ["R-EMPTY-FIRSTPAGE-ALLERGY"],
        "suggested_dsl": {"rule_id": "R-X", "type": "empty_field",
                          "name": "n", "message": "m", "version": "1",
                          "fields": ["allergy_drug"]},
        "field_refs": ["firstpage.allergy_drug"],
        "confidence": "high",
    }]}
    candidates, _ = validate_model_output(
        parsed, known_fids={11}, published_rule_ids={"R-EMPTY-FIRSTPAGE-ALLERGY"})
    assert candidates
    assert candidates[0]["validation_ok"] is False
    assert any("non-publishable" in e for e in candidates[0]["validation_errors"])
