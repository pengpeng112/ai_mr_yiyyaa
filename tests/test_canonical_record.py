# -*- coding: utf-8 -*-
"""012 P2 草案测试：CanonicalRecordEnvelope 契约与规范化（012 §10.1）。"""
from datetime import datetime

import pytest

from app.services.canonical_record import (
    SCHEMA_VERSION_V1,
    SOURCE_STATUS_OK,
    SOURCE_STATUS_QUERY_FAILED,
    CanonicalRecordEnvelope,
    SourceDiagnostics,
    assert_no_internal_key_in_labels,
    bundle_hash,
    coerce_visit_number,
    ensure_native_datetime,
    normalize_column_name,
    normalize_record_keys,
    sanitize_log_text,
)


def _make_envelope(**overrides) -> CanonicalRecordEnvelope:
    base = dict(
        source_system="vastbase_jhemr",
        source_name="progress",
        record_kind="progress",
        record_subtype="daily_progress",
        record_id="FILE-1",
        patient_key_internal="P-1",
        visit_number_internal="3",
        event_time=datetime(2026, 8, 4, 10, 0),
    )
    base.update(overrides)
    return CanonicalRecordEnvelope(**base)


class TestColumnNormalize:
    def test_oracle_uppercase_columns_normalized(self):
        record = {"PATIENT_ID": "P1", "FORM_TIME": datetime(2026, 8, 4)}
        normalized = normalize_record_keys(record)
        assert normalized == {"patient_id": "P1", "form_time": datetime(2026, 8, 4)}

    def test_chinese_column_names_preserved_lowercased(self):
        assert normalize_column_name("患者ID") == "患者id"

    def test_vastbase_lowercase_unchanged(self):
        assert normalize_column_name("file_unique_id") == "file_unique_id"


class TestCoerceVisitNumber:
    @pytest.mark.parametrize("value", [5, 5.0, "5", "5.0", " 5 "])
    def test_numeric_identities_unified(self, value):
        assert coerce_visit_number(value) == "5"

    def test_non_integer_numeric_preserved(self):
        assert coerce_visit_number("5.5") == "5.5"

    def test_none_returns_empty(self):
        assert coerce_visit_number(None) == ""

    def test_non_numeric_text_preserved(self):
        assert coerce_visit_number("A12") == "A12"


class TestNativeDatetime:
    def test_datetime_passthrough(self):
        value = datetime(2026, 8, 4, 12, 0)
        assert ensure_native_datetime(value) is value

    def test_none_allowed(self):
        assert ensure_native_datetime(None) is None

    def test_string_rejected(self):
        with pytest.raises(TypeError):
            ensure_native_datetime("2026-08-04 12:00:00")


class TestEnvelopeValidate:
    def test_valid_envelope_passes(self):
        assert _make_envelope().validate() == []

    def test_missing_record_id_fails(self):
        errors = _make_envelope(record_id="").validate()
        assert any("record_id" in e for e in errors)

    def test_missing_patient_key_fails(self):
        errors = _make_envelope(patient_key_internal="").validate()
        assert any("patient_key_internal" in e for e in errors)

    def test_missing_visit_number_fails(self):
        errors = _make_envelope(visit_number_internal="").validate()
        assert any("visit_number_internal" in e for e in errors)

    def test_illegal_source_status_fails(self):
        errors = _make_envelope(source_status="bogus").validate()
        assert any("source_status" in e for e in errors)

    def test_string_time_field_fails(self):
        errors = _make_envelope(created_at="2026-08-04").validate()
        assert any("created_at" in e for e in errors)

    def test_schema_version_default(self):
        assert _make_envelope().schema_version == SCHEMA_VERSION_V1
        assert _make_envelope().source_status == SOURCE_STATUS_OK


class TestSourceDiagnostics:
    def test_query_failed_distinct_from_zero_rows(self):
        diag = SourceDiagnostics(source_name="nursing")
        assert diag.row_count == 0 and not diag.query_failed
        diag.mark_query_failed("ORA-12609")
        assert diag.query_failed
        assert diag.error_code == "ORA-12609"
        assert diag.row_count == 0  # 失败不被写成"真实 0 行"以外的状态

    def test_zero_rows_without_failure_is_real_empty(self):
        diag = SourceDiagnostics(source_name="progress")
        assert not diag.query_failed
        assert diag.error_code is None


class TestPrivacyGuards:
    def test_bundle_hash_irreversible_and_stable(self):
        h1 = bundle_hash("P-1", "3")
        h2 = bundle_hash("P-1", "3")
        assert h1 == h2 and len(h1) == 16
        assert "P-1" not in h1

    def test_sanitize_log_text_masks_internal_keys(self):
        assert sanitize_log_text("患者 P-1 加载失败", "P-1") == "患者 [internal-key] 加载失败"

    def test_metric_labels_reject_internal_key(self):
        with pytest.raises(ValueError):
            assert_no_internal_key_in_labels({"bundle": "P-1::3"})
