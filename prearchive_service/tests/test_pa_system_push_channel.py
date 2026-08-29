# -*- coding: utf-8 -*-
"""T8-4 系统推送规则通道单测。

- DSL：report_expected 触发过 validate_rule（参数化/always 兜底/未知源拒绝）；
- 多文件加载合并（example + system_push 两文件，跨文件 rule_id 重复报错）；
- system_push 文件头含豁免声明（内容断言）；未写入任何真实新源规则；
- 占位规则过 validate_rule + 引擎空跑不命中；现有 example_rules 行为不变。
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from prearchive.collectors import DocumentEntry
from prearchive.context import SRC_PACS_ITF, PatientContext
from prearchive.engine import RuleEngine, evaluate_missing_doc
from prearchive.rules import (
    RuleValidationError,
    load_rules,
    load_rules_multi,
    validate_rule,
)

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
EXAMPLE = RULES_DIR / "example_rules.json"
SYSTEM_PUSH = RULES_DIR / "system_push_rules.json"

BASE = {
    "rule_id": "R-SP-PLACEHOLDER-PACS",
    "type": "missing_doc",
    "name": "占位：PACS报告缺失",
    "message": "占位规则（W10 清单到位前不启用）",
    "severity": "low",
    "version": "2026.08.29-channel-reserved",
    "mark_item_fid": None,
    "mark_item_note": "系统推送类豁免签字（用户 2026-08-28 口径）；W10 词表待回填",
    "enabled": False,
    "trigger": {"patient_has": "report_expected",
                "evidence": {"report_codes": ["CT"],
                             "trigger_sources": ["his_itf"]}},
    "expect": ["CT报告"],
    "match": {"sources": ["pacs_itf"], "by": "report_name_fuzzy",
              "vocab": {"CT报告": ["CT"]}},
}


# ---------------------------------------------------------------------------
# DSL：report_expected
# ---------------------------------------------------------------------------
def test_report_expected_validates_with_codes():
    spec = validate_rule(dict(BASE))
    assert spec.trigger["patient_has"] == "report_expected"


def test_report_expected_validates_with_always_fallback():
    raw = dict(BASE)
    raw["trigger"] = {"patient_has": "report_expected",
                      "evidence": {"always": True}}
    assert validate_rule(raw) is not None


def test_report_expected_rejects_missing_codes_and_always():
    raw = dict(BASE)
    raw["trigger"] = {"patient_has": "report_expected", "evidence": {}}
    with pytest.raises(RuleValidationError):
        validate_rule(raw)


def test_report_expected_rejects_unknown_trigger_source():
    raw = dict(BASE)
    raw["trigger"] = {"patient_has": "report_expected",
                      "evidence": {"report_codes": ["CT"],
                                   "trigger_sources": ["not_a_source"]}}
    with pytest.raises(RuleValidationError):
        validate_rule(raw)


# ---------------------------------------------------------------------------
# 多文件加载合并
# ---------------------------------------------------------------------------
def test_multi_file_merge_example_plus_system_push():
    specs, version = load_rules_multi([str(EXAMPLE), str(SYSTEM_PUSH)])
    example_only = load_rules(EXAMPLE)
    # system_push 当前零规则 → 合并=example 数量，版本拼接
    assert len(specs) == len(example_only)
    assert "2026.08.29-qc-authorized" in version


def test_multi_file_merges_rules_from_both(tmp_path):
    other = tmp_path / "other.json"
    rule = dict(BASE)
    rule["enabled"] = True
    other.write_text(json.dumps(
        {"version": "2026.08.29-test", "rules": [rule]},
        ensure_ascii=False), encoding="utf-8")
    specs, _ = load_rules_multi([str(EXAMPLE), str(other)])
    ids = {s.rule_id for s in specs}
    assert "R-SP-PLACEHOLDER-PACS" in ids
    assert any(i.startswith("R-MISS-") for i in ids)


def test_multi_file_rejects_cross_file_duplicate_id(tmp_path):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    dup = dict(data["rules"][0])   # 与 example 重复的 rule_id
    dup["name"] = dup["name"] + "（重复）"
    other = tmp_path / "dup.json"
    other.write_text(json.dumps(
        {"version": "v", "rules": [dup]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuleValidationError):
        load_rules_multi([str(EXAMPLE), str(other)])


# ---------------------------------------------------------------------------
# system_push 通道文件契约
# ---------------------------------------------------------------------------
def test_system_push_file_header_contains_exemption_and_no_real_rules():
    raw = json.loads(SYSTEM_PUSH.read_text(encoding="utf-8"))
    assert raw["rules"] == []                       # 未写入任何真实新源规则
    notes = "\\n".join(raw.get("channel_note") or [])
    assert "豁免" in notes and "签字" in notes       # 豁免声明（用户 2026-08-28 口径）
    assert "W10" in notes                            # 词表/清单依赖声明
    assert "example_rules" in notes                  # 两轨并行声明


# ---------------------------------------------------------------------------
# 占位规则引擎空跑不命中
# ---------------------------------------------------------------------------
def test_placeholder_rule_evaluates_no_hit_on_empty_context():
    spec = validate_rule(dict(BASE, enabled=True))
    ctx = PatientContext(patient_id="TESTP", visit_id="1",
                         finished_date_time=datetime(2026, 8, 28, 9, 0))
    notices = []
    problems = evaluate_missing_doc(ctx, spec, notices)
    # 无申请条目 → trigger_not_met → 不命中
    assert problems == []
    assert any(n.get("reason") == "trigger_not_met" for n in notices)


def test_placeholder_rule_always_variant_hits_when_doc_missing():
    raw = dict(BASE, enabled=True)
    raw["trigger"] = {"patient_has": "report_expected", "evidence": {"always": True}}
    raw["min_hours_after_event"] = 0
    spec = validate_rule(raw)
    ctx = PatientContext(patient_id="TESTP", visit_id="1",
                         finished_date_time=datetime(2026, 8, 28, 9, 0),
                         check_time=datetime(2026, 8, 29, 9, 0))
    notices = []
    problems = evaluate_missing_doc(ctx, spec, notices)
    # always 触发 + pacs_itf 无条目 → 判缺命中
    assert len(problems) == 1
    assert problems[0].rule_id == "R-SP-PLACEHOLDER-PACS"


def test_example_rules_behavior_unchanged():
    """现有 example_rules 行为不变（通道合并不影响既有规则集）。"""
    specs = load_rules(EXAMPLE)
    by_id = {s.rule_id: s for s in specs}
    assert len(specs) == 14   # 2026-08-29 授权回填后：+出院记录24h/有创操作24h
    assert by_id["R-TIME-ADMISSION-RECORD-24H"].doc_time_source == "blws"
