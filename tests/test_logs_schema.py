from app.schemas import PushLogItem


def test_push_log_item_accepts_none_severity_and_alert_level():
    payload = {
        "id": 1,
        "push_time": "2026-04-05T00:00:00",
        "trigger_type": "manual",
        "query_date": "2026-04-05",
        "patient_id": "p001",
        "patient_name": "张三",
        "dept": "耳鼻喉科",
        "audit_type_code": None,
        "audit_type_name": None,
        "status": "success",
        "inconsistency": 0,
        "severity": None,
        "risk_score": 0,
        "elapsed_ms": 100,
        "retry_count": 0,
        "pushed_flag": 1,
        "reviewed_flag": 0,
        "reviewed_by": None,
        "manual_override": 0,
        "skip_reason": None,
        "error_msg": None,
        "alert_level": None,
    }

    item = PushLogItem.model_validate(payload)
    assert item.severity == ""
    assert item.alert_level == ""
    assert item.error_msg == ""
    assert item.reviewed_by == ""
    assert item.audit_type_code == ""
    assert item.audit_type_name == ""
    assert item.qc_usable is False
    assert item.transport_success is False


def test_push_log_item_accepts_qc_usable_derived_fields():
    payload = {
        "id": 2,
        "push_time": "2026-07-14T00:00:00",
        "trigger_type": "auto",
        "query_date": "2026-07-14",
        "patient_id": "p002",
        "status": "success",
        "inconsistency": 0,
        "risk_score": 0,
        "elapsed_ms": 10,
        "retry_count": 0,
        "parse_status": "failed",
        "transport_success": True,
        "qc_usable": False,
        "qc_display_status": "parse_failed",
        "qc_display_label": "传输成功/解析失败",
    }
    item = PushLogItem.model_validate(payload)
    assert item.transport_success is True
    assert item.qc_usable is False
    assert item.qc_display_label == "传输成功/解析失败"
