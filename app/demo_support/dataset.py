"""确定性的 12 科室脱敏合成测试数据契约。"""
from __future__ import annotations

from datetime import date


DATASET_VERSION = "demo-12dept-v1"
DEFAULT_SEED = 20260813
BASE_DATE = date(2026, 8, 12)
SYNTHETIC_LABEL = "SYNTHETIC TEST DATA / 脱敏合成测试数据"

DEPARTMENTS = [
    ("DEMO-D001", "听觉植入科"),
    ("DEMO-D002", "帕金森病与头痛头晕专业"),
    ("DEMO-D003", "头颈放疗科"),
    ("DEMO-D004", "眩晕疾病科"),
    ("DEMO-D005", "耳内科"),
    ("DEMO-D006", "炎症性鼻病科"),
    ("DEMO-D007", "结构性心脏病科"),
    ("DEMO-D008", "耳鸣疾病科"),
    ("DEMO-D009", "肾脏病血液净化中心"),
    ("DEMO-D010", "头颈外科"),
    ("DEMO-D011", "消化内一科"),
    ("DEMO-D012", "创伤骨科（手足一组）"),
]

AUDIT_TYPES = [
    {
        "code": "progress_vs_nursing",
        "name": "病程与护理一致性质控",
        "builder": "generic_multi_source",
        "sources": ["progress", "nursing"],
        "dimensions": ["diagnosis_consistency", "nursing_level_consistency", "vital_sign_consistency", "condition_consistency", "treatment_measure_consistency", "timeline_consistency"],
    },
    {
        "code": "admission_vs_first_progress",
        "name": "入院记录与首次病程质控",
        "builder": "admission_first_progress",
        "sources": ["admission", "progress"],
        "dimensions": ["chief_complaint", "history_consistency", "diagnosis_basis", "treatment_plan", "timeline_consistency", "record_completeness"],
    },
    {
        "code": "jyjc_vs_bcnursing",
        "name": "检验检查与病程护理质控",
        "builder": "lab_exam_structured_progress_nursing",
        "sources": ["lab", "exam", "progress", "nursing"],
        "dimensions": ["lab_abnormal_followup", "exam_abnormal_followup", "clinical_response", "nursing_observation", "timeline_consistency", "record_completeness"],
        "group_key": ["patient_id", "visit_number", "audit_date"],
    },
    {
        "code": "syssvsscbc",
        "name": "首页手术诊断与首次病程质控",
        "builder": "frontpage_surgery_first_progress",
        "sources": ["frontpage", "first_progress"],
        "dimensions": ["operation_name_consistency", "operation_date_consistency", "anesthesia_consistency", "diagnosis_consistency", "postoperative_plan_completeness", "multi_operation_omission"],
    },
    {
        "code": "surgery_chain",
        "name": "围手术期文书链质控",
        "builder": "surgery_chain",
        "sources": ["perioperative"],
        "dimensions": ["preoperative_summary", "operation_record", "postoperative_progress", "diagnosis_consistency", "timeline_consistency", "record_completeness"],
    },
    {
        "code": "discharge_vs_frontpage",
        "name": "出院记录与病案首页质控",
        "builder": "discharge_frontpage",
        "sources": ["discharge", "progress"],
        "dimensions": ["diagnosis_consistency", "treatment_summary", "discharge_advice", "medication_consistency", "timeline_consistency", "record_completeness"],
    },
]

AUDIT_TYPE_BY_CODE = {item["code"]: item for item in AUDIT_TYPES}


def source_config(source_name: str) -> dict:
    return {
        "type": "sql",
        "backend": "default",
        "query_sql": "SELECT 1 AS fixture_only",
        "required": True,
        "field_mapping": {
            "patient_id": "patient_id",
            "visit_number": "visit_number",
            "patient_name": "patient_name",
            "admission_no": "admission_no",
            "dept": "dept",
            "record_key": "record_key",
            "record_name": "record_name",
            "content": "content",
            "event_time": "event_time",
        },
    }


def build_demo_config(app_port: int = 18080, dify_port: int = 18081, relay_port: int = 18082) -> dict:
    audit_types = []
    for order, spec in enumerate(AUDIT_TYPES, start=1):
        audit_types.append(
            {
                "code": spec["code"],
                "name": spec["name"],
                "description": f"{SYNTHETIC_LABEL}；仅用于隔离功能与流程测试",
                "enabled": True,
                "sort_order": order * 10,
                "default_for_schedule": False,
                "dimension_codes": spec["dimensions"],
                "sources": {name: source_config(name) for name in spec["sources"]},
                "group_key": spec.get("group_key", ["patient_id", "visit_number"]),
                "join_rules": [],
                "payload": {
                    "builder": spec["builder"],
                    "date_window_days": 3,
                    "progress_followup_days": 2,
                    "max_lab_items": 20,
                    "max_exam_reports": 10,
                    "include_normal_summary": True,
                    "surgery_fields": ["surgery"],
                    "diagnosis_fields": {"admission_diagnosis": "admission_diagnosis", "discharge_primary_diagnosis": "discharge_main_diagnosis"},
                },
                "dify": {
                    "base_url": f"http://127.0.0.1:{dify_port}/v1",
                    "api_key": "demo-local-only",
                    "workflow_input_variable": "mr_txt",
                    "workflow_output_key": "aa",
                    "user_identifier": "synthetic-test",
                    "timeout_seconds": 8,
                    "extra_inputs": {"mr_type": spec["code"]},
                    "targets": [],
                },
                "response": {},
                "display": {"summary_blocks": [], "detail_blocks": []},
            }
        )
    return {
        "data_source": {"type": "fixture"},
        "oracle": {"host": "", "port": 1521, "service_name": "", "username": "", "password_enc": "", "query_sql": ""},
        "postgresql": {"host": "", "port": 5432, "database": "", "username": "", "password_enc": ""},
        "emr_vastbase": {"enabled": False, "host": "", "port": 5432, "database": "", "username": "", "password_enc": ""},
        "dify": {
            "base_url": f"http://127.0.0.1:{dify_port}/v1",
            "api_key": "demo-local-only",
            "workflow_input_variable": "mr_txt",
            "workflow_output_key": "aa",
            "user_identifier": "synthetic-test",
            "timeout_seconds": 8,
            "extra_inputs": {},
            "targets": [],
        },
        "notify": {"enabled": False, "channels": []},
        "relay_alert": {
            "enabled": True,
            "base_url": f"http://127.0.0.1:{relay_port}",
            "endpoint": "/qc-record-alert",
            "secret_key": "demo-relay-secret-2026",
            "timeout_seconds": 5,
            "max_retry": 3,
            "severity_levels": ["high"],
            "source": "病历质控系统（脱敏合成测试）",
            "alert_dept_filter": [],
            "detail_page": {
                "enabled": True,
                "token_ttl_hours": 720,
                "external_base_url": f"http://127.0.0.1:{relay_port}",
                "internal_base_url": f"http://127.0.0.1:{app_port}",
            },
        },
        "scheduler": {"enabled": False},
        "scheduler_daily": {"enabled": False, "audit_type_codes": []},
        "scheduler_discharge": {"enabled": False, "audit_type_codes": []},
        "audit_types": audit_types,
        "demo_environment": {"synthetic": True, "label": SYNTHETIC_LABEL, "dataset_version": DATASET_VERSION},
    }
