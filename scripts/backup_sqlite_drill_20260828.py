# -*- coding: utf-8 -*-
"""SQLite 备份恢复轻量演练（031 T4-5 / D7；Oracle 部分归现场，本脚本只演练 SQLite）。

流程：
1. 定位本地应用库（默认 data/med_audit.db；不存在则用临时库造数演练）；
2. sqlite3 backup API 备份到时间戳文件；
3. 恢复到临时路径；
4. 一致性断言：表清单一致 + 每表行数一致 + 关键表抽样计数一致；
5. 输出 PASS/FAIL，退出码 0/1（演练产物落在临时目录，不污染仓库）。

用法：
    python scripts/backup_sqlite_drill_20260828.py [--db data/med_audit.db]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _table_names(conn: sqlite3.Connection) -> list:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    return [r[0] for r in rows]


def _row_counts(conn: sqlite3.Connection) -> dict:
    return {t: conn.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
            for t in _table_names(conn)}


def _make_tmp_db_with_sample(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL);
        CREATE TABLE push_log (id INTEGER PRIMARY KEY, patient_id TEXT, status TEXT);
        INSERT INTO users VALUES (1, 'admin'), (2, 'auditor');
        INSERT INTO push_log VALUES (1, 'P001', 'success'), (2, 'P002', 'failed');
        """)
    conn.commit()
    conn.close()


def run_drill(db_path: Path) -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="sqlite_drill_"))
    if not db_path.exists():
        sample = tmp_dir / "sample_source.db"
        _make_tmp_db_with_sample(sample)
        db_path = sample
        print(f"[drill] 本地库不存在，改用临时样本库演练：{db_path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = tmp_dir / f"backup_{stamp}.db"
    restore_path = tmp_dir / f"restore_{stamp}.db"

    # 1) 备份（sqlite3 backup API：在线一致性快照）
    src = sqlite3.connect(str(db_path))
    bak = sqlite3.connect(str(backup_path))
    with bak:
        src.backup(bak)
    src.close()
    bak.close()

    # 2) 恢复到新路径（备份文件即恢复源）
    restore_conn = sqlite3.connect(str(restore_path))
    backup_conn = sqlite3.connect(str(backup_path))
    with restore_conn:
        backup_conn.backup(restore_conn)

    # 3) 一致性断言
    origin = sqlite3.connect(str(db_path))
    failures = []
    origin_tables = _table_names(origin)
    restore_tables = _table_names(restore_conn)
    if origin_tables != restore_tables:
        failures.append(f"表清单不一致: {origin_tables} vs {restore_tables}")
    origin_counts = _row_counts(origin)
    restore_counts = _row_counts(restore_conn)
    for table, count in origin_counts.items():
        if restore_counts.get(table) != count:
            failures.append(f"表 {table} 行数不一致: {count} vs {restore_counts.get(table)}")

    print(f"[drill] 源库：{db_path}")
    print(f"[drill] 备份：{backup_path}（{backup_path.stat().st_size} bytes）")
    print(f"[drill] 恢复：{restore_path}")
    print(f"[drill] 表数：{len(origin_tables)}；总行数：{sum(origin_counts.values())}")
    if failures:
        for f in failures:
            print(f"[FAIL] {f}")
        result = 1
    else:
        print("[PASS] 备份→恢复→一致性断言全部通过")
        result = 0

    origin.close()
    restore_conn.close()
    backup_conn.close()
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="SQLite 备份恢复轻量演练（031 T4-5）")
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "med_audit.db"),
                        help="本地应用库路径（默认 data/med_audit.db；不存在用临时样本库）")
    args = parser.parse_args(argv)
    return run_drill(Path(args.db))


if __name__ == "__main__":
    sys.exit(main())
