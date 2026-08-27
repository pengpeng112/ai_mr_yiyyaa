# -*- coding: utf-8 -*-
"""time_limit 判定器单测。"""

from prearchive.context import SRC_JHEMR_BLWS
from prearchive.engine import RuleEngine

from helpers import doc, dt, make_ctx, notice_for, surgery, time_limit_rule


def test_time_limit_positive_admission_record_over_24h():
    ctx = make_ctx(admit_time=dt("2026-08-19 10:00:00"))
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "入院记录", event_time=dt("2026-08-20 20:00:00")),  # 34h
    ]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    details = output.problems[0]["details"]
    assert details["elapsed_hours"] == 34.0
    assert details["threshold_hours"] == 24


def test_time_limit_negative_within_limit():
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "入院记录", event_time=dt("2026-08-21 04:00:00")),  # 20h
    ]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-TIME")[0]["reason"] == "within_limit"


def test_time_limit_boundary_equal_not_hit():
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "入院记录", event_time=dt("2026-08-21 08:00:00")),  # 恰 24h
    ]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []


def test_time_limit_doc_missing_no_problem():
    """文书缺失属于 missing_doc 域：time_limit 不判缺失，只记 doc_not_found。"""
    ctx = make_ctx()
    ctx.documents = []
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-TIME")[0]["reason"] == "doc_not_found"


def test_time_limit_first_progress_8h_after_admission():
    rule = time_limit_rule(
        rule_id="R-TEST-TIME-8H", doc_name="首次病程记录", threshold_hours=8,
        match={"sources": ["jhemr_blws"], "by": "report_name_fuzzy",
               "vocab": {"首次病程记录": ["首次病程"]},
               "exclude_vocab": [], "template_field": "progress_template_name"},
    )
    ctx = make_ctx(admit_time=dt("2026-08-19 10:00:00"))
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "首次病程记录", event_time=dt("2026-08-19 15:00:00")),  # 5h
    ]
    assert RuleEngine([rule]).evaluate(ctx).problems == []

    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "首次病程记录", event_time=dt("2026-08-19 21:00:00")),  # 11h
    ]
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["elapsed_hours"] == 11.0


def test_time_limit_surgery_event_basis():
    """术后文书时限：事件时间取最早手术时间。"""
    rule = time_limit_rule(
        rule_id="R-TEST-TIME-POSTOP", doc_name="术后首次病程记录",
        event="surgery", threshold_hours=24,
        match={"sources": ["jhemr_blws"], "by": "report_name_fuzzy",
               "vocab": {"术后首次病程记录": ["术后首次病程"]},
               "exclude_vocab": [], "template_field": "progress_template_name"},
    )
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-23 16:00:00"))]
    ctx.documents = [
        doc(SRC_JHEMR_BLWS, "术后首次病程记录", event_time=dt("2026-08-25 20:00:00")),  # 52h
    ]
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["event"] == "surgery"


def test_time_limit_doc_time_unknown_no_problem():
    ctx = make_ctx()
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录", event_time=None)]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-TIME")[0]["reason"] == "doc_time_unknown"
