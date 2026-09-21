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


# ===========================================================================
# 046 T8：v2 回测——人工扣分=参照而非无条件金标准
# ===========================================================================
# 语义修正（对照 v1）：
# 1. 人工没扣分 ≠ 已审查合格：只有**人工已评范围内**（该就诊该 FID 被评审过，
#    无论是否扣分）的"规则命中且无扣分"才计 FP；范围外命中=unknown（不可判定）；
# 2. 对齐：规则结果的数据时点晚于人工所看数据时点+容忍窗（整改后回测整改前）
#    → 排除并计数，不进 TP/FN；
# 3. 五态参与判定：规则 unknown/pending 的子句不算 FN（无分母不可估计）；
# 4. precision/recall/覆盖率分母为 0 → None（不可估计），不写 100%；
# 5. 报告按 FID/子句/科室三级 + unknown 比例 + FP 原因聚合。
from datetime import datetime, timedelta


def _parse_ts(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _result_fids(result: dict, rule_id_map: dict) -> tuple:
    """结果行 → ({fid}, {fid→clause_id}, {fid→状态秩}, unmapped_rule_ids)。

    evaluations（046 T2 五态）优先；缺省回退 problems（等价 v1：命中=hit）。
    """
    mapping = rule_id_map or {}
    hits, clause_of, rank_of, unmapped = set(), {}, {}, []
    evaluations = result.get("evaluations")
    if evaluations is None:
        evaluations = [{"rule_id": p.get("rule_id"),
                        "mark_item_fid": p.get("mark_item_fid"),
                        "status": "fail"}
                       for p in result.get("problems") or []]
    for item in evaluations or []:
        # 兼容两键名：引擎 evaluations 用 fid；problems 摘要用 mark_item_fid
        fid = item.get("mark_item_fid", item.get("fid"))
        if fid is None:
            fid = mapping.get(item.get("rule_id") or "")
        if fid is None:
            unmapped.append(str(item.get("rule_id") or "<unknown>"))
            continue
        fid = int(fid)
        status = str(item.get("status") or "fail")
        if status == "fail":
            hits.add(fid)
            clause_of.setdefault(fid, item.get("clause_id") or "")
        rank = {"fail": 3, "unknown": 2, "pending": 2}.get(status, 1)
        if rank > rank_of.get(fid, 0):
            rank_of[fid] = rank
    return hits, clause_of, rank_of, sorted(set(unmapped))


def backtest_v2(manual: dict, results: list, *,
                rule_id_map: dict = None,
                alignment_tolerance_seconds: int = 86400) -> dict:
    """人工参照（扣分+已评阴性范围）vs 规则结果 → 三级指标。

    manual = {
      "deductions": [{patient_id, visit_id, fid, clause_id?, dept_code?,
                      reviewed_at, data_as_of?, deduct_ref?}],
      "evaluated_negatives": [{patient_id, visit_id, fids:[...], reviewed_at,
                               data_as_of?}],   # 评审过、未扣分的范围
      "hit_annotations": [{patient_id, visit_id, fid,
                           verdict: confirmed|false_positive|pending_review,
                           reason}],            # 人工对规则命中的复核标注
      "confirmation": {"confirmed_sample_count", "confirmed_by", "confirmed_at"}
    }
    results = [{patient_id, visit_id, dept_code, checked_at,
                ruleset_revision, problems, evaluations}]
    """
    mapping = rule_id_map or {}
    tolerance = timedelta(seconds=alignment_tolerance_seconds)

    deductions = {}          # (pid,vid) -> [row]
    reviewed = {}            # (pid,vid) -> {fid 已评（含扣分）}
    sample_meta = {}
    for row in manual.get("deductions") or []:
        key = (str(row.get("patient_id")), str(row.get("visit_id")))
        deductions.setdefault(key, []).append(row)
        reviewed.setdefault(key, set()).add(int(row["fid"]))
        sample_meta.setdefault(key, row)
    for row in manual.get("evaluated_negatives") or []:
        key = (str(row.get("patient_id")), str(row.get("visit_id")))
        for fid in row.get("fids") or []:
            reviewed.setdefault(key, set()).add(int(fid))
        sample_meta.setdefault(key, row)

    result_by_key = {(str(r.get("patient_id")), str(r.get("visit_id"))): r
                     for r in results or []}
    unmapped_all: set = set()

    counters = {"fid": {}, "clause": {}, "dept": {}}
    overall = {"tp": 0, "fp": 0, "fn": 0, "unknown": 0,
               "alignment_excluded": 0}
    fp_reasons: dict = {}
    alignment_excluded_visits = 0
    not_checked_visits = 0

    def _bucket(level, dim_key):
        table = counters[level]
        if dim_key not in table:
            table[dim_key] = {"tp": 0, "fp": 0, "fn": 0, "unknown": 0,
                              "alignment_excluded": 0}
        return table[dim_key]

    def _record(dim_keys, field):
        overall[field] += 1
        for level, key in dim_keys:
            _bucket(level, key)[field] += 1

    all_keys = set(deductions) | set(reviewed)
    for key in sorted(all_keys):
        meta = sample_meta.get(key) or {}
        reviewed_at = _parse_ts(meta.get("reviewed_at"))
        data_as_of = _parse_ts(meta.get("data_as_of")) or reviewed_at
        result = result_by_key.get(key)
        deduct_rows = deductions.get(key, [])
        deduct_fids = {int(d["fid"]) for d in deduct_rows}

        if result is None:
            # 无结果：人工扣分仍在，但规则侧不可判 → unknown（非 FN）
            not_checked_visits += 1
            for fid in sorted(deduct_fids):
                _record([("fid", fid)], "unknown")
            continue

        checked_at = _parse_ts(result.get("checked_at"))
        if reviewed_at is not None and checked_at is not None \
                and data_as_of is not None and checked_at > data_as_of + tolerance:
            # 整改后结果 vs 整改前扣分：对齐失败，排除（不进 TP/FN/unknown）
            alignment_excluded_visits += 1
            for fid in sorted(deduct_fids):
                _record([("fid", fid)], "alignment_excluded")
            continue

        dept = str(result.get("dept_code") or meta.get("dept_code") or "")
        dept_key = dept or "未标注科室"
        hits, clause_of, rank_of, unmapped = _result_fids(result, mapping)
        unmapped_all.update(unmapped)

        # 阳性参照逐条判：人工扣分 fid
        for row in deduct_rows:
            fid = int(row["fid"])
            clause = str(row.get("clause_id") or "")
            dims = [("fid", fid), ("clause", f"{fid}:{clause}"),
                    ("dept", dept_key)]
            if fid in hits:
                _record(dims, "tp")
            elif rank_of.get(fid, 0) >= 2:
                # 规则对该 fid 给出 unknown/pending：无确定结论 → 不可判
                _record(dims, "unknown")
            else:
                _record(dims, "fn")

        # 阴性范围判 FP：评审过、未扣分、但规则命中
        for fid in sorted(reviewed.get(key, set()) - deduct_fids):
            if fid in hits:
                _record([("fid", fid), ("dept", dept_key),
                         ("clause", f"{fid}:{clause_of.get(fid, '')}")], "fp")

        # 范围外命中：人工未评审该 fid → 不可判定（不进 FP）
        for fid in sorted(hits - reviewed.get(key, set())):
            _record([("fid", fid)], "unknown")

    for ann in manual.get("hit_annotations") or []:
        if str(ann.get("verdict")) == "false_positive":
            reason = str(ann.get("reason") or "未注明")
            fp_reasons[reason] = fp_reasons.get(reason, 0) + 1

    def _metrics(counter: dict) -> dict:
        tp, fp, fn = counter["tp"], counter["fp"], counter["fn"]
        unknown = counter["unknown"]
        judged = tp + fp + fn
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        unknown_ratio = unknown / (judged + unknown) if (judged + unknown) else None
        return {"tp": tp, "fp": fp, "fn": fn, "unknown": unknown,
                "judged": judged,
                "alignment_excluded": counter["alignment_excluded"],
                "precision": round(precision, 4) if precision is not None else None,
                "recall": round(recall, 4) if recall is not None else None,
                "unknown_ratio": round(unknown_ratio, 4)
                if unknown_ratio is not None else None}

    confirmation = manual.get("confirmation") or {}
    return {
        "schema_version": "2.0.0",
        "alignment": {
            "tolerance_seconds": alignment_tolerance_seconds,
            "excluded_visits": alignment_excluded_visits,
            "note": "规则 checked_at 晚于人工 data_as_of+容忍窗"
                    "=整改后回测整改前，整就诊排除"},
        "overall": _metrics(overall),
        "per_fid": {str(fid): _metrics(counter)
                    for fid, counter in sorted(counters["fid"].items())},
        "per_clause": {clause: _metrics(counter)
                       for clause, counter in sorted(counters["clause"].items())},
        "per_dept": {dept: _metrics(counter)
                     for dept, counter in sorted(counters["dept"].items())},
        "not_checked_visits": not_checked_visits,
        "fp_reason_counts": dict(sorted(fp_reasons.items())),
        "unmapped_problem_rule_ids": sorted(unmapped_all),
        "manual_scope": {
            "deduction_rows": len(manual.get("deductions") or []),
            "evaluated_negative_rows": len(manual.get("evaluated_negatives") or []),
            "confirmed_sample_count": confirmation.get("confirmed_sample_count"),
            "confirmed_by": confirmation.get("confirmed_by", ""),
            "confirmed_at": confirmation.get("confirmed_at", ""),
        },
        "result_count": len(results or []),
        "notes": [
            "人工扣分为参照而非无条件金标准：未评范围内规则命中计 unknown，不计 FP",
            "precision/recall/unknown_ratio 分母为 0 时为 null（不可估计），不写 100%",
            "规则 unknown/pending 子句不计 FN；无结果就诊的扣分计 unknown",
        ],
    }


def render_markdown_v2(report: dict) -> str:
    overall = report["overall"]

    def _fmt(value):
        return "-" if value is None else str(value)

    lines = [
        "# 人工参照回测报告 v2（046 T8）",
        "",
        f"- 对齐容忍窗：{report['alignment']['tolerance_seconds']}s；"
        f"整改后回测排除就诊={report['alignment']['excluded_visits']}；"
        f"无结果就诊={report['not_checked_visits']}",
        f"- 人工范围：扣分 {report['manual_scope']['deduction_rows']} 条 / "
        f"已评阴性 {report['manual_scope']['evaluated_negative_rows']} 条 / "
        f"确认样本 {report['manual_scope']['confirmed_sample_count']}",
        f"- 总体：TP={overall['tp']} FP={overall['fp']} FN={overall['fn']} "
        f"unknown={overall['unknown']}（judged={overall['judged']}）",
        f"- precision={_fmt(overall['precision'])}  recall={_fmt(overall['recall'])}"
        f"  unknown_ratio={_fmt(overall['unknown_ratio'])}"
        "（null=分母为 0 不可估计，不写 100%）",
        "",
        "| FID | TP | FP | FN | unknown | precision | recall | unknown_ratio |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for fid, m in report["per_fid"].items():
        lines.append(f"| {fid} | {m['tp']} | {m['fp']} | {m['fn']} | {m['unknown']} "
                     f"| {_fmt(m['precision'])} | {_fmt(m['recall'])} "
                     f"| {_fmt(m['unknown_ratio'])} |")
    lines += ["", "| 科室 | TP | FP | FN | unknown | precision | recall |",
              "|---|---|---|---|---|---|---|"]
    for dept, m in report["per_dept"].items():
        lines.append(f"| {dept} | {m['tp']} | {m['fp']} | {m['fn']} | {m['unknown']} "
                     f"| {_fmt(m['precision'])} | {_fmt(m['recall'])} |")
    if report["per_clause"]:
        lines += ["", "| 子句 | TP | FP | FN | unknown |",
                  "|---|---|---|---|---|"]
        for clause, m in report["per_clause"].items():
            lines.append(f"| {clause} | {m['tp']} | {m['fp']} | {m['fn']} "
                         f"| {m['unknown']} |")
    if report["fp_reason_counts"]:
        lines += ["", "FP 原因聚合：" + "；".join(
            f"{reason}×{count}" for reason, count
            in report["fp_reason_counts"].items())]
    if report["unmapped_problem_rule_ids"]:
        lines += ["", "> 无 FID 映射的 rule_id（不计入指标，映射缺口提示）："
                     + ", ".join(report["unmapped_problem_rule_ids"])]
    lines += ["", "> " + "；".join(report["notes"])]
    return "\n".join(lines) + "\n"
