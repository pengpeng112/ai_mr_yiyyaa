"""W2：契约校验器抛异常不得当成合格或历史兼容。

异常路径必须写入 contract_valid=False，并保留 validator_error:<ExcType>。
None 只留给本次根本没跑校验的结果。False 经 W1 守卫不替代旧当前。
"""

from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, _push_log_current_identity_index_ddl
from app.models import AuditDimensionResult, PushLog
from app.services.push_log_supersede import attach_success_push_log_as_current


SOURCE_KEY = "mode::daily_increment::progress_vs_nursing::SYN-W2::1"
PATIENT_ID = "SYN-W2"


def _boom(*_args, **_kwargs):
    raise RuntimeError("synthetic-validator-fault")


def _parsed_ready():
    return {
        "parse_success": True,
        "dimensions": [
            {
                "dimension": "诊断一致性",
                "dimension_code": "diagnosis_consistency",
                "status": "pass",
                "severity": "low",
            }
        ],
        "overall_conclusion": "已有结论",
        "inconsistency": False,
        "severity": "low",
        "focus_items": [],
        "parse_warning": "",
    }


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(_push_log_current_identity_index_ddl("push_log", "sqlite")))
    return sessionmaker(bind=engine)()


def test_post_process_validator_exception_is_not_valid(monkeypatch):
    from app.services.dify_schema_parser import _post_process_result
    import app.services.result_contract_validator as validator

    monkeypatch.setattr(validator, "validate_result_contract", _boom)
    result = _parsed_ready()
    _post_process_result(result, audit_type_code="progress_vs_nursing")
    assert result["contract_valid"] is False
    assert result["contract_errors"] == ["validator_error:RuntimeError"]


def test_pusher_validator_exception_is_false_not_none(monkeypatch):
    from app import dify_pusher
    import app.services.result_contract_validator as validator

    monkeypatch.setattr(validator, "validate_result_contract", _boom)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "workflow_run_id": "wf-w2",
                "task_id": "task-w2",
                "data": {"outputs": {"aa": "{}"}},
            }

    monkeypatch.setattr(dify_pusher.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr(dify_pusher, "parse_dify_structured_output", lambda *a, **k: _parsed_ready())

    result = dify_pusher.push_to_dify(
        "synthetic-mr",
        {"base_url": "http://dify.invalid/v1", "api_key": "test-key", "workflow_output_key": "aa"},
        PATIENT_ID,
        audit_type_code="progress_vs_nursing",
    )
    assert result["status"] == "success"
    assert result["contract_valid"] is False
    assert result["contract_errors"] == "validator_error:RuntimeError"
    assert "synthetic-validator-fault" not in str(result["contract_errors"])


def test_validation_not_run_stays_none(monkeypatch):
    """没跑校验（无维度）仍为 None，不得把历史兼容语义写成失败。"""
    from app import dify_pusher

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"workflow_run_id": "wf-w2b", "task_id": "task-w2b", "data": {"outputs": {"aa": "{}"}}}

    monkeypatch.setattr(dify_pusher.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr(
        dify_pusher,
        "parse_dify_structured_output",
        lambda *a, **k: {"parse_success": False, "dimensions": [], "inconsistency": False, "severity": ""},
    )
    result = dify_pusher.push_to_dify(
        "synthetic-mr",
        {"base_url": "http://dify.invalid/v1", "api_key": "test-key"},
        PATIENT_ID,
    )
    assert result["contract_valid"] is None
    assert result["contract_errors"] in ("", None, [])


def test_validator_fault_does_not_replace_old_current(monkeypatch):
    from app import dify_pusher
    import app.services.result_contract_validator as validator

    monkeypatch.setattr(validator, "validate_result_contract", _boom)

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"workflow_run_id": "wf-w2c", "task_id": "task-w2c", "data": {"outputs": {"aa": "{}"}}}

    monkeypatch.setattr(dify_pusher.requests, "post", lambda *a, **k: Response())
    monkeypatch.setattr(dify_pusher, "parse_dify_structured_output", lambda *a, **k: _parsed_ready())
    pushed = dify_pusher.push_to_dify(
        "synthetic-mr",
        {"base_url": "http://dify.invalid/v1", "api_key": "test-key"},
        PATIENT_ID,
        audit_type_code="progress_vs_nursing",
    )
    assert pushed["contract_valid"] is False

    db = _make_db()
    try:
        old = PushLog(
            push_time=datetime.now(),
            trigger_type="auto",
            query_date="2026-10-11",
            patient_id=PATIENT_ID,
            visit_number="1",
            audit_type_code="progress_vs_nursing",
            audit_run_mode="daily_increment",
            status="success",
            pushed_flag=1,
            parse_status="success",
            source_record_key=SOURCE_KEY,
            contract_valid=True,
        )
        db.add(old)
        db.flush()
        db.add(
            AuditDimensionResult(
                push_log_id=old.id,
                dimension_code="diagnosis_consistency",
                dimension="诊断一致性",
                status="❌",
                severity="medium",
            )
        )
        db.flush()
        new_log = PushLog(
            push_time=datetime.now(),
            trigger_type="manual",
            query_date="2026-10-11",
            patient_id=PATIENT_ID,
            visit_number="1",
            audit_type_code="progress_vs_nursing",
            audit_run_mode="daily_increment",
            status="success",
            pushed_flag=1,
            parse_status="success",
            source_record_key=SOURCE_KEY,
            contract_valid=pushed["contract_valid"],
            contract_errors=str(pushed["contract_errors"] or ""),
        )
        assert attach_success_push_log_as_current(db, new_log) == 0
        assert old.superseded_by is None
        assert new_log.superseded_by == old.id
        assert db.query(AuditDimensionResult).filter(AuditDimensionResult.push_log_id == old.id).count() == 1
    finally:
        db.close()
