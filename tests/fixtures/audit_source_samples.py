"""Task 4: 脱敏四源审计测试样例。"""
from __future__ import annotations


def scenario_same_day_complete() -> dict:
    return {
        "patient": {"patient_id": "P_DEMO_001", "visit_number": "1", "patient_name": "患者甲", "dept": "心内科"},
        "audit_date": "2026-04-26",
        "lab": [
            {
                "patient_id": "P_DEMO_001",
                "visit_number": "1",
                "audit_date": "2026-04-26",
                "test_no": "LAB-001",
                "item_name": "白细胞",
                "result": "12.3",
                "abnormal_indicator": "H",
                "result_time": "2026-04-26 08:10:00",
            },
            {
                "patient_id": "P_DEMO_001",
                "visit_number": "1",
                "audit_date": "2026-04-26",
                "test_no": "LAB-001",
                "item_name": "中性粒细胞比例",
                "result": "85%",
                "abnormal_indicator": "H",
                "result_time": "2026-04-26 08:10:00",
            },
        ],
        "exam": [
            {
                "patient_id": "P_DEMO_001",
                "visit_number": "1",
                "audit_date": "2026-04-26",
                "exam_no": "EXAM-001",
                "exam_class": "CT",
                "description": "胸部CT",
                "impression": "双肺散在感染影",
                "is_abnormal": "Y",
                "exam_time": "2026-04-26 09:20:00",
            }
        ],
        "progress": [
            {
                "patient_id": "P_DEMO_001",
                "visit_number": "1",
                "audit_date": "2026-04-26",
                "record_id": "PR-001",
                "record_name": "病程记录",
                "content": "患者咳嗽加重，考虑感染可能。",
                "event_time": "2026-04-26 10:00:00",
            }
        ],
        "nursing": [
            {
                "patient_id": "P_DEMO_001",
                "visit_number": "1",
                "audit_date": "2026-04-26",
                "record_id": "NU-001",
                "record_name": "护理记录",
                "content": "患者体温 38.3℃，已执行降温护理。",
                "event_time": "2026-04-26 10:30:00",
            }
        ],
    }


def scenario_missing_sources() -> dict:
    data = scenario_same_day_complete()
    data["exam"] = []
    data["nursing"] = []
    return data


def scenario_cross_day_progress() -> dict:
    data = scenario_same_day_complete()
    data["progress"].append(
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-27",
            "record_id": "PR-002",
            "record_name": "次日病程",
            "content": "次日复查炎症指标较前下降。",
            "event_time": "2026-04-27 08:10:00",
        }
    )
    return data


def scenario_mixed_normal_abnormal() -> dict:
    data = scenario_same_day_complete()
    data["lab"].append(
        {
            "patient_id": "P_DEMO_001",
            "visit_number": "1",
            "audit_date": "2026-04-26",
            "test_no": "LAB-002",
            "item_name": "血红蛋白",
            "result": "132",
            "abnormal_indicator": "N",
            "result_time": "2026-04-26 08:20:00",
        }
    )
    return data
