"""Tests for push_skip_policy — record-level key matching only."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.push_skip_policy import get_skip_reason, get_empty_lab_exam_skip_reason
from app.models import PushLog, QCFeedback


def _mock_db():
    return MagicMock()


def _make_chain(return_value):
    """Create a chained mock where filter/order_by/join return self."""
    m = MagicMock()
    m.filter.return_value = m
    m.order_by.return_value = m
    m.join.return_value = m
    m.first.return_value = return_value
    m.with_entities.return_value = m
    return m


def _setup_db(db, push_first_value=None, qc_first_value=None):
    """Wire db.query to return different chains for PushLog vs QCFeedback."""
    push_chain = _make_chain(push_first_value)
    qc_chain = _make_chain(qc_first_value)

    def query_side_effect(model, *args, **kwargs):
        if model == QCFeedback:
            return qc_chain
        return push_chain

    db.query.side_effect = query_side_effect
    return db


def _unreviewed_rec():
    rec = MagicMock()
    rec.id = 1
    rec.reviewed_flag = 0
    rec.manual_override = 0
    return rec


def _reviewed_rec():
    rec = MagicMock()
    rec.id = 2
    rec.reviewed_flag = 1
    rec.manual_override = 0
    return rec


def _rectified_qc_rec():
    rec = MagicMock()
    rec.id = 99
    return rec


class TestGetEmptyLabExamSkipReason:
    def test_empty_lab_and_exam_causes_skip(self):
        payload = {"abnormal_labs": {"items": []}, "abnormal_exams": {"reports": []},
                    "progress_context": {"records": []}, "nursing_context": {"records": []}}
        reason = get_empty_lab_exam_skip_reason(payload)
        assert reason == "检验和检查报告均为空，跳过 Dify 推送"

    def test_labs_but_no_progress_or_nursing(self):
        payload = {"abnormal_labs": {"items": [{"name": "WBC"}]},
                    "abnormal_exams": {"reports": []},
                    "progress_context": {"records": []}, "nursing_context": {"records": []}}
        reason = get_empty_lab_exam_skip_reason(payload)
        assert reason == "病程和护理记录均为空，跳过 Dify 推送"

    def test_has_labs_and_progress_does_not_skip(self):
        payload = {"abnormal_labs": {"items": [{"name": "WBC"}]},
                    "abnormal_exams": {"reports": []},
                    "progress_context": {"records": [{"time": "2026-01-01"}]},
                    "nursing_context": {"records": []}}
        reason = get_empty_lab_exam_skip_reason(payload)
        assert reason == ""


class TestSkipReasonRecordLevelOnly:
    def test_exact_key_match_unreviewed_blocks(self):
        """同 key 且未复核 → 拦截"""
        db = _mock_db()
        _setup_db(db, push_first_value=_unreviewed_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mrid::doc1",
                                       audit_run_mode="daily_increment")
        assert reason == "unreviewed_pending"

    def test_exact_key_match_reviewed_allows(self):
        """同 key 但已复核 → 允许"""
        db = _mock_db()
        _setup_db(db, push_first_value=_reviewed_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mrid::doc1",
                                       audit_run_mode="daily_increment")
        assert reason == ""

    def test_no_source_key_allows(self):
        """无 source_key → 允许（患者级回退已移除）"""
        db = _mock_db()
        _setup_db(db, push_first_value=_unreviewed_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="",
                                       audit_run_mode="daily_increment")
        assert reason == ""

    def test_unmatched_key_allows_new_record(self):
        """不同 key（新文书）→ 允许推送"""
        db = _mock_db()
        _setup_db(db, push_first_value=None)  # old key not found
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mrid::new_doc",
                                       audit_run_mode="daily_increment")
        assert reason == ""

    def test_discharge_with_key_unreviewed_blocks(self):
        """出院模式同 key 未复核仍拦截"""
        db = _mock_db()
        _setup_db(db, push_first_value=_unreviewed_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mode::discharge_final::pv1::1",
                                       audit_run_mode="discharge_final")
        assert reason == "unreviewed_pending"

    def test_discharge_with_key_reviewed_allows(self):
        """出院模式同 key 已复核允许"""
        db = _mock_db()
        _setup_db(db, push_first_value=_reviewed_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mode::discharge_final::pv1::1",
                                       audit_run_mode="discharge_final")
        assert reason == ""

    def test_same_patient_different_key_allowed(self):
        """同患者不同文书（不同 key）不拦截"""
        db = _mock_db()
        _setup_db(db, push_first_value=None)
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mrid::new_doc",
                                       audit_run_mode="daily_increment")
        assert reason == ""


class TestRectifiedSuppressed:
    def test_rectified_suppressed_blocks(self):
        """整改抑制跨模式生效"""
        db = _mock_db()
        _setup_db(db, push_first_value=None, qc_first_value=_rectified_qc_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="",
                                       audit_run_mode="discharge_final")
        assert reason == "rectified_suppressed"

    def test_rectified_suppressed_with_source_key_still_blocks(self):
        """整改抑制优先于 key 检查"""
        db = _mock_db()
        _setup_db(db, push_first_value=None, qc_first_value=_rectified_qc_rec())
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="mode::discharge_final::pv1::99",
                                       audit_run_mode="discharge_final")
        assert reason == "rectified_suppressed"

    def test_no_rectified_no_source_key_allows(self):
        """无整改、无 key → 正常推送"""
        db = _mock_db()
        _setup_db(db, push_first_value=None, qc_first_value=None)
        reason, msg = get_skip_reason(db, "p001", "1",
                                       source_record_key="",
                                       audit_run_mode="daily_increment")
        assert reason == ""
