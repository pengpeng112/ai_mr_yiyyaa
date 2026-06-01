"""Tests for lab_exam_progress_nursing payload builder (Task 9)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app.schemas import AuditTypeConfig
from app.services.lab_exam_payload_builder import _extract_lab_exam_event_specs, _has_abnormal_findings
from app.services.payload_composer import compose
from fixtures.audit_source_samples import scenario_cross_day_progress, scenario_same_day_complete


def _build_lab_exam_audit_type(builder: str = "lab_exam_progress_nursing") -> AuditTypeConfig:
    return AuditTypeConfig.model_validate(
        {
            "code": "lab_exam_vs_progress_nursing",
            "name": "检验检查 vs 病程护理",
            "sources": {
                "lab": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "patient_id", "visit_number": "visit_number"}},
                "exam": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "patient_id", "visit_number": "visit_number"}},
                "progress": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "patient_id", "visit_number": "visit_number"}},
                "nursing": {"type": "sql", "query_sql": "SELECT 1", "field_mapping": {"patient_id": "patient_id", "visit_number": "visit_number"}},
            },
            "group_key": ["patient_id", "visit_number", "audit_date"],
            "payload": {
                "builder": builder,
                "max_lab_items": 30,
                "max_exam_reports": 10,
                "progress_followup_days": 1,
                "include_normal_summary": False,
            },
            "dify": {"base_url": "http://example.com/v1"},
        }
    )


def _build_bundle(sample: dict) -> SimpleNamespace:
    sources = {
        "lab": sample["lab"],
        "exam": sample["exam"],
        "progress": sample["progress"],
        "nursing": sample["nursing"],
    }
    source_field_mappings = {
        "lab": {},
        "exam": {},
        "progress": {},
        "nursing": {},
    }
    if sample.get("patient"):
        sources["patient"] = [sample["patient"]]
        source_field_mappings["patient"] = {}

    return SimpleNamespace(
        bundle_id="P_DEMO_001::1::2026-04-26",
        group_values={"patient_id": "P_DEMO_001", "visit_number": "1", "audit_date": "2026-04-26"},
        sources=sources,
        source_field_mappings=source_field_mappings,
        primary_source="lab",
        query_date=sample["audit_date"],
    )


def test_compose_new_builder_contains_all_sections():
    sample = scenario_cross_day_progress()
    bundle = _build_bundle(sample)

    payload, mr_text = compose(_build_lab_exam_audit_type(), bundle, sample["audit_date"])

    assert payload["audit_type_code"] == "lab_exam_vs_progress_nursing"
    assert payload.get("mr_text") == mr_text
    assert "structured_input" not in payload
    assert "[检验异常摘要]" in mr_text
    assert "[检查异常摘要]" in mr_text
    assert "[病程记录]" in mr_text
    assert "[护理记录]" in mr_text
    assert payload.get("abnormal_labs", {}).get("selected_count", 0) >= 1
    assert payload.get("abnormal_exams", {}).get("selected_count", 0) >= 1


def test_structured_builder_keeps_structured_input():
    sample = scenario_cross_day_progress()
    bundle = _build_bundle(sample)

    payload, mr_text = compose(_build_lab_exam_audit_type("lab_exam_structured_progress_nursing"), bundle, sample["audit_date"])

    assert payload["structured_input"]["核查信息"]["审计类型编码"] == "lab_exam_vs_progress_nursing"
    assert json.loads(mr_text)["核查信息"]["审计类型编码"] == "lab_exam_vs_progress_nursing"


def test_compose_tracks_multiple_event_sources_with_same_report_time():
    sample = scenario_same_day_complete()
    sample["exam"] = []
    sample["lab"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "test_no": "LAB-A",
            "test_name": "急查生化",
            "item_name": "肌酐",
            "result": "42",
            "abnormal_indicator": "L",
            "is_abnormal": "Y",
            "result_time": "2026-05-02 08:58:37",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "test_no": "LAB-B",
            "test_name": "急查肝功",
            "item_name": "碱性磷酸酶",
            "result": "124",
            "abnormal_indicator": "H",
            "is_abnormal": "Y",
            "result_time": "2026-05-02 08:58:37",
        },
    ]
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "PR-AFTER-MULTI-LAB",
            "record_name": "多检验后病程",
            "content": "同一报告时间多个异常检验均应显示为关联来源",
            "event_time": "2026-05-02 16:16:19",
        }
    ]
    sample["nursing"] = []
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, "2026-05-01~2026-05-14")

    row = payload["progress_context"]["records"][0]
    assert len(row["matched_event_sources"]) == 2
    assert row["matched_event_source_labels"] == ["检验 急查生化 LAB-A", "检验 急查肝功 LAB-B"]
    assert row["matched_event_source_label"] == "检验 急查生化 LAB-A；检验 急查肝功 LAB-B"
    diagnostic_row = payload["context_match_diagnostics"]["matched_progress"][0]
    assert len(diagnostic_row["matched_event_sources"]) == 2


def test_compose_uses_lab_exam_event_dates_for_context():
    sample = scenario_same_day_complete()
    sample["audit_date"] = "2026-04-29"
    sample["patient"]["discharge_date"] = "2026-04-29"
    sample["progress"][0]["audit_date"] = "2026-04-29"
    sample["nursing"][0]["audit_date"] = "2026-04-29"
    bundle = _build_bundle(sample)

    payload, mr_text = compose(_build_lab_exam_audit_type(), bundle, sample["audit_date"])

    assert payload["rules"]["context_base_dates"] == ["2026-04-26"]
    assert payload["progress_context"]["records"][0]["record_id"] == "PR-001"
    assert payload["nursing_context"]["records"][0]["record_id"] == "NU-001"
    assert "患者咳嗽加重" in mr_text
    assert "已执行降温护理" in mr_text


def test_compose_filters_context_to_same_day_after_report_time():
    sample = scenario_same_day_complete()
    sample["lab"][0]["result_time"] = "2026-04-26 10:00:00"
    sample["lab"][1]["result_time"] = "2026-04-26 10:00:00"
    sample["exam"][0]["exam_time"] = "2026-04-27 16:00:00"
    sample["exam"][0]["report_time"] = "2026-04-27 16:00:00"
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "PR-BEFORE",
            "record_name": "报告前病程",
            "content": "报告前记录不应纳入",
            "event_time": "2026-04-26 09:00:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "PR-AFTER",
            "record_name": "报告后病程",
            "content": "报告后记录应纳入",
            "event_time": "2026-04-26 11:00:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-27",
            "record_id": "PR-NEXT-BEFORE",
            "record_name": "检查报告前病程",
            "content": "检查报告前记录不应纳入",
            "event_time": "2026-04-27 15:00:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-28",
            "record_id": "PR-FOLLOWUP",
            "record_name": "次日病程",
            "content": "随访次日记录不应纳入",
            "event_time": "2026-04-28 09:00:00",
        },
    ]
    sample["nursing"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "NU-BEFORE",
            "record_name": "报告前护理",
            "content": "报告前护理不应纳入",
            "event_time": "2026-04-26 09:30:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-27",
            "record_id": "NU-AFTER",
            "record_name": "检查报告后护理",
            "content": "检查报告后护理应纳入",
            "event_time": "2026-04-27 17:00:00",
        },
    ]
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, sample["audit_date"])

    assert [row["record_id"] for row in payload["progress_context"]["records"]] == []
    assert [row["record_id"] for row in payload["nursing_context"]["records"]] == []
    assert payload["rules"]["context_base_dates"] == []
    assert payload["rules"]["same_day_lab_exam_dates"] == []
    assert payload["rules"]["context_skipped_reason"] == "no_same_day_lab_exam_event"
    assert "same-day" in payload["rules"]["context_match_rule"]
    assert payload["context_match_diagnostics"]["matched_progress"] == []


def test_compose_requires_same_day_lab_and_exam_before_context_matching():
    sample = scenario_same_day_complete()
    sample["lab"][0]["result_time"] = "2026-05-02 08:58:37"
    sample["lab"][1]["result_time"] = "2026-05-02 08:58:37"
    sample["exam"][0]["exam_time"] = "2026-05-03 13:40:37"
    sample["exam"][0]["report_time"] = "2026-05-03 13:40:37"
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "PR-AFTER-LAB-ONLY",
            "record_name": "检验后病程",
            "content": "只有同日异常检验，没有同日异常检查，不应纳入",
            "event_time": "2026-05-02 16:16:19",
        }
    ]
    sample["nursing"] = []
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, "2026-05-01~2026-05-14")

    assert payload["rules"]["context_base_dates"] == []
    assert payload["rules"]["same_day_lab_exam_dates"] == []
    assert payload["rules"]["context_skipped_reason"] == "no_same_day_lab_exam_event"
    assert payload["progress_context"]["records"] == []


def test_compose_matches_context_when_only_abnormal_lab_exists():
    sample = scenario_same_day_complete()
    sample["exam"] = []
    sample["lab"][0]["result_time"] = "2026-05-02 08:58:37"
    sample["lab"][1]["result_time"] = "2026-05-02 08:58:37"
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "PR-AFTER-LAB-ONLY",
            "record_name": "检验后病程",
            "content": "只有异常检验时，同日且晚于检验结果时间应纳入",
            "event_time": "2026-05-02 16:16:19",
        }
    ]
    sample["nursing"] = []
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, "2026-05-01~2026-05-14")

    assert payload["rules"]["context_event_filter_mode"] == "single_source"
    assert payload["rules"]["context_base_dates"] == ["2026-05-02"]
    assert [row["record_id"] for row in payload["progress_context"]["records"]] == ["PR-AFTER-LAB-ONLY"]
    assert payload["progress_context"]["records"][0]["matched_event_source"]["source"] == "lab"


def test_compose_matches_context_when_only_abnormal_exam_exists():
    sample = scenario_same_day_complete()
    sample["lab"] = []
    sample["exam"][0]["exam_time"] = "2026-05-02 13:40:37"
    sample["exam"][0]["report_time"] = "2026-05-02 13:40:37"
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "PR-AFTER-EXAM-ONLY",
            "record_name": "检查后病程",
            "content": "只有异常检查时，同日且晚于检查报告时间应纳入",
            "event_time": "2026-05-02 16:16:19",
        }
    ]
    sample["nursing"] = []
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, "2026-05-01~2026-05-14")

    assert payload["rules"]["context_event_filter_mode"] == "single_source"
    assert payload["rules"]["context_base_dates"] == ["2026-05-02"]
    assert [row["record_id"] for row in payload["progress_context"]["records"]] == ["PR-AFTER-EXAM-ONLY"]
    assert payload["progress_context"]["records"][0]["matched_event_source"]["source"] == "exam"


def test_compose_matches_context_only_on_same_day_lab_exam_date():
    sample = scenario_same_day_complete()
    sample["lab"][0]["result_time"] = "2026-05-02 08:58:37"
    sample["lab"][1]["result_time"] = "2026-05-02 08:58:37"
    sample["exam"][0]["exam_time"] = "2026-05-02 13:40:37"
    sample["exam"][0]["report_time"] = "2026-05-02 13:40:37"
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "PR-AFTER-LAB-EXAM",
            "record_name": "同日检验检查后病程",
            "content": "同日存在异常检验和异常检查，且病程晚于报告时间，应纳入",
            "event_time": "2026-05-02 16:16:19",
        }
    ]
    sample["nursing"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-05-02",
            "record_id": "NU-AFTER-LAB-EXAM",
            "record_name": "同日检验检查后护理",
            "content": "同日存在异常检验和异常检查，且护理晚于报告时间，应纳入",
            "event_time": "2026-05-02 17:00:00",
        }
    ]
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, "2026-05-01~2026-05-14")

    assert payload["rules"]["context_base_dates"] == ["2026-05-02"]
    assert payload["rules"]["same_day_lab_exam_dates"] == ["2026-05-02"]
    assert [row["record_id"] for row in payload["progress_context"]["records"]] == ["PR-AFTER-LAB-EXAM"]
    assert [row["record_id"] for row in payload["nursing_context"]["records"]] == ["NU-AFTER-LAB-EXAM"]
    assert payload["context_match_diagnostics"]["same_day_lab_exam_dates"] == ["2026-05-02"]


def test_compose_does_not_match_context_from_non_abnormal_exam_report():
    sample = scenario_same_day_complete()
    sample["lab"] = []
    sample["exam"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "exam_no": "EXAM-NORMAL",
            "exam_class": "心电图",
            "exam_name": "床旁心电图",
            "description": "窦性心律",
            "impression": "窦性心律",
            "is_abnormal": "N",
            "exam_time": "2026-04-26 09:00:00",
            "report_time": "2026-04-26 09:00:00",
        }
    ]
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "PR-AFTER-NORMAL-EXAM",
            "record_name": "普通病程",
            "content": "正常检查后的病程不应因该检查纳入",
            "event_time": "2026-04-26 10:00:00",
        }
    ]
    sample["nursing"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "NU-AFTER-NORMAL-EXAM",
            "record_name": "普通护理",
            "content": "正常检查后的护理不应因该检查纳入",
            "event_time": "2026-04-26 10:30:00",
        }
    ]
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, sample["audit_date"])

    assert payload["rules"]["context_base_events"] == []
    assert payload["rules"]["context_base_dates"] == []
    assert payload["rules"]["context_skipped_reason"] == "no_abnormal_findings"
    assert payload["progress_context"]["records"] == []
    assert payload["nursing_context"]["records"] == []
    assert payload["context_match_diagnostics"]["included_event_sources"] == []


def test_compose_does_not_fallback_when_abnormal_exam_has_no_event_time():
    sample = scenario_same_day_complete()
    sample["lab"] = []
    sample["exam"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "exam_no": "EXAM-ABNORMAL-NO-TIME",
            "exam_class": "CT",
            "exam_name": "胸部CT",
            "description": "肺部感染",
            "impression": "异常",
            "is_abnormal": "Y",
            "exam_time": "",
            "report_time": "",
        }
    ]
    sample["progress"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "record_id": "PR-AFTER-NO-TIME",
            "record_name": "普通病程",
            "content": "异常检查无报告时间时不应回退纳入",
            "event_time": "2026-04-26 10:00:00",
        }
    ]
    sample["nursing"] = []
    bundle = _build_bundle(sample)

    payload, _ = compose(_build_lab_exam_audit_type(), bundle, sample["audit_date"])

    assert payload["rules"]["has_abnormal_findings"] is True
    assert payload["rules"]["context_base_events"] == []
    assert payload["rules"]["context_base_dates"] == []
    assert payload["rules"]["context_skipped_reason"] == "no_abnormal_event_time"
    assert payload["progress_context"]["records"] == []


def test_event_extraction_accepts_truthy_abnormal_values():
    lab_summary = {
        "items": [
            {"test_no": "LAB-Y", "test_name": "血常规", "is_abnormal": "Y", "result_time": "2026-04-26 09:00:00"},
            {"test_no": "LAB-N", "test_name": "生化", "is_abnormal": "N", "result_time": "2026-04-26 10:00:00"},
        ]
    }
    exam_summary = {
        "reports": [
            {"exam_no": "EXAM-1", "exam_name": "CT", "is_abnormal": 1, "report_time": "2026-04-26 11:00:00"},
            {"exam_no": "EXAM-0", "exam_name": "心电图", "is_abnormal": 0, "report_time": "2026-04-26 12:00:00"},
        ]
    }

    event_specs = _extract_lab_exam_event_specs(lab_summary, exam_summary)

    assert [item["source_id"] for item in event_specs] == ["LAB-Y", "EXAM-1"]
    assert _has_abnormal_findings(lab_summary, exam_summary) is True


def test_compose_structured_builder_outputs_json_string():
    sample = scenario_same_day_complete()
    sample["patient"] = {
        "patient_id": "P_DEMO_001",
        "visit_number": "1",
        "patient_name": "张三",
        "dept": "神经内科",
        "admission_no": "ZY001",
        "admission_date": "2026-04-20",
        "discharge_date": "2026-04-29",
        "admission_diagnosis": "肺部感染",
        "is_discharged": "是",
        "admission_dept_name": "急诊科",
        "discharge_dept_name": "神经内科",
        "discharge_main_diagnosis": "肺部感染好转",
        "surgery": "无",
    }
    sample["lab"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "test_no": "LAB-001",
            "test_name": "血常规",
            "report_item_name": "白细胞",
            "item_name": "白细胞",
            "result": "12.3",
            "units": "10^9/L",
            "abnormal_indicator": "H",
            "reference_range": "3.5-9.5",
            "result_time": "2026-04-26 08:10:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "test_no": "LAB-001",
            "test_name": "血常规",
            "report_item_name": "中性粒细胞比例",
            "item_name": "中性粒细胞比例",
            "result": "85",
            "units": "%",
            "abnormal_indicator": "H",
            "reference_range": "40-75",
            "result_time": "2026-04-26 08:10:00",
        },
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "test_no": "LAB-002",
            "test_name": "大生化",
            "report_item_name": "肌酐",
            "item_name": "肌酐",
            "result": "168",
            "units": "umol/L",
            "abnormal_indicator": "H",
            "reference_range": "57-97",
            "result_time": "2026-04-26 09:10:00",
        },
    ]
    sample["exam"] = [
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "exam_no": "EXAM-001",
            "exam_class": "B超",
            "exam_name": "腹部B超",
            "description": "胆囊壁增厚，胆囊结石声像。",
            "impression": "胆囊结石伴胆囊炎",
            "is_abnormal": "Y",
            "exam_time": "2026-04-26 09:20:00",
            "report_time": "2026-04-26 09:40:00",
        }
    ]
    bundle = _build_bundle(sample)

    payload, mr_text = compose(
        _build_lab_exam_audit_type("lab_exam_structured_progress_nursing"),
        bundle,
        sample["audit_date"],
    )
    data = json.loads(mr_text)

    assert isinstance(mr_text, str)
    assert payload.get("mr_text") == mr_text
    assert "mr_txt" not in payload
    assert data["核查信息"]["审核日期"] == "2026-04-26"
    assert data["患者信息"]["患者ID"] == "P_DEMO_001"
    assert data["患者信息"]["科室"] == "神经内科"
    assert "入院日期" not in data["患者信息"]
    assert "出院主诊断" not in data["患者信息"]
    assert "入院日期" not in mr_text
    assert payload["patient_info"]["admission_date"] == "2026-04-20"
    assert payload["patient_info"]["discharge_main_diagnosis"] == "肺部感染好转"
    assert payload["patient_info"]["department"] == "神经内科"
    lab_reports = data["检验检查"]["检验报告信息"]
    assert len(lab_reports) == 2
    lab_by_no = {item["检验单号"]: item for item in lab_reports}
    assert lab_by_no["LAB-001"]["检验项目"] == "血常规"
    assert len(lab_by_no["LAB-001"]["报告项目"]) == 2
    assert lab_by_no["LAB-001"]["报告项目"][0]["报告项目名称"] in {"白细胞", "中性粒细胞比例"}
    assert lab_by_no["LAB-002"]["报告项目"][0]["参考范围"] == "57-97"
    exam_report = data["检验检查"]["检查报告"][0]
    assert exam_report["检查类别"] == "B超"
    assert exam_report["检查名称"] == "腹部B超"
    assert exam_report["报告时间"] == "2026-04-26 09:40:00"
    assert exam_report["检查所见"] == "胆囊壁增厚，胆囊结石声像。"
    assert "检查印象" not in exam_report
    assert "是否异常" not in exam_report
    assert data["病程"]["病程记录"][0]["病程内容"]
    assert data["病程"]["病程记录"][0]["关联报告时间"]
    assert data["病程"]["病程记录"][0]["关联报告来源"]
    assert data["护理"]["护理记录"][0]["护理内容"]


def test_compose_legacy_builder_not_affected():
    sample = scenario_same_day_complete()
    audit_type = AuditTypeConfig.model_validate(
        {
            "code": "progress_vs_nursing",
            "name": "病程护理一致性",
            "sources": {
                "primary": {
                    "type": "sql",
                    "query_sql": "SELECT 1",
                    "field_mapping": {
                        "patient_id": "patient_id",
                        "visit_number": "visit_number",
                        "patient_name": "patient_name",
                        "dept": "dept",
                    },
                }
            },
            "payload": {"builder": "legacy_progress_nursing"},
            "dify": {"base_url": "http://example.com/v1"},
        }
    )
    primary_records = [
        {
            "patient_id": sample["patient"]["patient_id"],
            "visit_number": sample["patient"]["visit_number"],
            "patient_name": sample["patient"]["patient_name"],
            "dept": sample["patient"]["dept"],
            "病历文书_内容": "病程文本",
            "护理记录_内容": "护理文本",
        }
    ]
    bundle = SimpleNamespace(
        bundle_id="legacy::1",
        group_values={"patient_id": "P_DEMO_001", "visit_number": "1"},
        sources={"primary": primary_records},
        source_field_mappings={
            "primary": {
                "patient_id": "patient_id",
                "visit_number": "visit_number",
                "patient_name": "patient_name",
                "dept": "dept",
            }
        },
        primary_source="primary",
        query_date=sample["audit_date"],
    )

    payload, mr_text = compose(audit_type, bundle, sample["audit_date"])

    assert "mr_txt" not in payload
    assert payload.get("patient_info", {}).get("patient_id") == "P_DEMO_001"
    assert isinstance(mr_text, str)
    assert mr_text.strip()
    assert "审核日期:" in mr_text


if __name__ == "__main__":
    tests = [
        test_compose_new_builder_contains_all_sections,
        test_compose_structured_builder_outputs_json_string,
        test_compose_legacy_builder_not_affected,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"ERROR: {test.__name__}: {exc}")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    if failed > 0:
        raise SystemExit(1)
