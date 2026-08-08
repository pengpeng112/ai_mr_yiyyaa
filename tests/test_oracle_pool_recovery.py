"""Oracle 业务池瞬时错误识别与恢复相关单测。"""

from app.oracle_client import is_transient_oracle_error, _is_permanent_pool_failure
from app.database import is_transient_app_db_error


def test_ora_12541_is_transient():
    assert is_transient_oracle_error(RuntimeError("ORA-12541: TNS:no listener")) is True
    assert is_transient_oracle_error(Exception("DPI-1010: not connected")) is True


def test_dpi_1050_is_permanent_pool_failure():
    err = RuntimeError("DPI-1050: Oracle Client library is at version 11.2")
    assert _is_permanent_pool_failure(err) is True
    assert is_transient_oracle_error(err) is False


def test_tns_not_permanent_pool_failure():
    err = RuntimeError("ORA-12541: TNS:no listener")
    assert _is_permanent_pool_failure(err) is False


def test_ora_12609_is_transient_for_application_database_pool():
    assert is_transient_app_db_error(
        RuntimeError("ORA-12609: TNS: receive timeout")
    ) is True
