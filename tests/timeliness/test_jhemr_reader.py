"""T1：app/timeliness/jhemr_reader.py 假连接单元测试。

覆盖：只出现 SELECT/WITH 只读语句、%s 参数化（患者号不进 SQL 文本）、
500 对自动分批、列名转小写、readonly 会话与 statement_timeout 设置、
SQLSTATE 42501 → TimelinessPermissionMissing、配置解析（aizk_user 固定、
口令环境变量/密文两路、缺配置报错）、模板 timeliness 段骨架、
jhemr_reader.py 源码禁写关键词扫描。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from cryptography.fernet import InvalidToken

from app.timeliness import jhemr_reader
from app.timeliness.config import (
    PASSWORD_ENV_VAR,
    READONLY_USERNAME_FIXED,
    TimelinessNotConfigured,
    TimelinessPermissionMissing,
    get_timeliness_section,
    resolve_jhemr_readonly,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "jhemr_expected_columns.json"

FORBIDDEN_SQL_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|ALTER|GRANT)\b", re.IGNORECASE)

T1_TABLES = [
    "pats_in_hospital",
    "pat_visit",
    "jhmr_file_index",
    "operation",
    "emr_treament_apply",
    "emr_online_monitor",
    "jhmr_monitor_limit_log",
]


def load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def fixture_columns(qualified_table: str) -> list[str]:
    return load_fixture()["tables"][qualified_table]["columns"]


class FakePgError(Exception):
    """带 pgcode 的假 DBAPI 错误（模拟 psycopg2.errors.InsufficientPrivilege）。"""

    def __init__(self, pgcode: str | None, message: str = "permission denied"):
        super().__init__(message)
        self.pgcode = pgcode


class FakeCursor:
    """假 cursor：记录 execute 调用；description 模拟 Vastbase 大写列名。"""

    def __init__(self, columns: list[str], rows: list[tuple] | None = None, error: Exception | None = None):
        self._columns = list(columns)
        self._rows = list(rows or [])
        self._error = error
        self.executed: list[tuple[str, list]] = []
        self.description = None

    def execute(self, sql, params=None):
        self.executed.append((sql, list(params or [])))
        if self._error is not None:
            raise self._error
        self.description = [(c.upper(), None, None, None, None, None, None) for c in self._columns]

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor
        self.session_kwargs: dict | None = None
        self.closed = False

    def set_session(self, **kwargs):
        self.session_kwargs = kwargs

    def cursor(self):
        return self._cursor

    def close(self):
        self.closed = True


VALID_SECTION = {
    "enabled": True,
    "scan_interval_minutes": 5,
    "jhemr_readonly": {
        "host": "10.10.8.177",
        "port": 5432,
        "database": "jhemr",
        "username": READONLY_USERNAME_FIXED,
        "password_enc": "",
        "statement_timeout_ms": 60000,
        "connect_timeout_seconds": 10,
        "sslmode": "",
    },
    "jhemr_write": {"enabled": False},
    "pilot_dept_codes": [],
}


@pytest.fixture
def patch_conn(monkeypatch):
    """把 jhemr_reader.get_jhemr_readonly_connection 换成假连接，返回 FakeConnection。"""

    def _install(cursor: FakeCursor) -> FakeConnection:
        conn = FakeConnection(cursor)
        monkeypatch.setattr(
            jhemr_reader, "get_jhemr_readonly_connection", lambda section=None: conn
        )
        return conn

    return _install


# ---------- 配置解析 ----------


def test_resolve_uses_env_password_and_fixed_account(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-injected-secret")
    params = resolve_jhemr_readonly(VALID_SECTION)
    assert params["username"] == READONLY_USERNAME_FIXED == "aizk_user"
    assert params["password"] == "env-injected-secret"
    assert params["host"] == "10.10.8.177"
    assert params["database"] == "jhemr"
    assert params["statement_timeout_ms"] == 60000


def test_resolve_rejects_other_account(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV_VAR, raising=False)
    section = copy.deepcopy(VALID_SECTION)
    section["jhemr_readonly"]["username"] = "someone_else"
    section["jhemr_readonly"]["password_enc"] = "ciphertext-placeholder"
    with pytest.raises(TimelinessNotConfigured):
        resolve_jhemr_readonly(section)


def test_resolve_rejects_missing_host(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-injected-secret")
    section = copy.deepcopy(VALID_SECTION)
    section["jhemr_readonly"]["host"] = ""
    with pytest.raises(TimelinessNotConfigured):
        resolve_jhemr_readonly(section)


def test_resolve_rejects_missing_password(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV_VAR, raising=False)
    with pytest.raises(TimelinessNotConfigured):
        resolve_jhemr_readonly(VALID_SECTION)


def test_resolve_decrypts_password_enc(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV_VAR, raising=False)
    monkeypatch.setattr("app.timeliness.config.decrypt_value", lambda token: "decrypted-secret")
    section = copy.deepcopy(VALID_SECTION)
    section["jhemr_readonly"]["password_enc"] = "ciphertext-placeholder"
    params = resolve_jhemr_readonly(section)
    assert params["password"] == "decrypted-secret"


def test_resolve_reports_key_drift_without_echo(monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV_VAR, raising=False)

    def boom(token):
        raise InvalidToken()

    monkeypatch.setattr("app.timeliness.config.decrypt_value", boom)
    section = copy.deepcopy(VALID_SECTION)
    section["jhemr_readonly"]["password_enc"] = "ciphertext-placeholder"
    with pytest.raises(RuntimeError, match="密钥漂移"):
        resolve_jhemr_readonly(section)


def test_section_not_configured_when_missing_or_disabled():
    with pytest.raises(TimelinessNotConfigured):
        get_timeliness_section({})
    with pytest.raises(TimelinessNotConfigured):
        get_timeliness_section({"timeliness": {"enabled": False}})


def test_config_template_has_timeliness_skeleton():
    tpl = json.loads(
        (REPO_ROOT / "config" / "config.json.template").read_text(encoding="utf-8")
    )
    section = tpl["timeliness"]
    assert section["enabled"] is False
    readonly = section["jhemr_readonly"]
    assert readonly["username"] == "aizk_user"
    assert readonly["password_enc"] == ""
    assert readonly["statement_timeout_ms"] > 0
    assert section["jhemr_write"]["enabled"] is False
    assert section["pilot_dept_codes"] == []


# ---------- 连接建立 ----------


def test_connection_sets_readonly_and_statement_timeout(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-injected-secret")
    cursor = FakeCursor(["ok"], rows=[(1,)])
    conn = FakeConnection(cursor)
    captured: dict = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return conn

    result = jhemr_reader.get_jhemr_readonly_connection(VALID_SECTION, connect=fake_connect)
    assert result is conn
    assert conn.session_kwargs == {"readonly": True, "autocommit": True}
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]
    assert sql == "SET statement_timeout = %s"
    assert params == [60000]
    assert captured["user"] == "aizk_user"
    assert captured["dbname"] == "jhemr"
    assert captured["password"] == "env-injected-secret"
    # sslmode 未配置时不得传给驱动
    assert "sslmode" not in captured


def test_connection_passes_sslmode_only_when_configured(monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV_VAR, "env-injected-secret")
    section = copy.deepcopy(VALID_SECTION)
    section["jhemr_readonly"]["sslmode"] = "require"
    cursor = FakeCursor(["ok"], rows=[(1,)])
    conn = FakeConnection(cursor)
    captured: dict = {}

    jhemr_reader.get_jhemr_readonly_connection(section, connect=lambda **kw: (captured.update(kw), conn)[1])
    assert captured["sslmode"] == "require"


# ---------- 查询语义 ----------


def test_list_files_query_semantics(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    rows = jhemr_reader.list_files([("P1", "1"), ("P2", "2")])
    assert rows == []
    assert len(cursor.executed) == 1
    sql, params = cursor.executed[0]

    normalized = " ".join(sql.split()).upper()
    assert normalized.startswith("WITH TARGET(PID, VID) AS (VALUES")
    assert "SELECT" in normalized
    # 禁写关键词不出现
    assert FORBIDDEN_SQL_RE.search(sql) is None
    # 患者号只出现在参数里，不进 SQL 文本
    assert params == ["P1", "1", "P2", "2"]
    assert "P1" not in sql and "P2" not in sql
    assert sql.count("%s") == len(params)
    # T1 必取 13 列全部在选取列中
    for col in columns:
        assert f"f.{col}" in sql


def test_list_files_returns_lowercase_columns(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    row = tuple(f"val-{i}" for i in range(len(columns)))
    cursor = FakeCursor(columns, rows=[row])
    patch_conn(cursor)

    rows = jhemr_reader.list_files([("P1", "1")])
    assert len(rows) == 1
    assert list(rows[0].keys()) == columns  # fixture 列为小写；description 大写被统一转小写
    assert rows[0]["patient_id"] == "val-0"


def test_list_files_batches_over_500_pairs(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    pairs = [(f"P{i}", str(i)) for i in range(1200)]
    jhemr_reader.list_files(pairs)

    assert len(cursor.executed) == 3  # 500 + 500 + 200
    assert [len(params) for _, params in cursor.executed] == [1000, 1000, 400]
    for sql, params in cursor.executed:
        assert sql.count("%s") == len(params)
        for i in range(0, len(params), 2):
            assert params[i] not in sql


def test_list_files_exactly_500_is_single_batch(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    pairs = [(f"P{i}", str(i)) for i in range(500)]
    jhemr_reader.list_files(pairs)
    assert len(cursor.executed) == 1

    cursor.executed.clear()
    jhemr_reader.list_files(pairs + [("P501", "501")])
    assert len(cursor.executed) == 2


def test_list_monitor_rows_codes_parametrized_after_pairs(patch_conn):
    columns = fixture_columns("jhemr.emr_online_monitor")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    jhemr_reader.list_monitor_rows([("P1", "1"), ("P2", "2")], ["JH04.02.002", "JH04.02.001"])
    sql, params = cursor.executed[0]
    # 参数顺序与占位符一致：先患者对（VALUES），后监控码（IN）
    assert params == ["P1", "1", "P2", "2", "JH04.02.002", "JH04.02.001"]
    assert sql.count("%s") == len(params)
    assert "JH04.02.002" not in sql
    assert "SELECT M.*" in " ".join(sql.split()).upper()


def test_list_monitor_rows_without_codes_has_no_extra_filter(patch_conn):
    columns = fixture_columns("jhemr.emr_online_monitor")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    jhemr_reader.list_monitor_rows([("P1", "1")], None)
    sql, params = cursor.executed[0]
    assert params == ["P1", "1"]
    assert "ITEM_CODE IN" not in sql.upper()


def test_recent_discharges_parametrized_days(patch_conn):
    columns = fixture_columns("jhemr.pat_visit")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    jhemr_reader.list_recent_discharges(7)
    sql, params = cursor.executed[0]
    assert params == [7]
    normalized = " ".join(sql.split()).upper()
    assert "%S * INTERVAL '1 DAY'" in normalized
    assert "DISCHARGE_DATE_TIME >= CURRENT_TIMESTAMP" in normalized
    assert FORBIDDEN_SQL_RE.search(sql) is None

    with pytest.raises(ValueError):
        jhemr_reader.list_recent_discharges(0)


def test_consult_and_limit_logs_parametrized_since(patch_conn):
    apply_cols = fixture_columns("jhemr.emr_treament_apply")
    apply_cursor = FakeCursor(apply_cols, rows=[])
    patch_conn(apply_cursor)
    jhemr_reader.list_consult_applies("2026-11-01 00:00:00")
    sql, params = apply_cursor.executed[0]
    assert params == ["2026-11-01 00:00:00"]
    assert "APPLY_DATE_TIME >= %S" in " ".join(sql.split()).upper()
    # 2026-11-10 实证：consult_class 仅在 master，applyid LEFT JOIN（master 仅 8 行稀疏）。
    consult_upper = " ".join(sql.split()).upper()
    assert "LEFT JOIN" in consult_upper and "EMR_TREAMENT_APPLY_MASTER" in consult_upper
    assert "M.CONSULT_CLASS" in consult_upper
    with pytest.raises(ValueError):
        jhemr_reader.list_consult_applies("")

    limit_cursor = FakeCursor(["anything"], rows=[])
    patch_conn(limit_cursor)
    jhemr_reader.list_limit_logs("2026-11-01 00:00:00")
    sql2, params2 = limit_cursor.executed[0]
    assert params2 == ["2026-11-01 00:00:00"]
    assert FORBIDDEN_SQL_RE.search(sql2) is None


def test_list_inpatients_joins_two_tables(patch_conn):
    columns = ["patient_id", "visit_id", "dept_code", "admission_date_time", "dept_discharge_from", "discharge_date_time"]
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    jhemr_reader.list_inpatients()
    sql, params = cursor.executed[0]
    assert params == []
    upper = " ".join(sql.split()).upper()
    assert "JHEMR\".\"PATS_IN_HOSPITAL" in upper.replace('"', '"')
    assert "JOIN" in upper
    assert "ADMISSION_DATE_TIME" in upper
    assert FORBIDDEN_SQL_RE.search(sql) is None


def test_operations_select_explicit_columns(patch_conn):
    columns = fixture_columns("jhemr.operation")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)

    jhemr_reader.list_operations([("P1", "1")])
    sql, params = cursor.executed[0]
    assert params == ["P1", "1"]
    for col in columns:
        assert f"o.{col}" in sql


def test_empty_pairs_skips_query(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)
    assert jhemr_reader.list_files([]) == []
    assert cursor.executed == []


def test_invalid_pairs_raise_value_error(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, rows=[])
    patch_conn(cursor)
    with pytest.raises(ValueError):
        jhemr_reader.list_files([("P1", "")])
    with pytest.raises(ValueError):
        jhemr_reader.list_files([("P1",)])  # type: ignore[misc]


# ---------- 权限不足 ----------


def test_permission_missing_raises_typed_error(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(
        columns, error=FakePgError("42501", "permission denied for table jhmr_file_index")
    )
    patch_conn(cursor)

    with pytest.raises(TimelinessPermissionMissing) as excinfo:
        jhemr_reader.list_files([("P1", "1")])
    assert excinfo.value.table_name == "jhemr.jhmr_file_index"
    assert "aizk_user" in str(excinfo.value)


def test_permission_missing_for_monitor_table(patch_conn):
    columns = fixture_columns("jhemr.emr_online_monitor")
    cursor = FakeCursor(
        columns, error=FakePgError("42501", "permission denied for table emr_online_monitor")
    )
    patch_conn(cursor)

    with pytest.raises(TimelinessPermissionMissing) as excinfo:
        jhemr_reader.list_monitor_rows([("P1", "1")])
    assert excinfo.value.table_name == "jhemr.emr_online_monitor"


def test_other_db_errors_pass_through(patch_conn):
    columns = fixture_columns("jhemr.jhmr_file_index")
    cursor = FakeCursor(columns, error=FakePgError("42P01", "relation does not exist"))
    patch_conn(cursor)

    with pytest.raises(FakePgError):
        jhemr_reader.list_files([("P1", "1")])


def test_insufficient_privilege_by_class_name(patch_conn):
    class InsufficientPrivilege(Exception):
        pass

    columns = fixture_columns("jhemr.pat_visit")
    cursor = FakeCursor(columns, error=InsufficientPrivilege("permission denied"))
    patch_conn(cursor)

    with pytest.raises(TimelinessPermissionMissing) as excinfo:
        jhemr_reader.list_recent_discharges(7)
    assert excinfo.value.table_name == "jhemr.pat_visit"


# ---------- 全函数只读语义 + 源码禁写 ----------


def test_all_seven_functions_emit_readonly_sql(patch_conn):
    """七个固定函数逐个执行：语句均以 SELECT/WITH 开头且不含禁写关键词。"""
    calls: list[tuple[str, str]] = []  # (函数名, SQL)

    def run(fn_name, cursor, fn):
        patch_conn(cursor)
        fn()
        assert len(cursor.executed) >= 1, fn_name
        for sql, _ in cursor.executed:
            calls.append((fn_name, sql))

    run("list_inpatients", FakeCursor(["patient_id"]), jhemr_reader.list_inpatients)
    run("list_recent_discharges", FakeCursor(["patient_id"]), lambda: jhemr_reader.list_recent_discharges(7))
    run("list_files", FakeCursor(fixture_columns("jhemr.jhmr_file_index")), lambda: jhemr_reader.list_files([("P1", "1")]))
    run("list_operations", FakeCursor(fixture_columns("jhemr.operation")), lambda: jhemr_reader.list_operations([("P1", "1")]))
    run("list_consult_applies", FakeCursor(["applyid"]), lambda: jhemr_reader.list_consult_applies("2026-11-01"))
    run("list_monitor_rows", FakeCursor(["monitor_no"]), lambda: jhemr_reader.list_monitor_rows([("P1", "1")], ["JH04.02.002"]))
    run("list_limit_logs", FakeCursor(["flag"]), lambda: jhemr_reader.list_limit_logs("2026-11-01"))

    assert {name for name, _ in calls} == {
        "list_inpatients",
        "list_recent_discharges",
        "list_files",
        "list_operations",
        "list_consult_applies",
        "list_monitor_rows",
        "list_limit_logs",
    }
    for name, sql in calls:
        normalized = " ".join(sql.split()).upper()
        assert normalized.startswith(("SELECT", "WITH")), f"{name} 不是只读查询: {normalized[:60]}"
        assert FORBIDDEN_SQL_RE.search(sql) is None, f"{name} 出现禁写关键词"


def test_reader_source_contains_no_write_statements():
    """禁写断言：jhemr_reader.py 源码不得出现 INSERT/UPDATE/DELETE/ALTER/GRANT。"""
    source = Path(jhemr_reader.__file__).read_text(encoding="utf-8")
    matches = FORBIDDEN_SQL_RE.findall(source)
    assert matches == [], f"源码出现禁写关键词: {matches}"


# ---------- fixture 自身 ----------


def test_fixture_covers_seven_tables_and_lowercase():
    data = load_fixture()
    # 2026-11-10 §18.2 授权后经 sjzc 实证核对完成（证据 review/timeliness/T1_columns.json）。
    assert data["verified"] is True
    # T1 七表 + 会诊主表（consult_class 仅在此表，授权后新增）。
    assert {f"jhemr.{t}" for t in T1_TABLES} | {"jhemr.emr_treament_apply_master"} == set(data["tables"].keys())
    for qualified, meta in data["tables"].items():
        assert meta["columns"], qualified
        for col in meta["columns"]:
            assert col == col.lower(), f"{qualified}.{col} 应为小写"


def test_fixture_matches_real_column_evidence():
    """fixture 期望列必须被 2026-11-10 实证列清单快照完全覆盖。

    快照 = tests/timeliness/fixtures/jhemr_real_columns_20261110.json（随 git 跟踪；
    原始取证过程与分块证据在 review/timeliness/T1_columns.json、t1_columns_chunks/）。
    """
    evidence = json.loads(
        (Path(__file__).parent / "fixtures" / "jhemr_real_columns_20261110.json").read_text(encoding="utf-8")
    )
    real = {name: {c["column_name"] for c in cols} for name, cols in evidence["tables"].items()}
    data = load_fixture()
    for qualified, meta in data["tables"].items():
        assert qualified in real, f"实证清单缺表: {qualified}"
        missing = [c for c in meta["columns"] if c not in real[qualified]]
        assert not missing, f"{qualified} 期望列未实证: {missing}"
