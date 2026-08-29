# -*- coding: utf-8 -*-
"""T2-4 单测：4 条实测词表规则 + jhmr_file_index 标题时间源。

- 4 条新 missing_doc 规则（麻醉单 FID61/术前访视 FID59/术后随访 FID67/清点记录 FID88）
  加载校验通过、note 含签字警示、mark_item_fid 全 null、fixture 正反例；
- parse_topic_datetime 标题前缀时间解析正反例；
- time_limit doc_time_source=file_index_topic：标题时间超限命中/未超限通过/
  无索引行 doc_not_found/标题无时间戳 doc_time_unknown；
- 默认 doc_time_source=blws 行为不变（既有入院记录 24h 规则回归）。
"""
from datetime import datetime

import pytest

from prearchive.context import parse_topic_datetime
from prearchive.engine import RuleEngine
from prearchive.rules import load_rules, validate_rule

RULES_PATH = "rules/example_rules.json"


def _engine():
    rules = load_rules(RULES_PATH)
    return RuleEngine(rules, rule_version="test")


def _spec(engine, rule_id):
    return next(r for r in engine.rules if r.rule_id == rule_id)


def test_four_new_rules_load_with_signature_warnings():
    rules = load_rules(RULES_PATH)
    by_id = {r.rule_id: r for r in rules}
    for rule_id in ("R-MISS-ANESTHESIA-RECORD",
                    "R-MISS-ANESTHESIA-PREOP-VISIT",
                    "R-MISS-ANESTHESIA-POSTOP-FOLLOWUP",
                    "R-MISS-SURGERY-COUNT-RECORD"):
        spec = by_id[rule_id]
        assert spec.mark_item_fid is None
        assert "未经质控科签字" in spec.mark_item_note


def test_doc_time_source_validation():
    base = {
        "rule_id": "X", "type": "time_limit", "name": "n", "message": "m",
        "doc_name": "入院记录", "event": "admission", "threshold_hours": 24,
        "version": "v",
    }
    assert validate_rule(dict(base)).doc_time_source == "blws"
    assert validate_rule(dict(base, doc_time_source="file_index_topic")) \
        .doc_time_source == "file_index_topic"
    from prearchive.rules import RuleValidationError
    with pytest.raises(RuleValidationError):
        validate_rule(dict(base, doc_time_source="weird_source"))


# ---------------------------------------------------------------------------
# parse_topic_datetime 正反例
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("topic,expected", [
    ("2026-08-24 17:30 术后首次病程记录", datetime(2026, 8, 24, 17, 30)),
    ("2026-08-24 17:30:45 术后首程", datetime(2026, 8, 24, 17, 30, 45)),
    ("2026年8月24日 术后首次病程记录", datetime(2026, 8, 24)),
    ("2026/08/24 17:30 术后首程", datetime(2026, 8, 24, 17, 30)),
    ("2026-08-24 术后首次病程记录", datetime(2026, 8, 24)),
    ("202608241730 术后首程", datetime(2026, 8, 24, 17, 30)),
])
def test_parse_topic_datetime_positive(topic, expected):
    assert parse_topic_datetime(topic) == expected


@pytest.mark.parametrize("topic", [
    "术后首次病程记录",           # 无时间前缀
    "", None, "  ",
    "2026-13-99 10:00 病程",     # 非法日期
])
def test_parse_topic_datetime_negative(topic):
    assert parse_topic_datetime(topic) is None


# ---------------------------------------------------------------------------
# fixture 端到端：4 条 missing_doc 正反例 + 标题时间源 time_limit
# ---------------------------------------------------------------------------
def _build_ctx(builder, patient_id, visit_id="1"):
    from prearchive.fixture_sources import build_demo_fixtures
    from prearchive.collectors import JhemrCollector
    gw = build_demo_fixtures()
    collector = JhemrCollector(gw["jhemr"])
    visit = collector.fetch_finished_visits(None, 10)[0]
    # 直接构造 FinishedVisit 而非按 patient 过滤
    from prearchive.context import FinishedVisit
    pv = gw["jhemr"].fetch_pat_visit(patient_id, visit_id)
    fv = FinishedVisit(
        patient_id=patient_id, visit_id=visit_id,
        finished_date_time=datetime.fromisoformat(pv["finished_date_time"]),
    )
    return builder.build(fv, check_time=datetime(2026, 8, 28, 12, 0, 0))


def test_missing_doc_rules_positive_and_negative():
    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector,
        PatientContextBuilder, SmCollector,
    )
    from prearchive.fixture_sources import build_demo_fixtures

    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    engine = _engine()

    # 张某：有麻醉单/术前访视（负例），缺术后随访/清点记录（正例）
    ctx1 = _build_ctx(builder, "TEST0001")
    out1 = engine.evaluate(ctx1)
    hit1 = {p["rule_id"] for p in out1.problems}
    assert "R-MISS-ANESTHESIA-RECORD" not in hit1
    assert "R-MISS-ANESTHESIA-PREOP-VISIT" not in hit1
    assert "R-MISS-ANESTHESIA-POSTOP-FOLLOWUP" in hit1
    assert "R-MISS-SURGERY-COUNT-RECORD" in hit1

    # 王某：四项全齐（全负例）
    ctx3 = _build_ctx(builder, "TEST0003")
    out3 = engine.evaluate(ctx3)
    hit3 = {p["rule_id"] for p in out3.problems}
    for rule_id in ("R-MISS-ANESTHESIA-RECORD",
                    "R-MISS-ANESTHESIA-PREOP-VISIT",
                    "R-MISS-ANESTHESIA-POSTOP-FOLLOWUP",
                    "R-MISS-SURGERY-COUNT-RECORD"):
        assert rule_id not in hit3


def test_postop_first_progress_title_time_source():
    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector,
        PatientContextBuilder, SmCollector,
    )
    from prearchive.fixture_sources import build_demo_fixtures

    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    engine = _engine()

    # 张某：手术 08-23 16:00（麻醉单 FCKDATE），标题时间 08-25 10:00 → 42h 超限命中
    ctx1 = _build_ctx(builder, "TEST0001")
    out1 = engine.evaluate(ctx1)
    problem = next(p for p in out1.problems
                   if p["rule_id"] == "R-TIME-POSTOP-FIRST-PROGRESS-24H")
    assert problem["details"]["doc_time_source"] == "file_index_topic"
    assert problem["details"]["elapsed_hours"] > 24

    # 王某：手术 08-24 15:00，标题 08-24 17:30 → 2.5h 通过
    ctx3 = _build_ctx(builder, "TEST0003")
    out3 = engine.evaluate(ctx3)
    assert all(p["rule_id"] != "R-TIME-POSTOP-FIRST-PROGRESS-24H"
               for p in out3.problems)


def test_file_index_topic_unknown_and_missing_cases():
    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector,
        PatientContextBuilder, SmCollector,
    )
    from prearchive.context import FinishedVisit
    from prearchive.fixture_sources import build_demo_fixtures

    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]),
    )
    engine = _engine()
    rule = _spec(engine, "R-TIME-POSTOP-FIRST-PROGRESS-24H")

    # 李某（呼吸内科无手术）：event_time=surgery 无证据 → event_time_unknown
    ctx2 = builder.build(FinishedVisit(
        patient_id="TEST0002", visit_id="1",
        finished_date_time=datetime(2026, 8, 27, 9, 30)), 
        check_time=datetime(2026, 8, 28, 12, 0))
    notices = []
    from prearchive.engine import evaluate_time_limit
    problems = evaluate_time_limit(ctx2, rule, notices)
    assert problems == []
    assert any(n.get("reason") == "event_time_unknown" for n in notices)

    # 有手术但 file_index 无匹配行 → doc_not_found
    ctx1 = _build_ctx(builder, "TEST0001")
    ctx1.file_index = []   # 清空索引
    notices = []
    problems = evaluate_time_limit(ctx1, rule, notices)
    assert problems == []
    assert any(n.get("reason") == "doc_not_found" for n in notices)

    # 索引行标题无时间前缀 → doc_time_unknown
    ctx1b = _build_ctx(builder, "TEST0001")
    ctx1b.file_index = [dict(ctx1b.file_index[0], topic="术后首次病程记录（无时间戳）")]
    notices = []
    problems = evaluate_time_limit(ctx1b, rule, notices)
    assert problems == []
    assert any(n.get("reason") == "doc_time_unknown" for n in notices)


def test_default_blws_time_source_unchanged():
    """默认 doc_time_source=blws：既有入院记录 24h 规则行为不回归。"""
    engine = _engine()
    rule = _spec(engine, "R-TIME-ADMISSION-RECORD-24H")
    assert rule.doc_time_source == "blws"
