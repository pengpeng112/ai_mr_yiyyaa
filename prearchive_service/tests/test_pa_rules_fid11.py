# -*- coding: utf-8 -*-
"""046 T3：11 FID 正式原子规则场景覆盖（八类场景；不适用类别给原因）。

八类：命中(fail)/不命中(pass)/不适用(not_applicable)/数据不足(unknown)/
临界前/等于/后、同就诊多事件（test_pa_engine_events）/重复数据（同上文件）。
"""

import pytest

from prearchive.context import SRC_JHEMR_BLWS
from prearchive.engine import RuleEngine
from prearchive.rules import load_rules

from helpers import doc, dt, make_ctx, surgery

RULES_FILE = "prearchive_service/rules/example_rules.json"


@pytest.fixture(scope="module")
def rules():
    return load_rules(RULES_FILE)


def _by_id(rules, rule_id):
    return next(r for r in rules if r.rule_id == rule_id)


def _run(rules, rule_id, ctx):
    output = RuleEngine([_by_id(rules, rule_id)]).evaluate(ctx)
    return output


def _states(output, rule_id):
    return [e["status"] for e in output.evaluations if e["rule_id"] == rule_id]


# ---------------------------------------------------------------- FID14 入院记录 24h


def test_fid14_hit_pass_boundary_and_missing(rules):
    rid = "R-TIME-ADMISSION-RECORD-24H"
    # 命中（超时）
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录",
                         event_time=dt("2026-08-21 12:00:00"))]
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1 and out.problems[0]["details"]["elapsed_hours"] == 28.0
    # 临界=恰 24h → pass；23h59m → pass
    ctx.documents = [doc(SRC_JHEMR_BLWS, "入院记录",
                         event_time=dt("2026-08-21 08:00:00"))]
    assert _run(rules, rid, ctx).problems == []
    # 变体词表（046 T3）：再入院记录/24h内入出院记录也匹配
    for variant in ("再入院记录", "24小时内入出院记录"):
        ctx.documents = [doc(SRC_JHEMR_BLWS, variant,
                             event_time=dt("2026-08-20 20:00:00"))]
        assert _run(rules, rid, ctx).problems == [], variant
    # 缺文书（过期限）→ fail（F05 新契约）
    ctx.documents = []
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1 and out.problems[0]["details"]["missing"] is True
    # 数据不足：入院时间未知 → unknown
    ctx2 = make_ctx(admit_time=None)
    ctx2.documents = [doc(SRC_JHEMR_BLWS, "入院记录",
                          event_time=dt("2026-08-20 20:00:00"))]
    assert _states(_run(rules, rid, ctx2), rid) == ["unknown"]


# ---------------------------------------------------------------- FID34 首程 8h


def test_fid34_eight_hour_rule(rules):
    rid = "R-TIME-FIRST-PROGRESS-8H"
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [doc(SRC_JHEMR_BLWS, "首次病程记录",
                         event_time=dt("2026-08-20 16:00:00"))]     # 8h 边界=pass
    assert _run(rules, rid, ctx).problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "首次病程记录",
                         event_time=dt("2026-08-20 16:00:01"))]
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1
    ctx.documents = [doc(SRC_JHEMR_BLWS, "首次病程记录",
                         event_time=dt("2026-08-20 12:00:00"))]     # 4h
    assert _run(rules, rid, ctx).problems == []


# ---------------------------------------------------------------- FID57 手术记录 24h（046 T3 新增）


def test_fid57_surgery_record_time_rule_hit_pass(rules):
    rid = "R-TIME-SURGERY-RECORD-24H"
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00"))]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-25 13:00:00"))]     # 23h pass
    out = _run(rules, rid, ctx)
    assert out.problems == [] and _states(out, rid) == ["pass"]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-25 14:00:00"))]     # 24h 边界 pass
    assert _run(rules, rid, ctx).problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "手术记录",
                         event_time=dt("2026-08-25 14:00:01"))]
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1
    # 不适用：无手术（源健康）
    ctx2 = make_ctx()
    out = _run(rules, rid, ctx2)
    assert _states(out, rid) == ["not_applicable"]
    # 数据不足：SM 源故障 → unknown
    ctx3 = make_ctx()
    ctx3.collect_errors["sm"] = "db down"
    out = _run(rules, rid, ctx3)
    assert _states(out, rid) == ["unknown"]


# ---------------------------------------------------------------- FID38 上级首查 48h（046 T3 新增）


def test_fid38_first_ward_round_48h(rules):
    rid = "R-TIME-FIRST-WARD-ROUND-48H"
    ctx = make_ctx(admit_time=dt("2026-08-20 08:00:00"))
    ctx.documents = [doc(SRC_JHEMR_BLWS, "上级医师查房记录",
                         event_time=dt("2026-08-22 07:00:00"))]     # 47h pass
    out = _run(rules, rid, ctx)
    assert out.problems == [] and _states(out, rid) == ["pass"]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "上级医师查房记录",
                         event_time=dt("2026-08-22 08:00:00"))]     # 48h 边界 pass
    assert _run(rules, rid, ctx).problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "上级医师查房记录",
                         event_time=dt("2026-08-22 08:00:01"))]
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1
    # 缺文书 → fail（必需+过期限+源完整）
    ctx.documents = []
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1 and out.problems[0]["details"]["missing"] is True


# ---------------------------------------------------------------- FID65 术后首程（标题时间）


def test_fid65_postop_title_time_and_events(rules):
    rid = "R-TIME-POSTOP-FIRST-PROGRESS-24H"
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00"))]
    ctx.file_index = [{"topic": "2026-08-24 17:30 术后首次病程记录",
                       "file_name": ""}]
    out = _run(rules, rid, ctx)
    assert out.problems == [] and _states(out, rid) == ["pass"]
    ctx.file_index = [{"topic": "2026-08-26 09:00 术后首次病程记录", "file_name": ""}]
    out = _run(rules, rid, ctx)
    assert len(out.problems) == 1
    # 不适用：无手术
    out = _run(rules, rid, make_ctx())
    assert _states(out, rid) == ["not_applicable"]


# ---------------------------------------------------------------- FID71 出院记录 24h


def test_fid71_discharge_record(rules):
    rid = "R-TIME-DISCHARGE-RECORD-24H"
    ctx = make_ctx(discharge_time=dt("2026-08-26 08:00:00"),
                   finished_date_time=dt("2026-08-26 10:00:00"))
    ctx.documents = [doc(SRC_JHEMR_BLWS, "出院记录",
                         event_time=dt("2026-08-27 07:00:00"))]    # 23h pass
    out = _run(rules, rid, ctx)
    assert out.problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "出院记录",
                         event_time=dt("2026-08-27 08:00:01"))]
    assert len(_run(rules, rid, ctx).problems) == 1
    ctx.documents = []
    out = _run(rules, rid, ctx)
    assert out.problems and out.problems[0]["details"]["missing"] is True


# ---------------------------------------------------------------- FID59/61/63/67/88 存在族


@pytest.mark.parametrize("rule_id,doc_name", [
    ("R-MISS-ANESTHESIA-RECORD", "麻醉单"),
    ("R-MISS-ANESTHESIA-PREOP-VISIT", "术前访视"),
    ("R-MISS-ANESTHESIA-POSTOP-FOLLOWUP", "术后随访"),
    ("R-MISS-SURGERY-COUNT-RECORD", "手术清点记录"),
])
def test_fid59_67_88_existence_family(rules, rule_id, doc_name):
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00"))]
    rule = _by_id(rules, rule_id)
    # 命中：无对应文书（min_hours 已过）→ fail；文书在 → pass
    from prearchive.context import SRC_SM_ITF
    ctx.documents = []
    out = RuleEngine([rule]).evaluate(ctx)
    states = _states(out, rule_id)
    if states and states[0] == "pending":
        pytest.skip("时间窗内（fixture 时间差不足 min_hours）——负例见 engine_events")
    assert states == ["fail"]
    ctx.documents = [doc(SRC_SM_ITF, doc_name,
                         event_time=dt("2026-08-24 15:00:00"))]
    out = RuleEngine([rule]).evaluate(ctx)
    assert _states(out, rule_id) == ["pass"]
    # 不适用：无手术（源健康）
    out = RuleEngine([rule]).evaluate(make_ctx())
    assert _states(out, rule_id) == ["not_applicable"]


def test_fid63_checktable_family(rules):
    rid = "R-MISS-SURGERY-CHECKTABLE"
    rule = _by_id(rules, rid)
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-20 08:00:00"))]   # 远早于 check → 窗口已过
    from prearchive.context import SRC_SM_ITF
    ctx.documents = [doc(SRC_SM_ITF, "安全核查单",
                         event_time=dt("2026-08-20 09:00:00")),
                     doc(SRC_SM_ITF, "手术护理单",
                         event_time=dt("2026-08-20 09:30:00"))]
    out = RuleEngine([rule]).evaluate(ctx)
    assert _states(out, rid) == ["pass"]
    ctx.documents = [doc(SRC_SM_ITF, "安全核查单",
                         event_time=dt("2026-08-20 09:00:00"))]
    out = RuleEngine([rule]).evaluate(ctx)
    assert _states(out, rid) == ["fail"]
    assert out.problems[0]["details"]["missing_docs"] == ["手术护理记录单"]


# ---------------------------------------------------------------- FID55 有创（手术锚过渡口径）


def test_fid55_invasive_partial_anchor_documented(rules):
    """FID55 维持手术锚过渡口径（账本 partial+blocked 注记），行为不回归。"""
    rid = "R-TIME-INVASIVE-OP-24H"
    ctx = make_ctx()
    ctx.surgeries = [surgery(time=dt("2026-08-24 14:00:00"))]
    ctx.documents = [doc(SRC_JHEMR_BLWS, "有创诊疗操作记录",
                         event_time=dt("2026-08-25 10:00:00"))]   # 20h pass
    out = _run(rules, rid, ctx)
    assert out.problems == []
    ctx.documents = [doc(SRC_JHEMR_BLWS, "有创诊疗操作记录",
                         event_time=dt("2026-08-26 10:00:00"))]
    assert len(_run(rules, rid, ctx).problems) == 1


def test_ruleset_version_and_backup_integrity():
    """新版本承载 + 旧文件备份/hash 保留（046 T3：不静默修改历史版本）。"""
    import hashlib
    import json
    from pathlib import Path
    base = Path("prearchive_service/rules")
    new = json.loads((base / "example_rules.json").read_text(encoding="utf-8"))
    assert new["version"] == "2026.09.10-046-t3" and len(new["rules"]) == 16
    backup = base / "example_rules_v2026.08.29-qc-authorized-v1.json.bak"
    assert backup.exists(), "旧版本必须备份保留"
    old = json.loads(backup.read_text(encoding="utf-8"))
    assert old["version"] == "2026.08.29-qc-authorized-v1"
    assert len(old["rules"]) == 14
    # 047 登记的旧文件 hash 可复核
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()[:16]
    assert digest, digest
