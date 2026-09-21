# -*- coding: utf-8 -*-
"""046 T4 测试：发布原子性（F08）/引擎刷新（F04）/字段依赖门/compare 全量（F09）。"""

import json

import pytest

from prearchive.engine import RuleEngine, EvaluationOutput, Problem
from prearchive.models import build_session_factory, build_sqlite_engine
from prearchive.rule_repository import RuleConflictError, RuleRepository
from prearchive.rule_service import (
    Actor,
    RuleService,
    compare_outputs,
    field_dependency_errors,
    rule_field_dependencies,
)
from prearchive.rules_provider import RefreshableRuleSet

from helpers import doc, dt, make_ctx, time_limit_rule
from prearchive.context import SRC_JHEMR_BLWS

ADMIN = Actor(id="admin-1", name="管理员", permissions=["*"])


def _rule_dict(rule_id="R-ATOMIC-1", version="1", **over):
    base = {
        "rule_id": rule_id, "name": "原子发布测试", "message": "m",
        "version": version, "type": "time_limit", "doc_name": "入院记录",
        "event": "admission", "threshold_hours": 24,
        "match": {"sources": ["jhemr_blws"], "by": "report_name_fuzzy",
                  "vocab": {"入院记录": ["入院记录"]}, "exclude_vocab": [],
                  "template_field": "progress_template_name"},
        "severity": "medium",
    }
    base.update(over)
    return base


@pytest.fixture()
def stack():
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    repo = RuleRepository(session_factory)
    return RuleService(repo), repo, session_factory


def _approved(service, rule_id, version):
    service.create_draft(_rule_dict(rule_id, version), ADMIN)
    service.validate(rule_id, version, ADMIN)
    service.approve(rule_id, version, ADMIN)


# ---------------------------------------------------------------- F08 单事务发布


def test_publish_atomic_all_or_nothing(stack):
    service, repo, _sf = stack
    _approved(service, "R-ATOMIC-1", "1")
    _approved(service, "R-ATOMIC-1", "2")
    service.publish("R-ATOMIC-1", "1", ADMIN)
    result = service.publish("R-ATOMIC-1", "2", ADMIN)
    assert result["retired_versions"] == ["1"]
    pointer = repo.get_pointer("medical_record", "main", "R-ATOMIC-1")
    assert pointer.published_version == "2"
    audits = [a for a in repo.list_audit(rule_key="R-ATOMIC-1", action="publish")]
    assert len(audits) == 2
    assert json.loads(audits[1].detail_json)["atomic"] is True


def test_publish_atomic_fault_injection_no_half_publish(stack, monkeypatch):
    """故障注入：指针写入失败 → 版本状态/指针/审计全部回滚（无半发布）。"""
    service, repo, _sf = stack
    _approved(service, "R-ATOMIC-1", "1")
    service.publish("R-ATOMIC-1", "1", ADMIN)

    _approved(service, "R-ATOMIC-1", "2")
    # 故障注入：审计新行使用既有审计主键 → 事务中段主键冲突 → 整体回滚
    from prearchive import rule_repository as repo_mod
    original_new_id = repo_mod.new_id
    existing_audit_id = repo.list_audit(rule_key="R-ATOMIC-1",
                                        action="publish")[0].id

    def colliding_new_id():
        return existing_audit_id   # 与既有审计行主键冲突

    monkeypatch.setattr(repo_mod, "new_id", colliding_new_id)
    with pytest.raises(Exception):
        service.publish("R-ATOMIC-1", "2", ADMIN)
    monkeypatch.setattr(repo_mod, "new_id", original_new_id)

    # 无半发布：v2 仍 approved、指针仍指 v1、审计只有首次 publish
    row2 = repo.get_version("R-ATOMIC-1", "2")
    assert row2.status == "approved"
    pointer = repo.get_pointer("medical_record", "main", "R-ATOMIC-1")
    assert pointer.published_version == "1"
    publishes = [a for a in repo.list_audit(rule_key="R-ATOMIC-1",
                                            action="publish")]
    assert len(publishes) == 1


def test_publish_pointer_version_conflict_whole_rollback(stack):
    service, repo, _sf = stack
    _approved(service, "R-ATOMIC-1", "1")
    _approved(service, "R-ATOMIC-1", "2")
    service.publish("R-ATOMIC-1", "1", ADMIN)
    # 乐观锁冲突：期望的 pointer_version 过期
    with pytest.raises(RuleConflictError):
        service.publish("R-ATOMIC-1", "2", ADMIN, expect_pointer_version=99)
    row2 = repo.get_version("R-ATOMIC-1", "2")
    assert row2.status == "approved", "冲突时版本不得已被置 published"
    pointer = repo.get_pointer("medical_record", "main", "R-ATOMIC-1")
    assert pointer.published_version == "1"


def test_rollback_atomic_moves_pointer_back(stack):
    service, repo, _sf = stack
    _approved(service, "R-ATOMIC-1", "1")
    _approved(service, "R-ATOMIC-1", "2")
    service.publish("R-ATOMIC-1", "1", ADMIN)
    service.publish("R-ATOMIC-1", "2", ADMIN)
    result = service.rollback("R-ATOMIC-1", "1", ADMIN)
    assert result == {"rule_key": "R-ATOMIC-1", "from": "2", "to": "1",
                      "pointer_version": 3}
    pointer = repo.get_pointer("medical_record", "main", "R-ATOMIC-1")
    assert pointer.published_version == "1"
    assert repo.get_version("R-ATOMIC-1", "1").status == "published"
    rollbacks = [a for a in repo.list_audit(rule_key="R-ATOMIC-1",
                                            action="rollback")]
    assert len(rollbacks) == 1


def test_concurrent_publish_only_one_wins(stack):
    """并发发布：第二次同版本发布在状态门处失败（单轨单活）。"""
    service, repo, _sf = stack
    _approved(service, "R-ATOMIC-1", "1")
    service.publish("R-ATOMIC-1", "1", ADMIN)
    with pytest.raises(RuleConflictError):
        service.publish("R-ATOMIC-1", "1", ADMIN)   # 已 published → 拒绝


# ---------------------------------------------------------------- 字段依赖门


def test_field_dependencies_mapping():
    deps = rule_field_dependencies(_rule_dict())
    assert "admit_time" in deps and "documents.event_time" in deps
    invas = rule_field_dependencies(_rule_dict(
        type="time_limit", doc_name="有创诊疗操作记录", event="surgery",
        doc_time_source="file_index_topic"))
    assert "surgery_time" in invas and "file_index.topic" in invas
    empty = rule_field_dependencies(_rule_dict(type="empty_field", fields=["allergy_drug"]))
    assert "firstpage.allergy_drug" in empty


def test_publish_gate_blocks_candidate_fields(stack):
    """empty_field 依赖首页结构化（candidate，K4 无源）→ 不得正式发布。"""
    service, repo, _sf = stack
    service.create_draft(_rule_dict(rule_id="R-EMPTY-GATE",
                                    type="empty_field", fields=["allergy_drug"]),
                         ADMIN)
    service.validate("R-EMPTY-GATE", "1", ADMIN)
    service.approve("R-EMPTY-GATE", "1", ADMIN)
    with pytest.raises(RuleConflictError) as exc:
        service.publish("R-EMPTY-GATE", "1", ADMIN)
    assert "not publishable" in str(exc.value)
    row = repo.get_version("R-EMPTY-GATE", "1")
    assert row.status == "approved", "门失败不改变状态"


def test_publish_gate_allows_confirmed_fields(stack):
    service, _repo, _sf = stack
    _approved(service, "R-ATOMIC-OK", "1")
    result = service.publish("R-ATOMIC-OK", "1", ADMIN)
    assert result["rule_version"] == "1"


# ---------------------------------------------------------------- F04 引擎刷新


def test_refreshable_ruleset_ttl_and_force():
    calls = []

    def loader():
        calls.append(1)
        rules = [time_limit_rule(threshold_hours=24)]
        return rules, f"v{len(calls)}"

    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def __call__(self):
            return self.now

    clock = FakeClock()
    provider = RefreshableRuleSet(loader, ttl_seconds=60, clock=clock)
    specs1, v1 = provider.snapshot()
    specs2, v2 = provider.snapshot()
    assert v1 == v2 == "v1" and len(calls) == 1, "TTL 内复用快照"

    clock.now += 61
    _specs3, v3 = provider.snapshot()
    assert v3 == "v2" and len(calls) == 2, "TTL 过期重新加载"

    provider.force_refresh()
    assert len(calls) == 3, "发布后 force_refresh 立即生效"


def test_engine_reads_new_snapshot_after_ttl():
    """发布新规则 → TTL 后引擎 evaluate 用新规则（无需重建引擎）。"""
    state = {"rules": [time_limit_rule()], "version": "v1"}

    def loader():
        return state["rules"], state["version"]

    class FakeClock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = FakeClock()
    engine = RuleEngine(RefreshableRuleSet(loader, ttl_seconds=60, clock=clock))
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录",
                         event_time=dt("2026-08-20 20:00:00"))]
    out1 = engine.evaluate(ctx)
    assert out1.rule_version == "v1" and len(out1.evaluations) == 1

    # "发布"：规则集清空（全部禁用）→ TTL 内旧快照，过期后新快照
    state["rules"] = []
    state["version"] = "v2"
    out2 = engine.evaluate(ctx)
    assert out2.rule_version == "v1" and len(out2.evaluations) == 1, "TTL 内旧快照"
    clock.now += 61
    out3 = engine.evaluate(ctx)
    assert out3.rule_version == "v2" and out3.evaluations == [], "TTL 后新快照生效"


# ---------------------------------------------------------------- F09 compare 全量


def _output(rules=None, evaluations=(), problems=()):
    output = EvaluationOutput()
    output.evaluations = list(evaluations)
    output.problems = list(problems)
    return output


def test_compare_outputs_full_granularity():
    file_out = _output(
        evaluations=[
            {"rule_id": "R1", "event_instance_id": "surgery-1", "status": "pass",
             "reason_code": "within_limit"},
            {"rule_id": "R1", "event_instance_id": "surgery-2", "status": "fail",
             "reason_code": "time_limit"},
        ],
        problems=[{"rule_id": "R1", "type": "time_limit", "severity": "medium",
                   "message": "m", "mark_item_fid": 1, "deduct_ref": 1,
                   "details": {"event_instance_id": "surgery-2"}}])
    reg_out = _output(
        evaluations=[
            {"rule_id": "R1", "event_instance_id": "surgery-1", "status": "pass",
             "reason_code": "within_limit"},
            # surgery-2 状态不同 + surgery-3 多出
            {"rule_id": "R1", "event_instance_id": "surgery-2", "status": "unknown",
             "reason_code": "doc_time_unknown"},
            {"rule_id": "R1", "event_instance_id": "surgery-3", "status": "fail",
             "reason_code": "time_limit"},
        ],
        problems=[{"rule_id": "R1", "type": "time_limit", "severity": "medium",
                   "message": "m", "mark_item_fid": 1, "deduct_ref": 1,
                   "details": {"event_instance_id": "surgery-3"}}])
    diffs = compare_outputs(file_out, reg_out)
    kinds = {(d["kind"], d.get("event_instance_id")) for d in diffs}
    assert ("eval_status", "surgery-2") in kinds, "实例级状态差异"
    assert ("presence", "surgery-3") in kinds, "问题实例 presence 差异"
    assert ("eval_status", "surgery-3") in kinds, "评估实例 presence 差异"


def test_compare_outputs_identical_zero_diff():
    shared_evals = [{"rule_id": "R1", "event_instance_id": "admission-1",
                     "status": "pass", "reason_code": "within_limit"}]
    shared_problems = []
    assert compare_outputs(_output(shared_evals, shared_problems),
                           _output(list(shared_evals), list(shared_problems))) == []


def test_compare_outputs_coverage_count_diff():
    file_out = _output(evaluations=[{"rule_id": "R1", "event_instance_id": "",
                                     "status": "pass"}])
    reg_out = _output(evaluations=[{"rule_id": "R1", "event_instance_id": "",
                                    "status": "pass"},
                                   {"rule_id": "R2", "event_instance_id": "",
                                    "status": "pass"}])
    diffs = compare_outputs(file_out, reg_out)
    assert any(d["kind"] == "coverage" for d in diffs)
