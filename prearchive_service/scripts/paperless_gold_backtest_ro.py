# -*- coding: utf-8 -*-
"""影子结果 vs 无纸化人工金标准回测（只读；WP07 / 064 总计划）。

把「影子检出结果」与「CDMS 人工扣分/评审结果」转换成 backtest_v2 需要的结构后
**直接调用** `prearchive.backtest.backtest_v2` 与 `render_markdown_v2`（复用原则，
不重写指标计算）；报告患者标识哈希/掩码（P***后4位）。

输入（两种模式，单测走纯离线）：
- 影子检出结果：--results-json <file>（离线）或预检服务结果库只读（--result-db，
  SQLite/Oracle 均可，凭据走环境变量；本脚本只 SELECT）；
- 人工金标准：--manual-json <file>（离线）或 --paperless-json（盘点脚本输出结构）。

results-json 结构（与 backtest_v2 入参一致）：
[{"patient_id", "visit_id", "dept_code", "checked_at", "ruleset_revision",
  "problems": [{"rule_id", "severity", ...}], "evaluations": [{"fid", "status", ...}]}]
manual-json 结构：backtest_v2 的 manual（deductions/evaluated_negatives/
hit_annotations/confirmation）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prearchive.backtest import backtest_v2, render_markdown_v2  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "example_rules.json"


def mask_pid(value: Any) -> str:
    """患者号掩码：P*** + 后 4 位（报告不落完整患者号）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return "P***" + text[-4:] if len(text) > 4 else "P***" + text


def _rule_id_map(rules_path: Path) -> dict:
    """example_rules.json 的 rule_id → mark_item_fid 映射（backtest_v2 rule_id_map）。"""
    try:
        payload = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping = {}
    for rule in payload.get("rules") or []:
        if isinstance(rule, dict) and rule.get("mark_item_fid") is not None:
            mapping[str(rule.get("rule_id") or "")] = int(rule["mark_item_fid"])
    return mapping


def load_results(path: Path | None) -> list[dict]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("results") if isinstance(payload, dict) else payload


def load_manual(path: Path | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_manual_from_paperless(paperless_path: Path | None) -> dict:
    """从盘点脚本输出结构（T_MARK_DETAIL 口径）组装 backtest_v2 manual。

    盘点输出只有聚合计数，无法回溯逐患者——此处支持扩展版盘查结构
    {"deductions": [...], "evaluated_negatives": [...], "confirmation": {...}}；
    纯聚合输入无法构造金标准时返回空 manual（报告中说明范围不足）。
    """
    if not paperless_path or not Path(paperless_path).exists():
        return {}
    payload = json.loads(Path(paperless_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "deductions" in payload:
        return payload
    return {}   # 纯聚合盘点：缺逐患者明细，无法构成金标准


def fetch_results_from_db(db_url: str) -> list[dict]:
    """从预检服务结果库只读拉取影子结果（SELECT-only；SQLAlchemy 通用方言）。

    结果库 schema：prearchive_result（id/patient_id/visit_id/dept_code/
    finished_date_time/problems_json/rule_version）。凭据走 db_url（可 env: 引用）。
    """
    if db_url.startswith("env:"):
        import os
        db_url = os.environ.get(db_url[4:], "")
    if not db_url:
        raise RuntimeError("结果库连接串为空（--result-db env:VAR 未设置）")
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, patient_id, visit_id, dept_code, finished_date_time, "
            "problems_json, rule_version FROM prearchive_result "
            "ORDER BY finished_date_time DESC"
        )).fetchall()
    results = []
    for row in rows:
        results.append({
            "patient_id": str(row[1]),
            "visit_id": str(row[2]),
            "dept_code": str(row[3] or ""),
            "checked_at": row[4].isoformat() if row[4] else None,
            "ruleset_revision": str(row[6] or ""),
            "problems": json.loads(row[5] or "[]"),
            "evaluations": [],
        })
    return results


def render_masked_report(report: dict, markdown: str, *, source_note: str) -> str:
    """在 render_markdown_v2 输出后附患者号掩码清单段（不落完整患者号）。"""
    overall = report["overall"]
    lines = [
        "# 影子结果 vs 人工金标准回测（只读 / 脱敏）",
        "",
        f"- 数据来源：{source_note}",
        f"- 总体：TP={overall['tp']} FP={overall['fp']} FN={overall['fn']} "
        f"unknown={overall['unknown']}（judged={overall['judged']}）",
        f"- precision={overall['precision']} recall={overall['recall']}",
        f"- 建议阈值参考：命中率（recall）>= 0.80 且 误报率（FP/judged）<= 0.20 方可评估"
        f"「辅助上线」（须病案室确认）。",
        "",
        "## backtest_v2 明细",
        "",
        markdown,
        "",
        "## 患者标识（掩码 P***后4位）",
        "",
    ]
    seen = set()
    for key in sorted(report.get("patient_keys", []) or []):
        masked = mask_pid(key[0] if isinstance(key, (list, tuple)) else key)
        if masked not in seen:
            seen.add(masked)
            lines.append(f"- {masked}")
    if not seen:
        lines.append("- （本次回测范围无患者明细或已全部掩码）")
    lines += ["", "> 患者标识经 mask_pid 脱敏；原始患者号只保留后 4 位用于人工比对。"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="影子结果 vs 人工金标准回测（只读/脱敏）")
    parser.add_argument("--results-json", default="", help="影子检出结果 JSON（离线模式）")
    parser.add_argument("--result-db", default="", help="预检服务结果库连接（env:VAR 只读）")
    parser.add_argument("--manual-json", default="", help="人工金标准 JSON（backtest_v2 manual 结构）")
    parser.add_argument("--paperless-json", default="", help="盘点脚本扩展结构（含逐患者明细）")
    parser.add_argument("--rules-file", default=str(RULES_PATH))
    parser.add_argument("--output", default="",
                        help="Markdown 输出路径（默认 review/prearchive/paperless_gold_backtest_<YYYYMMDD>.md）")
    parser.add_argument("--tolerance-seconds", type=int, default=86400)
    args = parser.parse_args(argv)

    results = load_results(Path(args.results_json)) if args.results_json else []
    source_note = f"离线文件（--results-json {args.results_json}）" if args.results_json else ""
    if not results and args.result_db:
        results = fetch_results_from_db(args.result_db)
        source_note = f"结果库只读（--result-db，{len(results)} 条影子结果）"
    manual = load_manual(Path(args.manual_json)) if args.manual_json else {}
    if not manual:
        manual = build_manual_from_paperless(
            Path(args.paperless_json) if args.paperless_json else None)
        if args.paperless_json:
            source_note = f"{source_note} 人工金标准={args.paperless_json}".strip()
    if not results or not manual:
        print("[backtest] 缺少影子结果或人工金标准（--results-json/--manual-json 必填，"
              "或 --result-db/--paperless-json）", file=sys.stderr)
        return 2

    report = backtest_v2(
        manual, results,
        rule_id_map=_rule_id_map(Path(args.rules_file)),
        alignment_tolerance_seconds=args.tolerance_seconds,
    )
    # 附患者掩码清单（backtest_v2 无 patient_keys 输出——从入参 key 集推导）
    report = dict(report)
    keys = set()
    for row in manual.get("deductions") or []:
        keys.add((str(row.get("patient_id")), str(row.get("visit_id"))))
    for row in manual.get("evaluated_negatives") or []:
        keys.add((str(row.get("patient_id")), str(row.get("visit_id"))))
    report["patient_keys"] = sorted(keys)

    markdown = render_markdown_v2(report)
    output = Path(args.output or (
        REPO_ROOT / "review" / "prearchive"
        / f"paperless_gold_backtest_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.md"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_masked_report(report, markdown, source_note=source_note or "离线文件"),
        encoding="utf-8")
    print(f"[backtest] 已输出：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
