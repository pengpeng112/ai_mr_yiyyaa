"""015/C1：PushLog 当前身份唯一索引迁移（SQLite 部分唯一）。"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def sqlite_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "c1.db"
    url = f"sqlite:///{db_file}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    # 让 app.database 的 engine 指向临时库
    import app.database as database
    import app.models as models

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, autoflush=False, autocommit=False))
    models.Base.metadata.create_all(bind=engine)
    return engine


def test_current_identity_unique_index_blocks_second_success_current(sqlite_engine):
    from app.database import _ensure_push_log_current_identity_unique_index

    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO push_log (
                  id, push_time, trigger_type, query_date, patient_id, status,
                  source_record_key, audit_type_code, audit_run_mode
                ) VALUES
                (1, :t, 'manual', '2026-08-01', 'P1', 'success', 'key-a', 'progress_vs_nursing', 'daily_increment'),
                (2, :t, 'manual', '2026-08-01', 'P1', 'success', 'key-a', 'progress_vs_nursing', 'daily_increment')
                """
            ),
            {"t": datetime(2026, 8, 1, 12, 0, 0)},
        )

    # 有多 success 当前时迁移应跳过，不抛错
    _ensure_push_log_current_identity_unique_index()
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_push_log_current_identity'")
        ).fetchall()
        assert rows == []

    # 收成 1 success 当前后再建索引
    with sqlite_engine.begin() as conn:
        conn.execute(
            text("UPDATE push_log SET superseded_by = 2, superseded_at = :t WHERE id = 1"),
            {"t": datetime(2026, 8, 2, 12, 0, 0)},
        )
    _ensure_push_log_current_identity_unique_index()
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND name='uq_push_log_current_identity'")
        ).fetchall()
        assert rows
        sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_push_log_current_identity'")
        ).scalar()
        assert "success" in str(sql or "").lower()

    # 再插入同身份 success 当前应失败
    with pytest.raises(Exception):
        with sqlite_engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO push_log (
                      id, push_time, trigger_type, query_date, patient_id, status,
                      source_record_key, audit_type_code, audit_run_mode
                    ) VALUES
                    (3, :t, 'manual', '2026-08-03', 'P1', 'success', 'key-a', 'progress_vs_nursing', 'daily_increment')
                    """
                ),
                {"t": datetime(2026, 8, 3, 12, 0, 0)},
            )

    # 同身份 skipped 当前允许与 success 并存
    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO push_log (
                  id, push_time, trigger_type, query_date, patient_id, status,
                  source_record_key, audit_type_code, audit_run_mode
                ) VALUES
                (4, :t, 'manual', '2026-08-03', 'P1', 'skipped', 'key-a', 'progress_vs_nursing', 'daily_increment')
                """
            ),
            {"t": datetime(2026, 8, 3, 13, 0, 0)},
        )


def test_attach_success_push_log_as_current_supersedes_prior(sqlite_engine):
    from sqlalchemy.orm import sessionmaker
    from app.models import PushLog
    from app.services.push_log_supersede import attach_success_push_log_as_current

    Session = sessionmaker(bind=sqlite_engine)
    db = Session()
    old = PushLog(
        push_time=datetime(2026, 8, 1, 10, 0, 0),
        trigger_type="auto",
        query_date="2026-08-01",
        patient_id="P3",
        status="success",
        source_record_key="k-attach",
        audit_type_code="surgery_chain",
        audit_run_mode="daily_increment",
        pushed_flag=1,
    )
    db.add(old)
    db.commit()

    new = PushLog(
        push_time=datetime(2026, 8, 2, 10, 0, 0),
        trigger_type="auto",
        query_date="2026-08-02",
        patient_id="P3",
        status="success",
        source_record_key="k-attach",
        audit_type_code="surgery_chain",
        audit_run_mode="daily_increment",
        pushed_flag=1,
    )
    n = attach_success_push_log_as_current(db, new)
    db.commit()
    assert n == 1
    assert new.id is not None
    db.refresh(old)
    assert old.superseded_by == new.id
    db.close()


def test_remediate_script_dry_run_and_apply_sqlite(sqlite_engine, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "remediate_pushlog_multi_current.py"
    spec = importlib.util.spec_from_file_location("remediate_pushlog_multi_current", path)
    rem = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(rem)

    with sqlite_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO push_log (
                  id, push_time, trigger_type, query_date, patient_id, status, parse_status, pushed_flag,
                  source_record_key, audit_type_code, audit_run_mode
                ) VALUES
                (10, :t, 'auto', '2026-08-01', 'P9', 'failed', '', 0, 'k9', 'surgery_chain', 'daily_increment'),
                (11, :t, 'auto', '2026-08-01', 'P9', 'success', 'success', 1, 'k9', 'surgery_chain', 'daily_increment'),
                (12, :t, 'auto', '2026-08-01', 'P9', 'success', 'failed', 1, 'k9', 'surgery_chain', 'daily_increment')
                """
            ),
            {"t": datetime(2026, 8, 1, 10, 0, 0)},
        )

    assert rem.cmd_dry_run(sqlite_engine) == 0
    out = capsys.readouterr().out
    assert "duplicate_groups=1" in out
    assert "rows_to_supersede=2" in out

    assert rem.cmd_apply(sqlite_engine) == 0
    with sqlite_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, superseded_by FROM push_log WHERE source_record_key='k9' ORDER BY id")
        ).fetchall()
        # keeper should be 11 (qc_usable)
        assert {r[0]: r[1] for r in rows} == {10: 11, 11: None, 12: 11}
    assert rem.cmd_verify(sqlite_engine) == 0
    assert rem.cmd_create_index(sqlite_engine) == 0
