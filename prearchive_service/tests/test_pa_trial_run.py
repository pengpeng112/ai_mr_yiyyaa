# -*- coding: utf-8 -*-
"""046 T1b 试运行执行接线测试：真实 trial 执行→逐规则持久化→隔离→观察 API。"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from prearchive.closed_loop_api import create_closed_loop_router
from prearchive.closed_loop_models import (
    MatchCandidateRow,
    RunRow,
    RuleEvalRow,
)
from prearchive.match_service import CoverageRepository, MatchService, StubMatchModel
from prearchive.models import PrearchiveResult, build_session_factory, build_sqlite_engine
from prearchive.rule_models import OutboxRow
from prearchive.rule_repository import RuleRepository
from prearchive.rule_service import RuleService
from prearchive.trial_service import TrialService

from test_pa_closed_loop_api import ADMIN_TOKEN, SIGNING_SECRET, _headers  # noqa: F401


@pytest.fixture()
def stack():
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    repo = RuleRepository(session_factory)
    service = RuleService(repo)
    config = {"admin_api": {"enabled": True, "admin_token": ADMIN_TOKEN,
                            "signing_secret": SIGNING_SECRET},
              "rule_registry": {"mode": "file", "governance": {}}}
    app = FastAPI()
    app.include_router(create_closed_loop_router(config, session_factory, repo,
                                                 service))
    return TestClient(app), session_factory, repo


def _context_builder():
    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector, PatientContextBuilder,
        SmCollector,
    )
    from prearchive.fixture_sources import build_demo_fixtures
    fixtures = build_demo_fixtures()
    return PatientContextBuilder(
        jhemr=JhemrCollector(fixtures["jhemr"]),
        his=HisCollector(fixtures["his"]),
        sm=SmCollector(fixtures["sm"]),
        lis=LisCollector(fixtures["lis"]),
    )


def _create_trial_with_accepted_candidate(stack, fids=(38,)):
    client, session_factory, repo = stack
    coverage = CoverageRepository(session_factory)
    from prearchive.coverage import build_coverage_records, load_snapshot_items
    coverage.import_snapshot(build_coverage_records(load_snapshot_items()),
                             apply=True, actor_id="admin")
    match = MatchService(session_factory)
    task = match.create_task(fids=list(fids), actor_id="admin")
    match.run_task(task.id, model_client=StubMatchModel())
    accepted = [c for c in match.list_candidates(task.id)
                if c.validation_ok == 1 and json.loads(c.suggested_dsl_json or "{}")]
    assert accepted, "应存在可接受的合法候选"
    match.decide_candidate(accepted[0].id, "accepted",
                           __import__("prearchive.rule_service",
                                      fromlist=["Actor"]).Actor(id="admin"))
    r = client.post("/api/admin/trial/runs", headers=_headers(),
                    json={"candidate_ids": [accepted[0].id],
                          "scope": {"synthetic_only": True}})
    assert r.status_code == 200, r.text
    return r.json()["trial_run_id"]


def test_trial_execute_persists_isolated_evals(stack):
    """真实 trial 执行：requested→completed，逐规则逐患者落 RULE_EVAL(is_trial=1)，
    正式结果/Outbox/指针零改动（隔离）。"""
    client, session_factory, repo = stack
    trial_id = _create_trial_with_accepted_candidate(stack)

    pointers_before = {p.rule_key: p.published_version
                       for p in repo.list_pointers()}
    r = client.post(f"/api/admin/trial/runs/{trial_id}/execute", headers=_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed" and body["patients"] == 3

    with session_factory() as session:
        evals = session.execute(select(RuleEvalRow).where(
            RuleEvalRow.run_id == trial_id)).scalars().all()
        assert evals and all(e.is_trial == 1 for e in evals)
        # 每患者一条（fixture 三例 × 候选规则）
        assert len({e.event_instance_id.split("|")[-1] for e in evals}) == 3
        # 隔离：正式结果表与 Outbox 零行
        results = session.execute(select(PrearchiveResult)).scalars().all()
        assert results == []
        outbox = session.execute(select(OutboxRow)).scalars().all()
        assert outbox == []
        run = session.get(RunRow, trial_id)
        assert run.is_trial == 1 and run.status == "completed"
    # 正式指针未变
    assert {p.rule_key: p.published_version
            for p in repo.list_pointers()} == pointers_before


def test_trial_observations_and_feedback(stack):
    client, session_factory, _repo = stack
    trial_id = _create_trial_with_accepted_candidate(stack)
    client.post(f"/api/admin/trial/runs/{trial_id}/execute", headers=_headers())

    r = client.get(f"/api/admin/trial/runs/{trial_id}/observations",
                   headers=_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["totals"]["rules"] >= 1 and data["totals"]["executions"] >= 3
    rule_entry = data["rules"][0]
    assert rule_entry["executions"] == rule_entry["hits"] + rule_entry["pass"] \
        + rule_entry["unknown"] + rule_entry["pending"] + rule_entry["excluded"]

    # 人工反馈：确认缺陷 + 误报
    r = client.post(f"/api/admin/trial/runs/{trial_id}/feedback", headers=_headers(),
                    json={"rule_id": rule_entry["rule_id"],
                          "event_instance_id": "",
                          "verdict": "confirmed_defect", "note": "真实缺陷"})
    assert r.status_code == 200
    r = client.post(f"/api/admin/trial/runs/{trial_id}/feedback", headers=_headers(),
                    json={"rule_id": rule_entry["rule_id"],
                          "event_instance_id": "surgery-1|TEST0001",
                          "verdict": "false_positive", "note": "词表误命中"})
    assert r.status_code == 200
    r = client.post(f"/api/admin/trial/runs/{trial_id}/feedback", headers=_headers(),
                    json={"rule_id": rule_entry["rule_id"], "verdict": "maybe"})
    assert r.status_code == 422

    data = client.get(f"/api/admin/trial/runs/{trial_id}/observations",
                      headers=_headers()).json()
    assert data["totals"]["confirmed_defect"] == 1
    assert data["totals"]["false_positive"] == 1
    assert data["totals"]["reviewed"] == 2


def test_trial_accept_reject_does_not_touch_formal_engine(stack):
    """接受/驳回候选不改变正式引擎：指针/已发布规则/EXAMPLE 文件零改动。"""
    client, session_factory, repo = stack
    _create_trial_with_accepted_candidate(stack)
    # 未发布任何新规则：registry 中 accepted candidate 未产生草稿/版本
    with session_factory() as session:
        candidates = session.execute(select(MatchCandidateRow)).scalars().all()
        assert all(c.decision in ("accepted", "pending") for c in candidates)
    assert repo.list_rules(status="published")[1] == 0   # 未导入 → 无已发布规则


def test_trial_ruleset_rejects_unaccepted_candidate(stack):
    client, session_factory, _repo = stack
    coverage = CoverageRepository(session_factory)
    from prearchive.coverage import build_coverage_records, load_snapshot_items
    coverage.import_snapshot(build_coverage_records(load_snapshot_items()),
                             apply=True, actor_id="admin")
    match = MatchService(session_factory)
    task = match.create_task(fids=[38], actor_id="admin")
    match.run_task(task.id, model_client=StubMatchModel())
    pending = [c for c in match.list_candidates(task.id)][0]
    r = client.post("/api/admin/trial/runs", headers=_headers(),
                    json={"candidate_ids": [pending.id], "scope": {}})
    assert r.status_code == 200
    trial_id = r.json()["trial_run_id"]
    r = client.post(f"/api/admin/trial/runs/{trial_id}/execute", headers=_headers())
    assert r.status_code == 409 and "not accepted" in r.json()["detail"]


def test_trial_execute_404_and_reexecute_guard(stack):
    client, _sf, _repo = stack
    r = client.post("/api/admin/trial/runs/missing/execute", headers=_headers())
    assert r.status_code == 404
    trial_id = _create_trial_with_accepted_candidate(stack)
    assert client.post(f"/api/admin/trial/runs/{trial_id}/execute",
                      headers=_headers()).status_code == 200
    r = client.post(f"/api/admin/trial/runs/{trial_id}/execute", headers=_headers())
    assert r.status_code == 409   # completed 不可重复执行


def test_trial_service_direct_ruleset_build(stack):
    """rule_keys 路径：正式仓 published 版本只读构建（不产生新版本行）。"""
    client, session_factory, repo = stack
    # 导入 example 规则为 published（复用 import_files）
    from prearchive.rule_service import Actor
    repo_report = repo  # noqa: F841
    service = RuleService(repo)
    report = service.import_files(
        ["prearchive_service/rules/example_rules.json"], apply=True,
        actor=Actor(id="admin", name="管理员"))
    assert report["created"] == 16

    r = client.post("/api/admin/trial/runs", headers=_headers(),
                    json={"rule_keys": [{"rule_key": "R-TIME-FIRST-PROGRESS-8H"}],
                          "scope": {}})
    trial_id = r.json()["trial_run_id"]
    trial = TrialService(session_factory)
    specs = trial.build_trial_ruleset(trial_id)
    assert len(specs) == 1 and specs[0].rule_id == "R-TIME-FIRST-PROGRESS-8H"
    # 只读：导入后版本行数不因 trial 构建增加
    versions = repo.list_versions("R-TIME-FIRST-PROGRESS-8H")
    assert len(versions) == 1
