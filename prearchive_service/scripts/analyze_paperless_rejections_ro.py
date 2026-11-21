# -*- coding: utf-8 -*-
"""无纸化人工质控盘点（只读；WP07 / 064 总计划 拍板 D3 第 2 步准备）。

用途：从无纸化 CDMS（10.10.10.93）只读统计近 N 天人工扣分/打回数据，对照
`rules/example_rules.json` 已规则化的 `t_mark_item` FID，输出「已覆盖 /
高频未覆盖·可规则化 / 高频未覆盖·建议 AI」三组清单，为金标准回测与规则扩容
提供依据。零患者姓名/住院号输出（只输出计数与词频）。

数据来源（表名来自 CDMS 活库字典，全部只读 SELECT）：
- T_MARK_DETAIL d JOIN T_MARK_ITEM i ON d.FMARKITEMID = i.FID：扣分项 TOP30；
- T_MSS_REWORK：返工量、FCONTROLTYPE 分布、ISVOERDATE/VOERDAYS 超期分布；
- T_MSS_MRCONTROL：FDOCNAME 统计、FREMARK 高频关键词（只出词频不出原文）。

运行方式：
1) 真实库（病案室/信息科授权后）：
   export PAPERLESS_ORACLE_DSN=... PAPERLESS_ORACLE_USER=... PAPERLESS_ORACLE_PASSWORD=...
   python prearchive_service/scripts/analyze_paperless_rejections_ro.py --days 30 --output review/prearchive/xxx.md
2) 离线演练（单测/无账号）：--mock-json <file>（结构见 _MockData 下方注释）。

Oracle 11g 兼容：分页用 ROWNUM，不用 FETCH FIRST；连接用 cx_Oracle/oracledb
任一可用驱动，查询异常 fail-soft（输出错误段而非崩溃）。凭据只从环境变量读。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "example_rules.json"

# --mock-json 结构（全部脱敏数据）：
# {
#   "mark_details": [{"fid": 63, "item_name": "手术核查表缺失", "count": 5, "patients": 4}],
#   "rework": {"total": 12, "by_control_type": {"病历返工": 8, "护理返工": 4},
#              "overdue": {"ISVOERDATE_true": 3, "avg_voerdays": 2.5}},
#   "mr_control": {"by_doc_name": {"手术记录": 9}, "remark_keywords": {"缺少": 7, "未签名": 3}}
# }
# 缺 key 时按空数据处理。

STOP_WORDS = {"的", "了", "在", "是", "未", "无", "及", "与", "请", "需", "已", "按", "等", "中"}


def mask_patient_ref(value: Any) -> str:
    """防御性掩码：即便上游误带患者标识也不落报告（只留后 4 位）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return "****" + text[-4:]


def covered_fids(rules_path: Path = RULES_PATH) -> dict[int, str]:
    """example_rules.json 中各规则对应的 t_mark_item FID → 规则名映射。"""
    try:
        payload = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping: dict[int, str] = {}
    for rule in payload.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        fid = rule.get("mark_item_fid")
        if fid is None:
            continue
        try:
            mapping[int(fid)] = str(rule.get("name") or rule.get("rule_id") or "")
        except (TypeError, ValueError):
            continue
    return mapping


def _connect():
    """按环境变量连接 CDMS Oracle（cx_Oracle / python-oracledb 任一可用）。"""
    dsn = os.environ.get("PAPERLESS_ORACLE_DSN", "").strip()
    user = os.environ.get("PAPERLESS_ORACLE_USER", "").strip()
    password = os.environ.get("PAPERLESS_ORACLE_PASSWORD", "").strip()
    if not (dsn and user and password):
        raise RuntimeError(
            "PAPERLESS_ORACLE_DSN / USER / PASSWORD 环境变量未配置（或改用 --mock-json）")
    try:
        import oracledb  # type: ignore
        return oracledb.connect(user=user, password=password, dsn=dsn)
    except ImportError:
        import cx_Oracle  # type: ignore
        return cx_Oracle.connect(user=user, password=password, dsn=dsn)


def _fetch_rows(conn, sql: str, binds: dict) -> list[dict]:
    """执行只读 SELECT，列名小写化（兼容 Oracle 大写 cursor.description）。"""
    cur = conn.cursor()
    try:
        cur.execute(sql, binds or {})
        columns = [desc[0].lower() for desc in cur.description or []]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def fetch_from_oracle(days: int) -> dict:
    """真实库只读盘点（三类查询；ROWNUM 限行，Oracle 11g 兼容）。"""
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = _connect()
    try:
        mark_rows = _fetch_rows(conn, """
            SELECT * FROM (
                SELECT d.FMARKITEMID AS fid, i.FNAME AS item_name,
                       COUNT(*) AS cnt, COUNT(DISTINCT d.FPATIENTID) AS patients
                FROM T_MARK_DETAIL d JOIN T_MARK_ITEM i ON d.FMARKITEMID = i.FID
                WHERE d.FWRITETIME >= :since
                GROUP BY d.FMARKITEMID, i.FNAME
                ORDER BY COUNT(*) DESC
            ) WHERE ROWNUM <= 30
        """, {"since": since})
        rework_total = _fetch_rows(conn, """
            SELECT COUNT(*) AS cnt FROM T_MSS_REWORK WHERE FWRITETIME >= :since
        """, {"since": since})
        rework_by_type = _fetch_rows(conn, """
            SELECT NVL(FCONTROLTYPE, '未标注') AS control_type, COUNT(*) AS cnt
            FROM T_MSS_REWORK WHERE FWRITETIME >= :since
            GROUP BY FCONTROLTYPE ORDER BY COUNT(*) DESC
        """, {"since": since})
        rework_overdue = _fetch_rows(conn, """
            SELECT SUM(CASE WHEN ISVOERDATE = '1' THEN 1 ELSE 0 END) AS overdue_cnt,
                   AVG(VOERDAYS) AS avg_voerdays
            FROM T_MSS_REWORK WHERE FWRITETIME >= :since
        """, {"since": since})
        mr_by_doc = _fetch_rows(conn, """
            SELECT NVL(FDOCNAME, '未标注') AS doc_name, COUNT(*) AS cnt
            FROM T_MSS_MRCONTROL WHERE FWRITETIME >= :since
            GROUP BY FDOCNAME ORDER BY COUNT(*) DESC
        """, {"since": since})
        remarks = _fetch_rows(conn, """
            SELECT FREMARK FROM T_MSS_MRCONTROL
            WHERE FWRITETIME >= :since AND FREMARK IS NOT NULL AND ROWNUM <= 2000
        """, {"since": since})
    finally:
        conn.close()

    keywords: Counter = Counter()
    for row in remarks:
        text = str(row.get("fremark") or "")
        for token in re.findall(r"[\u4e00-\u9fa5]{2,6}", text):
            if token not in STOP_WORDS:
                keywords[token] += 1
    overdue = rework_overdue[0] if rework_overdue else {}
    return {
        "mark_details": [
            {"fid": int(r.get("fid") or 0), "item_name": str(r.get("item_name") or ""),
             "count": int(r.get("cnt") or 0), "patients": int(r.get("patients") or 0)}
            for r in mark_rows
        ],
        "rework": {
            "total": int((rework_total[0] or {}).get("cnt") or 0) if rework_total else 0,
            "by_control_type": {str(r.get("control_type")): int(r.get("cnt") or 0)
                                for r in rework_by_type},
            "overdue": {
                "overdue_cnt": int(overdue.get("overdue_cnt") or 0),
                "avg_voerdays": float(overdue.get("avg_voerdays") or 0),
            },
        },
        "mr_control": {
            "by_doc_name": {str(r.get("doc_name")): int(r.get("cnt") or 0) for r in mr_by_doc},
            "remark_keywords": dict(keywords.most_common(20)),
        },
    }


def load_mock(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def classify_coverage(mark_rows: list[dict], covered: dict[int, str]) -> dict[str, list[dict]]:
    """按频次与已规则化 FID 三组分类：已覆盖 / 高频未覆盖·可规则化 / 高频未覆盖·建议 AI。

    高频阈值：出现次数 >= TOP 集合的 30% 分位（且 >= 3 次）视为高频；
    可规则化=名称含形式关键词（缺失/未签/时限/超时/漏/缺项），其余建议 AI。
    """
    covered_rows, uncovered_rows = [], []
    for row in mark_rows:
        (covered_rows if int(row.get("fid") or 0) in covered else uncovered_rows).append(row)
    counts = sorted((int(r.get("count") or 0) for r in uncovered_rows), reverse=True)
    threshold = max(3, counts[max(0, len(counts) // 3) - 1] if counts else 3)
    formal_pattern = re.compile(r"缺失|未签|时限|超时|漏|缺项|未完成|未归档")
    ruleable = [r for r in uncovered_rows
                if int(r.get("count") or 0) >= threshold and formal_pattern.search(str(r.get("item_name") or ""))]
    ai_suggest = [r for r in uncovered_rows
                  if int(r.get("count") or 0) >= threshold and r not in ruleable]
    return {"covered": covered_rows, "ruleable": ruleable, "ai_suggest": ai_suggest}


def render_report(data: dict, days: int, covered: dict[int, str],
                  source_note: str) -> str:
    groups = classify_coverage(data.get("mark_details") or [], covered)
    rework = data.get("rework") or {}
    overdue = rework.get("overdue") or {}
    mr = data.get("mr_control") or {}
    lines = [
        "# 无纸化人工质控盘点（只读）",
        "",
        f"- 统计窗口：近 {days} 天；数据来源：{source_note}",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}（患者标识零输出）",
        f"- 已规则化 FID 数（example_rules.json）：{len(covered)}",
        "",
        "## 一、扣分项 TOP30",
        "",
        "| FID | 扣分项名称 | 次数 | 病历数 | 覆盖状态 |",
        "|---|---|---|---|---|",
    ]
    for row in data.get("mark_details") or []:
        fid = int(row.get("fid") or 0)
        status = f"已覆盖：{covered[fid]}" if fid in covered else "未覆盖"
        lines.append(f"| {fid} | {row.get('item_name') or '—'} | {row.get('count', 0)} "
                     f"| {row.get('patients', 0)} | {status} |")
    lines += [
        "",
        "## 二、三组覆盖分类",
        "",
        f"### 2.1 已覆盖（{len(groups['covered'])} 项）",
        "",
    ]
    for row in groups["covered"]:
        lines.append(f"- FID {row.get('fid')} {row.get('item_name') or '—'}（{row.get('count', 0)} 次）")
    lines += ["", f"### 2.2 高频未覆盖 · 可规则化（{len(groups['ruleable'])} 项，建议纳入下一版规则文件）", ""]
    for row in groups["ruleable"]:
        lines.append(f"- FID {row.get('fid')} {row.get('item_name') or '—'}（{row.get('count', 0)} 次）")
    lines += ["", f"### 2.3 高频未覆盖 · 建议 AI 语义（{len(groups['ai_suggest'])} 项，形式关键词不命中）", ""]
    for row in groups["ai_suggest"]:
        lines.append(f"- FID {row.get('fid')} {row.get('item_name') or '—'}（{row.get('count', 0)} 次）")
    lines += [
        "",
        "## 三、返工量盘点（T_MSS_REWORK）",
        "",
        f"- 返工总量：{rework.get('total', 0)}",
        f"- 超期完成：{overdue.get('overdue_cnt', 0)} 条，平均超期 {overdue.get('avg_voerdays', 0)} 天",
        "- 按返工类型分布：",
    ]
    for control_type, count in (rework.get("by_control_type") or {}).items():
        lines.append(f"  - {control_type}：{count}")
    lines += [
        "",
        "## 四、质控记录盘点（T_MSS_MRCONTROL）",
        "",
        "- 按文书类型：",
    ]
    for doc_name, count in (mr.get("by_doc_name") or {}).items():
        lines.append(f"  - {doc_name}：{count}")
    lines += ["", "- FREMARK 高频关键词（只出词频，不输出原文整句）："]
    keywords = mr.get("remark_keywords") or {}
    if keywords:
        lines.append("  " + "；".join(f"{word}×{count}" for word, count in list(keywords.items())[:20]))
    else:
        lines.append("  （无）")
    lines += ["", "> 本报告为只读盘点，不含患者姓名/住院号；金标准回测见 paperless_gold_backtest_ro.py。"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="无纸化人工质控盘点（只读）")
    parser.add_argument("--days", type=int, default=30, help="统计窗口天数（默认 30）")
    parser.add_argument("--mock-json", default="", help="离线演练数据文件（单测/无账号）")
    parser.add_argument("--output", default="",
                        help="Markdown 输出路径（默认 review/prearchive/paperless_rejections_<YYYYMMDD>.md）")
    parser.add_argument("--rules-file", default=str(RULES_PATH), help="规则文件路径（覆盖 FID 映射来源）")
    args = parser.parse_args(argv)

    if args.mock_json:
        data = load_mock(Path(args.mock_json))
        source_note = f"离线演练数据（--mock-json {args.mock_json}）"
    else:
        try:
            data = fetch_from_oracle(args.days)
            source_note = f"CDMS Oracle 只读实时查询（PAPERLESS_ORACLE_DSN，近 {args.days} 天）"
        except Exception as exc:  # noqa: BLE001
            print(f"[analyze] 连接/查询失败：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2

    output = Path(args.output or (
        REPO_ROOT / "review" / "prearchive"
        / f"paperless_rejections_{datetime.now().strftime('%Y%m%d')}.md"))
    output.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(data, args.days, covered_fids(Path(args.rules_file)), source_note)
    output.write_text(report, encoding="utf-8")
    print(f"[analyze] 已输出：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
