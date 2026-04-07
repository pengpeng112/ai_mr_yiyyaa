from io import BytesIO

from openpyxl import load_workbook

from app.services.export_service import FeedbackExportService


def _sample_row():
    return {
        "log_id": 1,
        "patient_name": "张三",
        "patient_id": "P001",
        "admission_no": "ZY001",
        "dept_name": "神经内科",
        "admission_date": "2026-04-01",
        "discharge_date": "2026-04-06",
        "admission_diagnosis": "入院诊断A",
        "is_discharged": "是",
        "admission_dept_name": "入院科A",
        "discharge_dept_name": "出院科B",
        "discharge_main_diagnosis": "出院主诊断C",
        "surgery": "手术D",
        "id_card": "110101199001011234",
        "address": "北京市朝阳区XX路88号",
        "phone": "13800138000",
        "feedback_status": "待处理",
        "severity": "高",
        "query_date": "2026-04-06",
        "push_time": "2026-04-06 10:00:00",
        "issue_count": 2,
        "overall_conclusion": "存在不一致",
        "overall_qc_summary": "摘要",
        "focus_items": "诊断一致性",
        "mr_text": "原始病历",
        "dimensions_text": "",
        "dimensions": {},
        "feedback_text": "请复核",
        "assigned_to": "李医生",
        "created_by": "王主任",
        "history_text": "pending -> acknowledged",
    }


def test_export_to_csv_uses_unmasked_rows(monkeypatch):
    service = FeedbackExportService(db=None)
    called = []

    def fake_build_case_rows(**kwargs):
        called.append(kwargs["mask_sensitive"])
        return [_sample_row()]

    monkeypatch.setattr(service, "_build_case_rows", fake_build_case_rows)

    data = service.export_to_csv("admin", None)

    assert called == [False]
    assert "110101199001011234" in data.decode("utf-8-sig")


def test_export_to_excel_returns_real_xlsx(monkeypatch):
    service = FeedbackExportService(db=None)
    called = []

    def fake_build_case_rows(**kwargs):
        called.append(kwargs["mask_sensitive"])
        row = _sample_row()
        row["patient_name"] = "张*"
        row["id_card"] = "110101********1234"
        row["address"] = "北京市朝阳******"
        row["phone"] = "138****8000"
        return [row]

    monkeypatch.setattr(service, "_build_case_rows", fake_build_case_rows)

    data = service.export_to_excel("admin", None)

    assert called == [True]
    assert data[:2] == b"PK"

    workbook = load_workbook(BytesIO(data))
    sheet = workbook.active
    assert sheet["B2"].value == "张*"
    assert sheet["D2"].value == "110101********1234"
    assert sheet["E2"].value == "北京市朝阳******"
    assert sheet["F2"].value == "138****8000"
