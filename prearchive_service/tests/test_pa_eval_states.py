# -*- coding: utf-8 -*-
"""046 T2 评估状态测试：§3.3 五态矩阵 + §T7.1 汇总算术 + RUN/RULE_EVAL 持久化。

场景矩阵（046 §7）逐条断言状态语义，不只断言 problems 数量。
"""

import json
from datetime import datetime

import pytest

from prearchive.context import SRC_JHEMR_BLWS, SRC_SM_ITF
from prearchive.engine import RuleEngine
from prearchive.eval_store import (
    SUMMARY_SCHEMA_VERSION,
    EvalRunStore,
    build_summary,
    source_health,
)
from prearchive.models import build_session_factory, build_sqlite_engine

from helpers import doc, dt, make_ctx, missing_doc_rule, surgery, time_limit_rule


# ---------------------------------------------------------------- 汇总算术（T7.1）


def test_summary_arithmetic_invariants():
    evaluations = [
        {"rule_id": "r1", "status": "pass"},
        {"rule_id": "r2", "status": "fail"},
        {"rule_id": "r3", "status": "unknown"},
        {"rule_id": "r4", "status": "pending"},
        {"rule_id": "r5", "status": "excluded", "exclusion_reason": "disabled"},
        {"rule_id": "r6", "status": "excluded", "exclusion_reason": "dept_excluded"},
    ]
    s = build_summary(evaluations=evaluations, catalog_count=92,
                      mapped_catalog_count=11,
                      source_health_map={"jhemr": {"status": "healthy"}},
                      rule_sources={"r1": ["jhemr_blws"], "r2": ["jhemr_blws"],
                                    "r3": ["jhemr_blws"], "r4": ["jhemr_blws"]})
    assert s["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert s["applicable_count"] == 4          # pass+fail+unknown+pending
    assert s["evaluated_count"] == 2           # pass+fail
    assert s["rule_instance_count"] == 6 == s["applicable_count"] + s["excluded_count"]
    assert s["exclusion_reasons"] == {"disabled": 1, "dept_excluded": 1}
    assert s["evaluation_coverage_pct"] == 50.0
    assert s["status"] == "fail"               # 有 fail 即 fail
    assert s["issue_count"] == 1
    assert s["required_source_checks"] == 4 and s["ready_source_checks"] == 4
    assert s["data_coverage_pct"] == 100.0


def test_summary_zero_denominators_are_null_not_hundred():
    s = build_summary(evaluations=[], catalog_count=92, mapped_catalog_count=0)
    assert s["evaluation_coverage_pct"] is None
    assert s["data_coverage_pct"] is None
    assert s["status"] == "not_run"            # 零规则不得显示"全部通过"
    assert s["applicable_count"] == 0

    # 全排除：未执行理由明确
    s2 = build_summary(evaluations=[
        {"rule_id": "r", "status": "excluded", "exclusion_reason": "disabled"}],
        catalog_count=92, mapped_catalog_count=1)
    assert s2["status"] == "not_run" or s2["evaluated_count"] == 0
    assert s2["excluded_count"] == 1

    # 全 unknown：状态=unknown，不是 pass
    s3 = build_summary(evaluations=[{"rule_id": "r", "status": "unknown"}],
                       catalog_count=92, mapped_catalog_count=1)
    assert s3["status"] == "unknown" and s3["evaluation_coverage_pct"] == 0.0

    # 只有 pending：状态=pending
    s4 = build_summary(evaluations=[{"rule_id": "r", "status": "pending"}],
                       catalog_count=92, mapped_catalog_count=1)
    assert s4["status"] == "pending"


def test_summary_partial_source_coverage():
    s = build_summary(
        evaluations=[{"rule_id": "r1", "status": "pass"}],
        catalog_count=92, mapped_catalog_count=1,
        source_health_map={"jhemr": {"status": "healthy"},
                           "sm": {"status": "error", "detail": "timeout"}},
        rule_sources={"r1": ["jhemr_blws", "sm_itf"]})
    assert s["required_source_checks"] == 2 and s["ready_source_checks"] == 1
    assert s["data_coverage_pct"] == 50.0


# ---------------------------------------------------------------- 引擎五态矩阵


def _eval_for(output, rule_id):
    return {e["rule_id"]: e for e in output.evaluations}[rule_id]


def test_zero_rules_is_not_all_pass():
    output = RuleEngine([]).evaluate(make_ctx())
    assert output.problems == [] and output.evaluations == []
    s = build_summary(evaluations=output.evaluations, catalog_count=92,
                      mapped_catalog_count=0)
    assert s["status"] == "not_run"


def test_all_disabled_rules_are_excluded_not_passed():
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    rules = [missing_doc_rule(enabled=False), time_limit_rule(enabled=False)]
    output = RuleEngine(rules).evaluate(ctx)
    statuses = {e["rule_id"]: e["status"] for e in output.evaluations}
    assert set(statuses.values()) == {"excluded"}
    assert all(e["exclusion_reason"] == "disabled" for e in output.evaluations)


def test_no_surgery_evidence_healthy_sources_not_applicable():
    """无手术证据 + 手术证据源健康 → not_applicable（046 §3.3：不能没采到=无手术
    的反面：源健康时可下不适用结论）。"""
    ctx = make_ctx()      # collect_errors 空 = 源健康
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert _eval_for(output, "R-TEST-MISS")["status"] == "not_applicable"


def test_no_surgery_evidence_with_source_error_unknown():
    ctx = make_ctx()
    ctx.collect_errors["sm"] = "db timeout"
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    ev = _eval_for(output, "R-TEST-MISS")
    assert ev["status"] == "unknown"
    assert ev["reason_code"] == "trigger_not_met_source_error"


def test_overdue_missing_doc_is_fail():
    ctx = make_ctx()      # 手术 08-23，check 08-28 → 远过期
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert _eval_for(output, "R-TEST-MISS")["status"] == "fail"


def test_missing_doc_with_source_error_unknown_not_fail():
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    ctx.collect_errors["sm"] = "connection refused"
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert output.problems == []
    ev = _eval_for(output, "R-TEST-MISS")
    assert ev["status"] == "unknown"
    assert ev["reason_code"] == "missing_doc_source_error"


def test_partial_source_success_mixed_states():
    """部分源成功：sm 故障（缺文书不能定性）+ jhemr 健康（入院记录超时可判）。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "入院记录", event_time=dt("2026-08-22 04:00:00")),
    ]
    ctx.collect_errors["sm"] = "db down"
    output = RuleEngine([missing_doc_rule(), time_limit_rule()]).evaluate(ctx)
    assert _eval_for(output, "R-TEST-MISS")["status"] == "unknown"
    assert _eval_for(output, "R-TEST-TIME")["status"] == "fail"   # 36h 超 24h
    s = build_summary(evaluations=output.evaluations, catalog_count=92,
                      mapped_catalog_count=2,
                      source_health_map=source_health(ctx),
                      rule_sources={"R-TEST-MISS": ["sm_itf"],
                                    "R-TEST-TIME": ["jhemr_blws"]})
    assert s["fail_count"] == 1 and s["unknown_count"] == 1
    assert s["data_coverage_pct"] == 50.0


def test_pending_records_deadline_for_recheck():
    ctx = make_ctx(check_time=dt("2026-08-23 17:00:00"))
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    rule = missing_doc_rule(min_hours_after_event=48)
    output = RuleEngine([rule]).evaluate(ctx)
    ev = _eval_for(output, "R-TEST-MISS")
    assert ev["status"] == "pending"
    assert ev["deadline"] == "2026-08-25T16:00:00"


def test_evaluation_evidence_minimal_no_documents_text():
    ctx = make_ctx()
    ctx.documents = []
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    ev = _eval_for(output, "R-TEST-TIME")
    text = json.dumps(ev["evidence"], ensure_ascii=False)
    assert "fixture患者" not in text      # 不携带患者标识
    assert len(text) < 600                # 最小证据


# ---------------------------------------------------------------- 源健康面


def test_source_health_map_from_collect_errors():
    ctx = make_ctx()
    ctx.collect_errors["sm"] = "timeout"
    health = source_health(ctx)
    assert health["sm"]["status"] == "error"
    assert health["jhemr"]["status"] == "healthy"


# ---------------------------------------------------------------- RUN/RULE_EVAL 持久化


@pytest.fixture()
def store():
    return EvalRunStore(build_session_factory(build_sqlite_engine(":memory:")))


def test_run_revision_increments_on_recheck(store):
    run1 = store.start_run(patient_id="P1", visit_number="1",
                           trigger_type="paperless_rpa")
    run2 = store.start_run(patient_id="P1", visit_number="1",
                           trigger_type="manual_recheck")
    run_other = store.start_run(patient_id="P1", visit_number="2",
                                trigger_type="paperless_rpa")
    assert (run1.run_revision, run2.run_revision) == (1, 2)
    assert run_other.run_revision == 1      # 不同就诊不串次
    assert store.latest_run("P1", "1").id == run2.id


def test_record_evals_idempotent_and_unique(store):
    run = store.start_run(patient_id="P1", visit_number="1",
                          trigger_type="paperless_rpa")
    evals = [{"rule_id": "r1", "status": "pass", "rule_version": "v1",
              "event_instance_id": "", "evidence": {"k": 1}},
             {"rule_id": "r2", "status": "fail", "rule_version": "v1",
              "event_instance_id": "surgery-1", "evidence": {}}]
    assert store.record_evals(run.id, evals) == 2
    assert store.record_evals(run.id, evals) == 2   # 重写幂等
    rows = store.list_evals(run.id)
    assert len(rows) == 2
    assert {r.status for r in rows} == {"pass", "fail"}
    assert rows[0].deadline_at is None

    summary = build_summary(evaluations=evals, catalog_count=92,
                            mapped_catalog_count=2)
    finished = store.finish_run(run.id, "completed", summary,
                                {"jhemr": {"status": "healthy"}},
                                result_id=101)
    assert finished.status == "completed" and finished.result_id == 101
    assert json.loads(finished.summary_json)["fail_count"] == 1
    reloaded = store.get_run(run.id)
    assert json.loads(reloaded.source_health_json)["jhemr"]["status"] == "healthy"


def test_processor_persists_run_and_evals():
    """046 F06：正常处理路径自动落 RUN/RULE_EVAL/RESULT 评估明细。"""
    from prearchive.trigger import PrecheckProcessor
    from prearchive.context import FinishedVisit

    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    store = EvalRunStore(session_factory)
    from prearchive.store import ResultRepository
    repository = ResultRepository(session_factory)

    class _NullPusher:
        class resolver:
            @staticmethod
            def resolve(ctx):
                return None

        def push_result(self, row, ctx):
            return {"status": "skipped", "detail": ""}

    class _CtxBuilder:
        def build(self, visit, check_time=None):
            ctx = make_ctx()
            ctx.patient_id = visit.patient_id
            ctx.visit_id = visit.visit_id
            ctx.visit_number = "1"
            ctx.finished_date_time = visit.finished_date_time
            return ctx

    ctx_builder = _CtxBuilder()
    processor = PrecheckProcessor(
        ctx_builder, RuleEngine([time_limit_rule()]), repository, _NullPusher(),
        eval_store=store, trigger_type="paperless_rpa",
        catalog_provider=lambda: {"catalog_count": 92,
                                  "mapped_catalog_count": 1})
    visit = FinishedVisit(patient_id="TEST0200", visit_id="1",
                          finished_date_time=dt("2026-08-26 10:00:00"))
    row = processor.process(visit, check_time=dt("2026-08-28 09:00:00"))

    run = store.latest_run("TEST0200", "1")
    assert run is not None and run.status == "completed"
    assert run.result_id == row.id
    evals = store.list_evals(run.id)
    assert len(evals) == 1 and evals[0].rule_id == "R-TEST-TIME"
    # RESULT 行携带评估明细（F06）
    assert json.loads(row.evaluations_json)
    assert json.loads(row.summary_json)["schema_version"] == SUMMARY_SCHEMA_VERSION
    assert json.loads(row.notices_json)


def test_legacy_result_rows_without_eval_details():
    """历史 NULL 行：不补造已通过——读侧显示'历史记录未保存评估明细'。"""
    session_factory = build_session_factory(build_sqlite_engine(":memory:"))
    from prearchive.store import ResultRepository
    repository = ResultRepository(session_factory)
    row = repository.upsert_result(
        patient_id="OLD1", visit_id="1",
        finished_date_time=dt("2026-08-01 10:00:00"),
        problems=[], rule_version="2026.08")
    assert row.evaluations_json == "[]"      # 历史行=空，不伪造
    assert json.loads(row.summary_json) == {}
