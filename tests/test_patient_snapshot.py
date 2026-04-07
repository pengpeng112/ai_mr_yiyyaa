from types import SimpleNamespace

from app.services.patient_snapshot import (
    apply_privacy_masking,
    extract_raw_record_sections,
    extract_patient_snapshot,
    normalize_privacy_masking_config,
)


def test_extract_patient_snapshot_from_request_json():
    log = SimpleNamespace(
        patient_name="张三",
        patient_id="P001",
        admission_no="ZY001",
        dept="听觉植入科",
        request_json=(
            '{"patient_info":{"patient_name":"李四","patient_id":"P002","admission_no":"ZY002",'
            '"admission_date":"2026-04-01","discharge_date":"2026-04-06","admission_diagnosis":"入院诊断A",'
            '"is_discharged":"是","admission_dept_name":"入院科A","discharge_dept_name":"出院科B",'
            '"discharge_main_diagnosis":"出院主诊断C","surgery":"手术D","id_card":"110101199001011234",'
            '"address":"北京市朝阳区XX路88号","phone":"13800138000","department":"神经内科"}}'
        ),
    )
    snapshot = extract_patient_snapshot(log)
    assert snapshot["patient_name"] == "李四"
    assert snapshot["patient_id"] == "P002"
    assert snapshot["admission_no"] == "ZY002"
    assert snapshot["dept_name"] == "神经内科"
    assert snapshot["admission_date"] == "2026-04-01"
    assert snapshot["discharge_main_diagnosis"] == "出院主诊断C"
    assert snapshot["id_card"] == "110101199001011234"


def test_privacy_masking_applies_selected_fields():
    data = {
        "patient_name": "张三丰",
        "id_card": "110101199001011234",
        "address": "北京市朝阳区XX路88号",
        "phone": "13800138000",
    }
    cfg = normalize_privacy_masking_config(
        {
            "enabled": True,
            "mask_name": True,
            "mask_id_card": True,
            "mask_address": True,
            "mask_phone": True,
        }
    )
    masked = apply_privacy_masking(data, cfg)
    assert masked["patient_name"] != data["patient_name"]
    assert masked["id_card"].startswith("110101")
    assert masked["id_card"].endswith("1234")
    assert masked["phone"].startswith("138")
    assert masked["phone"].endswith("8000")
    assert "*" in masked["address"]


def test_mask_id_card_handles_short_lengths():
    cfg = normalize_privacy_masking_config({"enabled": True, "mask_id_card": True})

    masked_9 = apply_privacy_masking({"id_card": "123456789"}, cfg)
    masked_10 = apply_privacy_masking({"id_card": "1234567890"}, cfg)

    assert masked_9["id_card"] == "123****89"
    assert masked_10["id_card"] == "123*****90"


def test_extract_raw_record_sections_from_request_json():
    log = SimpleNamespace(
        request_json=(
            '{"medical_documents":[{"document_time":"2026-04-01 08:00:00","document_name":"首次病程记录","signed_doctor":"张医生","content":"病程内容A"}],'
            '"nursing_records":[{"record_time":"2026-04-01 09:00:00","record_type":"护理记录","recorder":"李护士","content":"护理内容B",'
            '"vitals":{"temperature":"36.8","heart_rate_pulse":"80","respiratory_rate":"18"},'
            '"assessment":{"consciousness":"清醒","skin_condition":"正常"},'
            '"supportive_care":{"intake":"500ml","output":"300ml"}}]}'
        ),
    )

    sections = extract_raw_record_sections(log)
    assert "首次病程记录" in sections["medical_documents_text"]
    assert "病程内容A" in sections["medical_documents_text"]
    assert "护理内容B" in sections["nursing_records_text"]
    assert "生命体征" in sections["nursing_records_text"]
