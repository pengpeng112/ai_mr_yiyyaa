# -*- coding: utf-8 -*-
"""046 T2 预检结果库新增列的显式迁移（默认 dry-run；--apply 才写库）。

背景：MED_PREARCHIVE_RESULT 新增 evaluations_json/notices_json/source_health_json/
summary_json 四列（F06）；闭环九张新表（CATALOG/COVERAGE/RUN/RULE_EVAL/ISSUE/
ISSUE_ACTION/MATCH_*/VIEW_TICKET）由建库 create_all 或 Oracle 手工 DDL
（sql/create_prearchive_closed_loop_oracle_20260910.sql）落库。
SQLite 既有库的 RESULT 表不会因 create_all 自动加列——本脚本做 additive ALTER。

- 只加列/建表，不删不改既有列；幂等（已存在即跳过）；
- Oracle 模式打印待执行 DDL 清单（生产按 023 §9.1 批准后在 DBA 侧执行）；
- 历史行新列保持默认值（读取侧显示"历史记录未保存评估明细"，不补造）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RESULT_NEW_COLUMNS = [
    ("evaluations_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("notices_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("source_health_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("summary_json", "TEXT NOT NULL DEFAULT '{}'"),
]

CLOSED_LOOP_TABLES = [
    "MED_PREARCHIVE_CATALOG_ITEM", "MED_PREARCHIVE_COVERAGE_MAP",
    "MED_PREARCHIVE_RUN", "MED_PREARCHIVE_RULE_EVAL",
    "MED_PREARCHIVE_ISSUE", "MED_PREARCHIVE_ISSUE_ACTION",
    "MED_PREARCHIVE_MATCH_TASK", "MED_PREARCHIVE_MATCH_CANDIDATE",
    "MED_PREARCHIVE_TRIAL_FEEDBACK", "MED_PREARCHIVE_VIEW_TICKET",
]


def plan_sqlite(db_path: Path) -> dict:
    plan = {"db": str(db_path), "columns_to_add": [], "tables_to_create": [],
            "existing_columns": [], "missing_db": not db_path.exists()}
    if plan["missing_db"]:
        return plan
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(MED_PREARCHIVE_RESULT)").fetchall()}
        plan["existing_columns"] = sorted(cols)
        if cols:
            for name, ddl in RESULT_NEW_COLUMNS:
                if name not in cols:
                    plan["columns_to_add"].append((name, ddl))
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for table in CLOSED_LOOP_TABLES:
            if table not in tables:
                plan["tables_to_create"].append(table)
    finally:
        conn.close()
    return plan


def apply_sqlite(db_path: Path, plan: dict) -> dict:
    if plan["missing_db"]:
        return {"error": "db not found (fresh db will create_all 全量结构)"}
    applied = {"columns_added": [], "tables_created": []}
    conn = sqlite3.connect(str(db_path))
    try:
        for name, ddl in plan["columns_to_add"]:
            conn.execute(f"ALTER TABLE MED_PREARCHIVE_RESULT ADD COLUMN {name} {ddl}")
            applied["columns_added"].append(name)
        # 新表交给 SQLAlchemy create_all（同进程 import 建模后执行）
        if plan["tables_to_create"]:
            sys.path.insert(0, str(ROOT / "prearchive_service"))
            from prearchive.models import build_sqlite_engine, Base
            import prearchive.closed_loop_models  # noqa: F401 注册新表
            engine = build_sqlite_engine(str(db_path))
            Base.metadata.create_all(engine, tables=[
                Base.metadata.tables[t] for t in plan["tables_to_create"]
                if t in Base.metadata.tables])
            engine.dispose()
            applied["tables_created"] = plan["tables_to_create"]
        conn.commit()
    finally:
        conn.close()
    return applied


def oracle_ddl_checklist() -> list:
    sql_path = ROOT / "prearchive_service" / "sql" / \
        "create_prearchive_closed_loop_oracle_20260910.sql"
    if sql_path.exists():
        return [f"执行 {sql_path}（闭环九表）",
                "ALTER TABLE MED_PREARCHIVE_RESULT ADD ("
                + ", ".join(f"{n} {d.split()[0]} DEFAULT "
                            f"{d.split('DEFAULT ')[1]}" for n, d in RESULT_NEW_COLUMNS)
                + ")"]
    return [f"缺少 {sql_path}"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="046 预检结果库 additive 迁移")
    parser.add_argument("--db", type=Path,
                        default=ROOT / "prearchive_service" / "data" /
                        "prearchive_result.db",
                        help="SQLite 结果库路径")
    parser.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    args = parser.parse_args(argv)

    plan = plan_sqlite(args.db)
    result = {"mode": "apply" if args.apply else "dry-run", **plan,
              "oracle_checklist": oracle_ddl_checklist()}
    if args.apply:
        result["applied"] = apply_sqlite(args.db, plan)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
