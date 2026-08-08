# -*- coding: utf-8 -*-
"""012 P2 草案测试：Oracle 护理窄查询 Adapter（Mock 连接，012 §10.1/§10.3）。"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.services.nursing_record_adapter import (
    NURSING_DATE_FIELD_CREATED_DATE,
    NURSING_DATE_FIELD_FORM_TIME,
    NURSING_RECORD_V2_SQL_TEMPLATE,
    build_nursing_v2_sql,
    fetch_nursing_records_v2,
)

_COLUMNS = [
    "patient_key_internal", "patient_id", "patient_uid",
    "visit_number_internal", "visit_number", "nursing_record_id",
    "event_time", "form_time", "created_at", "source_updated_at",
    "template_code", "record_type", "record_name",
    "recorder_code", "recorder_name", "dept_code", "dept_name", "bed_no",
    "nursing_content", "content", "temperature", "pulse", "respiration",
    "blood_pressure", "oxygen_saturation", "blood_glucose", "consciousness",
    "nurse_signature", "reviewer_signature", "mapping_version",
]


def _row(**overrides):
    base = dict(
        patient_key_internal="P-1", patient_id="P-1", patient_uid="IDX-9",
        visit_number_internal=2, visit_number=2, nursing_record_id=88001,
        event_time=datetime(2026, 8, 4, 9, 0),
        form_time=datetime(2026, 8, 4, 9, 0),
        created_at=datetime(2026, 8, 4, 21, 30),
        source_updated_at=None,
        template_code=572, record_type="一般患者护理记录单",
        record_name="一般患者护理记录单",
        recorder_code="N01", recorder_name="护士甲",
        dept_code="0306", dept_name="内科", bed_no="12",
        nursing_content="护理正文", content="护理正文",
        temperature="36.5", pulse="80", respiration="18",
        blood_pressure="120 / 80", oxygen_saturation="98",
        blood_glucose=None, consciousness=None,
        nurse_signature="N01", reviewer_signature=None,
        mapping_version="nursing-node-map-v2-20260807",
    )
    base.update(overrides)
    return tuple(base.get(c) for c in _COLUMNS)


def _make_conn(rows):
    cursor = MagicMock()
    cursor.description = [(c,) for c in _COLUMNS]
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


class TestSqlContract:
    def test_template_scope_frozen_572_709(self):
        assert "f.template_code IN (572, 709)" in NURSING_RECORD_V2_SQL_TEMPLATE

    def test_both_time_fields_selected(self):
        sql = build_nursing_v2_sql()
        assert "f.form_time," in sql
        assert "f.created_date," in sql

    def test_half_open_window_and_binds(self):
        sql = build_nursing_v2_sql(NURSING_DATE_FIELD_FORM_TIME)
        assert "f.form_time >= :date_from" in sql
        assert "f.form_time < :date_to" in sql
        assert ":patient_key" in sql

    def test_discharge_mode_uses_created_date(self):
        sql = build_nursing_v2_sql(NURSING_DATE_FIELD_CREATED_DATE)
        assert "f.created_date >= :date_from" in sql
        assert "f.created_date < :date_to" in sql
        assert "f.form_time >= :date_from" not in sql

    def test_date_field_whitelist_rejects_injection(self):
        with pytest.raises(ValueError):
            build_nursing_v2_sql("form_time; DROP TABLE x--")
        with pytest.raises(ValueError):
            build_nursing_v2_sql("event_time")

    def test_content_non_empty_having_kept(self):
        assert "HAVING" in NURSING_RECORD_V2_SQL_TEMPLATE

    def test_anchor_relation_preserved(self):
        assert "f.patient_uid = a.patient_uid" in NURSING_RECORD_V2_SQL_TEMPLATE
        assert "pat_index_no" in NURSING_RECORD_V2_SQL_TEMPLATE


class TestFetch:
    def test_happy_path_envelope(self):
        conn, cursor = _make_conn([_row()])
        envelopes, diag = fetch_nursing_records_v2(conn, "P-1", datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert diag.valid_count == 1 and not diag.query_failed
        env = envelopes[0]
        assert env.record_id == "88001"
        assert env.record_kind == "nursing"
        assert env.event_time == datetime(2026, 8, 4, 9, 0)       # form_time
        assert env.created_at == datetime(2026, 8, 4, 21, 30)     # created_date 独立保留
        assert env.structured_fields["temperature"] == "36.5"
        cursor.close.assert_called_once()

    def test_default_date_field_is_form_time(self):
        conn, cursor = _make_conn([])
        fetch_nursing_records_v2(conn, "P-1", datetime(2026, 8, 4), datetime(2026, 8, 5))
        executed_sql = cursor.execute.call_args[0][0]
        assert "f.form_time >= :date_from" in executed_sql

    def test_duplicate_form_id_skipped(self):
        conn, _ = _make_conn([_row(), _row()])
        envelopes, diag = fetch_nursing_records_v2(conn, "P-1", datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert len(envelopes) == 1
        assert diag.skipped_count == 1

    def test_query_failure_fails_closed(self):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("ORA-12609")
        conn = MagicMock()
        conn.cursor.return_value = cursor
        with pytest.raises(RuntimeError):
            fetch_nursing_records_v2(conn, "P-1", datetime(2026, 8, 4), datetime(2026, 8, 5))
        cursor.close.assert_called_once()

    def test_real_zero_rows_distinct_from_failure(self):
        conn, _ = _make_conn([])
        envelopes, diag = fetch_nursing_records_v2(conn, "P-1", datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert envelopes == []
        assert diag.row_count == 0 and not diag.query_failed
