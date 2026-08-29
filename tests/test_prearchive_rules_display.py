"""归档前预检规则只读展示契约测试（用户 2026-08-29 需求：质控类型页两类分区展示）。

覆盖：视图服务两类解析/授权回填内容断言/目录缺失 fail-open/端点鉴权与路由优先级
（/prearchive 不得被 /{code} 吞掉）。
"""
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import audit_types
from app.services.prearchive_rules_view import load_prearchive_rules_view

REPO_RULES_DIR = Path(__file__).resolve().parent.parent / \
    "prearchive_service" / "rules"


# ---------------------------------------------------------------------------
# 视图服务（真实仓库规则文件）
# ---------------------------------------------------------------------------
def test_view_loads_real_repo_rules_two_categories():
    view = load_prearchive_rules_view(REPO_RULES_DIR)
    assert view["available"] is True
    keys = [c["key"] for c in view["categories"]]
    assert keys == ["mark_item", "system_push"]
    mark_item = view["categories"][0]
    assert len(mark_item["rules"]) == 14
    assert "authorized" in mark_item.get("version", "")
    system_push = view["categories"][1]
    assert system_push["rules"] == []            # W10 未提供，占位通道
    assert "豁免" in system_push["description"]


def test_view_mark_item_rules_authorized_fids_backfilled():
    view = load_prearchive_rules_view(REPO_RULES_DIR)
    rules = {r["rule_id"]: r for r in view["categories"][0]["rules"]}
    # 030 §3 一期 11 条 FID 全覆盖
    expected = {
        "R-TIME-ADMISSION-RECORD-24H": 14,
        "R-TIME-FIRST-PROGRESS-8H": 34,
        "R-MISS-SURGERY-PREPOST-DOCS": 57,
        "R-MISS-SURGERY-CHECKTABLE": 63,
        "R-MISS-ANESTHESIA-RECORD": 61,
        "R-MISS-ANESTHESIA-PREOP-VISIT": 59,
        "R-MISS-ANESTHESIA-POSTOP-FOLLOWUP": 67,
        "R-MISS-SURGERY-COUNT-RECORD": 88,
        "R-TIME-POSTOP-FIRST-PROGRESS-24H": 65,
        "R-TIME-DISCHARGE-RECORD-24H": 71,
        "R-TIME-INVASIVE-OP-24H": 55,
    }
    for rid, fid in expected.items():
        assert rules[rid]["mark_item_fid"] == fid, rid
    # 家族规则 fid=null + 说明；摘要不含词表全文（只读最小化）
    assert rules["R-MISS-LAB-REPORT-FAMILY"]["mark_item_fid"] is None
    blob = json.dumps(view, ensure_ascii=False)
    assert "exclude_vocab" not in blob
    assert "vocab" not in blob


def test_view_fail_open_on_missing_dir(tmp_path):
    view = load_prearchive_rules_view(tmp_path / "no_such_dir")
    assert view["available"] is False
    assert all(c["rules"] == [] for c in view["categories"])


def test_view_fail_open_on_invalid_json(tmp_path):
    (tmp_path / "example_rules.json").write_text("{invalid", encoding="utf-8")
    view = load_prearchive_rules_view(tmp_path)
    assert view["available"] is False
    mark_item = view["categories"][0]
    assert mark_item["rules"] == []
    assert "解析失败" in mark_item.get("error", "")


def test_view_minimal_channel_file_tolerated(tmp_path):
    """通道文件缺 rules 键（空占位）不报错、不置 fail。"""
    (tmp_path / "example_rules.json").write_text(
        json.dumps({"version": "v", "rules": []}, ensure_ascii=False),
        encoding="utf-8")
    view = load_prearchive_rules_view(tmp_path)
    assert view["available"] is True


# ---------------------------------------------------------------------------
# 端点：鉴权 + 路由优先级
# ---------------------------------------------------------------------------
@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(audit_types.router, prefix="/api/audit-types")
    return TestClient(app)


def test_prearchive_endpoint_requires_auth(client):
    r = client.get("/api/audit-types/prearchive")
    assert r.status_code in (401, 403)


def test_prearchive_endpoint_returns_view(client):
    client.app.dependency_overrides[get_current_user] = lambda: object()
    r = client.get("/api/audit-types/prearchive")
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is True
    assert [c["key"] for c in data["categories"]] == ["mark_item", "system_push"]
    assert len(data["categories"][0]["rules"]) == 14


def test_prearchive_route_not_shadowed_by_code_param(client):
    """/prearchive 必须先于 /{code} 注册：带当前用户访问不落进详情路由。"""
    client.app.dependency_overrides[get_current_user] = lambda: object()
    # 若被 /{code} 吞掉，会走 AuditTypeConfig 校验并 404/422；这里应返回视图 JSON
    r = client.get("/api/audit-types/prearchive")
    assert r.status_code == 200
    assert "categories" in r.json()
