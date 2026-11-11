"""JHEMR 列清单只读查证脚本（病历时效质控 T1）。

仅查询 information_schema.columns，输出 T1 七张表的真实列名/类型到 JSON，
供回填 tests/timeliness/fixtures/jhemr_expected_columns.json（verified=true）。

运行环境要求（本任务编制时未执行、未直连生产）：
- 具备 config.json 的 timeliness 配置段（enabled=true、host 指向可达的
  JHEMR 库、口令经 TIMELINESS_JHEMR_PASSWORD 或 password_enc 提供）；
- 环境装有 psycopg2 且网络可达 10.10.8.177:5432（由用户在授权环境运行）；
- 网络不可达或未配置时脚本直接报错退出，不做任何降级直连。

用法：
    python scripts/timeliness/inspect_jhemr_columns.py
    python scripts/timeliness/inspect_jhemr_columns.py --out review/timeliness/T1_columns.json
    python scripts/timeliness/inspect_jhemr_columns.py --tables jhmr_file_index
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# 保证以 `python scripts/timeliness/inspect_jhemr_columns.py` 直跑时可导入 app 包。
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.timeliness.config import (  # noqa: E402
    TimelinessNotConfigured,
    TimelinessPermissionMissing,
)
from app.timeliness.jhemr_reader import (  # noqa: E402
    SCHEMA_NAME,
    get_jhemr_readonly_connection,
)

# T1 固定七表（与 app/timeliness/jhemr_reader.py 保持一致）。
TABLES = [
    "pats_in_hospital",
    "pat_visit",
    "jhmr_file_index",
    "operation",
    "emr_treament_apply",
    "emr_online_monitor",
    "jhmr_monitor_limit_log",
]

_COLUMNS_SQL = (
    "SELECT column_name, data_type, ordinal_position, is_nullable "
    "FROM information_schema.columns "
    "WHERE table_schema = %s AND table_name = %s "
    "ORDER BY ordinal_position"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="只读查证 JHEMR 列清单（information_schema）")
    parser.add_argument(
        "--out",
        default="review/timeliness/T1_columns.json",
        help="输出 JSON 路径（默认 review/timeliness/T1_columns.json）",
    )
    parser.add_argument(
        "--tables",
        default="",
        help="逗号分隔的表名过滤（默认查 T1 全部七表）",
    )
    args = parser.parse_args()

    tables = [t.strip() for t in args.tables.split(",") if t.strip()] or TABLES
    unknown = [t for t in tables if t not in TABLES]
    if unknown:
        print(f"未知表名（仅允许 T1 七表）: {unknown}", file=sys.stderr)
        return 2

    result = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "readonly information_schema.columns only",
        "schema": SCHEMA_NAME,
        "tables": {},
    }

    try:
        conn = get_jhemr_readonly_connection()
    except TimelinessNotConfigured as exc:
        print(f"timeliness 配置未就绪: {exc}", file=sys.stderr)
        return 2

    try:
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(_COLUMNS_SQL, (SCHEMA_NAME, table))
                rows = cur.fetchall()
                result["tables"][f"{SCHEMA_NAME}.{table}"] = [
                    {
                        "column_name": str(row[0]).lower(),
                        "data_type": str(row[1]),
                        "ordinal_position": int(row[2]),
                        "is_nullable": str(row[3]),
                    }
                    for row in rows
                ]
    except TimelinessPermissionMissing as exc:
        # information_schema 对所有账号可读；走到这里说明配置账号被限制，
        # 按约定报告缺权限表，不换账号。
        print(f"权限不足: {exc}", file=sys.stderr)
        return 3
    finally:
        try:
            conn.close()
        except Exception:
            pass

    empty = [name for name, cols in result["tables"].items() if not cols]
    if empty:
        print(f"警告：以下表在 information_schema 中无列记录（可能无权限或表名不符）: {empty}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已输出 {sum(len(v) for v in result['tables'].values())} 列 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
