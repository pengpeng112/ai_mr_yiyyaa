# -*- coding: utf-8 -*-
"""046 T1 覆盖账本测试：92 条逐条登记、FID 唯一、导入幂等、差异可追溯。"""

import json

import pytest

from prearchive.coverage import (
    COVERAGE_OUTPUT,
    SNAPSHOT_DEFAULT,
    build_coverage_records,
    coverage_counts,
    diff_coverage_against_rules,
    load_snapshot_items,
    write_coverage_json,
)
from prearchive.match_service import CoverageRepository
from prearchive.models import build_session_factory, build_sqlite_engine

from helpers import dt


@pytest.fixture()
def records():
    return build_coverage_records(load_snapshot_items())


@pytest.fixture()
def repo():
    return CoverageRepository(build_session_factory(build_sqlite_engine(":memory:")))


def test_ledger_covers_all_92_unique_fids(records):
    fids = [r["fid"] for r in records]
    assert len(records) == 92
    assert len(set(fids)) == 92, "FID 必须唯一"
    snapshot_fids = {int(i["fid"]) for i in load_snapshot_items()}
    assert set(fids) == snapshot_fids, "账本集合必须与快照一致"


def test_ledger_category_counts_match_030(records):
    cats = {"A": 0, "B": 0, "C": 0}
    for r in records:
        cats[r["category"]] += 1
    assert cats == {"A": 23, "B": 7, "C": 62}, "030 历史 A/B/C 分类对照"


def test_every_record_has_required_fields(records):
    for r in records:
        assert r["original_text"] and r["original_text_sha256"]
        assert r["score"] and r["group_name"]
        assert r["interpretation"] and r["clauses"], f"FID{r['fid']} 缺解释或条款"
        assert r["overall_method"] in ("deterministic", "ai_assist", "manual",
                                       "data_blocked")
        clause_ids = [c["clause_id"] for c in r["clauses"]]
        assert len(set(clause_ids)) == len(clause_ids), "条款 ID 不得重复"
        for c in r["clauses"]:
            assert c["method"] in ("deterministic", "ai_assist", "manual",
                                   "data_blocked")
            assert c["coverage"] in ("full", "partial", "none")
            # blocked/data_blocked 必须写明缺口，不得伪装覆盖
            if c["coverage"] != "full":
                assert c["uncovered_clauses"], f"{c['clause_id']} 未覆盖部分必须留痕"
            if c["method"] == "data_blocked":
                assert c["blocked_reason"], f"{c['clause_id']} blocked 必须给原因"


def test_counts_summary(records):
    counts = coverage_counts(records)
    assert counts["catalog_count"] == 92
    assert sum(counts["by_method"].values()) == 92
    assert counts["full_coverage"] + counts["partial_coverage"] + \
        counts["no_coverage"] == 92
    # 不虚报：full 的只有已发布时限规则覆盖的条款 FID
    assert 0 < counts["full_coverage"] <= 11


def test_one_fid_many_clauses_vs_one_rule_many_fids(records):
    """一 FID 多条款（如 FID57 存在性/时限/签名）与一规则多问题不混淆：
    FID57 至少 3 条款；条款级可 full（时限子句 046 T3 落地），但整 FID 不得宣称
    full（签名/内容条款未覆盖）。"""
    fid57 = next(r for r in records if r["fid"] == 57)
    assert len(fid57["clauses"]) >= 3
    full_clauses = [c for c in fid57["clauses"] if c["coverage"] == "full"]
    partial_clauses = [c for c in fid57["clauses"] if c["coverage"] == "partial"]
    assert full_clauses and partial_clauses
    assert all(c["rule_ids"] for c in full_clauses)


def test_published_rule_linkage(records):
    example = json.loads((SNAPSHOT_DEFAULT.parent / "example_rules.json")
                         .read_text(encoding="utf-8"))
    linked = diff_coverage_against_rules(records, example["rules"])
    # 046 T3：+R-TIME-SURGERY-RECORD-24H(57)/R-TIME-FIRST-WARD-ROUND-48H(38) → 16 条
    assert linked["published_rules"] == 16
    assert set(linked["linked_fids"]) == {63, 57, 14, 34, 61, 59, 67, 88, 65, 71,
                                          55, 38}
    assert linked["dangling_fids"] == [], "已发布规则 FID 必须都在 92 目录内"
    assert len(linked["unlinked_rule_ids"]) == 3  # fid=null 的三条（首页过敏/诊断重复/检验族）


def test_snapshot_import_idempotent_and_diff_visible(repo):
    records = build_coverage_records(load_snapshot_items())
    r1 = repo.import_snapshot(records, apply=True, actor_id="op-1")
    assert r1["catalog_created"] == 92
    clause_rows = r1["coverage_upserted"]
    assert clause_rows >= 92          # 条款级 upsert（92 FID 共 123 条款行）
    r2 = repo.import_snapshot(records, apply=True, actor_id="op-1")
    assert r2["catalog_created"] == 0 and r2["catalog_skipped"] == 92
    assert r2["coverage_upserted"] == clause_rows   # upsert 幂等（行数一致）

    # 新快照批次：改名/改分差异可见，历史批次保留
    renamed = [dict(r) for r in records[:5]]
    renamed[0] = {**renamed[0], "original_text": "改名后的评分项", "snapshot_id":
                  "paperless_items_snapshot_test2"}
    report = repo.import_snapshot(renamed, apply=True, actor_id="op-2")
    assert report["diff"]["renamed"] == [renamed[0]["fid"]]
    items, total = repo.list_coverage()
    assert total == 92


def test_list_coverage_filters_and_search(repo):
    repo.import_snapshot(build_coverage_records(load_snapshot_items()),
                         apply=True, actor_id="op-1")
    items, total = repo.list_coverage(method="data_blocked")
    assert total > 0 and all(
        all(c["method"] == "data_blocked" for c in e["clauses"])
        for e in items)
    items, total = repo.list_coverage(fid=57)
    assert total == 1 and items[0]["fid"] == 57
    items, total = repo.list_coverage(q="手术")
    assert total >= 1
    paged, total_all = repo.list_coverage(page=1, page_size=10)
    assert len(paged) == 10 and total_all == 92


def test_confirm_fid_exact_match_protection(repo):
    from prearchive.rule_service import Actor
    repo.import_snapshot(build_coverage_records(load_snapshot_items()),
                         apply=True, actor_id="op-1")
    rows = repo.confirm_fid(14, Actor(id="qc-1", name="质控员"))
    assert rows >= 1
    items, _ = repo.list_coverage(fid=14)
    assert items[0]["status"] == "confirmed"


def test_coverage_json_file_stable(records):
    path = write_coverage_json(records, COVERAGE_OUTPUT)
    data = json.loads(COVERAGE_OUTPUT.read_text(encoding="utf-8"))
    assert data["version"].startswith("v1")
    assert len(data["items"]) == 92
    assert data["counts"]["catalog_count"] == 92
    # 原文 hash 可复核
    import hashlib
    for item in data["items"][:10]:
        assert item["original_text_sha256"] == hashlib.sha256(
            item["original_text"].encode("utf-8")).hexdigest()
