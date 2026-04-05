import pytest

from app.db_client_base import (
    build_oracle_execute_params,
    inject_condition_into_sql,
    normalize_sql,
    validate_configurable_sql,
    validate_sql_identifier,
)


def test_validate_sql_identifier_accepts_chinese_and_underscore():
    assert validate_sql_identifier("所在科室_名称") == "所在科室_名称"


def test_validate_sql_identifier_rejects_empty():
    with pytest.raises(ValueError):
        validate_sql_identifier(" ")


def test_validate_sql_identifier_rejects_bad_chars():
    with pytest.raises(ValueError):
        validate_sql_identifier("dept-name")


def test_validate_configurable_sql_accepts_select():
    sql = "SELECT * FROM foo WHERE id = 1"
    assert validate_configurable_sql(sql) == sql


def test_validate_configurable_sql_rejects_non_select():
    with pytest.raises(ValueError):
        validate_configurable_sql("UPDATE foo SET a=1")


def test_normalize_sql_trim_bom_and_tail():
    assert normalize_sql("\ufeffSELECT 1；/;") == "SELECT 1"


def test_inject_condition_into_sql_with_where():
    sql = "SELECT * FROM t WHERE a=1 ORDER BY id"
    out = inject_condition_into_sql(sql, "b=2")
    assert "WHERE a=1 AND b=2" in out


def test_inject_condition_into_sql_without_where():
    sql = "SELECT * FROM t ORDER BY id"
    out = inject_condition_into_sql(sql, "a=1")
    assert out.startswith("SELECT * FROM t WHERE a=1")


def test_build_oracle_execute_params_only_uses_binds():
    sql = "SELECT * FROM t WHERE d=:d0 AND q=:query_date"
    params = build_oracle_execute_params(sql, {"d0": "A", "query_date": "2026-01-01", "x": 1})
    assert params == {"d0": "A", "query_date": "2026-01-01"}


def test_build_oracle_execute_params_missing_raises():
    sql = "SELECT * FROM t WHERE d=:d0 AND q=:query_date"
    with pytest.raises(ValueError):
        build_oracle_execute_params(sql, {"d0": "A"})
