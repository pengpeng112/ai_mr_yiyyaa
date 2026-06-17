"""Tests for push_log_supersede — discharge_final覆盖在院daily_increment成功日志。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog
from app.services.push_log_supersede import ensure_supersede, mark_daily_logs_superseded


def _mock_log(**kwargs):
    defaults = {
        "id": 200,
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "discharge_final",
        "status": "success",
        "source_record_key": "mode::discharge_final::pv::1",
    }
    defaults.update(kwargs)
    log = MagicMock()
    for k, v in defaults.items():
        setattr(log, k, v)
    type(log).id = log.id
    return log


def _make_chain():
    m = MagicMock()
    m.filter.return_value = m
    m.not_like.return_value = m
    m.notlike.return_value = m
    m.is_.return_value = m
    m.update.return_value = 1
    return m


class TestMarkDailyLogsSuperseded:
    def test_skip_when_not_discharge_final(self):
        log = _mock_log(audit_run_mode="daily_increment")
        db = MagicMock()
        result = mark_daily_logs_superseded(db, log)
        assert result == 0

    def test_skip_when_not_success(self):
        log = _mock_log(status="failed")
        db = MagicMock()
        result = mark_daily_logs_superseded(db, log)
        assert result == 0

    def test_skip_when_visit_number_empty(self):
        log = _mock_log(visit_number="")
        db = MagicMock()
        result = mark_daily_logs_superseded(db, log)
        assert result == 0

    def test_skip_when_visit_number_none(self):
        log = _mock_log(visit_number=None)
        db = MagicMock()
        result = mark_daily_logs_superseded(db, log)
        assert result == 0

    def test_covers_same_patient_visit_rule(self):
        log = _mock_log()
        chain = _make_chain()
        db = MagicMock()
        db.query.return_value = chain

        result = mark_daily_logs_superseded(db, log)
        assert result == 1

        call = db.query.call_args
        assert call is not None

    def test_progress_vs_nursing_compat_empty_code(self):
        log = _mock_log(audit_type_code="progress_vs_nursing")
        chain = _make_chain()
        db = MagicMock()
        db.query.return_value = chain

        result = mark_daily_logs_superseded(db, log)
        assert result == 1

    def test_excludes_discharge_final_source_keys(self):
        log = _mock_log()
        chain = _make_chain()
        db = MagicMock()
        db.query.return_value = chain

        mark_daily_logs_superseded(db, log)
        assert chain.filter.call_count >= 1

    def test_other_audit_type_exact_match(self):
        log = _mock_log(audit_type_code="surgery_chain")
        chain = _make_chain()
        db = MagicMock()
        db.query.return_value = chain

        result = mark_daily_logs_superseded(db, log)
        assert result == 1


class TestEnsureSupersede:
    """verify ensure_supersede propagates exceptions."""

    def test_propagates_exception(self):
        log = _mock_log()
        db = MagicMock()
        db.query.side_effect = RuntimeError("db error")

        raised = False
        try:
            ensure_supersede(db, log)
        except RuntimeError:
            raised = True
        assert raised, "ensure_supersede must raise on exception"

    def test_returns_count_on_success(self):
        log = _mock_log()
        chain = _make_chain()
        db = MagicMock()
        db.query.return_value = chain

        result = ensure_supersede(db, log)
        assert result == 1

    @patch("app.services.push_log_supersede.mark_daily_logs_superseded")
    def test_does_not_catch_return_value_0(self, mock_mark):
        mock_mark.return_value = 0
        log = _mock_log()
        db = MagicMock()
        result = ensure_supersede(db, log)
        assert result == 0


# ---------------------------------------------------------------------------
# SQLite 内存库集成测试 —— 验证真实 SQL 过滤与 bulk update 行为
# ---------------------------------------------------------------------------

def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _make_log(**kwargs):
    """创建 PushLog 实例，未指定的字段使用合理默认值。"""
    defaults = {
        "push_time": datetime.now(),
        "trigger_type": "auto",
        "query_date": "2026-06-01",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "daily_increment",
        "status": "success",
        "pushed_flag": 1,
        "source_record_key": "",
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def _make_discharge_log(**kwargs):
    defaults = {
        "push_time": datetime.now(),
        "trigger_type": "auto",
        "query_date": "2026-06-05",
        "patient_id": "P001",
        "visit_number": "1",
        "audit_type_code": "progress_vs_nursing",
        "audit_run_mode": "discharge_final",
        "status": "success",
        "pushed_flag": 1,
        "source_record_key": "mode::discharge_final::pv::1",
    }
    defaults.update(kwargs)
    return PushLog(**defaults)


def _force_field_null(db, log_id, field_name):
    """在 SQL 层面将字段强制设为 NULL。

    ORM 的 ``default=''`` 会在 INSERT 时把 None 转为空串，
    历史脏数据中的真实 NULL 需用 UPDATE 模拟。
    """
    db.query(PushLog).filter(PushLog.id == log_id).update(
        {field_name: None}, synchronize_session=False
    )


class TestSqliteIntegration:
    """SQLite :memory: 集成测试，验证真实 SQL 过滤语义与 update 行为。"""

    def test_null_source_record_key_is_covered(self):
        """source_record_key IS NULL 的 daily success 必须被覆盖（核心回归点）。"""
        db = _make_db()
        try:
            daily = _make_log()
            db.add(daily)
            db.flush()
            _force_field_null(db, daily.id, "source_record_key")
            db.commit()
            db.refresh(daily)
            assert daily.source_record_key is None

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 1

            db.refresh(daily)
            assert daily.superseded_by == discharge.id
            assert daily.superseded_at is not None
        finally:
            db.close()

    def test_empty_source_record_key_is_covered(self):
        """source_record_key == '' 的 daily success 必须被覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(source_record_key="")
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 1

            db.refresh(daily)
            assert daily.superseded_by == discharge.id
        finally:
            db.close()

    def test_legacy_source_record_key_is_covered(self):
        """source_record_key='legacy::...' 的 daily success 必须被覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(source_record_key="legacy::P001|1|||")
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 1
        finally:
            db.close()

    def test_discharge_final_source_key_excluded(self):
        """source_record_key='mode::discharge_final::...' 的 daily 不应被覆盖。"""
        db = _make_db()
        try:
            # 该记录虽然 audit_run_mode=daily_increment，但 key 含 discharge_final 前缀
            daily = _make_log(
                audit_run_mode="daily_increment",
                source_record_key="mode::discharge_final::pv::99",
            )
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 0

            db.refresh(daily)
            assert daily.superseded_by is None
        finally:
            db.close()

    def test_progress_vs_nursing_compat_null_and_empty_code(self):
        """progress_vs_nursing 覆盖兼容 audit_type_code='' 和 NULL。"""
        db = _make_db()
        try:
            daily_empty = _make_log(source_record_key="k1", audit_type_code="")
            daily_none = _make_log(source_record_key="k2", audit_type_code="")
            db.add_all([daily_empty, daily_none])
            db.flush()
            # daily_none 强制 audit_type_code 为 NULL（模拟历史脏数据）
            _force_field_null(db, daily_none.id, "audit_type_code")
            db.commit()

            discharge = _make_discharge_log(audit_type_code="progress_vs_nursing")
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 2

            db.refresh(daily_empty)
            db.refresh(daily_none)
            assert daily_empty.superseded_by == discharge.id
            assert daily_none.superseded_by == discharge.id
        finally:
            db.close()

    def test_other_audit_type_exact_match(self):
        """非 progress_vs_nursing 类型按精确 code 匹配。"""
        db = _make_db()
        try:
            daily_match = _make_log(audit_type_code="surgery_chain", source_record_key="sc1")
            daily_other = _make_log(audit_type_code="admission_vs_first_progress", source_record_key="af1")
            db.add_all([daily_match, daily_other])
            db.commit()

            discharge = _make_discharge_log(audit_type_code="surgery_chain")
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 1

            db.refresh(daily_match)
            db.refresh(daily_other)
            assert daily_match.superseded_by == discharge.id
            assert daily_other.superseded_by is None
        finally:
            db.close()

    def test_already_superseded_not_re_covered(self):
        """已被覆盖（superseded_by != NULL）的 daily 不重复覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(source_record_key="k1", superseded_by=999)
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 0

            db.refresh(daily)
            assert daily.superseded_by == 999  # 保持原值
        finally:
            db.close()

    def test_skipped_daily_not_covered(self):
        """status='skipped' 的 daily 不被覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(status="skipped", source_record_key="k1")
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 0
        finally:
            db.close()

    def test_different_patient_not_covered(self):
        """不同 patient_id 的 daily 不被覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(patient_id="P999", source_record_key="k1")
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log(patient_id="P001")
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 0
        finally:
            db.close()

    def test_different_visit_number_not_covered(self):
        """同患者但不同 visit_number 的 daily 不被覆盖。"""
        db = _make_db()
        try:
            daily = _make_log(visit_number="2", source_record_key="k1")
            db.add(daily)
            db.commit()

            discharge = _make_discharge_log(visit_number="1")
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 0
        finally:
            db.close()

    def test_mixed_batch_covers_correct_subset(self):
        """混合场景：仅符合条件的 daily 被覆盖，其余不受影响。"""
        db = _make_db()
        try:
            null_key_log = _make_log()  # 先创建，后面强制设为 NULL
            should_cover = [
                null_key_log,
                _make_log(source_record_key="legacy::a"),        # legacy key
                _make_log(source_record_key="", audit_type_code=""),  # empty key + empty code
            ]
            should_not_cover = [
                _make_log(source_record_key="mode::discharge_final::x"),  # discharge key
                _make_log(status="failed", source_record_key="ok"),       # failed
                _make_log(patient_id="P002", source_record_key="ok"),     # diff patient
                _make_log(superseded_by=888, source_record_key="ok"),     # already superseded
            ]
            db.add_all(should_cover + should_not_cover)
            db.flush()
            _force_field_null(db, null_key_log.id, "source_record_key")
            db.commit()

            discharge = _make_discharge_log()
            db.add(discharge)
            db.commit()

            count = mark_daily_logs_superseded(db, discharge)
            assert count == 3

            for log in should_cover:
                db.refresh(log)
                assert log.superseded_by == discharge.id
            for log in should_not_cover:
                db.refresh(log)
                assert log.superseded_by is None or log.superseded_by == 888
        finally:
            db.close()
