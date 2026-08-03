"""P011 P4-8.1 统一错误码分类与 SchedulerHistory.error_code 测试。

覆盖：
- classify_oracle_error 对各类 Oracle 异常的分类正确性。
- SchedulerHistory 模型具备 error_code 字段（schema 校验）。
- write_scheduler_history_safe 在 error_code 缺失时从 error_msg 自动归类。
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SchedulerHistory
from app.oracle_client import (
    ORA_TNS_RECEIVE_TIMEOUT,
    ORACLE_QUERY_TIMEOUT,
    ORACLE_CONNECTION_RESET,
    ORACLE_POOL_UNAVAILABLE,
    ORACLE_SQL_OR_SCHEMA,
    ORACLE_TRANSIENT_OTHER,
    ORACLE_UNKNOWN,
    classify_oracle_error,
    is_transient_oracle_error,
)


@pytest.fixture
def db():
    """内存 SQLite + StaticPool，供需要真实 DB 的测试使用。"""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---- classify_oracle_error 分类正确性 ----

class TestClassifyOracleError:
    def test_ora_12609_classified_as_tns_receive_timeout(self):
        assert classify_oracle_error(RuntimeError("ORA-12609: TNS: receive timeout")) == ORA_TNS_RECEIVE_TIMEOUT

    def test_tns_receive_timeout_chinese_message(self):
        assert classify_oracle_error(RuntimeError("tns: receive timeout")) == ORA_TNS_RECEIVE_TIMEOUT

    def test_query_timeout_dpi_1067(self):
        assert classify_oracle_error(RuntimeError("DPI-1067: query timeout")) == ORACLE_QUERY_TIMEOUT

    def test_query_timeout_ora_01013(self):
        assert classify_oracle_error(RuntimeError("ORA-01013: user requested cancel")) == ORACLE_QUERY_TIMEOUT

    def test_connection_reset_ora_03113(self):
        assert classify_oracle_error(RuntimeError("ORA-03113: end-of-file on communication channel")) == ORACLE_CONNECTION_RESET

    def test_connection_reset_ora_03135(self):
        assert classify_oracle_error(RuntimeError("ORA-03135: connection lost contact")) == ORACLE_CONNECTION_RESET

    def test_connection_reset_text(self):
        assert classify_oracle_error(ConnectionError("connection reset by peer")) == ORACLE_CONNECTION_RESET

    def test_pool_unavailable_ora_12519(self):
        assert classify_oracle_error(RuntimeError("ORA-12519: TNS:no appropriate service handler found")) == ORACLE_POOL_UNAVAILABLE

    def test_pool_unavailable_chinese_message(self):
        assert classify_oracle_error(RuntimeError("连接池获取连接失败")) == ORACLE_POOL_UNAVAILABLE

    def test_sql_error_table_not_exist(self):
        assert classify_oracle_error(RuntimeError("ORA-00942: table or view does not exist")) == ORACLE_SQL_OR_SCHEMA

    def test_sql_error_invalid_identifier(self):
        assert classify_oracle_error(RuntimeError('ORA-00904: "在院科室编码" invalid identifier')) == ORACLE_SQL_OR_SCHEMA

    def test_sql_error_insufficient_privileges(self):
        assert classify_oracle_error(RuntimeError("ORA-01031: insufficient privileges")) == ORACLE_SQL_OR_SCHEMA

    def test_sql_error_invalid_number(self):
        assert classify_oracle_error(RuntimeError("ORA-01722: invalid number")) == ORACLE_SQL_OR_SCHEMA

    def test_sql_error_priority_over_transient(self):
        """SQL/Schema 错误即使包含某些瞬时关键字，也优先识别为不可重试。"""
        # ORA-00942 不是瞬时错误，但确认 SQL 类优先级最高
        assert classify_oracle_error(RuntimeError("ORA-00942 table does not exist")) == ORACLE_SQL_OR_SCHEMA

    def test_transient_other_ora_12541(self):
        """ORA-12541 监听不可用属于其他瞬时错误。"""
        assert classify_oracle_error(RuntimeError("ORA-12541: TNS:no listener")) == ORACLE_TRANSIENT_OTHER

    def test_unknown_error(self):
        assert classify_oracle_error(ValueError("something else entirely")) == ORACLE_UNKNOWN

    def test_none_returns_unknown(self):
        assert classify_oracle_error(None) == ORACLE_UNKNOWN


# ---- classify_oracle_error 与 is_transient_oracle_error 的一致性 ----

class TestClassificationConsistency:
    def test_sql_schema_errors_are_not_transient(self):
        """被归类为 SQL/Schema 的错误，不应当被 is_transient 识别为可重试。"""
        sql_errors = [
            RuntimeError("ORA-00942: table or view does not exist"),
            RuntimeError("ORA-01031: insufficient privileges"),
            RuntimeError("ORA-01722: invalid number"),
        ]
        for err in sql_errors:
            assert classify_oracle_error(err) == ORACLE_SQL_OR_SCHEMA
            assert is_transient_oracle_error(err) is False

    def test_tns_receive_timeout_is_transient(self):
        err = RuntimeError("ORA-12609: TNS: receive timeout")
        assert classify_oracle_error(err) == ORA_TNS_RECEIVE_TIMEOUT
        assert is_transient_oracle_error(err) is True


# ---- SchedulerHistory 模型具备 error_code 字段 ----

class TestSchedulerHistoryErrorCodeField:
    def test_model_has_error_code_column(self):
        """SchedulerHistory 模型必须包含 error_code 列。"""
        assert hasattr(SchedulerHistory, "error_code")

    def test_error_code_has_index(self):
        """error_code 应建索引，便于按错误码聚合统计。"""
        columns = {c.name: c for c in SchedulerHistory.__table__.columns}
        assert "error_code" in columns
        # 确认列上有索引（单独 index=True 会生成 idx）
        index_names = {idx.columns.keys()[0] for idx in SchedulerHistory.__table__.indexes if len(idx.columns) == 1}
        assert "error_code" in index_names or any(
            "error_code" in str(idx.columns) for idx in SchedulerHistory.__table__.indexes
        )


# ---- write_scheduler_history_safe 自动从 error_msg 推断 error_code ----

class TestSchedulerHistoryAutoClassification:
    def test_write_history_auto_classifies_ora_12609(self, db, monkeypatch):
        """error_code 缺失但 error_msg 含 ORA-12609 时，应自动归类。"""
        from app.services import scheduler_history_service
        from app.services.scheduler_history_service import write_scheduler_history_safe

        # 让服务内部 SessionLocal 指向测试内存 DB
        monkeypatch.setattr(scheduler_history_service, "SessionLocal", lambda: db)

        msg = write_scheduler_history_safe(
            query_date="2026-08-03",
            audit_type_code="progress_vs_nursing",
            total_records=0,
            success_count=0,
            failed_count=0,
            duration_seconds=10,
            status="failed",
            audit_run_mode="daily_increment",
            error_msg="ORA-12609: TNS: receive timeout during fetch",
        )
        # 写入成功返回空串
        assert msg == ""

        last = db.query(SchedulerHistory).order_by(SchedulerHistory.id.desc()).first()
        assert last is not None
        assert last.error_code == ORA_TNS_RECEIVE_TIMEOUT
        assert last.status == "failed"

    def test_write_history_explicit_error_code_preserved(self, db, monkeypatch):
        """显式传入 error_code 时，不覆盖。"""
        from app.services import scheduler_history_service
        from app.services.scheduler_history_service import write_scheduler_history_safe

        monkeypatch.setattr(scheduler_history_service, "SessionLocal", lambda: db)

        write_scheduler_history_safe(
            query_date="2026-08-03",
            audit_type_code="progress_vs_nursing",
            total_records=5,
            success_count=5,
            failed_count=0,
            duration_seconds=10,
            status="completed",
            audit_run_mode="discharge_final",
            error_msg="",
            error_code="dify_target_pool_unavailable",
        )

        last = db.query(SchedulerHistory).order_by(SchedulerHistory.id.desc()).first()
        assert last is not None
        assert last.error_code == "dify_target_pool_unavailable"

    def test_write_history_success_has_empty_error_code(self, db, monkeypatch):
        """成功记录的 error_code 应为空。"""
        from app.services import scheduler_history_service
        from app.services.scheduler_history_service import write_scheduler_history_safe

        monkeypatch.setattr(scheduler_history_service, "SessionLocal", lambda: db)

        write_scheduler_history_safe(
            query_date="2026-08-03",
            audit_type_code="progress_vs_nursing",
            total_records=5,
            success_count=5,
            failed_count=0,
            duration_seconds=10,
            status="completed",
            audit_run_mode="daily_increment",
            error_msg="",
        )

        last = db.query(SchedulerHistory).order_by(SchedulerHistory.id.desc()).first()
        assert last is not None
        assert last.error_code == ""
