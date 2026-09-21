# -*- coding: utf-8 -*-
"""046 T8 回测运行脚本：合成基准（默认）与院内受控只读通道（骨架）。

用法::

    # 合成基准（demo fixtures + example 规则；零真实数据，产出 markdown 到 review/）
    python scripts/run_prearchive_backtest_20260911.py

    # 院内真实回测（受控只读；需授权后准备两份聚合脱敏 JSON，患者级明细不出源库）
    python scripts/run_prearchive_backtest_20260911.py \
        --manual docs/remediation/backtest_manual_YYYYMMDD.json \
        --results docs/remediation/backtest_results_YYYYMMDD.json \
        --out review/backtest-hospital-<日期>.md

输入契约见 prearchive_service/prearchive/backtest.py::backtest_v2 docstring
（manual=人工扣分+已评阴性范围+命中复核标注+确认样本；results=规则结果行，
evaluations 优先）。真实回测红线：患者级资料不离开批准环境；文档仅聚合结果
与脱敏标识（046 §T8）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRE = REPO / "prearchive_service"
sys.path.insert(0, str(PRE))


def run_synthetic() -> dict:
    """合成基准：demo fixtures 三患者 × example 规则 → v2 报告。"""
    from prearchive.backtest import backtest_v2, render_markdown_v2
    from prearchive.collectors import (
        HisCollector,
        JhemrCollector,
        LisCollector,
        PatientContextBuilder,
        SmCollector,
    )
    from prearchive.context import FinishedVisit, parse_datetime
    from prearchive.engine import RuleEngine
    from prearchive.fixture_sources import build_demo_fixtures
    from prearchive.rules import load_rules, rules_version

    rules_file = PRE / "rules" / "example_rules.json"
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
        visit = FinishedVisit(
            patient_id=row["patient_id"], visit_id=row["visit_id"],
            finished_date_time=parse_datetime(row["finished_date_time"]))
        output = engine.evaluate(builder.build(visit))
        results.append({
            "patient_id": visit.patient_id, "visit_id": visit.visit_id,
            "dept_code": row["dept_code"], "checked_at": "2026-08-28T09:00:00",
            "ruleset_revision": output.rule_version,
            "evaluations": output.evaluations})

    manual = {
        # 合成人工参照（虚构）：李某扣 FID14（与引擎一致=TP 面）；
        # 张某评过未扣 FID71（阴性范围）；王某全阴性范围（多 FID）。
        "deductions": [
            {"patient_id": "TEST0002", "visit_id": "1", "fid": 14,
             "clause_id": "C1", "dept_code": "D002",
             "reviewed_at": "2026-08-28T10:00:00", "deduct_ref": 2.0}],
        "evaluated_negatives": [
            {"patient_id": "TEST0001", "visit_id": "1", "fids": [71, 57],
             "reviewed_at": "2026-08-28T10:00:00"},
            {"patient_id": "TEST0003", "visit_id": "1",
             "fids": [14, 34, 55, 57, 65, 71],
             "reviewed_at": "2026-08-28T10:30:00"}],
        "hit_annotations": [],
        "confirmation": {"confirmed_sample_count": 3, "confirmed_by": "合成基准",
                         "confirmed_at": "2026-09-11"},
    }
    report = backtest_v2(manual, results)
    return {"report": report, "markdown": render_markdown_v2(report)}


def run_hospital(manual_path: str, results_path: str) -> dict:
    from prearchive.backtest import backtest_v2, render_markdown_v2
    manual = json.loads(Path(manual_path).read_text(encoding="utf-8"))
    results = json.loads(Path(results_path).read_text(encoding="utf-8"))
    report = backtest_v2(manual, results)
    return {"report": report, "markdown": render_markdown_v2(report)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="046 T8 回测运行（合成/院内）")
    parser.add_argument("--manual", help="院内模式：人工参照 JSON（授权后准备）")
    parser.add_argument("--results", help="院内模式：规则结果 JSON")
    parser.add_argument("--out", default="",
                        help="markdown 输出路径（默认 review/backtest-synthetic-<日期>.md）")
    args = parser.parse_args(argv)

    if args.manual and args.results:
        bundle = run_hospital(args.manual, args.results)
        out = Path(args.out or
                   f"review/backtest-hospital-{datetime.now():%Y%m%d}.md")
    else:
        bundle = run_synthetic()
        out = Path(args.out or
                   f"review/backtest-synthetic-{datetime.now():%Y%m%d}.md")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(bundle["markdown"], encoding="utf-8")
    print(f"[backtest] markdown → {out}")
    print(json.dumps(bundle["report"]["overall"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
