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


def test_lab_exam_export_filters_legacy_progress_nursing_dimensions():
    service = FeedbackExportService(db=None)
    row = _sample_row()
    row["audit_type_code"] = "jyjc_vs_bcnursing"
    row["audit_type_name"] = "检查检验 vs 护理病程"
    row["dimension_items"] = [
        {"dimension": "诊断一致性"},
        {"dimension": "护理级别一致"},
        {"dimension": "检验危急值一致性"},
    ]
    row["dimensions"] = {
        "生命体征一致性": {},
        "检查结果与病程一致性": {},
    }

    columns = service._dimension_columns_for_export([row], "jyjc_vs_bcnursing")
    names = [name for name, _ in columns]

    assert "诊断一致性" not in names
    assert "护理级别一致" not in names
    assert "生命体征一致性" not in names
    assert names == ["检验危急值一致性", "检查结果与病程一致性"]


def test_lab_exam_excludes_legacy_dimensions_from_detail_rows():
    service = FeedbackExportService(db=None)

    assert service._should_exclude_dimension_for_export("诊断一致性", True) is True
    assert service._should_exclude_dimension_for_export("检验危急值一致性", True) is False


def test_progress_vs_nursing_export_keeps_canonical_dimensions():
    service = FeedbackExportService(db=None)

    columns = service._dimension_columns_for_export([], "progress_vs_nursing")
    names = [name for name, _ in columns]

    assert "诊断一致性" in names
    assert "生命体征一致性" in names
    assert "时间线一致性" in names
