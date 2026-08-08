#!/usr/bin/env python3
"""清理 PushLog「多当前」重复（015/C1）。

策略：
- 不删除任何历史行
- 对 (source_record_key, audit_type_code, audit_run_mode) 且 superseded_by IS NULL
  的分组，若 count>1：只保留 1 条当前，其余标 superseded_by=保留行 id
- 保留优先级：qc_usable > transport success > pushed_flag=1 > 更大 id（更新）

用法（容器内或本地应用库）：
  python scripts/remediate_pushlog_multi_current.py --dry-run
  python scripts/remediate_pushlog_multi_current.py --apply
  python scripts/remediate_pushlog_multi_current.py --verify
  python scripts/remediate_pushlog_multi_current.py --create-index
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime


def _table(engine) -> str:
    return "MED_PUSH_LOG" if engine.dialect.name == "oracle" else "push_log"


def _dup_count_sql(table: str) -> str:
    return f"""
SELECT COUNT(*) FROM (
  SELECT source_record_key, audit_type_code, audit_run_mode
  FROM {table}
  WHERE superseded_by IS NULL
    AND source_record_key IS NOT NULL
  GROUP BY source_record_key, audit_type_code, audit_run_mode
  HAVING COUNT(*) > 1
) dup_groups
"""


def _preview_sql(table: str, dialect: str) -> str:
    # Oracle 用 KEEP；SQLite 用窗口函数
    if dialect == "oracle":
        return f"""
SELECT
  COUNT(*) AS group_count,
  NVL(SUM(cnt - 1), 0) AS rows_to_supersede
FROM (
  SELECT COUNT(*) AS cnt
  FROM {table}
  WHERE superseded_by IS NULL
    AND source_record_key IS NOT NULL
  GROUP BY source_record_key, audit_type_code, audit_run_mode
  HAVING COUNT(*) > 1
) grp
"""
    return f"""
SELECT
  COUNT(*) AS group_count,
  COALESCE(SUM(cnt - 1), 0) AS rows_to_supersede
FROM (
  SELECT COUNT(*) AS cnt
  FROM {table}
  WHERE superseded_by IS NULL
    AND source_record_key IS NOT NULL
    AND source_record_key != ''
  GROUP BY source_record_key, audit_type_code, audit_run_mode
  HAVING COUNT(*) > 1
) grp
"""


def _apply_sql_oracle(table: str) -> str:
    """将重复组中非 keeper 行标记为被替代。"""
    return f"""
MERGE INTO {table} t
USING (
  WITH base AS (
    SELECT
      id,
      source_record_key,
      NVL(audit_type_code, CHR(0)) AS audit_type_code_n,
      NVL(audit_run_mode, 'daily_increment') AS audit_run_mode_n,
      ROW_NUMBER() OVER (
        PARTITION BY source_record_key,
                     NVL(audit_type_code, CHR(0)),
                     NVL(audit_run_mode, 'daily_increment')
        ORDER BY
          CASE
            WHEN status = 'success'
             AND NVL(parse_status, 'x') = 'success'
             AND (contract_valid IS NULL OR contract_valid <> 0)
            THEN 4
            WHEN status = 'success' AND NVL(parse_status, 'x') = 'success'
            THEN 3
            WHEN status = 'success'
            THEN 2
            ELSE 1
          END DESC,
          NVL(pushed_flag, 0) DESC,
          id DESC
      ) AS rn,
      FIRST_VALUE(id) OVER (
        PARTITION BY source_record_key,
                     NVL(audit_type_code, CHR(0)),
                     NVL(audit_run_mode, 'daily_increment')
        ORDER BY
          CASE
            WHEN status = 'success'
             AND NVL(parse_status, 'x') = 'success'
             AND (contract_valid IS NULL OR contract_valid <> 0)
            THEN 4
            WHEN status = 'success' AND NVL(parse_status, 'x') = 'success'
            THEN 3
            WHEN status = 'success'
            THEN 2
            ELSE 1
          END DESC,
          NVL(pushed_flag, 0) DESC,
          id DESC
      ) AS keeper_id
    FROM {table}
    WHERE superseded_by IS NULL
      AND source_record_key IS NOT NULL
  ),
  dups AS (
    SELECT source_record_key, audit_type_code_n, audit_run_mode_n
    FROM base
    GROUP BY source_record_key, audit_type_code_n, audit_run_mode_n
    HAVING COUNT(*) > 1
  )
  SELECT b.id AS victim_id, b.keeper_id
  FROM base b
  JOIN dups d
    ON b.source_record_key = d.source_record_key
   AND b.audit_type_code_n = d.audit_type_code_n
   AND b.audit_run_mode_n = d.audit_run_mode_n
  WHERE b.rn > 1
) s
ON (t.id = s.victim_id)
WHEN MATCHED THEN UPDATE SET
  t.superseded_by = s.keeper_id,
  t.superseded_at = SYSDATE
"""


def _apply_sql_sqlite(table: str) -> str:
    return f"""
WITH base AS (
  SELECT
    id,
    source_record_key,
    COALESCE(audit_type_code, '') AS audit_type_code_n,
    COALESCE(audit_run_mode, 'daily_increment') AS audit_run_mode_n,
    ROW_NUMBER() OVER (
      PARTITION BY source_record_key,
                   COALESCE(audit_type_code, ''),
                   COALESCE(audit_run_mode, 'daily_increment')
      ORDER BY
        CASE
          WHEN status = 'success'
           AND COALESCE(parse_status, 'x') = 'success'
           AND (contract_valid IS NULL OR contract_valid != 0)
          THEN 4
          WHEN status = 'success' AND COALESCE(parse_status, 'x') = 'success'
          THEN 3
          WHEN status = 'success'
          THEN 2
          ELSE 1
        END DESC,
        COALESCE(pushed_flag, 0) DESC,
        id DESC
    ) AS rn,
    FIRST_VALUE(id) OVER (
      PARTITION BY source_record_key,
                   COALESCE(audit_type_code, ''),
                   COALESCE(audit_run_mode, 'daily_increment')
      ORDER BY
        CASE
          WHEN status = 'success'
           AND COALESCE(parse_status, 'x') = 'success'
           AND (contract_valid IS NULL OR contract_valid != 0)
          THEN 4
          WHEN status = 'success' AND COALESCE(parse_status, 'x') = 'success'
          THEN 3
          WHEN status = 'success'
          THEN 2
          ELSE 1
        END DESC,
        COALESCE(pushed_flag, 0) DESC,
        id DESC
    ) AS keeper_id
  FROM {table}
  WHERE superseded_by IS NULL
    AND source_record_key IS NOT NULL
    AND source_record_key != ''
),
dups AS (
  SELECT source_record_key, audit_type_code_n, audit_run_mode_n
  FROM base
  GROUP BY source_record_key, audit_type_code_n, audit_run_mode_n
  HAVING COUNT(*) > 1
),
victims AS (
  SELECT b.id AS victim_id, b.keeper_id
  FROM base b
  JOIN dups d
    ON b.source_record_key = d.source_record_key
   AND b.audit_type_code_n = d.audit_type_code_n
   AND b.audit_run_mode_n = d.audit_run_mode_n
  WHERE b.rn > 1
)
UPDATE {table}
SET
  superseded_by = (SELECT keeper_id FROM victims v WHERE v.victim_id = {table}.id),
  superseded_at = CURRENT_TIMESTAMP
WHERE id IN (SELECT victim_id FROM victims)
"""


def _create_index_sql(table: str, dialect: str) -> list[str]:
    """部分唯一：仅约束「当前 + 有 key」行；历史行可多条。"""
    if dialect == "oracle":
        # 函数唯一索引：非当前行三列均为 NULL，Oracle 允许多个全 NULL
        return [
            f"""
CREATE UNIQUE INDEX uq_push_log_current_identity ON {table} (
  CASE WHEN superseded_by IS NULL AND source_record_key IS NOT NULL
       THEN source_record_key END,
  CASE WHEN superseded_by IS NULL AND source_record_key IS NOT NULL
       THEN NVL(audit_type_code, CHR(0)) END,
  CASE WHEN superseded_by IS NULL AND source_record_key IS NOT NULL
       THEN NVL(audit_run_mode, 'daily_increment') END
)
""".strip()
        ]
    return [
        f"""
CREATE UNIQUE INDEX IF NOT EXISTS uq_push_log_current_identity
ON {table}(source_record_key, audit_type_code, audit_run_mode)
WHERE superseded_by IS NULL
  AND source_record_key IS NOT NULL
  AND source_record_key != ''
""".strip()
    ]


def _index_exists(conn, engine, index_name: str) -> bool:
    from sqlalchemy import text

    name = index_name.upper()
    if engine.dialect.name == "oracle":
        n = conn.execute(
            text("SELECT COUNT(*) FROM user_indexes WHERE index_name = :n"),
            {"n": name},
        ).scalar()
        return int(n or 0) > 0
    # sqlite
    rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='index' AND name=:n"), {"n": index_name}).fetchall()
    return bool(rows)


def cmd_dry_run(engine) -> int:
    from sqlalchemy import text

    table = _table(engine)
    dialect = engine.dialect.name
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        current = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE superseded_by IS NULL")).scalar()
        row = conn.execute(text(_preview_sql(table, dialect))).fetchone()
        groups = int(row[0] or 0)
        victims = int(row[1] or 0)
        print(f"table={table} dialect={dialect}")
        print(f"total_rows={total}")
        print(f"current_rows={current}")
        print(f"duplicate_groups={groups}")
        print(f"rows_to_supersede={victims}")
        print(f"ts={datetime.now().isoformat(timespec='seconds')}")
        # sample keepers
        if dialect == "oracle" and groups:
            sample = conn.execute(text(f"""
SELECT * FROM (
  SELECT source_record_key, audit_type_code, audit_run_mode, COUNT(*) AS cnt,
         MAX(id) KEEP (
           DENSE_RANK FIRST ORDER BY
             CASE WHEN status='success' AND NVL(parse_status,'x')='success'
                       AND (contract_valid IS NULL OR contract_valid<>0) THEN 4
                  WHEN status='success' AND NVL(parse_status,'x')='success' THEN 3
                  WHEN status='success' THEN 2 ELSE 1 END DESC,
             NVL(pushed_flag,0) DESC, id DESC
         ) AS keeper_id
  FROM {table}
  WHERE superseded_by IS NULL AND source_record_key IS NOT NULL
  GROUP BY source_record_key, audit_type_code, audit_run_mode
  HAVING COUNT(*) > 1
  ORDER BY cnt DESC
) WHERE ROWNUM <= 10
""")).fetchall()
            print("sample_top10_groups=")
            for r in sample:
                key = str(r[0] or "")
                if len(key) > 70:
                    key = key[:67] + "..."
                print(f"  cnt={r[3]} keeper_id={r[4]} type={r[1]} mode={r[2]} key={key}")
    return 0


def cmd_apply(engine) -> int:
    from sqlalchemy import text

    table = _table(engine)
    dialect = engine.dialect.name
    sql = _apply_sql_oracle(table) if dialect == "oracle" else _apply_sql_sqlite(table)
    with engine.begin() as conn:
        before = conn.execute(text(_dup_count_sql(table) if dialect == "oracle" else _preview_sql(table, dialect))).fetchone()
        # for sqlite preview returns 2 cols; for oracle dup_count returns 1
        if dialect == "oracle":
            print(f"before_duplicate_groups={int(before[0] or 0)}")
        else:
            print(f"before_duplicate_groups={int(before[0] or 0)} rows_to_supersede={int(before[1] or 0)}")
        result = conn.execute(text(sql))
        # rowcount may be -1 on some drivers
        print(f"merge_rowcount={getattr(result, 'rowcount', None)}")
        after_groups = conn.execute(text(_dup_count_sql(table))).scalar()
        print(f"after_duplicate_groups={int(after_groups or 0)}")
        current = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE superseded_by IS NULL")).scalar()
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        print(f"after_current_rows={current}")
        print(f"after_total_rows={total}")
        print(f"applied_at={datetime.now().isoformat(timespec='seconds')}")
        if int(after_groups or 0) != 0:
            print("ERROR: still have duplicate current groups", file=sys.stderr)
            raise RuntimeError("cleanup incomplete; rolling back")
    print("APPLY_OK")
    return 0


def cmd_verify(engine) -> int:
    from sqlalchemy import text

    table = _table(engine)
    with engine.connect() as conn:
        groups = int(conn.execute(text(_dup_count_sql(table))).scalar() or 0)
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
        current = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE superseded_by IS NULL")).scalar()
        print(f"table={table}")
        print(f"total_rows={total}")
        print(f"current_rows={current}")
        print(f"duplicate_groups={groups}")
        print("VERIFY_OK" if groups == 0 else "VERIFY_FAIL")
        return 0 if groups == 0 else 1


def cmd_create_index(engine) -> int:
    from sqlalchemy import text

    table = _table(engine)
    dialect = engine.dialect.name
    # require clean data first
    with engine.connect() as conn:
        groups = int(conn.execute(text(_dup_count_sql(table))).scalar() or 0)
        if groups != 0:
            print(f"ERROR: refuse create index, duplicate_groups={groups}", file=sys.stderr)
            return 2
        if _index_exists(conn, engine, "uq_push_log_current_identity"):
            print("index_already_exists=uq_push_log_current_identity")
            print("CREATE_INDEX_SKIP")
            return 0
    with engine.begin() as conn:
        for stmt in _create_index_sql(table, dialect):
            print(f"exec={stmt[:80]}...")
            conn.execute(text(stmt))
    print("CREATE_INDEX_OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Remediate multi-current PushLog rows (015/C1)")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--verify", action="store_true")
    g.add_argument("--create-index", action="store_true")
    args = parser.parse_args(argv)

    from app.database import engine

    if args.dry_run:
        return cmd_dry_run(engine)
    if args.apply:
        return cmd_apply(engine)
    if args.verify:
        return cmd_verify(engine)
    if args.create_index:
        return cmd_create_index(engine)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
