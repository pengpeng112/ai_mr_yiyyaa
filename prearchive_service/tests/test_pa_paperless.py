# -*- coding: utf-8 -*-
"""T2-7 无纸化对接单测：快照/同步五差异/回测指标/网关 SQL 黑名单。

- 快照 92 条解析与 FID 唯一性；
- 同步工具五类差异各自检出（构造基线变体断言）+ 对快照自身零差异（自洽）；
- 回测指标数值断言（构造已知 P=2/3、R=2/4 用例算精确值）+ rule_id 换算；
- 网关 SQL 文本断言：meta SQL 不含患者列黑名单；mark_items 分页参数；
- config paperless 源默认 disabled 且校验通过。
"""
import json
from pathlib import Path

import pytest

from prearchive.backtest import backtest, hit_fids_from_results, render_markdown
from prearchive.config import DEFAULTS, validate_config
from prearchive.paperless import (
    META_SQL_PATIENT_COLUMN_BLACKLIST,
    FixturePaperlessGateway,
    SqlPaperlessGateway,
    load_snapshot_items,
)
from prearchive.sync_paperless_rules import diff_items, main as sync_main

SNAPSHOT = Path(__file__).resolve().parent.parent / \
    "rules/paperless_items_snapshot_20260828.json"


@pytest.fixture(scope="module")
def items():
    return load_snapshot_items(SNAPSHOT)


# ---------------------------------------------------------------------------
# 快照契约
# ---------------------------------------------------------------------------
def test_snapshot_has_92_unique_fids(items):
    assert len(items) == 92
    fids = [int(r["fid"]) for r in items]
    assert len(set(fids)) == 92
    for row in items:
        assert set(row.keys()) == {"fid", "ftypeid", "fscore", "fname"}
        assert row["fname"]


def test_snapshot_meta_declares_non_patient():
    meta = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["_meta"]
    assert meta.get("patient_data") is False
    assert "031 附录A" in meta.get("固化依据", "")


def test_fixture_gateway_paginates_snapshot(items):
    gw = FixturePaperlessGateway(SNAPSHOT)
    page1 = gw.fetch_mark_items(since_fid=0, limit=50)
    assert len(page1) == 50
    last = page1[-1]["fid"]
    page2 = gw.fetch_mark_items(since_fid=last, limit=50)
    assert page2 and page2[0]["fid"] > last
    # 全量翻页拼齐 92
    collected, since = [], 0
    while True:
        page = gw.fetch_mark_items(since_fid=since, limit=50)
        if not page:
            break
        collected.extend(page)
        since = page[-1]["fid"]
    assert len(collected) == 92


# ---------------------------------------------------------------------------
# 同步五差异
# ---------------------------------------------------------------------------
def _baseline_variant(items, mutate):
    baseline = [dict(r) for r in items]
    return mutate(baseline)


def test_sync_zero_diff_against_self(items):
    diff = diff_items(items, [dict(r) for r in items])
    assert diff == {"added": [], "disabled": [], "renamed": [],
                    "rescored": [], "retyped": []}


def test_sync_detects_added(items):
    baseline = [dict(r) for r in items if int(r["fid"]) != 92]
    diff = diff_items(items, baseline)
    assert diff["added"] == [92]
    assert not any(diff[k] for k in ("disabled", "renamed", "rescored", "retyped"))


def test_sync_detects_rename(items):
    baseline = _baseline_variant(items, lambda b: (
        [dict(r, fname="改名了") if int(r["fid"]) == 12 else r for r in b]))
    diff = diff_items(items, baseline)
    assert diff["renamed"] == [12]


def test_sync_detects_rescore(items):
    baseline = _baseline_variant(items, lambda b: (
        [dict(r, fscore="999") if int(r["fid"]) == 15 else r for r in b]))
    diff = diff_items(items, baseline)
    assert diff["rescored"] == [15]


def test_sync_detects_retype(items):
    baseline = _baseline_variant(items, lambda b: (
        [dict(r, ftypeid="99") if int(r["fid"]) == 58 else r for r in b]))
    diff = diff_items(items, baseline)
    assert diff["retyped"] == [58]


def test_sync_detects_disable_real_pull_shape(items):
    # 实拉版行含 fisenable；翻转 1→0 视为停用
    current = [dict(r, fisenable=0) if int(r["fid"]) == 75 else dict(r, fisenable=1)
               for r in items]
    baseline = [dict(r, fisenable=1) for r in items]
    diff = diff_items(current, baseline)
    assert diff["disabled"] == [75]


def test_sync_cli_self_consistent_zero_exit():
    assert sync_main(["--snapshot", str(SNAPSHOT)]) == 0


def test_sync_cli_diff_exit_one(tmp_path, items):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(
        {"items": [dict(r) for r in items if int(r["fid"]) != 1]},
        ensure_ascii=False), encoding="utf-8")
    assert sync_main(["--snapshot", str(SNAPSHOT),
                      "--baseline", str(baseline_path),
                      "--output", str(tmp_path / "report.md")]) == 1
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "新增 FID" in report and "FID：1" in report


# ---------------------------------------------------------------------------
# 回测指标（构造已知数值）
# ---------------------------------------------------------------------------
def test_backtest_known_precision_recall():
    # 金标准：P1 命中 {12, 75}；P2 命中 {12, 72, 15}
    samples = [
        {"patient_id": "TESTP1", "visit_id": "1", "hit_fids": [12, 75]},
        {"patient_id": "TESTP2", "visit_id": "1", "hit_fids": [12, 72, 15]},
    ]
    # 预检：P1 命中 {12, 88(误报)}；P2 命中 {12, 72}
    results = [
        {"patient_id": "TESTP1", "visit_id": "1",
         "problems": [{"mark_item_fid": 12}, {"mark_item_fid": 88}]},
        {"patient_id": "TESTP2", "visit_id": "1",
         "problems": [{"mark_item_fid": 12}, {"mark_item_fid": 72}]},
    ]
    report = backtest(samples, results)
    # 总体 TP=3 FP=1 FN=2 → P=3/4=0.75 R=3/5=0.6
    assert report["overall"]["tp"] == 3
    assert report["overall"]["fp"] == 1
    assert report["overall"]["fn"] == 2
    assert report["overall"]["precision"] == 0.75
    assert report["overall"]["recall"] == 0.6
    assert report["false_positive"] == 1
    # 按 FID：88 只有 FP；15/75 只有 FN；12 TP=2 P=1 R=1
    assert report["per_fid"]["88"] == {"tp": 0, "fp": 1, "fn": 0,
                                       "precision": 0.0, "recall": None}
    assert report["per_fid"]["12"]["tp"] == 2
    assert report["per_fid"]["12"]["precision"] == 1.0
    md = render_markdown(report)
    assert "precision=0.75" in md


def test_backtest_rule_id_mapping_and_unmapped():
    samples = [{"patient_id": "TESTP9", "visit_id": "1", "hit_fids": [61]}]
    results = [{
        "patient_id": "TESTP9", "visit_id": "1",
        "problems": [
            {"rule_id": "R-MISS-ANESTHESIA-RECORD", "mark_item_fid": None},
            {"rule_id": "R-UNKNOWN-RULE", "mark_item_fid": None},
        ],
    }]
    hits, unmapped = hit_fids_from_results(results, {"R-MISS-ANESTHESIA-RECORD": 61})
    assert hits[("TESTP9", "1")] == {61}
    assert unmapped == ["R-UNKNOWN-RULE"]

    report = backtest(samples, results, {"R-MISS-ANESTHESIA-RECORD": 61})
    assert report["overall"]["tp"] == 1
    assert report["unmapped_problem_rule_ids"] == ["R-UNKNOWN-RULE"]


# ---------------------------------------------------------------------------
# 网关 SQL 黑名单 + 分页参数
# ---------------------------------------------------------------------------
def test_gold_meta_sql_has_no_patient_columns():
    sql = SqlPaperlessGateway.GOLD_META_SQL.upper()
    for column in META_SQL_PATIENT_COLUMN_BLACKLIST:
        assert column not in sql, f"meta SQL 不得含患者列 {column}"
    assert "GROUP BY" in sql          # 聚合口径
    assert "T_MARK_MAIN" in sql and "T_MARK_DETAIL" in sql


def test_mark_items_sql_pagination_and_order():
    sql = SqlPaperlessGateway.MARK_ITEMS_SQL.upper()
    assert "FID > :SINCE_FID" in sql
    assert "ORDER BY FID" in sql
    assert "FETCH FIRST :LIMIT ROWS ONLY" in sql
    assert "FISENABLE = 1" in sql


def test_config_paperless_source_defaults_disabled():
    cfg = validate_config(DEFAULTS)
    src = cfg["sources"]["paperless"]
    assert src["enabled"] is False
    assert src["type"] == "oracle"
    assert src["host"].startswith("<")      # DSN 占位
