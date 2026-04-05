"""
将现有 SQLite 业务表迁移到 Oracle 应用库。

用法：
python scripts/migrate_sqlite_to_oracle.py --source data/med_audit.db

前提：
1. 已配置 APP_ORACLE_HOST / APP_ORACLE_PORT / APP_ORACLE_SERVICE_NAME / APP_ORACLE_USERNAME / APP_ORACLE_PASSWORD
2. 目标 Oracle 用户具备建表权限
3. 该脚本会将 APP_DB_TYPE 临时切换为 oracle
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
os.environ["APP_DB_TYPE"] = "oracle"

from sqlalchemy import Boolean, DateTime, inspect  # noqa: E402

from app.database import SessionLocal, init_db, engine  # noqa: E402
from app.models import (  # noqa: E402
    AuditConclusion,
    AuditDimensionResult,
    Department,
    NotifyLog,
    Permission,
    PushLog,
    QCFeedback,
    QCFeedbackHistory,
    Role,
    RolePermission,
    SchedulerHistory,
    User,
)


TABLES = [
    ("push_log", PushLog),
    ("audit_dimension_result", AuditDimensionResult),
    ("audit_conclusion", AuditConclusion),
    ("scheduler_history", SchedulerHistory),
    ("notify_log", NotifyLog),
    ("departments", Department),
    ("roles", Role),
    ("permissions", Permission),
    ("role_permissions", RolePermission),
    ("users", User),
    ("qc_feedback", QCFeedback),
    ("qc_feedback_history", QCFeedbackHistory),
]


def _parse_datetime(value):
    if value in (None, ""):
        return value
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return datetime.fromisoformat(text)


def _normalize_row(model, row_dict: dict) -> dict:
    normalized = {}
    columns = {column.name: column for column in model.__table__.columns}
    for key, value in row_dict.items():
        if key not in columns:
            continue
        column = columns[key]
        if value is None:
            normalized[key] = None
            continue
        if isinstance(column.type, DateTime):
            normalized[key] = _parse_datetime(value)
        elif isinstance(column.type, Boolean):
            normalized[key] = bool(value)
        else:
            normalized[key] = value
    return normalized


def _sqlite_table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _target_table_empty(session, model) -> bool:
    return (session.query(model).count() or 0) == 0


def migrate(source_db: Path):
    if not source_db.exists():
        raise FileNotFoundError(f"SQLite 数据库不存在: {source_db}")

    init_db()
    inspector = inspect(engine)
    print(f"[INFO] 目标数据库类型: {engine.dialect.name}")
    print(f"[INFO] 已创建/检测目标表: {inspector.get_table_names()}")

    sqlite_conn = sqlite3.connect(str(source_db))
    sqlite_conn.row_factory = sqlite3.Row

    session = SessionLocal()
    try:
        for source_table, model in TABLES:
            if not _sqlite_table_exists(sqlite_conn, source_table):
                print(f"[SKIP] 源表不存在: {source_table}")
                continue

            if not _target_table_empty(session, model):
                print(f"[SKIP] 目标表非空，跳过: {model.__tablename__}")
                continue

            rows = sqlite_conn.execute(f"SELECT * FROM {source_table}").fetchall()
            if not rows:
                print(f"[OK] 源表为空: {source_table}")
                continue

            payload = [_normalize_row(model, dict(row)) for row in rows]
            session.bulk_insert_mappings(model, payload)
            session.commit()
            print(f"[OK] {source_table} -> {model.__tablename__}: {len(payload)} 条")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        sqlite_conn.close()


def main():
    parser = argparse.ArgumentParser(description="迁移 SQLite 业务表到 Oracle")
    parser.add_argument("--source", default=str(ROOT_DIR / "data" / "med_audit.db"), help="SQLite 源库路径")
    args = parser.parse_args()
    migrate(Path(args.source))


if __name__ == "__main__":
    main()
