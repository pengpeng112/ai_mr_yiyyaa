# -*- coding: utf-8 -*-
"""046 T8 回测 v2 测试：人工扣分=参照而非无条件金标准。

核心语义断言：
- 未评范围内规则命中 → unknown（人工没扣分≠已审查合格，不计 FP）；
- 已评阴性范围内命中 → FP；
- 整改后结果回测整改前扣分 → 对齐排除（不进 TP/FN）；
- 规则 unknown/pending → 不计 FN；
- 分母 0 → precision/recall/unknown_ratio=None（不可估计，不写 100%）；
- FID/子句/科室三级聚合 + FP 原因聚合 + v1 兼容（problems 回退）。
"""

from prearchive.backtest import backtest_v2, render_markdown_v2


def _deduction(pid, vid, fid, clause="C1", reviewed="2026-08-28T10:00:00",
               data_as_of=None, dept=None):
    row = {"patient_id": pid, "visit_id": vid, "fid": fid,
           "clause_id": clause, "reviewed_at": reviewed}
    if data_as_of:
        row["data_as_of"] = data_as_of
    if dept:
        row["dept_code"] = dept
    return row


def _result(pid, vid, *, fids_hit=(), fids_unknown=(), fids_pass=(),
            checked="2026-08-27T12:00:00", dept="D001", unmapped=()):
    evaluations = []
    for fid in fids_hit:
        evaluations.append({"rule_id": f"R-{fid}", "mark_item_fid": fid,
                            "status": "fail", "clause_id": "C1"})
    for fid in fids_unknown:
        evaluations.append({"rule_id": f"R-{fid}", "mark_item_fid": fid,
                            "status": "unknown", "clause_id": "C1"})
    for fid in fids_pass:
        evaluations.append({"rule_id": f"R-{fid}", "mark_item_fid": fid,
                            "status": "pass", "clause_id": "C1"})
    for rule_id in unmapped:
        evaluations.append({"rule_id": rule_id, "mark_item_fid": None,
                            "status": "fail"})
    return {"patient_id": pid, "visit_id": vid, "dept_code": dept,
            "checked_at": checked, "ruleset_revision": "v-test",
            "evaluations": evaluations}


def test_unreviewed_hit_is_unknown_not_fp():
    """人工未评审的 FID 上规则命中：不可判定（unknown），不是 FP。"""
    manual = {"deductions": [_deduction("P1", "1", 14)],
              "evaluated_negatives": []}
    results = [_result("P1", "1", fids_hit={14, 71})]   # 71 未被人工评审
    report = backtest_v2(manual, results)
    assert report["overall"]["tp"] == 1        # FID14 人工扣+规则中
    assert report["overall"]["fp"] == 0        # 71 未评 → 不计 FP
    assert report["overall"]["unknown"] == 1
    assert report["per_fid"]["71"]["unknown"] == 1
    assert report["per_fid"]["71"]["fp"] == 0


def test_reviewed_negative_scope_hit_is_fp():
    """评审过未扣分的 FID 上规则命中 → FP。"""
    manual = {
        "deductions": [_deduction("P1", "1", 14)],
        "evaluated_negatives": [
            {"patient_id": "P1", "visit_id": "1", "fids": [71],
             "reviewed_at": "2026-08-28T10:00:00"}]}
    results = [_result("P1", "1", fids_hit={14, 71})]
    report = backtest_v2(manual, results)
    assert report["overall"]["tp"] == 1 and report["overall"]["fp"] == 1
    assert report["per_fid"]["71"]["fp"] == 1


def test_rule_unknown_not_counted_as_fn():
    """规则对扣分 FID 给出 unknown（源故障/时间不可靠）→ 不可判，不是 FN。"""
    manual = {"deductions": [_deduction("P1", "1", 14)]}
    results = [_result("P1", "1", fids_unknown={14})]
    report = backtest_v2(manual, results)
    assert report["overall"]["fn"] == 0
    assert report["overall"]["unknown"] == 1
    assert report["overall"]["judged"] == 0
    assert report["overall"]["precision"] is None    # 分母 0=不可估计
    assert report["overall"]["recall"] is None


def test_rule_miss_with_definite_pass_is_fn():
    """规则已执行且明确 pass、人工仍扣分 → FN（规则漏检）。"""
    manual = {"deductions": [_deduction("P1", "1", 14)]}
    results = [_result("P1", "1", fids_pass={14})]
    report = backtest_v2(manual, results)
    assert report["overall"]["fn"] == 1
    assert report["overall"]["recall"] == 0.0


def test_post_rectification_result_excluded_by_alignment():
    """整改后结果回测整改前扣分 → 对齐排除，不进任何指标。"""
    manual = {"deductions": [
        _deduction("P1", "1", 14, reviewed="2026-08-28T10:00:00",
                   data_as_of="2026-08-28T10:00:00")]}
    # 结果 checked_at=09-10（医生 09-01 已补记录）→ 晚于 data_as_of+1 天
    results = [_result("P1", "1", fids_pass={14}, checked="2026-09-10T09:00:00")]
    report = backtest_v2(manual, results)
    assert report["overall"]["fn"] == 0 and report["overall"]["tp"] == 0
    assert report["overall"]["alignment_excluded"] == 1
    assert report["alignment"]["excluded_visits"] == 1
    # 对齐内的结果正常参与
    in_window = backtest_v2(
        manual, [_result("P1", "1", fids_pass={14},
                         checked="2026-08-28T18:00:00")])
    assert in_window["overall"]["fn"] == 1


def test_missing_result_counts_unknown_not_fn():
    """无预检结果就诊的人工扣分 → unknown（不可判），不是 FN。"""
    manual = {"deductions": [_deduction("P9", "1", 14)]}
    report = backtest_v2(manual, results=[])
    assert report["not_checked_visits"] == 1
    assert report["overall"]["fn"] == 0 and report["overall"]["unknown"] == 1


def test_zero_denominator_renders_as_none_not_100pct():
    """无任何已判样本 → precision/recall/unknown_ratio=null（不写 100%）。"""
    manual = {"deductions": [], "evaluated_negatives": []}
    report = backtest_v2(manual, results=[])
    assert report["overall"]["precision"] is None
    assert report["overall"]["recall"] is None
    assert report["overall"]["unknown_ratio"] is None
    markdown = render_markdown_v2(report)
    assert "不可估计" in markdown and "100%" not in markdown.replace(
        "不写 100%", "")


def test_per_dept_and_clause_aggregation():
    manual = {
        "deductions": [
            _deduction("P1", "1", 14, clause="C1", dept="D001"),
            _deduction("P2", "1", 71, clause="C2", dept="D002"),
        ],
        "evaluated_negatives": [
            {"patient_id": "P1", "visit_id": "1", "fids": [57],
             "reviewed_at": "2026-08-28T10:00:00"}]}
    results = [
        _result("P1", "1", fids_hit={14, 57}, dept="D001"),
        _result("P2", "1", fids_pass={71}, dept="D002"),
    ]
    report = backtest_v2(manual, results)
    assert report["per_dept"]["D001"] == {"tp": 1, "fp": 1, "fn": 0} \
        or (report["per_dept"]["D001"]["tp"] == 1
            and report["per_dept"]["D001"]["fp"] == 1
            and report["per_dept"]["D001"]["fn"] == 0)
    assert report["per_dept"]["D002"]["fn"] == 1
    assert report["per_clause"]["14:C1"]["tp"] == 1
    assert report["per_clause"]["71:C2"]["fn"] == 1
    assert report["per_clause"]["57:C1"]["fp"] == 1


def test_fp_reason_aggregation_from_hit_annotations():
    manual = {
        "deductions": [_deduction("P1", "1", 14)],
        "evaluated_negatives": [
            {"patient_id": "P1", "visit_id": "1", "fids": [57, 71],
             "reviewed_at": "2026-08-28T10:00:00"}],
        "hit_annotations": [
            {"patient_id": "P1", "visit_id": "1", "fid": 57,
             "verdict": "false_positive", "reason": "文书存在但标题变体未收录"},
            {"patient_id": "P1", "visit_id": "1", "fid": 71,
             "verdict": "false_positive", "reason": "豁免场景（自动出院）"},
            {"patient_id": "P1", "visit_id": "1", "fid": 14,
             "verdict": "confirmed", "reason": "确属缺陷"},
        ]}
    results = [_result("P1", "1", fids_hit={14, 57, 71})]
    report = backtest_v2(manual, results)
    assert report["fp_reason_counts"] == {
        "文书存在但标题变体未收录": 1, "豁免场景（自动出院）": 1}
    assert report["overall"]["tp"] == 1 and report["overall"]["fp"] == 2


def test_manual_scope_metadata_recorded():
    manual = {
        "deductions": [_deduction("P1", "1", 14)],
        "confirmation": {"confirmed_sample_count": 42,
                         "confirmed_by": "质控科", "confirmed_at": "2026-08-29"}}
    report = backtest_v2(manual, results=[])
    scope = report["manual_scope"]
    assert scope["deduction_rows"] == 1
    assert scope["confirmed_sample_count"] == 42
    assert scope["confirmed_by"] == "质控科"


def test_v1_problems_fallback_and_unmapped_rule_ids():
    """无 evaluations 的旧结果行回退 problems；无 FID 映射规则只提示不计数。"""
    manual = {
        "deductions": [_deduction("P1", "1", 14)],
        "evaluated_negatives": [
            {"patient_id": "P1", "visit_id": "1", "fids": [34],
             "reviewed_at": "2026-08-28T10:00:00"}]}
    results = [{
        "patient_id": "P1", "visit_id": "1", "dept_code": "D001",
        "checked_at": "2026-08-27T12:00:00",
        "problems": [
            {"rule_id": "R-TIME-ADMISSION-RECORD-24H", "mark_item_fid": 14},
            {"rule_id": "R-TIME-FIRST-PROGRESS-8H", "mark_item_fid": 34},
            {"rule_id": "R-NO-FID-RULE", "mark_item_fid": None}],
    }]
    report = backtest_v2(manual, results,
                         rule_id_map={})
    assert report["overall"]["tp"] == 1
    assert report["overall"]["fp"] == 1
    assert "R-NO-FID-RULE" in report["unmapped_problem_rule_ids"]


def test_synthetic_benchmark_fixture_pipeline(tmp_path):
    """合成基准端到端：fixtures 三患者 → 引擎结果 → v2 报告（markdown 落盘）。"""
    from pathlib import Path
    from prearchive.collectors import (
        HisCollector, JhemrCollector, LisCollector, PatientContextBuilder,
        SmCollector)
    from prearchive.engine import RuleEngine
    from prearchive.fixture_sources import build_demo_fixtures
    from prearchive.rules import load_rules, rules_version

    rules_file = Path(__file__).resolve().parent.parent / "rules" / "example_rules.json"
    gateways = build_demo_fixtures()
    builder = PatientContextBuilder(
        jhemr=JhemrCollector(gateways["jhemr"]),
        his=HisCollector(gateways["his"]),
        sm=SmCollector(gateways["sm"]),
        lis=LisCollector(gateways["lis"]))
    engine = RuleEngine(load_rules(rules_file),
                        rule_version=rules_version(rules_file))

    results = []
    for row in gateways["jhemr"].pat_visits:
        from datetime import datetime
        from prearchive.context import FinishedVisit, parse_datetime
        visit = FinishedVisit(
            patient_id=row["patient_id"], visit_id=row["visit_id"],
            finished_date_time=parse_datetime(row["finished_date_time"]))
        output = engine.evaluate(builder.build(visit))
        results.append({
            "patient_id": visit.patient_id, "visit_id": visit.visit_id,
            "dept_code": row["dept_code"], "checked_at": "2026-08-28T09:00:00",
            "ruleset_revision": output.rule_version,
            "evaluations": output.evaluations})

    # 合成人工参照：李某（D002）扣 FID14（真缺陷=引擎也命中）；
    # 张某（D001）评过未扣 FID71（阴性范围；引擎对张某首页不可用=unknown 不命中）
    manual = {
        "deductions": [
            _deduction("TEST0002", "1", 14, reviewed="2026-08-28T10:00:00",
                       dept="D002")],
        "evaluated_negatives": [
            {"patient_id": "TEST0001", "visit_id": "1", "fids": [71],
             "reviewed_at": "2026-08-28T10:00:00"}],
        "confirmation": {"confirmed_sample_count": 2, "confirmed_by": "合成"},
    }
    report = backtest_v2(manual, results)
    assert report["overall"]["tp"] == 1
    assert report["overall"]["fp"] == 0            # 张某 FID71 引擎未命中（unknown 源）
    assert report["result_count"] == 3
    markdown = render_markdown_v2(report)
    out = tmp_path / "backtest-synthetic.md"
    out.write_text(markdown, encoding="utf-8")
    assert "FID" in markdown and "不可估计" in markdown
