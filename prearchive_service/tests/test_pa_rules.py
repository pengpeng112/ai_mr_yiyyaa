# -*- coding: utf-8 -*-
"""规则 DSL 单测：示例规则加载 + 各类型校验负例。"""

import json
from pathlib import Path

import pytest

from prearchive.rules import (
    RuleValidationError,
    load_rules,
    looks_like_signed_version,
    rules_version,
    validate_rule,
)

RULES_FILE = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"

BASE = {
    "rule_id": "R-X", "name": "n", "message": "m", "type": "missing_doc",
    "version": "2026.08.27-dev",
    "trigger": {"patient_has": "surgery",
                "evidence": {"surgery_evidence": "sm_itf_entry"}},
    "expect": ["手术记录"],
    "match": {"sources": ["sm_itf"], "by": "report_name_fuzzy"},
}


def test_example_rules_load():
    rules = load_rules(RULES_FILE)
    assert len(rules) >= 6, "示例规则必须 ≥6 条"
    types = {r.rule_type for r in rules}
    assert types == {"missing_doc", "time_limit", "empty_field", "duplicate"}
    # 授权契约（2026-08-29）：质控科已授权免签字，一期 11 条 FID 已回填；
    # 家族规则（检验/首页族）fid 保持 null 且 note 说明原因
    from prearchive.rules import rules_version as _rv
    for rule in rules:
        assert rule.version
        assert ("质控科" in rule.mark_item_note or "签字" in rule.mark_item_note
                or "授权" in rule.mark_item_note)
    by_id = {r.rule_id: r for r in rules}
    for rid, fid in (("R-TIME-ADMISSION-RECORD-24H", 14),
                     ("R-TIME-FIRST-PROGRESS-8H", 34),
                     ("R-MISS-SURGERY-PREPOST-DOCS", 57),
                     ("R-MISS-SURGERY-CHECKTABLE", 63),
                     ("R-MISS-ANESTHESIA-RECORD", 61),
                     ("R-MISS-ANESTHESIA-PREOP-VISIT", 59),
                     ("R-MISS-ANESTHESIA-POSTOP-FOLLOWUP", 67),
                     ("R-MISS-SURGERY-COUNT-RECORD", 88),
                     ("R-TIME-POSTOP-FIRST-PROGRESS-24H", 65),
                     ("R-TIME-DISCHARGE-RECORD-24H", 71),
                     ("R-TIME-INVASIVE-OP-24H", 55)):
        assert by_id[rid].mark_item_fid == fid, rid
    for rid in ("R-MISS-LAB-REPORT-FAMILY", "R-EMPTY-FIRSTPAGE-ALLERGY",
                "R-DUP-FIRSTPAGE-DIAGNOSIS"):
        assert by_id[rid].mark_item_fid is None, rid
    assert "authorized" in rules_version(RULES_FILE)


def test_example_rules_cover_required_scenarios():
    rules = load_rules(RULES_FILE)
    ids = {r.rule_id for r in rules}
    assert "R-MISS-SURGERY-CHECKTABLE" in ids       # 手术核查表缺失
    assert "R-MISS-SURGERY-PREPOST-DOCS" in ids     # 术前术后文书族
    assert "R-TIME-ADMISSION-RECORD-24H" in ids     # 入院记录24h时限
    assert "R-EMPTY-FIRSTPAGE-ALLERGY" in ids       # 首页过敏空项（条件规则）
    assert "R-DUP-FIRSTPAGE-DIAGNOSIS" in ids       # 诊断重复
    assert "R-MISS-LAB-REPORT-FAMILY" in ids        # 检验报告族
    # A2 治理字段齐备
    allergy = next(r for r in rules if r.rule_id == "R-EMPTY-FIRSTPAGE-ALLERGY")
    assert allergy.enabled and allergy.version and allergy.dept_codes == []
    checktable = next(r for r in rules if r.rule_id == "R-MISS-SURGERY-CHECKTABLE")
    assert checktable.require_source_ready is True
    assert checktable.min_hours_after_event == 2
    assert checktable.match.get("exclude_vocab")    # A15 负向词表


def test_validate_rejects_unknown_type():
    raw = dict(BASE, type="semantic_ai")
    with pytest.raises(RuleValidationError, match="type must be one of"):
        validate_rule(raw)


def test_validate_rejects_missing_expect():
    raw = dict(BASE)
    raw.pop("expect")
    with pytest.raises(RuleValidationError, match="expect"):
        validate_rule(raw)


def test_validate_rejects_wu_in_blacklist():
    """'无' 是临床合法填写，禁止加入空项黑名单（A13）。"""
    raw = {
        "rule_id": "R-E", "name": "n", "message": "m", "type": "empty_field",
        "version": "v1", "fields": ["allergy_drug"],
        "extra_blacklist_values": ["无"],
    }
    with pytest.raises(RuleValidationError, match="合法填写"):
        validate_rule(raw)


def test_validate_rejects_bad_severity_and_threshold():
    raw = dict(BASE, severity="critical")
    with pytest.raises(RuleValidationError, match="severity"):
        validate_rule(raw)
    raw_time = {
        "rule_id": "R-T", "name": "n", "message": "m", "type": "time_limit",
        "version": "v", "doc_name": "入院记录", "event": "admission",
        "threshold_hours": 0,
    }
    with pytest.raises(RuleValidationError, match="threshold_hours"):
        validate_rule(raw_time)


def test_validate_rejects_unknown_source_and_event():
    raw = json.loads(json.dumps(BASE))
    raw["match"]["sources"] = ["cdss"]
    with pytest.raises(RuleValidationError, match="unknown match source"):
        validate_rule(raw)
    raw_time = {
        "rule_id": "R-T2", "name": "n", "message": "m", "type": "time_limit",
        "version": "v", "doc_name": "d", "event": "birthday", "threshold_hours": 1,
    }
    with pytest.raises(RuleValidationError, match="event must be one of"):
        validate_rule(raw_time)


def test_validate_requires_version():
    raw = dict(BASE)
    raw.pop("version")
    with pytest.raises(RuleValidationError, match="version required"):
        validate_rule(raw)


def test_validate_lab_order_requires_codes():
    raw = dict(BASE, trigger={"patient_has": "lab_order", "evidence": {}})
    with pytest.raises(RuleValidationError, match="report_codes"):
        validate_rule(raw)


def test_load_rules_rejects_duplicate_ids(tmp_path):
    raw = {"version": "v", "rules": [BASE, dict(BASE)]}
    path = tmp_path / "dup.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuleValidationError, match="duplicate rule_id"):
        load_rules(path)


def test_load_rules_rejects_missing_file(tmp_path):
    with pytest.raises(RuleValidationError, match="not found"):
        load_rules(tmp_path / "nope.json")


def test_signed_version_hint():
    assert looks_like_signed_version("2026.09.10-qc-v1") is True
    assert looks_like_signed_version("dev") is False
