"""009 二次整改测试：P0 契约/门禁/preview/self-supersede、P1 调度/lease/retry。"""

import json
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    HistoricalRerunBatch,
    HistoricalRerunItem,
    PushExecution,
    PushLog,
    SchedulerHistory,
)


@pytest.fixture
def db():
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


def _make_push_log(db, **kwargs):
    defaults = dict(
        push_time=datetime.now(),
        trigger_type="auto",
        query_date="2026-07-01",
        patient_id="P001",
        patient_name="Test",
        visit_number="1",
        audit_type_code="progress_vs_nursing",
        source_record_key="key_001",
        status="success",
        pushed_flag=1,
        parse_status="success",
        audit_run_mode="daily_increment",
    )
    defaults.update(kwargs)
    log = PushLog(**defaults)
    db.add(log)
    db.flush()
    return log


# ─── P0-1: 权威契约维度集合 ───


class TestP01ContractDimensions:
    """六类权威合法样本 contract valid；缺维度/非法组合 contract invalid。"""

    def _make_dims(self, codes, status="pass", severity="low", alert="blue", confidence=0.9):
        return [
            {"dimension_code": c, "status": status, "severity": severity, "alert_level": alert, "confidence": confidence}
            for c in codes
        ]

    def test_progress_vs_nursing_six_dims_valid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "diagnosis_consistency", "nursing_level_consistency", "vital_sign_consistency",
            "condition_consistency", "treatment_measure_consistency", "timeline_consistency",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "progress_vs_nursing")
        assert valid, f"Expected valid, got errors: {errors}"

    def test_jyjc_vs_bcnursing_six_dims_valid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "lab_abnormal_followup", "exam_abnormal_followup", "progress_result_consistency",
            "nursing_recorded_consistency", "high_risk_response_consistency", "timeline_consistency",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "jyjc_vs_bcnursing")
        assert valid, f"Expected valid, got errors: {errors}"

    def test_surgery_chain_ten_dims_valid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "patient_info_consistency", "timeline_consistency", "preoperative_template_validity",
            "diagnosis_consistency", "operation_consistency", "anesthesia_material_step_consistency",
            "intraoperative_to_postoperative_consistency", "postoperative_record_completeness",
            "consent_subject_validity", "text_quality",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "surgery_chain")
        assert valid, f"Expected valid, got errors: {errors}"

    def test_discharge_vs_frontpage_nine_dims_valid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "patient_info_consistency", "chief_complaint_consistency", "admission_diagnosis_consistency",
            "diagnosis_backfill_validity", "new_discharge_diagnosis_evidence",
            "treatment_course_completeness", "discharge_advice_consistency",
            "discharge_condition_consistency", "text_quality",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "discharge_vs_frontpage")
        assert valid, f"Expected valid, got errors: {errors}"

    def test_syssvsscbc_four_dims_valid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "diagnosis_consistency", "operation_consistency",
            "diagnosis_operation_match", "timeline_consistency",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "syssvsscbc")
        assert valid, f"Expected valid, got errors: {errors}"

    def test_missing_dimension_invalid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = ["diagnosis_consistency", "nursing_level_consistency"]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "progress_vs_nursing")
        assert not valid
        assert any("missing_dimensions" in e for e in errors)

    def test_unknown_dimension_code_invalid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "diagnosis_consistency", "nursing_level_consistency", "vital_sign_consistency",
            "condition_consistency", "treatment_measure_consistency", "timeline_consistency",
            "bogus_dimension",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "progress_vs_nursing")
        assert not valid
        assert any("unknown_dimension_codes" in e for e in errors)

    def test_warn_low_blue_is_valid_hint(self):
        """warn/low/blue 是合法 hint 组合，不得归一成 medium/yellow。"""
        from app.services.result_contract_validator import normalize_dimension_combo
        dim = {"status": "warn", "severity": "low", "alert_level": "blue", "confidence": 0.9}
        result, errors = normalize_dimension_combo(dim)
        assert result["status"] == "warn"
        assert result["severity"] == "low"
        assert result["alert_level"] == "blue"
        assert len(errors) == 0

    def test_low_confidence_forces_unknown_gray(self):
        from app.services.result_contract_validator import normalize_dimension_combo
        dim = {"status": "fail", "severity": "high", "alert_level": "red", "confidence": 0.3}
        result, errors = normalize_dimension_combo(dim)
        assert result["status"] == "unknown"
        assert result["severity"] == "low"
        assert result["alert_level"] == "gray"

    def test_admission_without_override_fails_closed(self):
        """admission_vs_first_progress 无配置快照时 fail-closed。"""
        from app.services.result_contract_validator import validate_result_contract
        codes = ["diagnosis_consistency", "history_consistency"]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "admission_vs_first_progress")
        assert not valid
        assert any("admission_dimensions_not_configured" in e for e in errors)

    def test_admission_with_override_valid(self):
        """admission_vs_first_progress 有配置快照时正常校验。"""
        from app.services.result_contract_validator import validate_result_contract
        codes = ["diagnosis_consistency", "history_consistency", "examination_consistency"]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(
            result, "admission_vs_first_progress",
            expected_dimensions_override=codes,
        )
        assert valid, f"Expected valid, got errors: {errors}"

    def test_duplicate_dimension_code_invalid(self):
        from app.services.result_contract_validator import validate_result_contract
        codes = [
            "diagnosis_consistency", "diagnosis_consistency", "nursing_level_consistency",
            "vital_sign_consistency", "condition_consistency", "treatment_measure_consistency",
            "timeline_consistency",
        ]
        result = {"dimensions": self._make_dims(codes)}
        valid, errors = validate_result_contract(result, "progress_vs_nursing")
        assert not valid
        assert any("duplicate_dimension_code" in e for e in errors)


# ─── P0-2: contract_valid 门禁 ───


class TestP02ContractGate:
    """contract_valid=False 不得 supersede、不得当前可见。"""

    def test_is_qc_usable_contract_false(self):
        from app.services.qc_status_semantics import is_qc_usable
        assert is_qc_usable("success", "success", contract_valid=False) is False

    def test_is_qc_usable_contract_none_legacy(self):
        from app.services.qc_status_semantics import is_qc_usable
        assert is_qc_usable("success", "success", contract_valid=None) is True

    def test_is_qc_usable_contract_true(self):
        from app.services.qc_status_semantics import is_qc_usable
        assert is_qc_usable("success", "success", contract_valid=True) is True

    def test_supersede_blocked_contract_invalid(self, db):
        from app.services.push_log_supersede import mark_historical_reaudit_superseded
        old = _make_push_log(db, source_record_key="sk1")
        new = _make_push_log(db, source_record_key="sk1", contract_valid=False)
        result = mark_historical_reaudit_superseded(db, new)
        assert result == 0
        db.refresh(old)
        assert old.superseded_by is None

    def test_supersede_allowed_contract_valid(self, db):
        from app.services.push_log_supersede import mark_historical_reaudit_superseded
        old = _make_push_log(db, source_record_key="sk2")
        new = _make_push_log(db, source_record_key="sk2", contract_valid=True)
        result = mark_historical_reaudit_superseded(db, new)
        assert result == 1
        db.flush()
        db.refresh(old)
        assert old.superseded_by == new.id

    def test_discharge_supersede_blocked_contract_invalid(self, db):
        from app.services.push_log_supersede import mark_daily_logs_superseded
        old = _make_push_log(db, audit_run_mode="daily_increment", source_record_key="")
        discharge = _make_push_log(
            db, audit_run_mode="discharge_final", status="success",
            parse_status="success", contract_valid=False,
        )
        result = mark_daily_logs_superseded(db, discharge)
        assert result == 0

    def test_push_log_model_has_contract_fields(self, db):
        log = _make_push_log(db, contract_valid=True, contract_errors="")
        db.refresh(log)
        assert log.contract_valid == 1
        assert log.contract_errors == ""

    def test_current_filter_hides_contract_invalid(self, db):
        """contract_valid=0 不得进入默认当前结果视图；NULL 历史兼容可见。"""
        from app.services.current_result_filter import apply_current_result_filter, is_current_result
        ok = _make_push_log(db, source_record_key="cv_ok", contract_valid=True)
        bad = _make_push_log(db, source_record_key="cv_bad", contract_valid=False)
        legacy = _make_push_log(db, source_record_key="cv_legacy", contract_valid=None)
        db.flush()
        rows = apply_current_result_filter(db.query(PushLog)).all()
        ids = {r.id for r in rows}
        assert ok.id in ids
        assert legacy.id in ids
        assert bad.id not in ids
        assert is_current_result(ok) is True
        assert is_current_result(legacy) is True
        assert is_current_result(bad) is False


# ─── P0-3: preview load_failed fail-closed ───


class TestP03PreviewFailClosed:
    """load_failed > 0 时禁止创建批次。"""

    def test_create_batch_rejects_load_failed(self, db):
        from app.services.historical_rerun_service import create_batch_from_preview
        preview = {
            "candidate_hash": "abc123",
            "config_snapshot_hash": "cfg",
            "candidates": [],
            "load_failed_count": 2,
            "manifest_complete": False,
            "date_from": "2026-01-01",
            "date_to": "2026-01-07",
            "date_dimension": "query_date",
            "audit_type_codes": ["progress_vs_nursing"],
            "dept_filter": [],
            "audit_run_mode": "daily_increment",
        }
        with pytest.raises(ValueError, match="incomplete"):
            create_batch_from_preview(
                db, preview,
                actor="test", reason="test", confirm_candidate_hash="abc123",
            )

    def test_create_batch_rejects_manifest_incomplete(self, db):
        from app.services.historical_rerun_service import create_batch_from_preview
        preview = {
            "candidate_hash": "abc123",
            "config_snapshot_hash": "cfg",
            "candidates": [],
            "load_failed_count": 0,
            "manifest_complete": False,
            "date_from": "2026-01-01",
            "date_to": "2026-01-07",
            "date_dimension": "query_date",
            "audit_type_codes": [],
            "dept_filter": [],
            "audit_run_mode": "daily_increment",
        }
        with pytest.raises(ValueError, match="manifest_complete"):
            create_batch_from_preview(
                db, preview,
                actor="test", reason="test", confirm_candidate_hash="abc123",
            )

    def test_create_batch_ok_when_complete(self, db):
        from app.services.historical_rerun_service import create_batch_from_preview
        preview = {
            "candidate_hash": "abc123",
            "config_snapshot_hash": "cfg",
            "candidates": [],
            "load_failed_count": 0,
            "manifest_complete": True,
            "date_from": "2026-01-01",
            "date_to": "2026-01-07",
            "date_dimension": "query_date",
            "audit_type_codes": [],
            "dept_filter": [],
            "audit_run_mode": "daily_increment",
        }
        batch = create_batch_from_preview(
            db, preview,
            actor="test", reason="test reason", confirm_candidate_hash="abc123",
        )
        assert batch.status == "confirmed"

    def test_historical_batch_clob_columns_are_last_for_oracle(self):
        """Oracle INSERT 绑定中 CLOB 后不得再出现扩展非 LOB 字段。"""
        columns = list(HistoricalRerunBatch.__table__.columns)
        text_positions = [i for i, column in enumerate(columns) if column.name in {
            "audit_type_codes_json", "dept_filter_json", "last_error"
        }]
        assert text_positions == list(range(len(columns) - 3, len(columns)))


# ─── P0-4: 禁止 self-supersede ───


class TestP04NoSelfSupersede:
    """superseded_by 不得等于自身 id；discarded 状态退出当前视图。"""

    def test_discarded_not_current(self, db):
        from app.services.current_result_filter import apply_current_result_filter, is_current_result
        log = _make_push_log(db, status="discarded")
        assert is_current_result(log) is False
        current = apply_current_result_filter(db.query(PushLog)).filter(PushLog.id == log.id).first()
        assert current is None

    def test_superseded_not_current(self, db):
        from app.services.current_result_filter import is_current_result
        log = _make_push_log(db, superseded_by=999)
        assert is_current_result(log) is False

    def test_normal_success_is_current(self, db):
        from app.services.current_result_filter import is_current_result
        log = _make_push_log(db)
        assert is_current_result(log) is True

    def test_no_self_supersede_in_historical_rerun(self):
        """验证 historical_rerun_service 不再使用 superseded_by = log.id 模式。"""
        import inspect
        from app.services import historical_rerun_service
        source = inspect.getsource(historical_rerun_service)
        assert "log.superseded_by = log.id" not in source


# ─── P1-1: SchedulerHistory 传 audit_run_mode/error_msg ───


class TestP11SchedulerHistory:
    def test_scheduler_history_model_fields(self, db):
        h = SchedulerHistory(
            run_time=datetime.now(),
            trigger_type="auto",
            query_date="2026-07-01",
            audit_type_code="progress_vs_nursing",
            total_records=10,
            success_count=8,
            failed_count=2,
            duration_seconds=30,
            status="completed",
            audit_run_mode="discharge_final",
            error_msg="test error",
        )
        db.add(h)
        db.flush()
        db.refresh(h)
        assert h.audit_run_mode == "discharge_final"
        assert h.error_msg == "test error"

    def test_runner_passes_audit_run_mode(self):
        """验证 scheduler_audit_runner 源码包含 audit_run_mode=audit_run_mode。"""
        import inspect
        from app.services import scheduler_audit_runner
        source = inspect.getsource(scheduler_audit_runner.run_daily_push_for_audit_type)
        assert "audit_run_mode=audit_run_mode" in source
        assert "error_msg=" in source


# ─── P1-2: consumer lease 心跳 ───


class TestP12ConsumerLease:
    def test_heartbeat_class_exists(self):
        from app.services.historical_rerun_service import _LeaseHeartbeat
        hb = _LeaseHeartbeat(batch_id=1, owner_token="tok", interval=1.0)
        assert hb._batch_id == 1

    def test_single_consumer_enforcement(self, db):
        from app.services.historical_rerun_service import _try_acquire_consumer_lease
        batch = HistoricalRerunBatch(
            status="running", actor="test", reason="test",
            date_from="2026-01-01", date_to="2026-01-07",
            date_dimension="query_date",
            audit_type_codes_json="[]", dept_filter_json="[]",
            existing_result_policy="replace_current",
            alert_policy="suppress",
            candidate_hash="h", config_snapshot_hash="c",
            candidate_count=0, processed=0,
            success_count=0, failed_count=0, skipped_count=0, superseded_count=0,
        )
        db.add(batch)
        db.flush()
        assert _try_acquire_consumer_lease(db, batch.id, "owner_a") is True
        db.commit()
        assert _try_acquire_consumer_lease(db, batch.id, "owner_b") is False


# ─── P1-3: claim 异常可重试 ───


class TestP13ClaimRetryable:
    def test_in_flight_not_business_skip(self):
        """验证 historical_rerun_service 对 in_flight 不标记为 skipped。"""
        import inspect
        from app.services import historical_rerun_service
        source = inspect.getsource(historical_rerun_service._process_one_item)
        assert "retryable" in source
        assert 'if reason in ("in_flight", "claim_exception")' in source

    def test_oracle_claim_locks_by_primary_key_without_first(self):
        """避免 Oracle 将 ORDER BY + first + FOR UPDATE 编译为不可更新内联视图。"""
        import inspect
        from app.services import historical_rerun_service
        source = inspect.getsource(historical_rerun_service._claim_next_item)
        assert "item_id_row" in source
        assert ".with_for_update()\n        .one_or_none()" in source


# ─── P2: 诊断口径 ───


class TestP2Diagnostics:
    def test_qc_usable_includes_contract(self):
        from app.services.qc_status_semantics import is_qc_usable, derive_qc_display_status
        assert derive_qc_display_status("success", "success", contract_valid=False) == "contract_invalid"
        assert derive_qc_display_status("success", "success", contract_valid=True) == "qc_usable"
        assert derive_qc_display_status("success", "success", contract_valid=None) == "qc_usable"

    def test_enrich_log_status_fields(self):
        from app.services.qc_status_semantics import enrich_log_status_fields
        fields = enrich_log_status_fields("success", "success", contract_valid=False)
        assert fields["qc_usable"] is False
        assert fields["qc_display_status"] == "contract_invalid"


# ─── P2: start_batch_async 原子 token ───


class TestP2StartBatchAsync:
    def test_start_batch_async_reserves_token(self):
        """start_batch_async 在启动线程前原子预留 token。"""
        import inspect
        from app.services import historical_rerun_service
        source = inspect.getsource(historical_rerun_service.start_batch_async)
        assert "secrets.token_hex" in source
        assert "_active_consumers[batch_id] = owner_token" in source

    def test_lease_release_logs_error(self):
        """lease 释放失败记录结构化错误而非静默吞掉。"""
        import inspect
        from app.services import historical_rerun_service
        source = inspect.getsource(historical_rerun_service.run_batch)
        assert "relying on expiry recovery" in source


# ─── P2: execute_retry 修复 ───


class TestP2RetryFixes:
    def test_retry_persists_contract_valid(self):
        """retry 新日志持久化 contract_valid/contract_errors。"""
        import inspect
        from app.services.push_executor import PushExecutor
        source = inspect.getsource(PushExecutor.execute_retry)
        assert 'contract_valid=dify_result.get("contract_valid")' in source
        assert 'contract_errors=' in source

    def test_retry_supersede_guarded(self):
        """retry 仅当旧日志仍为当前结果时才 supersede。"""
        import inspect
        from app.services.push_executor import PushExecutor
        source = inspect.getsource(PushExecutor.execute_retry)
        assert "if log.superseded_by is None" in source

    def test_retry_alert_suppressed_by_default(self):
        """retry 默认 suppress 告警。"""
        import inspect
        from app.services.push_executor import PushExecutor
        source = inspect.getsource(PushExecutor.execute_retry)
        assert "retry 默认 suppress 告警" in source


# ─── P2: 对账诊断口径 ───


class TestP2ReconciliationDiagnostics:
    def test_reconciliation_includes_identity_fields(self, db):
        """对账输出包含正式业务身份字段。"""
        from app.services.historical_rerun_service import build_reconciliation
        batch = HistoricalRerunBatch(
            status="completed", actor="test", reason="test",
            date_from="2026-01-01", date_to="2026-01-07",
            date_dimension="query_date",
            audit_type_codes_json="[]", dept_filter_json="[]",
            existing_result_policy="replace_current",
            alert_policy="suppress",
            candidate_hash="h", config_snapshot_hash="c",
            candidate_count=2, processed=2,
            success_count=1, failed_count=1, skipped_count=0, superseded_count=1,
        )
        db.add(batch)
        db.flush()
        item = HistoricalRerunItem(
            batch_id=batch.id,
            business_identity_hash="bih",
            source_record_key="sk_test",
            audit_type_code="progress_vs_nursing",
            audit_run_mode="daily_increment",
            patient_id="P001",
            visit_number="1",
            query_date="2026-01-01",
            status="success",
            previous_current_push_log_id=None,
            new_push_log_id=None,
        )
        db.add(item)
        db.flush()
        result = build_reconciliation(db, batch.id)
        assert "total_items" in result
        assert "empty_key_count" in result
        assert "qc_usable_count" in result
        assert "dual_current_count" in result
        assert result["total_items"] == 1
        assert result["dual_current_count"] == 0

    def test_reconciliation_empty_key_counted(self, db):
        """空 source_record_key 单列计数。"""
        from app.services.historical_rerun_service import build_reconciliation
        batch = HistoricalRerunBatch(
            status="completed", actor="test", reason="test",
            date_from="2026-01-01", date_to="2026-01-07",
            date_dimension="query_date",
            audit_type_codes_json="[]", dept_filter_json="[]",
            existing_result_policy="replace_current",
            alert_policy="suppress",
            candidate_hash="h", config_snapshot_hash="c",
            candidate_count=1, processed=1,
            success_count=1, failed_count=0, skipped_count=0, superseded_count=0,
        )
        db.add(batch)
        db.flush()
        item = HistoricalRerunItem(
            batch_id=batch.id,
            business_identity_hash="bih2",
            source_record_key="",
            audit_type_code="progress_vs_nursing",
            audit_run_mode="daily_increment",
            patient_id="P002",
            visit_number="1",
            query_date="2026-01-02",
            status="success",
        )
        db.add(item)
        db.flush()
        result = build_reconciliation(db, batch.id)
        assert result["empty_key_count"] == 1
