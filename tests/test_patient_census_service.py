"""Tests for patient_census_service: exception desensitization and precheck safety."""

from __future__ import annotations

from unittest import mock
from unittest.mock import MagicMock

import pytest


class TestPrecheckExceptionDesensitization:
    def test_precheck_exception_does_not_leak_sql_or_secrets(self):
        """预检异常不泄露 SQL/密钥原文"""
        from app.services.patient_census_service import precheck_by_patient_census

        with mock.patch("app.services.patient_census_service._assert_data_source_oracle"), \
             mock.patch("app.services.patient_census_service.load_patient_census",
                        return_value=([{"patient_id": "p001", "visit_number": "1"}], 1)), \
             mock.patch("app.services.patient_census_service.load_patient_bundles",
                        side_effect=Exception("ORA-00904 SELECT password FROM jhemr.v_qybr api_key=sk-123456")), \
             mock.patch("app.services.patient_census_service.logger"), \
             mock.patch("app.services.patient_census_service.AuditTypeRegistry") as mock_reg:

            mock_reg_instance = MagicMock()
            mock_reg.return_value = mock_reg_instance
            audit_type = MagicMock()
            audit_type.code = "jyjc_vs_bcnursing"
            mock_reg_instance.get.return_value = audit_type

            result = precheck_by_patient_census(
                config={"data_source": {"type": "oracle"}},
                mode="discharged",
                query_date="2026-06-05",
                dept_filter=["020103"],
                audit_type_codes=["jyjc_vs_bcnursing"],
                limit_patients=1,
            )

            failed_result = next((r for r in result.get("audit_results", [])
                                  if r.get("status") == "failed"), None)
            assert failed_result is not None, "expected a failed audit_result"
            assert failed_result.get("error_code") == "precheck_failed"
            assert "ORA" not in failed_result.get("error", ""), "error should not leak SQL"
            assert "SELECT" not in failed_result.get("error", ""), "error should not leak SQL"
            assert "api_key" not in failed_result.get("error", ""), "error should not leak secrets"
            assert "password" not in failed_result.get("error", ""), "error should not leak secrets"

    def test_precheck_discharged_progress_vs_nursing_skips_heavy_sql(self):
        """出院 progress_vs_nursing 预检返回 skipped_heavy_source 且不调用 load_patient_bundles"""
        from app.services.patient_census_service import precheck_by_patient_census

        bundle_called = []

        def fake_load(*args, **kwargs):
            bundle_called.append(True)
            return ([], {})

        with mock.patch("app.services.patient_census_service._assert_data_source_oracle"), \
             mock.patch("app.services.patient_census_service.load_patient_census",
                        return_value=([{"patient_id": "p001"}], 2)), \
             mock.patch("app.services.patient_census_service.load_patient_bundles",
                        side_effect=fake_load), \
             mock.patch("app.services.patient_census_service.logger"), \
             mock.patch("app.services.patient_census_service.AuditTypeRegistry") as mock_reg:

            mock_reg_instance = MagicMock()
            mock_reg.return_value = mock_reg_instance
            audit_type = MagicMock()
            audit_type.code = "progress_vs_nursing"
            mock_reg_instance.get.return_value = audit_type

            precheck_by_patient_census(
                config={"data_source": {"type": "oracle"}},
                mode="discharged",
                query_date="2026-06-05",
                dept_filter=["020103"],
                audit_type_codes=["progress_vs_nursing"],
                limit_patients=2,
            )

            assert len(bundle_called) == 0, "load_patient_bundles must not be called for discharged progress_vs_nursing"

    def test_precheck_non_discharged_progress_vs_nursing_calls_bundles(self):
        """非出院模式 progress_vs_nursing 预检正常调用 load_patient_bundles"""
        from app.services.patient_census_service import precheck_by_patient_census

        bundle_called = []

        def fake_load(*args, **kwargs):
            bundle_called.append(True)
            return ([{"patient_id": "p001"}], {"source_row_counts": {"frontpage": 1}})

        with mock.patch("app.services.patient_census_service._assert_data_source_oracle"), \
             mock.patch("app.services.patient_census_service.load_patient_census",
                        return_value=([{"patient_id": "p001"}], 2)), \
             mock.patch("app.services.patient_census_service.load_patient_bundles",
                        side_effect=fake_load), \
             mock.patch("app.services.patient_census_service.logger"), \
             mock.patch("app.services.patient_census_service.AuditTypeRegistry") as mock_reg, \
             mock.patch("app.services.patient_census_service.summarize_bundles",
                        return_value={"pushable_count": 1, "skip_count": 0,
                                      "skip_reason_counts": {}, "side_counts": {},
                                      "sample_bundles": []}):

            mock_reg_instance = MagicMock()
            mock_reg.return_value = mock_reg_instance
            audit_type = MagicMock()
            audit_type.code = "progress_vs_nursing"
            mock_reg_instance.get.return_value = audit_type

            precheck_by_patient_census(
                config={"data_source": {"type": "oracle"}},
                mode="inpatient",
                query_date="2026-06-05",
                dept_filter=["020103"],
                audit_type_codes=["progress_vs_nursing"],
                limit_patients=2,
            )

            assert len(bundle_called) == 1, "load_patient_bundles should be called for inpatient progress_vs_nursing"
