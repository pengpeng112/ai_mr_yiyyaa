"""SQLite 应用库 busy_timeout / WAL 连接级设置测试（037 RP-A / P-001）。

NullPool 每连接新建，PRAGMA 必须挂在 connect 监听器；
调度推送线程与请求线程并发写时应等待而不是立刻 database is locked。
"""
import threading

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.database import is_transient_app_db_error


def test_t1_busy_timeout_pragma_on_each_connection(tmp_path):
    from app.database import create_engine_for_config, DB_PATH
    import app.database as db_module
    import os

    # 用临时文件库构造引擎（绕开模块级全局 engine 的真实 DB_PATH）
    tmp_db = tmp_path / "busy_test.db"
    orig_url = db_module._build_sqlite_url
    db_module._build_sqlite_url = lambda: f"sqlite:///{tmp_db.as_posix()}"
    try:
        eng = create_engine_for_config()
    finally:
        db_module._build_sqlite_url = orig_url

    with eng.connect() as conn:
        val = conn.exec_driver_sql("PRAGMA busy_timeout").fetchone()[0]
        assert int(val) >= 30000
    # NullPool：第二条新连接同样生效
    with eng.connect() as conn:
        val2 = conn.exec_driver_sql("PRAGMA busy_timeout").fetchone()[0]
        assert int(val2) >= 30000
    eng.dispose()


def test_t2_concurrent_writes_no_locked_errors(tmp_path):
    """两线程各插 40 行同一表：busy_timeout 生效时零 database is locked。"""
    tmp_db = tmp_path / "concurrent.db"
    eng = create_engine(
        f"sqlite:///{tmp_db.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=NullPool,
    )

    from sqlalchemy import event

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_connection, _record):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY, tag TEXT)"))
        conn.commit()

    errors: list[str] = []

    def worker(tag: str):
        for i in range(40):
            try:
                with eng.connect() as conn:
                    conn.execute(text("INSERT INTO t (tag) VALUES (:t)"), {"t": tag})
                    conn.commit()
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not any("locked" in e.lower() or "busy" in e.lower() for e in errors), errors
    with eng.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM t")).fetchone()[0]
    assert total == 80
    eng.dispose()


def test_t3_transient_marker_includes_sqlite_lock():
    class _FakeOperationalError(Exception):
        pass

    assert is_transient_app_db_error(_FakeOperationalError("database is locked"))
    assert is_transient_app_db_error(_FakeOperationalError("database is busy"))
    assert not is_transient_app_db_error(_FakeOperationalError("no such table: users"))
