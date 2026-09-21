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


def test_time_limit_doc_missing_past_deadline_is_defect():
    """046 F05 迁移：旧断言=缺文书 problems==[]（pass/doc_not_found）——已证实为
    误判通过缺口。新契约：必需（规则声明）+ 源完整 + 过期限 → 缺文书=缺陷。"""
    ctx = make_ctx()          # 入院 08-20 08:00，check 08-28 → 远过 24h 期限
    ctx.documents = []
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    details = output.problems[0]["details"]
    assert details["missing"] is True
    assert details["deadline"] == "2026-08-21T08:00:00"
    evals = [e for e in output.evaluations if e["rule_id"] == "R-TEST-TIME"]
    assert evals and evals[0]["status"] == "fail"
    assert evals[0]["reason_code"] == "doc_not_found"   # 046 T3：notice 侧 fail 记录


def test_time_limit_doc_missing_within_deadline_pending():
    """期限内文书未到 → pending（登记复查时间），不判缺陷不算通过。"""
    ctx = make_ctx(admit_time=dt("2026-08-27 20:00:00"))
    ctx.documents = []
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    evals = [e for e in output.evaluations if e["rule_id"] == "R-TEST-TIME"]
    assert evals and evals[0]["status"] == "pending"
    assert evals[0]["deadline"] == "2026-08-28T20:00:00"


def test_time_limit_doc_missing_with_source_error_unknown():
    """源故障时缺文书不能断言不存在 → unknown（不扣分不误报）。"""
    ctx = make_ctx()
    ctx.documents = []
    ctx.collect_errors["jhemr"] = "connection refused"
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    evals = [e for e in output.evaluations if e["rule_id"] == "R-TEST-TIME"]
    assert evals and evals[0]["status"] == "unknown"
    assert evals[0]["reason_code"] == "doc_not_found_source_error"


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


def test_time_limit_event_time_unknown_is_unknown_eval():
    """046 F05 迁移：事件时间不可靠旧=pass → 新=unknown（不当合格）。"""
    ctx = make_ctx(admit_time=None)
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录",
                         event_time=dt("2026-08-20 20:00:00"))]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    evals = [e for e in output.evaluations if e["rule_id"] == "R-TEST-TIME"]
    assert evals and evals[0]["status"] == "unknown"
    assert evals[0]["reason_code"] == "event_time_unknown"


def test_time_limit_doc_time_unknown_is_unknown_eval():
    """046 F05 迁移：文书时间不可靠旧=pass → 新=unknown（不当合格）。"""
    ctx = make_ctx()
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录", event_time=None)]
    output = RuleEngine([time_limit_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-TIME")[0]["reason"] == "doc_time_unknown"
    evals = [e for e in output.evaluations if e["rule_id"] == "R-TEST-TIME"]
    assert evals and evals[0]["status"] == "unknown"
