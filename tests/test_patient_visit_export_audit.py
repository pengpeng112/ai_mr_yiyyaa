from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.routers import patient_qc


def _request() -> Request:
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


def _admin_user():
    return SimpleNamespace(id=9, username="admin", role_id=1)


def _call_export(**kwargs):
    defaults = dict(
        request=_request(),
        patient_id=None,
        patient_name=None,
        admission_no=None,
        visit_number=None,
        dept=None,
        discharge_dept_name=None,
        severity=None,
        audit_type_code=None,
        status=None,
        date_from=None,
        date_to=None,
        db=object(),
        current_user=_admin_user(),
    )
    defaults.update(kwargs)
    return patient_qc.export_patient_visit_summary(**defaults)


def test_patient_visit_export_success_audits_count(monkeypatch):
    calls = []
    captured = {}

    def fake_export(db, patient_keys=None):
        captured["patient_keys"] = patient_keys
        return b"xlsx", "xlsx", 7

    monkeypatch.setattr(
        patient_qc,
        "query_patient_qc_visit_keys",
        lambda db, filters, current_user=None: {("P1", "1")},
    )
    monkeypatch.setattr(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        fake_export,
    )
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: calls.append(kwargs))

    response = _call_export(severity="high", date_from="2026-08-01", date_to="2026-08-10")

    assert response.body == b"xlsx"
    assert captured["patient_keys"] == {("P1", "1")}
    assert calls[0]["export_type"] == "patient_visit"
    assert calls[0]["export_format"] == "excel"
    assert calls[0]["record_count"] == 7
    assert calls[0]["filter_criteria"]["scope"] == "filtered_all_pages"
    assert calls[0]["filter_criteria"]["source"] == "TEMP_PAT_VISIT_LIST"
    assert calls[0]["filter_criteria"]["severity"] == "high"
    assert calls[0]["filter_criteria"]["date_from"] == "2026-08-01"
    assert calls[0]["filter_criteria"]["date_to"] == "2026-08-10"


@pytest.mark.parametrize("error, status", [(ValueError("bad input"), 400), (RuntimeError("db failed"), 500)])
def test_patient_visit_export_failure_audit_does_not_change_http_error(monkeypatch, error, status):
    calls = []
    monkeypatch.setattr(
        patient_qc,
        "query_patient_qc_visit_keys",
        lambda db, filters, current_user=None: set(),
    )
    monkeypatch.setattr(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        lambda db, patient_keys=None: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(HTTPException) as caught:
        _call_export()

    assert caught.value.status_code == status
    assert calls[0]["status"] == "failed"
    assert calls[0]["record_count"] == 0
    assert calls[0]["filter_criteria"]["scope"] == "filtered_all_pages"


def test_patient_visit_export_business_error_survives_audit_error(monkeypatch):
    monkeypatch.setattr(
        patient_qc,
        "query_patient_qc_visit_keys",
        lambda db, filters, current_user=None: set(),
    )
    monkeypatch.setattr(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        lambda db, patient_keys=None: (_ for _ in ()).throw(ValueError("bad input")),
    )
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("audit down")))

    with pytest.raises(HTTPException) as caught:
        _call_export()
    assert caught.value.status_code == 400


def test_patient_visit_export_generic_error_is_audited(monkeypatch):
    calls = []
    monkeypatch.setattr(
        patient_qc,
        "query_patient_qc_visit_keys",
        lambda db, filters, current_user=None: set(),
    )
    monkeypatch.setattr(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        lambda db, patient_keys=None: (_ for _ in ()).throw(Exception("unexpected internal detail")),
    )
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(HTTPException) as caught:
        _call_export()
    assert caught.value.status_code == 500
    assert caught.value.detail == "患者就诊数据导出失败"
    assert "unexpected internal detail" not in caught.value.detail
    assert calls[0]["status"] == "failed"
    assert calls[0]["record_count"] == 0


def test_patient_visit_export_masks_sensitive_filters_in_audit(monkeypatch):
    calls = []
    monkeypatch.setattr(
        patient_qc,
        "query_patient_qc_visit_keys",
        lambda db, filters, current_user=None: {("P9", "2")},
    )
    monkeypatch.setattr(
        "app.services.patient_visit_export_service.export_patient_visit_summary",
        lambda db, patient_keys=None: (b"x", "xlsx", 1),
    )
    monkeypatch.setattr(patient_qc, "record_export_audit", lambda **kwargs: calls.append(kwargs))

    _call_export(
        patient_id="SECRET_PID",
        patient_name="真实姓名",
        admission_no="ADM-99",
        visit_number="3",
        dept="心内科",
    )
    criteria = calls[0]["filter_criteria"]
    assert criteria["patient_id"] == "已提供"
    assert criteria["patient_name"] == "已提供"
    assert criteria["admission_no"] == "已提供"
    assert criteria["visit_number"] == "已提供"
    assert criteria["dept"] == "心内科"
    blob = str(criteria)
    assert "SECRET_PID" not in blob
    assert "真实姓名" not in blob
    assert "ADM-99" not in blob
