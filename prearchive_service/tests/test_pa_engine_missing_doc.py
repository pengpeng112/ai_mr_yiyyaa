# -*- coding: utf-8 -*-
"""missing_doc 判定器单测：正/反例 + 时间窗/源水位/触发/治理门（028 §3.1 场景）。"""

from prearchive.context import (
    SRC_HIS_ITF,
    SRC_JHEMR_BLWS,
    SRC_LIS_ITF,
    SRC_SM_ITF,
)
from prearchive.engine import RuleEngine

from helpers import (
    doc,
    dt,
    make_ctx,
    missing_doc_rule,
    notice_for,
    surgery,
)


def _surgery_ctx(**overrides):
    ctx = make_ctx(**overrides)
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    return ctx


def test_missing_doc_positive_surgery_checktable_missing():
    ctx = _surgery_ctx()
    ctx.documents = [doc(SRC_SM_ITF, "手术记录", update_time=dt("2026-08-26 10:40:00"))]
    rule = missing_doc_rule(require_source_ready=True)
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1
    problem = output.problems[0]
    assert problem["rule_id"] == "R-TEST-MISS"
    assert problem["details"]["missing_docs"] == ["手术安全核查表"]
    assert problem["severity"] == "medium"


def test_missing_doc_negative_entry_present_via_vocab():
    ctx = _surgery_ctx()
    ctx.documents = [
        doc(SRC_SM_ITF, "手术安全核查表", update_time=dt("2026-08-26 10:40:00")),
    ]
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "all_docs_present"


def test_missing_doc_vocab_fuzzy_match():
    """词表模糊匹配：条目名含词表关键词即算在（'XX医院手术安全核查单'）。"""
    ctx = _surgery_ctx()
    ctx.documents = [doc(SRC_SM_ITF, "XX医院手术安全核查单")]
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert output.problems == []


def test_missing_doc_exclude_vocab_wins():
    """负向词表一票否决：条目名命中词表但含排除词 → 仍判缺（A15 误命中防护）。"""
    ctx = _surgery_ctx()
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术安全核查知情同意书")]
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["missing_docs"] == ["手术安全核查表"]


def test_missing_doc_within_time_window_no_judge():
    """负例：手术后未满 min_hours_after_event → 不判缺（A2/R15）。"""
    ctx = make_ctx(check_time=dt("2026-08-23 17:00:00"),   # 术后 1h
                   finished_date_time=dt("2026-08-23 16:30:00"))
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    rule = missing_doc_rule(min_hours_after_event=2)
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "within_time_window"

    # 时间窗过后正常判缺
    ctx.check_time = dt("2026-08-23 19:00:00")
    output2 = RuleEngine([rule]).evaluate(ctx)
    assert len(output2.problems) == 1


def test_missing_doc_source_not_ready_no_judge():
    """负例：require_source_ready 且 SM 水位早于完成时间 → 不判缺（R15 竞态防护）。"""
    ctx = _surgery_ctx()
    ctx.documents = []          # 完全没有 SM 条目 → 水位缺失
    ctx.source_watermarks.pop("sm")
    rule = missing_doc_rule(require_source_ready=True)
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "source_not_ready"

    # jhemr 就绪但 sm 未就绪：匹配源任一未就绪即跳过
    ctx2 = _surgery_ctx()
    ctx2.documents = []
    ctx2.source_watermarks["sm"] = dt("2026-08-26 09:00:00")   # 早于完成 10:00
    output2 = RuleEngine([rule]).evaluate(ctx2)
    assert output2.problems == []
    assert notice_for(output2, "R-TEST-MISS")[0]["reason"] == "source_not_ready"


def test_missing_doc_trigger_not_met():
    ctx = make_ctx()          # 无手术
    output = RuleEngine([missing_doc_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "trigger_not_met"


def test_missing_doc_surgery_evidence_source_filter():
    """surgery_evidence=his_firstpage_operation 时，SM 条目不算手术证据。"""
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"), source="sm_itf_entry")]
    rule = missing_doc_rule(trigger={"patient_has": "surgery",
                                     "evidence": {"surgery_evidence":
                                                  "his_firstpage_operation"}})
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "trigger_not_met"


def test_missing_doc_lab_order_trigger_and_lis():
    ctx = make_ctx()
    # HIS 有检验医嘱编码 "1"（占位字典），LIS 缺血常规
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "入院记录", update_time=ctx.finished_date_time),
        doc(SRC_HIS_ITF, "1", update_time=ctx.finished_date_time),
        doc(SRC_LIS_ITF, "尿常规检验报告", update_time=ctx.finished_date_time),
    ]
    rule = missing_doc_rule(
        rule_id="R-TEST-LAB",
        expect=["血常规检验报告"],
        trigger={"patient_has": "lab_order",
                 "evidence": {"source": "his_itf", "report_codes": ["1"]}},
        match={"sources": ["lis_itf"], "by": "report_name_fuzzy",
               "vocab": {"血常规检验报告": ["血常规"]},
               "exclude_vocab": [], "template_field": "progress_template_name"},
    )
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["rule_id"] == "R-TEST-LAB"


def test_missing_doc_dept_scope_gate():
    ctx = _surgery_ctx(dept_code="D001")
    rule = missing_doc_rule(dept_codes=["D999"])
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "dept_not_matched"

    rule_all = missing_doc_rule(dept_codes=[])
    assert len(RuleEngine([rule_all]).evaluate(ctx).problems) == 1


def test_missing_doc_exempt_scene_gate():
    ctx = _surgery_ctx()
    ctx.scenes = ["自动出院"]
    rule = missing_doc_rule(exempt_scenes=["自动出院"])
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "exempt_scene"


def test_missing_doc_disabled_rule_skipped():
    ctx = _surgery_ctx()
    output = RuleEngine([missing_doc_rule(enabled=False)]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-MISS")[0]["reason"] == "disabled"


def test_engine_error_isolated_per_rule(monkeypatch):
    """单条规则异常不阻断其他规则（evaluator_error 记录）。"""
    ctx = _surgery_ctx()
    rule = missing_doc_rule()

    # 正常路径先出问题
    assert len(RuleEngine([rule]).evaluate(ctx).problems) == 1

    def boom(ctx, rule, notices):
        raise RuntimeError("boom")

    monkeypatch.setattr("prearchive.engine.evaluate_missing_doc", boom)
    output = RuleEngine([rule]).evaluate(ctx)
    assert output.problems == []
    assert any(n["reason"] == "evaluator_error" for n in output.notices)
