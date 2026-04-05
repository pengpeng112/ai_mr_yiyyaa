import pytest

from app import oracle_client


def test_normalize_oracle_sql_keeps_valid_sql():
    assert oracle_client._normalize_oracle_sql("SELECT * FROM t") == "SELECT * FROM t"


def test_inject_condition_into_sql_oracle_path():
    sql = "SELECT * FROM t GROUP BY dept"
    out = oracle_client._inject_condition_into_sql(sql, "a=1")
    assert "WHERE a=1 GROUP BY" in out


def test_build_execute_params_oracle_missing_bind():
    with pytest.raises(ValueError):
        oracle_client._build_execute_params("SELECT * FROM t WHERE d=:d0", {})
