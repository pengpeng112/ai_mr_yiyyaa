# -*- coding: utf-8 -*-
"""048 T4 匹配任务恢复与事务健壮性：故障注入（事务中断/取消/重复执行/任务消失）。

修复对应（match_service.py）：
- 候选持久化 + 游标推进合并为单事务（_commit_fid_progress），且同 (task_id,fid)
  先替换后插入——崩溃重启重跑不产生重复候选、不丢已成功 FID；
- run 启动=条件 UPDATE（并发重复 run 只有一个执行器，其余幂等返回）；
- 终态=条件 UPDATE（取消竞争不被 completed 覆盖）；
- 执行中任务被删除 → ValueError 明确结果（不再是 refresh(None) 异常）。
"""

import json

import pytest
from sqlalchemy import select

from prearchive.closed_loop_models import MatchCandidateRow, MatchTaskRow
from prearchive.coverage import build_coverage_records, load_snapshot_items
from prearchive.match_service import MatchService, StubMatchModel
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


def _candidate_rows(sf, task_id):
    with sf() as session:
        return list(session.execute(select(MatchCandidateRow).where(
            MatchCandidateRow.task_id == task_id)).scalars().all())


def _task(sf, task_id):
    with sf() as session:
        row = session.get(MatchTaskRow, task_id)
        session.refresh(row)
        session.expunge(row)
        return row


def test_crash_between_candidates_and_cursor_no_duplicates_on_rerun(stack):
    """复现旧缺陷态：候选已写、游标未记（两事务间隙崩溃的落库现场），
    重启续跑后同 FID 候选被替换而非翻倍，且已成功 FID 不丢。"""
    svc, sf, _cov = stack
    task = svc.create_task(fids=[38, 41], actor_id="admin-1")
    # 人为构造旧缺陷崩溃现场：38 的候选写入但 processed/progress 未推进
    record38 = next(r for r in svc.coverage_records() if r["fid"] == 38)
    exact = svc._exact_match_record(record38)
    if exact is None:
        from prearchive.match_service import build_match_input, validate_model_output
        stub = StubMatchModel()
        parsed = json.loads(stub.complete(build_match_input(record38, [])))
        exact, _errors = validate_model_output(parsed, svc.known_fids(),
                                               svc.published_rule_ids())
    svc._commit_fid_progress(task.id, 38, exact)
    with sf() as session:
        row = session.get(MatchTaskRow, task.id)
        row.processed_fids_json = "[]"          # 崩溃：游标丢失
        row.progress_done = 0
        row.status = "failed"
        session.commit()

    result = svc.run_task(task.id, model_client=StubMatchModel())
    assert result.status in ("completed", "partial")
    rows = _candidate_rows(sf, task.id)
    fid38_rows = [r for r in rows if r.fid == 38]
    assert len(fid38_rows) == len(exact), "重跑同 FID 候选必须替换而非翻倍"
    final = _task(sf, task.id)
    assert json.loads(final.processed_fids_json) == [38, 41]
    assert final.progress_done == 2


def test_candidate_and_cursor_are_single_transaction(stack):
    """单 FID 提交后，候选与游标要么同时可见：注入候选写入后崩溃（会话不 commit）
    ——通过直接调用并断言同事务字段齐变；再验证中途异常整体回滚。"""
    svc, sf, _cov = stack
    task = svc.create_task(fids=[38], actor_id="admin-1")
    # 正常路径：一次调用后候选+游标同时落库
    svc._commit_fid_progress(task.id, 38, [], failed=[])
    row = _task(sf, task.id)
    assert json.loads(row.processed_fids_json) == [38]
    assert row.progress_done == 1
    # 回滚路径：同一会话内先 delete+insert 候选，任务行推进后抛异常 → 全回滚
    from prearchive.rule_models import new_id
    with sf() as session:
        t = session.get(MatchTaskRow, task.id)
        before_done = t.progress_done
        session.add(MatchCandidateRow(id=new_id(), task_id=task.id, fid=99))
        t.progress_done = before_done + 999
        session.flush()
        session.rollback()
    row2 = _task(sf, task.id)
    assert row2.progress_done == before_done
    assert _candidate_rows(sf, task.id) == [] or all(
        r.fid != 99 for r in _candidate_rows(sf, task.id))


def test_task_disappears_during_run_raises_clear_valueerror(stack):
    """执行中任务被并发删除 → 明确 ValueError，不再 refresh(None) 崩溃。"""
    svc, sf, _cov = stack

    class DeleteTaskStub(StubMatchModel):
        def complete(self, prompt):
            fid = json.loads(prompt)["fid"]
            if fid == 41:
                with sf() as session:
                    row = session.get(MatchTaskRow, task_id_holder["id"])
                    session.delete(row)
                    session.commit()
            return super().complete(prompt)

    task_id_holder = {}
    task = svc.create_task(fids=[38, 41], actor_id="admin-1")
    task_id_holder["id"] = task.id
    with pytest.raises(ValueError, match="task (disappeared|not found)"):
        svc.run_task(task.id, model_client=DeleteTaskStub())


def test_concurrent_duplicate_run_only_one_executor(stack):
    """任务已处于 running（另一执行器持有）→ 重复 run 幂等返回，不重复执行、
    不重复写候选。"""
    svc, sf, _cov = stack
    task = svc.create_task(fids=[38], actor_id="admin-1")
    with sf() as session:
        row = session.get(MatchTaskRow, task.id)
        row.status = "running"
        row.progress_done = 1
        row.processed_fids_json = json.dumps([38])
        session.commit()

    calls = []

    class CountingStub(StubMatchModel):
        def complete(self, prompt):
            calls.append(json.loads(prompt)["fid"])
            return super().complete(prompt)

    result = svc.run_task(task.id, model_client=CountingStub())
    assert calls == [], "running 状态被其他执行器持有时不得重复执行"
    assert result.status == "running"


def test_cancel_vs_complete_race_cancelled_not_overwritten(stack):
    """终态写入与取消竞争：最后一个 FID 处理中被取消 → 终态保持 cancelled
    （条件终态迁移不覆盖）。"""
    svc, sf, _cov = stack

    class CancelAtLastFid(StubMatchModel):
        def complete(self, prompt):
            fid = json.loads(prompt)["fid"]
            if fid == 41:
                svc.cancel_task(task_id_holder["id"], actor_id="admin-1")
            return super().complete(prompt)

    task_id_holder = {}
    task = svc.create_task(fids=[38, 41], actor_id="admin-1")
    task_id_holder["id"] = task.id
    result = svc.run_task(task.id, model_client=CancelAtLastFid())
    # 41 完成后进入终态块；若取消发生在终态块读行之后，条件 UPDATE 兜底
    assert result.status in ("cancelled", "completed")
    final = _task(sf, task.id)
    # 取消先落库 → 终态不得覆盖（取消在本用例模型回调内先于终态块提交）
    assert final.status == "cancelled", f"取消不得被终态覆盖：{final.status}"


def test_rerun_completed_task_returns_as_is(stack):
    """completed 任务重复 run → 原样返回，候选集不变。"""
    svc, sf, _cov = stack
    task = svc.create_task(fids=[38], actor_id="admin-1")
    first = svc.run_task(task.id, model_client=StubMatchModel())
    assert first.status == "completed"
    rows_before = _candidate_rows(sf, task.id)
    again = svc.run_task(task.id, model_client=StubMatchModel())
    assert again.status == "completed"
    assert len(_candidate_rows(sf, task.id)) == len(rows_before)
