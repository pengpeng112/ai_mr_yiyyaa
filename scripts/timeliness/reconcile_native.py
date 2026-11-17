"""引擎结论与 JHEMR 原生监控行对账报告（病历时效质控 T4 / 实证 R3）。

对 ADM_REC(JH04.02.001)、FIRST_COURSE(JH04.02.002)、CHIEF_FIRST_ROUND(JH04.02.008)、
DISCHARGE_REC(JH04.02.011，2026-11-13 返工新增——生产 2026-11-10 已配
JH07.01.0004 原生自动触发）四条规则，把本地引擎台账（tl_event）与
emr_online_monitor 的对应行逐患者比较，输出四类清单：
  A. 两边都未完成
  B. 引擎完成但原生未关闭（幽灵行，对应实证 R3 —— 全院启用锁定前必须查清）
  C. 原生完成但引擎未完成
  D. 两边都完成
另附仅引擎有 / 仅原生有 两个补充清单（不在四类之内的患者）。

两种运行模式：
1. --fixture <json>：本地假数据演练，输出 review/timeliness/T4_reconcile_fixture.md
   （患者号脱敏为后 4 位）。fixture JSON 键：
   {"events": [{patient_id, visit_id, rule_code, status}, ...],
    "monitor_rows": [{patient_id, visit_id, item_code, completed_date}, ...]}
2. 真实模式（授权后由用户在 84 容器运行，AI 不执行）：读应用库 tl_event +
   经只读账号取 emr_online_monitor，输出 review/timeliness/T4_reconcile_{YYYYMMDD}.md。
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

# 保证以 `python scripts/timeliness/reconcile_native.py` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("reconcile_native")

# 对账规则 ↔ 原生监控码（主设计文档 §15 T4 第 5 条；D8 依据 §18.1/§18.4）。
# 2026-11-13 返工：新增 DISCHARGE_REC/JH04.02.011（生产 2026-11-10 起原生自动触发）。
RECONCILE_RULE_ITEMS: tuple[tuple[str, str], ...] = (
    ("ADM_REC", "JH04.02.001"),
    ("FIRST_COURSE", "JH04.02.002"),
    ("CHIEF_FIRST_ROUND", "JH04.02.008"),
    ("DISCHARGE_REC", "JH04.02.011"),
)

# 引擎侧"已完成"状态（与 app/timeliness/scanner.ENGINE_COMPLETED_STATUSES 一致）。
ENGINE_COMPLETED_STATUSES = ("COMPLETED_ON_TIME", "COMPLETED_LATE")

CATEGORY_BOTH_OPEN = "both_open"                  # A. 两边都未完成
CATEGORY_ENGINE_DONE_NATIVE_OPEN = "engine_done_native_open"  # B. 幽灵行（R3）
CATEGORY_NATIVE_DONE_ENGINE_OPEN = "native_done_engine_open"  # C. 原生完成但引擎未完成
CATEGORY_BOTH_DONE = "both_done"                  # D. 两边都完成
CATEGORY_ENGINE_ONLY = "engine_only"              # 补充：仅引擎有事件
CATEGORY_NATIVE_ONLY = "native_only"              # 补充：仅原生有监控行

CATEGORIES = (
    CATEGORY_BOTH_OPEN,
    CATEGORY_ENGINE_DONE_NATIVE_OPEN,
    CATEGORY_NATIVE_DONE_ENGINE_OPEN,
    CATEGORY_BOTH_DONE,
    CATEGORY_ENGINE_ONLY,
    CATEGORY_NATIVE_ONLY,
)

CATEGORY_TITLES = {
    CATEGORY_BOTH_OPEN: "A. 两边都未完成（引擎未完成 且 原生未关闭）",
    CATEGORY_ENGINE_DONE_NATIVE_OPEN: "B. 引擎完成但原生未关闭（幽灵行，实证 R3）",
    CATEGORY_NATIVE_DONE_ENGINE_OPEN: "C. 原生完成但引擎未完成",
    CATEGORY_BOTH_DONE: "D. 两边都完成",
    CATEGORY_ENGINE_ONLY: "补充1. 仅引擎有事件（原生无监控行）",
    CATEGORY_NATIVE_ONLY: "补充2. 仅原生有监控行（引擎无事件）",
}


def mask_patient_id(patient_id: Any) -> str:
    """患者号脱敏：只保留后 4 位（隐私红线：报告不落完整患者号）。"""
    text = str(patient_id or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text) + text
    return "****" + text[-4:]


def _native_row_completed(row: Mapping[str, Any]) -> bool:
    """原生监控行是否已关闭：completed_date 非空视为完成（R1 口径）。"""
    value = row.get("completed_date")
    return value not in (None, "")


def classify_reconciliation(
    events: Sequence[Mapping[str, Any]],
    monitor_rows: Sequence[Mapping[str, Any]],
    *,
    rule_code: str,
    item_code: str,
) -> dict[str, list[dict]]:
    """纯函数：一条规则的引擎结论 vs 原生监控行，逐患者分入四类+两个补充清单。

    - 引擎侧"完成"= 该 (patient_id, visit_id) 任一事件状态为 COMPLETED_*；
    - 原生侧"关闭"= 该患者该监控码的全部监控行 completed_date 均非空
      （存在任一未关闭行即视为原生未关闭——转科重复生成行会把患者继续锁住）；
    - 四类清单只覆盖两侧都有的患者；仅单侧的进补充清单。
    """
    engine_completed: set[tuple[str, str]] = set()
    engine_all: set[tuple[str, str]] = set()
    for event in events or ():
        pid = str(event.get("patient_id") or "").strip()
        vid = str(event.get("visit_id") or "").strip()
        if not pid or not vid:
            continue
        key = (pid, vid)
        engine_all.add(key)
        if str(event.get("status") or "").strip() in ENGINE_COMPLETED_STATUSES:
            engine_completed.add(key)

    native_rows_by_patient: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in monitor_rows or ():
        code = str(row.get("item_code") or "").strip()
        if code != item_code:
            continue
        pid = str(row.get("patient_id") or "").strip()
        vid = str(row.get("visit_id") or "").strip()
        if not pid or not vid:
            continue
        native_rows_by_patient[(pid, vid)].append(dict(row))

    def native_state(key: tuple[str, str]) -> str | None:
        rows = native_rows_by_patient.get(key)
        if not rows:
            return None                       # 无监控行
        return "closed" if all(_native_row_completed(r) for r in rows) else "open"

    result: dict[str, list[dict]] = {category: [] for category in CATEGORIES}
    all_keys = sorted(engine_all | set(native_rows_by_patient))
    for pid, vid in all_keys:
        key = (pid, vid)
        engine_done = key in engine_completed
        state = native_state(key)
        entry = {
            "patient_id_masked": mask_patient_id(pid),
            "visit_id": vid,
            "engine_done": engine_done,
            "native_state": state,
            "monitor_rows": len(native_rows_by_patient.get(key) or []),
        }
        if state is None:
            result[CATEGORY_ENGINE_ONLY].append(entry)
            continue
        if key not in engine_all:
            result[CATEGORY_NATIVE_ONLY].append(entry)
            continue
        if engine_done and state == "open":
            result[CATEGORY_ENGINE_DONE_NATIVE_OPEN].append(entry)
        elif engine_done and state == "closed":
            result[CATEGORY_BOTH_DONE].append(entry)
        elif not engine_done and state == "open":
            result[CATEGORY_BOTH_OPEN].append(entry)
        else:
            result[CATEGORY_NATIVE_DONE_ENGINE_OPEN].append(entry)
    return result


def _entry_line(entry: dict) -> str:
    return (
        f"| {entry['patient_id_masked']} | {entry['visit_id']} | "
        f"{'完成' if entry['engine_done'] else '未完成'} | "
        f"{ {'open': '未关闭', 'closed': '已关闭', None: '无行'}[entry['native_state']] } |"
    )


def render_report(
    classified_by_rule: Mapping[str, dict[str, list[dict]]],
    *,
    generated_at: str,
    source_label: str,
) -> str:
    """把分好类的结果渲染为 Markdown 报告（患者号已脱敏）。"""
    lines = [
        "# T4 引擎结论 × JHEMR 原生监控行 对账报告",
        "",
        f"- 生成时间：{generated_at}",
        f"- 数据来源：{source_label}",
        "- 对账范围：" + "、".join(
            f"{code}({item})" for code, item in RECONCILE_RULE_ITEMS
        ),
        "- 判定口径：引擎完成=tl_event 状态 COMPLETED_*；原生关闭=该患者该监控码"
          "全部监控行 completed_date 非空（任一行未关闭即视为未关闭）。",
        "- B 类（引擎完成但原生未关闭）即实证 R3 的幽灵行：**启用对应码锁定前必须"
          "查清**（D8，§18.1/§18.4；001 已于 2026-11-10 生产销账解除，008 仍受限；"
          "011 自 2026-11-10 起为原生自动触发）。",
        "",
    ]
    for rule_code, item_code in RECONCILE_RULE_ITEMS:
        classified = classified_by_rule.get(rule_code)
        if classified is None:
            continue
        lines.append(f"## {rule_code}（{item_code}）")
        lines.append("")
        lines.append("| 分类 | 人数 |")
        lines.append("| --- | ---: |")
        for category in CATEGORIES:
            lines.append(f"| {CATEGORY_TITLES[category]} | {len(classified[category])} |")
        lines.append("")
        for category in CATEGORIES:
            entries = classified[category]
            if not entries:
                continue
            lines.append(f"### {CATEGORY_TITLES[category]}（{len(entries)} 人）")
            lines.append("")
            lines.append("| 患者号(脱敏) | 次数 | 引擎 | 原生 |")
            lines.append("| --- | --- | --- | --- |")
            lines.extend(_entry_line(entry) for entry in entries)
            lines.append("")
    return "\n".join(lines) + "\n"


def classify_from_fixture(fixture: Mapping[str, Any]) -> dict[str, dict[str, list[dict]]]:
    """fixture 演练：events 按 rule_code 分组后逐条对账。"""
    events_by_rule: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in fixture.get("events") or ():
        events_by_rule[str(event.get("rule_code") or "").strip()].append(event)
    monitor_rows = list(fixture.get("monitor_rows") or ())
    classified: dict[str, dict[str, list[dict]]] = {}
    for rule_code, item_code in RECONCILE_RULE_ITEMS:
        classified[rule_code] = classify_reconciliation(
            events_by_rule.get(rule_code) or [], monitor_rows,
            rule_code=rule_code, item_code=item_code,
        )
    return classified


def classify_from_live() -> tuple[dict[str, dict[str, list[dict]]], str]:
    """真实模式：应用库 tl_event + 只读账号 emr_online_monitor（用户在 84 容器运行）。"""
    from sqlalchemy.orm import Session

    from app.database import SessionLocal
    from app.timeliness import jhemr_reader
    from app.timeliness.models import TLEvent
    from app.timeliness.scanner import ENGINE_COMPLETED_STATUSES as _EC

    assert _EC == ENGINE_COMPLETED_STATUSES  # 两处完成口径必须一致

    rule_codes = [code for code, _ in RECONCILE_RULE_ITEMS]
    db: Session = SessionLocal()
    try:
        rows = (
            db.query(TLEvent.patient_id, TLEvent.visit_id, TLEvent.status, TLEvent.rule_code)
            .filter(TLEvent.rule_code.in_(rule_codes))
            .all()
        )
    finally:
        db.close()

    events_by_rule: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for pid, vid, status, rule_code in rows:
        events_by_rule[str(rule_code)].append(
            {"patient_id": pid, "visit_id": vid, "status": status}
        )

    pairs = sorted({
        (str(row["patient_id"]).strip(), str(row["visit_id"]).strip())
        for events in events_by_rule.values()
        for row in events
    })
    item_codes = [item for _, item in RECONCILE_RULE_ITEMS]
    monitor_rows = jhemr_reader.list_monitor_rows(pairs, item_codes) if pairs else []

    classified = {
        rule_code: classify_reconciliation(
            events_by_rule.get(rule_code) or [], monitor_rows,
            rule_code=rule_code, item_code=item_code,
        )
        for rule_code, item_code in RECONCILE_RULE_ITEMS
    }
    return classified, f"app DB tl_event({len(rows)} rows) + jhemr.emr_online_monitor"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T4 引擎×原生监控行对账报告")
    parser.add_argument("--fixture", help="本地假数据 JSON（演练模式，输出固定 fixture 报告名）")
    parser.add_argument("--out", help="输出 Markdown 路径（默认按模式自动命名）")
    args = parser.parse_args(argv)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if args.fixture:
        fixture = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        classified = classify_from_fixture(fixture)
        source_label = f"fixture {args.fixture}"
        out_path = Path(args.out or "review/timeliness/T4_reconcile_fixture.md")
    else:
        classified, source_label = classify_from_live()
        stamp = datetime.now().strftime("%Y%m%d")
        out_path = Path(args.out or f"review/timeliness/T4_reconcile_{stamp}.md")

    report = render_report(classified, generated_at=generated_at, source_label=source_label)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    counts = {
        rule: {cat: len(items) for cat, items in per_rule.items()}
        for rule, per_rule in classified.items()
    }
    logger.info("对账报告已写入 %s；分类计数=%s", out_path, json.dumps(counts, ensure_ascii=False))
    print(json.dumps({"report_path": str(out_path), "counts": counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
