# -*- coding: utf-8 -*-
"""金标准回测框架（031 T2-7）：fixture 驱动本地可跑，真数据等 W9 批准。

口径（R13）：
- 人工扣分样本（金标准）：[{patient_id, visit_id, hit_fids:[FID...]}]——
  fixture 一律 TEST 前缀虚构；FID 取值域=快照；
- 预检结果集：[{patient_id, visit_id, problems:[...]}]——problems 内
  mark_item_fid 映射后的命中集合；示例规则 fid=null 时按 rule_id 对照表换算
  （rule_id_map: {rule_id: fid}，由调用方提供）；
- 输出：总体 + 按 FID 两级 precision / recall / false-positive。

真数据版=同一框架换数据源（生产只读侧拉聚合脱敏样本，走 W9 批准，
患者级明细一行不出无纸化库）。
"""

from __future__ import annotations

from collections import defaultdict


def hit_fids_from_results(results: list, rule_id_map: dict = None) -> dict:
    """预检结果 → {(pid, vid): set(FID)}。

    problem["mark_item_fid"] 优先；为 null 时用 rule_id_map[rule_id] 换算；
    两者皆缺的 problem 计入 unmapped_problem_ids（报告提示映射缺口）。
    """
    mapping = rule_id_map or {}
    hits: dict = defaultdict(set)
    unmapped = []
    for row in results or []:
        key = (str(row.get("patient_id") or ""), str(row.get("visit_id") or ""))
        for problem in row.get("problems") or []:
            fid = problem.get("mark_item_fid")
            if fid is None:
                fid = mapping.get(problem.get("rule_id") or "")
            if fid is None:
                unmapped.append(problem.get("rule_id") or "<unknown>")
                continue
            hits[key].add(int(fid))
    return dict(hits), sorted(set(unmapped))


def backtest(samples: list, results: list, rule_id_map: dict = None) -> dict:
    """样本（金标准）vs 预检结果 → 总体+按 FID 两级指标。

    - precision = TP / (TP + FP)：预检命中中人工也扣分的比例；
    - recall    = TP / (TP + FN)：人工扣分中预检命中的比例；
    - false_positive = 预检命中但人工未扣分的 (患者, FID) 计数。
    """
    hits, unmapped = hit_fids_from_results(results, rule_id_map)
    gold: dict = defaultdict(set)
    for row in samples or []:
        key = (str(row.get("patient_id") or ""), str(row.get("visit_id") or ""))
        gold[key] = {int(f) for f in (row.get("hit_fids") or [])}

    tp_total = fp_total = fn_total = 0
    per_fid: dict = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    all_keys = set(gold) | set(hits)
    for key in all_keys:
        gold_fids = gold.get(key) or set()
        hit_fids = hits.get(key) or set()
        for fid in hit_fids & gold_fids:
            tp_total += 1
            per_fid[fid]["tp"] += 1
        for fid in hit_fids - gold_fids:
            fp_total += 1
            per_fid[fid]["fp"] += 1
        for fid in gold_fids - hit_fids:
            fn_total += 1
            per_fid[fid]["fn"] += 1

    def _metrics(tp, fp, fn):
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        return {"tp": tp, "fp": fp, "fn": fn,
                "precision": round(precision, 4) if precision is not None else None,
                "recall": round(recall, 4) if recall is not None else None}

    return {
        "overall": _metrics(tp_total, fp_total, fn_total),
        "false_positive": fp_total,
        "per_fid": {str(fid): _metrics(m["tp"], m["fp"], m["fn"])
                    for fid, m in sorted(per_fid.items())},
        "unmapped_problem_rule_ids": unmapped,
        "sample_count": len(samples or []),
        "result_count": len(results or []),
    }


def render_markdown(report: dict) -> str:
    overall = report["overall"]
    lines = [
        "# 金标准回测报告（backtest）",
        "",
        f"- 样本数：{report['sample_count']}；预检结果数：{report['result_count']}",
        f"- 总体：TP={overall['tp']} FP={overall['fp']} FN={overall['fn']}",
        (f"- precision={overall['precision']}  recall={overall['recall']}  "
         f"false-positive={report['false_positive']}"),
        "",
        "| FID | TP | FP | FN | precision | recall |",
        "|---|---|---|---|---|---|",
    ]
    for fid, m in report["per_fid"].items():
        lines.append(
            f"| {fid} | {m['tp']} | {m['fp']} | {m['fn']} | "
            f"{m['precision'] if m['precision'] is not None else '-'} | "
            f"{m['recall'] if m['recall'] is not None else '-'} |")
    if report["unmapped_problem_rule_ids"]:
        lines.append("")
        lines.append("> 注意：以下 rule_id 无 FID 映射（示例规则未签字回填属预期）："
                     + ", ".join(report["unmapped_problem_rule_ids"]))
    return "\n".join(lines) + "\n"
