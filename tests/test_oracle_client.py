import pytest

from app import oracle_client


def test_apply_query_timeout_uses_connection_property():
    class FakeConnection:
        call_timeout = 0

    conn = FakeConnection()
    assert oracle_client._apply_query_timeout(conn, {"statement_timeout_ms": 2500}) == 2500
    assert conn.call_timeout == 2500


def test_apply_query_timeout_enforces_minimum():
    class FakeConnection:
        callTimeout = 0

    conn = FakeConnection()
    assert oracle_client._apply_query_timeout(conn, {"query_timeout_ms": 10}) == 1000
    assert conn.callTimeout == 1000


def test_apply_query_timeout_invalid_value_falls_back_to_default(caplog):
    class FakeConnection:
        call_timeout = 0

    conn = FakeConnection()
    assert oracle_client._apply_query_timeout(conn, {"query_timeout_ms": "invalid"}) == 60000
    assert conn.call_timeout == 60000
    assert "回退 60000ms" in caplog.text


def test_ping_applies_timeout_before_driver_ping(monkeypatch):
    events = []

    class FakeConnection:
        call_timeout = 0

        def ping(self):
            events.append(("ping", self.call_timeout))

    conn = FakeConnection()
    oracle_client._ping_oracle_connection(conn, {"query_timeout_ms": 3210})
    assert events == [("ping", 3210)]


def test_reset_oracle_pool_does_not_force_close(monkeypatch):
    close_args = []

    class FakePool:
        def close(self, *, force):
            close_args.append(force)

    monkeypatch.setattr(oracle_client, "_oracle_pool", FakePool())
    monkeypatch.setattr(oracle_client, "_oracle_pool_key", ("old",))
    oracle_client.reset_oracle_pool()

    assert close_args == [False]
    assert oracle_client._oracle_pool is None
    assert oracle_client._oracle_pool_key is None


def test_apply_query_timeout_tolerates_legacy_client_rejection(caplog, monkeypatch):
    monkeypatch.setattr(oracle_client, "_query_timeout_unsupported_warned", False)
    class FakeConnection:
        @property
        def call_timeout(self):
            return 0

        @call_timeout.setter
        def call_timeout(self, _value):
            raise RuntimeError("DPI-1050: Oracle Client 18.1 or higher is needed")

    assert oracle_client._apply_query_timeout(
        FakeConnection(), {"query_timeout_ms": 2500}
    ) == 2500
    assert "继续使用驱动默认超时" in caplog.text

    caplog.clear()
    oracle_client._apply_query_timeout(FakeConnection(), {"query_timeout_ms": 2500})
    assert "继续使用驱动默认超时" not in caplog.text


def test_normalize_oracle_sql_keeps_valid_sql():
    assert oracle_client._normalize_oracle_sql("SELECT * FROM t") == "SELECT * FROM t"


def test_inject_condition_into_sql_oracle_path():
    sql = "SELECT * FROM t GROUP BY dept"
    out = oracle_client._inject_condition_into_sql(sql, "a=1")
    assert "WHERE a=1 GROUP BY" in out


def test_build_execute_params_oracle_missing_bind():
    with pytest.raises(ValueError):
        oracle_client._build_execute_params("SELECT * FROM t WHERE d=:d0", {})


def test_build_oracle_dept_filter_uses_dept_codes():
    dept_filter, fallback, params = oracle_client._build_oracle_dept_filter(["020103"], "所在科室名称")
    assert 'a."所在科室编码" IN (:d0)' in dept_filter
    assert 'a."出院科室编码" IN (:d0)' in dept_filter
    assert fallback == dept_filter
    assert params == {"d0": "020103"}


def test_build_oracle_dept_filter_keeps_name_filter():
    dept_filter, fallback, params = oracle_client._build_oracle_dept_filter(["听觉植入科"], "所在科室名称")
    assert dept_filter == "a.所在科室名称 IN (:d0)"
    assert fallback == "所在科室名称 IN (:d0)"
    assert params == {"d0": "听觉植入科"}


def test_build_oracle_dept_filter_supports_mixed_codes_and_names():
    dept_filter, fallback, params = oracle_client._build_oracle_dept_filter(["020103", "听觉植入科"], "所在科室名称")
    assert 'a."所在科室编码" IN (:dc0)' in dept_filter
    assert 'a."出院科室编码" IN (:dc0)' in dept_filter
    assert "a.所在科室名称 IN (:dn0)" in dept_filter
    assert 'a."所在科室编码" IN (:dc0)' in fallback
    assert "所在科室名称 IN (:dn0)" in fallback
    assert params == {"dc0": "020103", "dn0": "听觉植入科"}


def test_resolve_oracle_pool_settings_clamps_and_parses(monkeypatch):
    fake_cx = type(
        "FakeCX",
        (),
        {
            "SPOOL_ATTRVAL_WAIT": 1,
            "SPOOL_ATTRVAL_TIMEDWAIT": 2,
        },
    )()
    monkeypatch.setattr(oracle_client, "cx_Oracle", fake_cx)
    settings = oracle_client._resolve_oracle_pool_settings(
        {
            "pool_min": "0",
            "pool_max": "2",
            "pool_increment": "-1",
            "pool_timeout_seconds": "5",
            "acquire_timeout_seconds": "0",
            "pool_fallback_direct": "true",
        }
    )
    assert settings["pool_min"] == 1
    assert settings["pool_max"] == 2
    assert settings["pool_increment"] == 1
    assert settings["pool_timeout_seconds"] == 10
    assert settings["acquire_timeout_seconds"] == 1
    assert settings["fallback_direct_connect"] is True
    assert settings["use_timed_wait"] is True


def test_resolve_oracle_pool_settings_without_timedwait(monkeypatch):
    fake_cx = type(
        "FakeCX",
        (),
        {
            "SPOOL_ATTRVAL_WAIT": 11,
        },
    )()
    monkeypatch.setattr(oracle_client, "cx_Oracle", fake_cx)
    settings = oracle_client._resolve_oracle_pool_settings({})
    assert settings["getmode"] == 11
    assert settings["use_timed_wait"] is False
def test_fetch_records_retries_ora_12609_once(monkeypatch):
    from app import oracle_client

    class Cursor:
        description = [("患者ID",)]

        def __init__(self, fails):
            self.fails = fails

        def execute(self, sql, params):
            if self.fails:
                raise RuntimeError("ORA-12609: TNS: receive timeout")

        def fetchall(self):
            return [("P001",)]

        def close(self):
            return None

    class Connection:
        call_timeout = 0

        def __init__(self, fails):
            self.fails = fails

        def cursor(self):
            return Cursor(self.fails)

        def rollback(self):
            return None

        def close(self):
            return None

    connections = iter([Connection(True), Connection(False)])
    resets = []
    monkeypatch.setattr(oracle_client, "get_oracle_connection", lambda config: next(connections))
    monkeypatch.setattr(oracle_client, "reset_oracle_pool", lambda: resets.append(True))

    records = oracle_client.fetch_records(
        {"query_sql": "SELECT patient_id AS \"患者ID\" FROM dual WHERE :query_date IS NOT NULL"},
        [],
        "2026-07-31",
    )

    assert records == [{"患者ID": "P001"}]
    assert resets == [True]


# ---- P011 P4-8.2 行为测试：补 S-04 标注的缺口 ----

class _FailingCursor:
    """始终在 execute 抛出指定异常的游标。"""
    description = [("患者ID",)]

    def __init__(self, exc):
        self.exc = exc

    def execute(self, sql, params):
        raise self.exc

    def fetchall(self):
        return []

    def close(self):
        return None


class _FailingConnection:
    """配合 _FailingCursor 的连接。"""

    def __init__(self, exc):
        self.exc = exc
        self.call_timeout = 0
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return _FailingCursor(self.exc)

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_fetch_records_ora_12609_second_failure_does_not_recurse(monkeypatch):
    """P011-8.2: ORA-12609 第二次仍失败时，只产生一次明确失败，不递归重试。"""
    exc = RuntimeError("ORA-12609: TNS: receive timeout")
    # 两次连接都失败：模拟重建池后仍然故障
    conns = [_FailingConnection(exc), _FailingConnection(exc)]
    resets = []
    calls = {"count": 0}

    def fake_get_conn(config):
        calls["count"] += 1
        return conns[calls["count"] - 1]

    monkeypatch.setattr(oracle_client, "get_oracle_connection", fake_get_conn)
    monkeypatch.setattr(oracle_client, "reset_oracle_pool", lambda: resets.append(True))

    with pytest.raises(RuntimeError, match="ORA-12609"):
        oracle_client.fetch_records(
            {"query_sql": "SELECT patient_id AS \"患者ID\" FROM dual WHERE :query_date IS NOT NULL"},
            [],
            "2026-07-31",
        )
    # 关键断言：只调用 get_oracle_connection 两次（初次 + 一次重试），不第三次
    assert calls["count"] == 2
    # 连接池只重建一次
    assert resets == [True]
    # 第二个连接确实回滚并关闭
    assert conns[1].rolled_back is True
    assert conns[1].closed is True


def test_fetch_records_sql_schema_error_not_retried(monkeypatch):
    """P011-8.2: SQL/权限/对象不存在错误不得重试。"""
    exc = RuntimeError("ORA-00942: table or view does not exist")
    conns = [_FailingConnection(exc)]
    resets = []
    calls = {"count": 0}

    def fake_get_conn(config):
        calls["count"] += 1
        return conns[calls["count"] - 1]

    monkeypatch.setattr(oracle_client, "get_oracle_connection", fake_get_conn)
    monkeypatch.setattr(oracle_client, "reset_oracle_pool", lambda: resets.append(True))

    with pytest.raises(RuntimeError, match="ORA-00942"):
        oracle_client.fetch_records(
            {"query_sql": "SELECT patient_id AS \"患者ID\" FROM dual WHERE :query_date IS NOT NULL"},
            [],
            "2026-07-31",
        )
    # 关键断言：SQL 错误不重试，只调用一次连接
    assert calls["count"] == 1
    # 连接池不重建
    assert resets == []


def test_fetch_records_permission_error_not_retried(monkeypatch):
    """P011-8.2: 权限不足（ORA-01031）不重试。"""
    exc = RuntimeError("ORA-01031: insufficient privileges")
    conns = [_FailingConnection(exc)]
    resets = []
    calls = {"count": 0}

    def fake_get_conn(config):
        calls["count"] += 1
        return conns[calls["count"] - 1]

    monkeypatch.setattr(oracle_client, "get_oracle_connection", fake_get_conn)
    monkeypatch.setattr(oracle_client, "reset_oracle_pool", lambda: resets.append(True))

    with pytest.raises(RuntimeError, match="ORA-01031"):
        oracle_client.fetch_records(
            {"query_sql": "SELECT patient_id AS \"患者ID\" FROM dual"},
            [],
            "2026-07-31",
        )
    assert calls["count"] == 1
    assert resets == []
