from pathlib import Path

from app.services.push_executor import _patient_fingerprint


def test_patient_log_fingerprint_is_stable_and_does_not_reveal_identifier():
    patient_id = "patient-secret-123456"
    first = _patient_fingerprint(patient_id)
    assert first == _patient_fingerprint(patient_id)
    assert len(first) == 12
    assert patient_id not in first


def test_runtime_push_log_templates_do_not_emit_raw_patient_ids():
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "app/services/push_executor.py",
        "app/services/bulk_push_executor.py",
        "app/services/push_async_executor.py",
        "app/services/push_log_supersede.py",
        "app/utils/patient_dept_query.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "patient_id=%s" not in source
        assert "patient_id={patient_id}" not in source
