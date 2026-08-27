# -*- coding: utf-8 -*-
"""empty_field / duplicate 判定器单测（含首页族条件跳过与 A13「无」语义）。"""

from prearchive.engine import (
    RuleEngine,
    evaluate_duplicate,
    evaluate_empty_field,
    normalize_name,
)
from prearchive.rules import RuleSpec

from helpers import duplicate_rule, empty_field_rule, firstpage, make_ctx, notice_for


def test_empty_field_family_skipped_when_firstpage_unavailable():
    """首页源不可读（P0-3④ 硬闸门）→ empty_field/duplicate 整族跳过。"""
    ctx = make_ctx()
    ctx.firstpage = firstpage(available=False)
    engine = RuleEngine([empty_field_rule(), duplicate_rule()])
    output = engine.evaluate(ctx)
    assert output.problems == []
    for rule_id in ("R-TEST-EMPTY", "R-TEST-DUP"):
        assert notice_for(output, rule_id)[0]["reason"] == "firstpage_source_unavailable"


def test_empty_field_positive_blank_and_none():
    ctx = make_ctx()
    ctx.firstpage = firstpage(allergy_drug="")
    output = RuleEngine([empty_field_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["empty_fields"] == ["allergy_drug"]

    ctx.firstpage = firstpage(allergy_drug=None)
    assert len(RuleEngine([empty_field_rule()]).evaluate(ctx).problems) == 1


def test_empty_field_wu_is_legal_not_empty():
    """A13：临床「无过敏」= 合法填写，不判空。"""
    ctx = make_ctx()
    ctx.firstpage = firstpage(allergy_drug="无")
    output = RuleEngine([empty_field_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-EMPTY")[0]["reason"] == "all_fields_filled"

    ctx.firstpage = firstpage(allergy_drug=" 无 ")
    assert RuleEngine([empty_field_rule()]).evaluate(ctx).problems == []


def test_empty_field_multiple_fields_one_problem():
    rule = empty_field_rule(fields=["allergy_drug", "birth_place"])
    ctx = make_ctx()
    ctx.firstpage = firstpage(allergy_drug="", birth_place="")
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1
    assert output.problems[0]["details"]["empty_fields"] == ["allergy_drug", "birth_place"]


def test_duplicate_positive_normalized_match():
    ctx = make_ctx()
    ctx.firstpage = firstpage(
        diagnoses=["1.社区获得性肺炎", "２.社区获得性肺炎", "肺结核"])
    output = RuleEngine([duplicate_rule()]).evaluate(ctx)
    assert len(output.problems) == 1
    dups = output.problems[0]["details"]["duplicates"]
    assert "社区获得性肺炎" in dups and len(dups["社区获得性肺炎"]) == 2


def test_duplicate_circled_number_prefix():
    assert normalize_name("①肺炎") == "肺炎"
    ctx = make_ctx()
    ctx.firstpage = firstpage(diagnoses=["①肺炎", "2、肺炎"])
    output = RuleEngine([duplicate_rule()]).evaluate(ctx)
    assert len(output.problems) == 1


def test_duplicate_negative_distinct():
    ctx = make_ctx()
    ctx.firstpage = firstpage(diagnoses=["1.急性阑尾炎", "2.急性胃肠炎"])
    output = RuleEngine([duplicate_rule()]).evaluate(ctx)
    assert output.problems == []
    assert notice_for(output, "R-TEST-DUP")[0]["reason"] == "no_duplicate"


def test_duplicate_surgeries_list_field():
    rule = duplicate_rule(list_field="surgeries")
    ctx = make_ctx()
    ctx.firstpage = firstpage(surgeries=["阑尾切除术", "（1）阑尾切除术"])
    output = RuleEngine([rule]).evaluate(ctx)
    assert len(output.problems) == 1


def test_normalize_name_fullwidth_and_spaces():
    assert normalize_name("  １.肺炎  ") == "肺炎"
    assert normalize_name("肺炎　") == "肺炎"          # 全角空格
    assert normalize_name("(12)肺结核") == "肺结核"
