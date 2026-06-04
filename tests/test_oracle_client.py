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
