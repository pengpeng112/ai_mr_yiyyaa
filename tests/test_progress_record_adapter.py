# -*- coding: utf-8 -*-
"""012 P2 草案测试：Vastbase 病程 Adapter（Mock 连接，012 §10.1/§10.3）。"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from app.services.progress_record_adapter import (
    PROGRESS_MR_CLASSES_V1,
    PROGRESS_RECORD_V1_SQL,
    _progress_batch_sql,
    fetch_progress_records_v1_batch,
    fetch_progress_records_v1,
)


def _make_conn(columns, rows):
    cursor = MagicMock()
    cursor.description = [(c,) for c in columns]
    cursor.fetchall.return_value = rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


_COLUMNS = [
    "patient_key_internal", "visit_number_internal", "progress_record_id",
    "event_time", "created_at", "signed_at", "source_updated_at",
    "progress_class_code", "record_subtype", "progress_title",
    "progress_content", "author_code", "dept_code", "source_status",
]


def _row(**overrides):
    base = dict(
        patient_key_internal="P-1",
        visit_number_internal=3,
        progress_record_id="F-001",
        event_time=datetime(2026, 8, 4, 10, 0),
        created_at=datetime(2026, 8, 4, 10, 5),
        signed_at=None,
        source_updated_at=None,
        progress_class_code="EMR10.00.03",
        record_subtype="daily_progress",
        progress_title="日常病程记录",
        progress_content="正文",
        author_code="D001",
        dept_code="0306",
        source_status="ok",
    )
    base.update(overrides)
    return tuple(base[c] for c in _COLUMNS)


class TestSqlContract:
    def test_scope_and_event_time_frozen(self):
        for mr_class in ("EMR10.00.01", "EMR10.00.02", "EMR10.00.03"):
            assert mr_class in PROGRESS_RECORD_V1_SQL
        assert PROGRESS_MR_CLASSES_V1 == ("EMR10.00.01", "EMR10.00.02", "EMR10.00.03")

    def test_no_to_char_on_time_filter(self):
        # 012 §10.3：禁止在 WHERE 对时间 TO_CHAR（16 号原型全文不得出现）
        assert "TO_CHAR" not in PROGRESS_RECORD_V1_SQL.upper()

    def test_half_open_window_and_binds(self):
        assert "caption_date_time >= %(date_from)s" in PROGRESS_RECORD_V1_SQL
        assert "caption_date_time < %(date_to)s" in PROGRESS_RECORD_V1_SQL
        assert "%(patient_id)s" in PROGRESS_RECORD_V1_SQL
        assert "%(visit_number)s" in PROGRESS_RECORD_V1_SQL

    def test_psycopg2_literal_percent_is_escaped(self):
        assert "LIKE '%%首次病程%%'" in PROGRESS_RECORD_V1_SQL
        assert "LIKE '%首次病程%'" not in PROGRESS_RECORD_V1_SQL

    def test_content_left_join_not_inner(self):
        assert "LEFT JOIN jhfile.jhmr_file_content_text" in PROGRESS_RECORD_V1_SQL

    def test_batch_sql_uses_each_target_window(self):
        sql = _progress_batch_sql(2)
        assert "target_visits (patient_id, visit_id, date_from, date_to)" in sql
        assert "caption_date_time >= t.date_from" in sql
        assert "%(date_from_0)s" in sql and "%(date_from_1)s" in sql
        assert "caption_date_time >= %(date_from)s" not in sql


class TestFetch:
    def test_happy_path_envelope(self):
        conn, cursor = _make_conn(_COLUMNS, [_row()])
        envelopes, diag = fetch_progress_records_v1(conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert diag.row_count == 1 and diag.valid_count == 1 and diag.skipped_count == 0
        assert not diag.query_failed
        env = envelopes[0]
        assert env.record_id == "F-001"
        assert env.visit_number_internal == "3"  # numeric 规范化不改变身份
        assert env.event_time == datetime(2026, 8, 4, 10, 0)
        assert env.mapping_version
        cursor.close.assert_called_once()

    def test_bind_params_normalized(self):
        conn, cursor = _make_conn(_COLUMNS, [])
        fetch_progress_records_v1(conn, "P-1", 3.0, datetime(2026, 8, 4), datetime(2026, 8, 5))
        params = cursor.execute.call_args[0][1]
        assert params["visit_number"] == "3"
        assert params["patient_id"] == "P-1"

    def test_missing_content_preserved_with_status(self):
        conn, _ = _make_conn(_COLUMNS, [_row(progress_content=None, source_status="missing_content")])
        envelopes, diag = fetch_progress_records_v1(conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert diag.valid_count == 1  # 正文缺失保留记录，不静默丢行
        assert envelopes[0].source_status == "missing_content"
        assert envelopes[0].content is None

    def test_vastbase_string_times_are_parsed_at_adapter_boundary(self):
        conn, _ = _make_conn(_COLUMNS, [_row(
            event_time="2026-08-04 10:00:00",
            created_at="2026-08-04T10:05:00",
            signed_at="",
            source_updated_at="2026-08-04 11:00:00",
        )])
        envelopes, diag = fetch_progress_records_v1(
            conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5)
        )
        assert diag.valid_count == 1
        assert envelopes[0].event_time == datetime(2026, 8, 4, 10, 0)
        assert envelopes[0].created_at == datetime(2026, 8, 4, 10, 5)
        assert envelopes[0].signed_at is None

    def test_invalid_string_time_remains_contract_violation(self):
        conn, _ = _make_conn(_COLUMNS, [_row(event_time="not-a-date")])
        envelopes, diag = fetch_progress_records_v1(
            conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5)
        )
        assert envelopes == []
        assert diag.skipped_count == 1

    def test_duplicate_record_id_fails_closed(self):
        conn, cursor = _make_conn(_COLUMNS, [_row(), _row()])
        with pytest.raises(ValueError, match="duplicate record_id"):
            fetch_progress_records_v1(
                conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5)
            )
        cursor.close.assert_called_once()

    def test_contract_violation_skipped(self):
        conn, _ = _make_conn(_COLUMNS, [_row(progress_record_id=None)])
        envelopes, diag = fetch_progress_records_v1(conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert envelopes == []
        assert diag.skipped_count == 1

    def test_query_failure_fails_closed(self):
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("connection lost")
        conn = MagicMock()
        conn.cursor.return_value = cursor
        with pytest.raises(RuntimeError):
            fetch_progress_records_v1(conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5))
        cursor.close.assert_called_once()  # 资源关闭

    def test_real_zero_rows_distinct_from_failure(self):
        conn, _ = _make_conn(_COLUMNS, [])
        envelopes, diag = fetch_progress_records_v1(conn, "P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5))
        assert envelopes == []
        assert diag.row_count == 0 and not diag.query_failed and diag.error_code is None

    def test_batch_uses_one_query_per_chunk_and_preserves_identity(self):
        conn, cursor = _make_conn(_COLUMNS, [])
        result, diag = fetch_progress_records_v1_batch(
            conn,
            [(f"P-{index}", 1) for index in range(200)],
            datetime(2026, 8, 4), datetime(2026, 8, 5),
            batch_size=50,
        )
        assert len(result) == 200
        assert cursor.execute.call_count == 4
        assert "patient_id_0" in cursor.execute.call_args_list[0].args[0]
        assert diag.row_count == 0 and not diag.query_failed

    def test_batch_identity_mismatch_fails_closed(self):
        conn, cursor = _make_conn(_COLUMNS, [_row(patient_key_internal="OTHER")])
        with pytest.raises(ValueError, match="identity mismatch"):
            fetch_progress_records_v1_batch(
                conn, [("P-1", 3)], datetime(2026, 8, 4), datetime(2026, 8, 5)
            )
        cursor.close.assert_called_once()

    def test_batch_conflicting_windows_fail_closed_before_query(self):
        conn, cursor = _make_conn(_COLUMNS, [])
        with pytest.raises(ValueError, match="conflicting windows"):
            fetch_progress_records_v1_batch(
                conn,
                [
                    ("P-1", 3, datetime(2026, 8, 4), datetime(2026, 8, 5)),
                    ("P-1", 3, datetime(2026, 8, 3), datetime(2026, 8, 5)),
                ],
                datetime(2026, 8, 4), datetime(2026, 8, 5),
            )
        cursor.execute.assert_not_called()

    @pytest.mark.parametrize("batch_size", [0, -1, True, 201])
    def test_batch_size_is_strict(self, batch_size):
        conn, cursor = _make_conn(_COLUMNS, [])
        with pytest.raises(ValueError, match="batch_size"):
            fetch_progress_records_v1_batch(
                conn, [("P-1", 3)], datetime(2026, 8, 4), datetime(2026, 8, 5),
                batch_size=batch_size,
            )
        cursor.execute.assert_not_called()
