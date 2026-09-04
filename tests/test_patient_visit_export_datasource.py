"""患者就诊导出数据源前置校验与 RuntimeError 日志测试（037 RP-F / P-006 / U-5）。"""
import json
from datetime import datetime
from unittest import mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import PushLog, User
from app.routers import patient_qc
from app.services import patient_visit_export_service as export_svc
from app.auth import hash_password


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _admin(db):
    from app.models import Role
    role = db.query(Role).filter(Role.name == "admin").first()
    if not role:
        role = Role(name="admin", description="")
        db.add(role)
        db.flush()
    u = User(username="admin_export", password_hash=hash_password("x"), full_name="管理员", role_id=role.id)
    db.add(u)
    db.commit()
    return u


def _make_request():
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/patient-qc/export/patient-visit-summary",
        "headers": [(b"user-agent", b"focused-test")],
        "client": ("127.0.0.1", 1234),
        "query_string": b"",
        "scheme": "http",
        "server": ("test", 80),
        "asgi": {"version": "3.0"},
    })


def _add_log(db, patient_id="P100"):
    log = PushLog(
        patient_id=patient_id, visit_number="1", dept="内科", patient_name="张三",
        admission_no="A100", status="success", severity="high", trigger_type="manual",
        query_date="2026-08-01", push_time=datetime(2026, 8, 5, 10, 0, 0),
        inconsistency=0, risk_score=0, elapsed_ms=0, retry_count=0, contract_valid=1,
        audit_type_code="progress_vs_nursing", request_json="",
    )
    db.add(log)
    db.commit()
    return log


def test_t1_fixture_with_nonempty_keys_raises_value_error(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    cfg = {"data_source": {"type": "fixture"}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr("app.config.load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))

    with mock.patch("app.oracle_client.get_oracle_connection") as mock_conn:
        with pytest.raises(ValueError, match="Oracle"):
            export_svc.export_patient_visit_summary(object(), patient_keys={("P100", "1")})
        mock_conn.assert_not_called()  # 不得触碰 Oracle 驱动


def test_t3_empty_keys_still_returns_header_workbook(monkeypatch, tmp_path):
    """空筛选命中 = 200 表头文件（031 T1-0 契约），数据源检查不阻塞。"""
    cfg = {"data_source": {"type": "fixture"}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr("app.config.load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))
    xlsx_bytes, fmt, count = export_svc.export_patient_visit_summary(object(), patient_keys=set())
    assert fmt == "xlsx"
    assert count == 0
    assert isinstance(xlsx_bytes, bytes) and xlsx_bytes


def test_t2_route_fixture_returns_400_with_failed_audit(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_ISOLATED_MODE", "true")
    db = _make_db()
    admin = _admin(db)
    _add_log(db)

    cfg = {"data_source": {"type": "fixture"}}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr("app.config.load_config", lambda: json.loads(cfg_file.read_text(encoding="utf-8")))

    audit_calls = []
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: audit_calls.append(kwargs))

    with mock.patch("app.oracle_client.get_oracle_connection") as mock_conn:
        with pytest.raises(HTTPException) as exc_info:
            patient_qc.export_patient_visit_summary(
                request=_make_request(),
                patient_id="P100", patient_name=None, admission_no=None, visit_number=None,
                dept=None, discharge_dept_name=None, severity=None, audit_type_code=None,
                status=None, date_from=None, date_to=None,
                current_user=admin, db=db,
            )
        assert exc_info.value.status_code == 400
        mock_conn.assert_not_called()
    failed = [c for c in audit_calls if c.get("status") == "failed"]
    assert failed, "失败审计必须落档"


def test_t4_runtime_error_logs_traceback(monkeypatch):
    db = _make_db()
    admin = _admin(db)

    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: None)
    with mock.patch(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        side_effect=RuntimeError("Oracle client is not available"),
    ):
        with mock.patch.object(patient_qc.logger, "error") as mock_log:
            with pytest.raises(HTTPException) as exc_info:
                patient_qc.export_patient_visit_summary(
                    request=_make_request(),
                    patient_id=None, patient_name=None, admission_no=None, visit_number=None,
                    dept=None, discharge_dept_name=None, severity=None, audit_type_code=None,
                    status=None, date_from=None, date_to=None,
                    current_user=admin, db=db,
                )
            assert exc_info.value.status_code == 500

    called_with_exc_info = [
        c for c in mock_log.call_args_list
        if c.kwargs.get("exc_info") is True and "RuntimeError" in str(c.args[0])
    ]
    assert called_with_exc_info, (
        f"RuntimeError 日志必须带 exc_info=True，实际调用: {mock_log.call_args_list}"
    )
