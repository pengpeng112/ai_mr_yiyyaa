# -*- coding: utf-8 -*-
"""归档前预检规则只读视图（质控类型页展示用）。

边界：本模块**只读取** `prearchive_service/rules/*.json` 数据文件（直接 json 解析，
零 Python import——主服务不反向依赖 prearchive 代码，隔离红线不破）；文件缺失/
解析失败时 fail-open 返回 available=False，不影响任何主服务链路。

展示口径（用户 2026-08-29 需求：预检规则在"质控类型"页展示，与既有六类推送
质控分列两类）：
- 类别一 mark_item：无纸化评分项规则（example_rules.json，质控科已授权免签字，
  2026-08-29 业务负责人转达）；
- 类别二 system_push：系统推送类报告规则（system_push_rules.json，豁免签字，
  等业务 W10 清单，当前占位零规则）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent.parent / \
    "prearchive_service" / "rules"

_RULE_FILES = {
    "mark_item": "example_rules.json",
    "system_push": "system_push_rules.json",
}

_CATEGORY_META = {
    "mark_item": {
        "name": "无纸化评分项规则",
        "description": "对应无纸化系统 92 条评分项映射（030 v1.1）；质控科已授权免签字"
                       "（业务负责人 2026-08-29 转达），一期 11 条评分项编号已回填。"
                       "归属归档前预检服务，独立于六类 Dify 推送质控。",
    },
    "system_push": {
        "name": "系统推送类报告规则",
        "description": "病理/PACS 等系统推送报告的缺失判定；豁免质控科签字（用户口径），"
                       "规则清单由业务方提供（W10）后录入，当前为占位通道。",
    },
}

_SUMMARY_FIELDS = (
    "rule_id", "name", "type", "severity", "mark_item_fid", "mark_item_note",
    "deduct_ref", "enabled", "version", "message",
)


def _rules_dir() -> Path:
    configured = os.getenv("PREARCHIVE_RULES_DIR", "").strip()
    if configured:
        return Path(configured)
    return DEFAULT_RULES_DIR


def _summarize_rule(raw: dict) -> dict:
    summary = {key: raw.get(key) for key in _SUMMARY_FIELDS}
    # 展示辅助字段（不暴露 trigger 细节/词表全文，保持只读摘要最小化）
    expect = raw.get("expect") or []
    summary["expect"] = [str(x) for x in expect][:8]
    doc_name = str(raw.get("doc_name") or "").strip()
    summary["doc_name"] = doc_name
    sources = ((raw.get("match") or {}).get("sources")) or []
    summary["sources"] = [str(x) for x in sources]
    return summary


def load_prearchive_rules_view(rules_dir=None) -> dict:
    """读取预检规则文件并输出两类只读摘要；fail-open。"""
    base = Path(rules_dir) if rules_dir else _rules_dir()
    view = {
        "available": False,
        "source_dir": str(base),
        "note": "归档前预检规则目录不可读（预检服务未随主服务部署时属预期）",
        "categories": [
            {"key": key, "name": _CATEGORY_META[key]["name"],
             "description": _CATEGORY_META[key]["description"], "rules": []}
            for key in ("mark_item", "system_push")
        ],
    }
    if not base.is_dir():
        return view

    available = True
    for key, filename in _RULE_FILES.items():
        path = base / filename
        category = next(c for c in view["categories"] if c["key"] == key)
        if not path.exists():
            continue   # 空通道/未部署：该类规则留空
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rules = payload.get("rules") or []
            category["rules"] = [_summarize_rule(r) for r in rules
                                 if isinstance(r, dict)]
            version = str(payload.get("version") or "").strip()
            if version:
                category["version"] = version
            version_note = str(payload.get("version_note")
                               or "".join(payload.get("channel_note") or []))
            if version_note:
                category["version_note"] = version_note[:300]
        except (OSError, json.JSONDecodeError, ValueError):
            available = False
            category["rules"] = []
            category["error"] = "规则文件解析失败"

    view["available"] = available
    if available:
        view["note"] = ""
    return view
