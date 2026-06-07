"""Tests for relay_alert_service: conclusion fallback, suppress_ai_push, and visit_number SQL."""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock, PropertyMock

import pytest


def _make_query_chain(return_value=None, chain_class=None):
    """Create a chained mock that returns itself on filter/join/order_by."""
    m = MagicMock()
    m.filter.return_value = m
    m.join.return_value = m
    m.order_by.return_value = m
    m.with_entities.return_value = m
    m.first.return_value = return_value
    m.all.return_value = return_value if isinstance(return_value, list) else []
    return m


class TestConclusionFallback:
    def test_conclusion_fallback_when_dimensions_exist_but_none_severe(self):
        """有维度但无 severity 命中 + conclusion high → 应创建 __conclusion__"""
        from app.services.relay_alert_service import RelayAlertService

        db = MagicMock()
        log = MagicMock()
        log.id = 1
        log.visit_number = "1"
        log.patient_id = "p001"
        log.audit_type_code = "progress_vs_nursing"
        log.push_time = "2026-01-01 10:00:00"

        dim1 = MagicMock()
        dim1.dimension_code = "lab_abnormal"
        dim1.severity = "medium"
        dim1.dimension = "lab"
        dim1.issue_summary = ""
        dim1.explanation = ""
        dim1.alert_level = ""
        dim1.closure_hours = ""

        conclusion = MagicMock()
        conclusion.severity = "high"
        conclusion.overall_conclusion = "高危问题"
        conclusion.overall_qc_summary = ""
        conclusion.alert_level = "red"
        conclusion.closure_hours = "24"

        suppress_chain = _make_query_chain(None)
        push_chain = _make_query_chain(log)
        conclusion_chain = _make_query_chain(conclusion)
        dim_chain = _make_query_chain([dim1])

        def query_side(model):
            from app.models import QCFeedback, PushLog, AuditConclusion, AuditDimensionResult
            if model == QCFeedback:
                return suppress_chain
            if model == PushLog:
                return push_chain
            if model == AuditConclusion:
                return conclusion_chain
            if model == AuditDimensionResult:
                return dim_chain
            return MagicMock()

        db.query.side_effect = query_side

        cfg = {"relay_alert": {"enabled": True, "severity_levels": ["high"], "source": "test"}}
        svc = RelayAlertService(db, cfg)

        svc._create_alert_log = MagicMock(return_value=MagicMock())
        svc._append_detail_fields = MagicMock()
        svc._build_payload = MagicMock(return_value={})
        svc._exists_alert = MagicMock(return_value=False)

        with mock.patch("app.services.relay_alert_service._get_patient_info",
                        return_value={"patient_id": "p001", "visit_number": "1"}):
            added = svc.enqueue_high_severity_alerts(1)
        assert added == 1, f"expected 1 conclusion alert but got {added}"


class TestSuppressAIPush:
    def test_suppress_ai_push_prevents_alert_creation(self):
        """存在 QCFeedback.suppress_ai_push=True + rectified 时不应创建 alert"""
        from app.services.relay_alert_service import RelayAlertService

        db = MagicMock()
        log = MagicMock()
        log.id = 1
        log.visit_number = "1"
        log.patient_id = "p001"
        log.audit_type_code = "progress_vs_nursing"
        log.push_time = "2026-01-01 10:00:00"

        suppress_rec = MagicMock()
        suppress_rec.id = 99
        suppress_chain = _make_query_chain(suppress_rec)
        push_chain = _make_query_chain(log)

        def query_side(model):
            from app.models import QCFeedback, PushLog
            if model == QCFeedback:
                return suppress_chain
            if model == PushLog:
                return push_chain
            return MagicMock()

        db.query.side_effect = query_side

        cfg = {"relay_alert": {"enabled": True, "severity_levels": ["high"], "source": "test"}}
        svc = RelayAlertService(db, cfg)

        added = svc.enqueue_high_severity_alerts(1)
        assert added == 0, "suppress_ai_push should prevent all alerts"


class TestVisitNumberSQL:
    def test_query_patient_dept_code_with_visit_number(self):
        """有 visit_number 时 SQL 应包含次数条件"""
        from app.services.relay_alert_service import _query_patient_dept_code

        with mock.patch("app.services.relay_alert_service._is_oracle_data_source", return_value=True):
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchone.return_value = ["020103"]

            with mock.patch("app.services.relay_alert_service._get_oracle_connection_from_config", return_value=conn):
                _query_patient_dept_code("p001", "2")
                sql_called = cur.execute.call_args[0][0]
                params_called = cur.execute.call_args[0][1]
                assert '"次数"' in sql_called, f"SQL should contain 次数 column: {sql_called}"
                assert params_called[1] == "2", f"visit_number param should be '2': {params_called}"

    def test_query_patient_dept_code_without_visit_number(self):
        """无 visit_number 时回退为只按患者ID查询"""
        from app.services.relay_alert_service import _query_patient_dept_code

        with mock.patch("app.services.relay_alert_service._is_oracle_data_source", return_value=True):
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchone.return_value = ["020103"]

            with mock.patch("app.services.relay_alert_service._get_oracle_connection_from_config", return_value=conn):
                _query_patient_dept_code("p001", "")
                sql_called = cur.execute.call_args[0][0]
                assert '"次数"' not in sql_called, f"SQL should not contain 次数 without visit_number: {sql_called}"

    def test_query_attending_doctor_with_visit_number(self):
        """有 visit_number 时 SQL 应包含次数条件"""
        from app.services.relay_alert_service import _query_attending_doctor

        with mock.patch("app.services.relay_alert_service._is_oracle_data_source", return_value=True):
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchone.return_value = ["D001", "张医生"]

            with mock.patch("app.services.relay_alert_service._get_oracle_connection_from_config", return_value=conn):
                _query_attending_doctor("p001", "3")
                sql_called = cur.execute.call_args[0][0]
                params_called = cur.execute.call_args[0][1]
                assert '"次数"' in sql_called, f"SQL should contain 次数 column: {sql_called}"
                assert params_called.get("vn") == "3", f"visit_number param should be '3': {params_called}"

    def test_query_attending_doctor_without_visit_number(self):
        """无 visit_number 时回退为只按患者ID查询"""
        from app.services.relay_alert_service import _query_attending_doctor

        with mock.patch("app.services.relay_alert_service._is_oracle_data_source", return_value=True):
            conn = MagicMock()
            cur = MagicMock()
            conn.cursor.return_value = cur
            cur.fetchone.return_value = ["D002", "李医生"]

            with mock.patch("app.services.relay_alert_service._get_oracle_connection_from_config", return_value=conn):
                _query_attending_doctor("p001", "")
                sql_called = cur.execute.call_args[0][0]
                assert '"次数"' not in sql_called, f"SQL should not contain 次数 without visit_number: {sql_called}"
