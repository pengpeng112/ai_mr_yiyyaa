# -*- coding: utf-8 -*-
"""012 P2 草案测试：双源 loader 时间窗/fail-closed/锚点校验（全 Mock，不触库）。"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.canonical_record import CanonicalRecordEnvelope, SourceDiagnostics
from app.services.source_feature_flags import SourceFlags

MODULE = "app.services.dual_source_loader"


def _flags():
    return SourceFlags(progress_source="vastbase_v1", nursing_source="oracle_v1")


class _Payload:
    def __init__(self, dual_cfg=None, flags=None):
        self._d = {"builder": "progress_nursing_multi_source", "dual_source": dual_cfg or {}}
        if flags:
            self._d["source_flags"] = flags

    def model_dump(self):
        return dict(self._d)


class _AuditType:
    code = "progress_vs_nursing"
    name = "病程与护理"

    def __init__(self, dual_cfg=None, flags=None):
        self.payload = _Payload(dual_cfg, flags)
        self.sources = {}


DUAL_CFG = {
    "anchor_query_sql": "SELECT PATIENT_ID, VISIT_NUMBER, ADMISSION_TIME, DISCHARGE_TIME FROM JHEMR.V_QYBR WHERE ROWNUM < 10",
    "anchor_field_mapping": {
        "patient_id": "PATIENT_ID",
        "visit_number": "VISIT_NUMBER",
        "admission_time": "ADMISSION_TIME",
        "discharge_time": "DISCHARGE_TIME",
    },
}


def _env(record_id="F-1", kind="progress"):
    return CanonicalRecordEnvelope(
        source_system="vastbase_jhemr", source_name=kind, record_kind=kind,
        record_subtype="daily_progress", record_id=record_id,
        patient_key_internal="P-1", visit_number_internal="3",
        event_time=datetime(2026, 8, 4, 10, 0), content="正文",
    )


def _nursing_env(record_id, created_at):
    return CanonicalRecordEnvelope(
        source_system="oracle_ydhl", source_name="nursing", record_kind="nursing",
        record_subtype="general", record_id=record_id,
        patient_key_internal="P-1_3", visit_number_internal="3",
        event_time=datetime(2026, 8, 4, 8, 0), created_at=created_at, content="护理正文",
    )


def _mock_oracle_conn(anchor_rows):
    cursor = MagicMock()
    cursor.description = [("PATIENT_ID",), ("VISIT_NUMBER",), ("ADMISSION_TIME",), ("DISCHARGE_TIME",)]
    cursor.fetchall.return_value = anchor_rows
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def _run(anchor_rows, run_mode="daily_increment", date_dimension="query_date",
         progress_side_effect=None, nursing_side_effect=None):
    progress_result = ([_env("F-1")], SourceDiagnostics(source_name="progress", row_count=1, valid_count=1))
    nursing_result = ([_env("88001", kind="nursing")], SourceDiagnostics(source_name="nursing", row_count=1, valid_count=1))
    with patch(f"{MODULE}.get_oracle_connection", return_value=_mock_oracle_conn(anchor_rows)), \
         patch(f"{MODULE}.get_emr_vastbase_connection", return_value=MagicMock()), \
         patch(f"{MODULE}.fetch_progress_records_v1",
               side_effect=progress_side_effect or (lambda *a, **k: progress_result)) as mock_progress, \
         patch(f"{MODULE}.fetch_nursing_records_v2",
               side_effect=nursing_side_effect or (lambda *a, **k: nursing_result)) as mock_nursing:
        from app.services.dual_source_loader import load_patient_bundles_dual_source

        result = load_patient_bundles_dual_source(
            audit_type=_AuditType(DUAL_CFG),
            root_config={},
            query_date="2026-08-04",
            date_dimension=date_dimension,
            return_diagnostics=True,
            flags=_flags(),
            audit_run_mode=run_mode,
        )
    return result, mock_progress, mock_nursing


class TestMixedFlagsFailClosed:
    def test_mixed_flags_rejected(self):
        from app.services.dual_source_loader import load_patient_bundles_dual_source

        with pytest.raises(ValueError, match="全双源|vastbase_v1"):
            load_patient_bundles_dual_source(
                audit_type=_AuditType(DUAL_CFG), root_config={}, query_date="2026-08-04",
                flags=SourceFlags(progress_source="vastbase_v1", nursing_source="legacy"),
            )


class TestDailyMode:
    def test_daily_window_single_day_and_form_time(self):
        (bundles, diag), mock_progress, mock_nursing = _run(
            [("P-1", 3, datetime(2026, 8, 1, 9, 0), None)],
        )
        # 病程/护理同为 query_date 单日半开窗
        p_args = mock_progress.call_args[0]
        assert p_args[3] == datetime(2026, 8, 4, 0, 0)
        assert p_args[4] == datetime(2026, 8, 5, 0, 0)
        n_kwargs = mock_nursing.call_args
        assert n_kwargs[1]["date_field"] == "form_time"
        assert n_kwargs[0][1] == "P-1_3"
        assert n_kwargs[0][2] == datetime(2026, 8, 4, 0, 0)
        assert n_kwargs[0][3] == datetime(2026, 8, 5, 0, 0)
        assert diag["run_mode"] == "daily"
        assert len(bundles) == 1

    def test_bundle_identity_and_independent_arrays(self):
        (bundles, diag), _, _ = _run([("P-1", 3.0, None, None)])
        bundle = bundles[0]
        assert bundle.bundle_id == "P-1::3"  # numeric visit 规范化不改变身份
        assert set(bundle.sources.keys()) == {"progress", "nursing"}
        assert bundle.sources["progress"][0]["record_id"] == "F-1"
        assert bundle.sources["nursing"][0]["record_id"] == "88001"


class TestDischargeMode:
    def test_discharge_window_admission_to_discharge_plus_one(self):
        (bundles, diag), mock_progress, mock_nursing = _run(
            [("P-1", 3, datetime(2026, 7, 28, 10, 0), datetime(2026, 8, 4, 15, 0))],
            run_mode="discharge_final", date_dimension="discharge_date",
        )
        p_args = mock_progress.call_args[0]
        assert p_args[3] == datetime(2026, 7, 28, 10, 0)          # 入院起
        assert p_args[4] == datetime(2026, 8, 5, 15, 0)           # 出院+1 天
        assert mock_nursing.call_args[1]["date_field"] == "created_date"
        assert diag["run_mode"] == "discharge"

    def test_missing_anchor_times_skipped(self):
        (bundles, diag), _, _ = _run(
            [("P-1", 3, None, None)],
            run_mode="discharge_final", date_dimension="discharge_date",
        )
        assert bundles == []
        assert diag["skipped_records"] == 1

    def test_nursing_created_date_must_match_a_progress_day(self):
        nursing_result = (
            [
                _nursing_env("N-1", datetime(2026, 8, 4, 9, 0)),
                _nursing_env("N-2", datetime(2026, 8, 3, 9, 0)),
            ],
            SourceDiagnostics(source_name="nursing", row_count=2, valid_count=2),
        )
        (bundles, diag), _, _ = _run(
            [("P-1", 3, datetime(2026, 7, 28, 10, 0), datetime(2026, 8, 4, 15, 0))],
            run_mode="discharge_final",
            date_dimension="discharge_date",
            nursing_side_effect=lambda *a, **k: nursing_result,
        )
        assert [item["record_id"] for item in bundles[0].sources["nursing"]] == ["N-1"]
        assert diag["relation_filtered_counts"] == {"nursing_created_date_not_progress_day": 1}


class TestFailClosed:
    def test_progress_query_failure_propagates(self):
        with pytest.raises(RuntimeError, match="ORA-12609"):
            _run([("P-1", 3, None, None)], progress_side_effect=RuntimeError("ORA-12609"))

    def test_nursing_query_failure_propagates(self):
        with pytest.raises(RuntimeError, match="ORA-12609"):
            _run([("P-1", 3, None, None)], nursing_side_effect=RuntimeError("ORA-12609"))

    def test_missing_anchor_keys_skipped_not_guessed(self):
        (bundles, diag), _, _ = _run([("", None, None, None)])
        assert bundles == []
        assert diag["skipped_records"] == 1

    def test_daily_missing_nursing_is_not_a_pushable_bundle(self):
        empty_nursing = ([], SourceDiagnostics(source_name="nursing", row_count=0, valid_count=0))
        (bundles, diag), _, _ = _run(
            [("P-1", 3, None, None)],
            nursing_side_effect=lambda *a, **k: empty_nursing,
        )
        assert bundles == []
        assert diag["skipped_records"] == 1
        assert diag["required_source_missing_counts"] == {"nursing": 1}

    def test_discharge_missing_nursing_keeps_progress_candidate(self):
        empty_nursing = ([], SourceDiagnostics(source_name="nursing", row_count=0, valid_count=0))
        (bundles, diag), _, _ = _run(
            [("P-1", 3, datetime(2026, 7, 28, 10, 0), datetime(2026, 8, 4, 15, 0))],
            run_mode="discharge_final",
            date_dimension="discharge_date",
            nursing_side_effect=lambda *a, **k: empty_nursing,
        )
        assert len(bundles) == 1
        assert bundles[0].sources["nursing"] == []
        assert diag["skipped_records"] == 0


class TestNursingPatientKey:
    def test_builds_legacy_composite_key(self):
        from app.services.nursing_record_adapter import build_ydhl_patient_key

        assert build_ydhl_patient_key("P-1", 3.0) == "P-1_3"

    def test_missing_component_fails_closed(self):
        from app.services.nursing_record_adapter import build_ydhl_patient_key

        with pytest.raises(ValueError, match="patient_id"):
            build_ydhl_patient_key("P-1", None)


class TestLoaderDispatch:
    def test_legacy_path_when_flags_off(self):
        """source_flags 缺省时不得进入双源分发（旧路径回归保证）。"""
        from app.services.data_source_loader import load_patient_bundles

        class _LegacyPayload:
            def model_dump(self):
                return {"builder": "generic_multi_source"}

        class _LegacyType:
            code = "x"
            name = "x"
            payload = _LegacyPayload()
            sources = {}
            join_rules = []

        with patch(f"{MODULE}.load_patient_bundles_dual_source") as mock_dual:
            bundles = load_patient_bundles(_LegacyType(), {}, "2026-08-04")
            mock_dual.assert_not_called()
        assert bundles == []

    def test_dispatch_to_dual_when_flags_on(self):
        from app.services.data_source_loader import load_patient_bundles

        class _DualType(_AuditType):
            def __init__(self):
                super().__init__(DUAL_CFG, flags={"progress_source": "vastbase_v1", "nursing_source": "oracle_v1"})

        with patch(f"{MODULE}.load_patient_bundles_dual_source", return_value=[]) as mock_dual:
            load_patient_bundles(_DualType(), {}, "2026-08-04", audit_run_mode="daily_increment")
            mock_dual.assert_called_once()
            assert mock_dual.call_args[1]["audit_run_mode"] == "daily_increment"
