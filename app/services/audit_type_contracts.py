"""正式六类质控的稳定编码与安全模板契约。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any


OFFICIAL_AUDIT_TYPE_CODES = (
    "admission_vs_first_progress",
    "discharge_vs_frontpage",
    "surgery_chain",
    "progress_vs_nursing",
    "jyjc_vs_bcnursing",
    "syssvsscbc",
)

DEPRECATED_AUDIT_TYPE_CODES = frozenset(
    {
        "lab_exam_vs_progress_nursing",
        "frontpage_surgery_diagnosis_vs_first_progress",
        "orders_vs_progress",
    }
)

_SPECS: dict[str, dict[str, Any]] = {
    "admission_vs_first_progress": {
        "name": "入院记录与首次病程质控",
        "builder": "admission_first_progress",
        "sources": {"admission": ("emr_vastbase", "admission"), "progress": ("emr_vastbase", "first_progress")},
        "dimensions": [
            "chief_complaint", "history_of_present_illness", "past_history",
            "physical_examination", "auxiliary_examination", "initial_diagnosis",
            "diagnosis_consistency", "treatment_plan", "timeline_consistency", "text_quality",
        ],
        "mr_type": "入院与首次病程核查",
    },
    "discharge_vs_frontpage": {
        "name": "出院记录与病案首页质控",
        "builder": "discharge_frontpage",
        "sources": {"discharge": ("emr_vastbase", "discharge"), "progress": ("emr_vastbase", "progress")},
        "dimensions": [
            "diagnosis_consistency", "treatment_summary", "discharge_advice",
            "medication_consistency", "timeline_consistency", "record_completeness",
        ],
        "mr_type": "出院与病案首页核查",
    },
    "surgery_chain": {
        "name": "围手术期文书链质控",
        "builder": "surgery_chain",
        "sources": {"perioperative": ("emr_vastbase", "surgery")},
        "dimensions": [
            "preoperative_summary", "operation_record", "postoperative_progress",
            "diagnosis_consistency", "timeline_consistency", "record_completeness",
        ],
        "mr_type": "围手术期核查",
    },
    "progress_vs_nursing": {
        "name": "病程与护理一致性质控",
        "builder": "legacy_progress_nursing",
        "sources": {"primary": ("default", "")},
        "dimensions": [
            "diagnosis_consistency", "nursing_level_consistency", "vital_sign_consistency",
            "condition_consistency", "treatment_measure_consistency", "timeline_consistency",
        ],
        "mr_type": "病程与护理核查",
    },
    "jyjc_vs_bcnursing": {
        "name": "检验检查与病程护理质控",
        "builder": "lab_exam_structured_progress_nursing",
        "sources": {
            "lab": ("default", ""), "exam": ("default", ""),
            "progress": ("default", ""), "nursing": ("default", ""),
        },
        "dimensions": [
            "lab_abnormal_followup", "exam_abnormal_followup", "progress_result_consistency",
            "nursing_recorded_consistency", "high_risk_response_consistency", "timeline_consistency",
        ],
        "mr_type": "检验检查与病程护理核查",
    },
    "syssvsscbc": {
        "name": "首页手术诊断与首次病程质控",
        "builder": "frontpage_surgery_first_progress",
        "sources": {"frontpage": ("default", ""), "first_progress": ("default", "")},
        "dimensions": [
            "operation_name_consistency", "operation_date_consistency", "anesthesia_consistency",
            "diagnosis_consistency", "postoperative_plan_completeness", "multi_operation_omission",
        ],
        "group_key": ["patient_id", "visit_number", "operation_date"],
        "mr_type": "首页手术诊断与首次病程核查",
    },
}


def build_safe_template_audit_types() -> list[dict[str, Any]]:
    """生成不含凭据、默认禁用且无法被误认为生产就绪的六类模板。"""
    result: list[dict[str, Any]] = []
    for order, code in enumerate(OFFICIAL_AUDIT_TYPE_CODES, start=1):
        spec = _SPECS[code]
        sources: dict[str, dict[str, Any]] = {}
        for source_name, (backend, document_kind) in spec["sources"].items():
            sources[source_name] = {
                "type": "sql",
                "backend": backend,
                "data_source": "emr_vastbase" if backend == "emr_vastbase" else "",
                "document_kind": document_kind,
                "load_strategy": "bulk",
                "query_sql": "",
                "field_mapping": {},
                "required": True,
            }

        result.append(
            {
                "code": code,
                "name": spec["name"],
                "description": "安全初始化模板：启用前必须配置并验证真实只读数据源与 Dify Workflow",
                "enabled": False,
                "sort_order": order * 10,
                "default_for_schedule": False,
                "dimension_codes": list(spec["dimensions"]),
                "sources": sources,
                "group_key": deepcopy(spec.get("group_key", ["patient_id", "visit_number"])),
                "join_rules": [],
                "payload": {"builder": spec["builder"], "requires_configuration": True},
                "dify": {
                    "base_url": "",
                    "api_key_enc": "",
                    "workflow_input_variable": "mr_txt",
                    "workflow_output_key": "aa",
                    "user_identifier": "med-audit-system",
                    "timeout_seconds": 90,
                    "extra_inputs": {"mr_type": spec["mr_type"]},
                    "targets": [],
                },
                "response": {
                    "parse_strategy": "hybrid",
                    "dimension_path": "$.dimensions",
                    "conclusion_path": "$.overall_conclusion",
                    "severity_path": "$.severity",
                    "risk_score_path": "$.risk_score",
                    "inconsistency_path": "$.inconsistency",
                },
                "display": {
                    "summary_blocks": [
                        {"label": "总体结论", "path": "$.overall_conclusion", "type": "text_block"},
                        {"label": "风险分值", "path": "$.risk_score", "type": "severity_badge"},
                    ],
                    "detail_blocks": [
                        {"label": "维度详情", "path": "$.dimensions", "type": "dimension_grid"},
                    ],
                },
            }
        )
    return result


def audit_type_closure_errors(config: dict[str, Any]) -> list[str]:
    """返回六类/调度引用闭包错误；不读取密钥或医疗数据。"""
    errors: list[str] = []
    items = config.get("audit_types", []) or []
    codes = [str(item.get("code") or "").strip() for item in items if isinstance(item, dict)]
    duplicates = sorted({code for code in codes if code and codes.count(code) > 1})
    if duplicates:
        errors.append("audit_types duplicate codes: " + ", ".join(duplicates))
    deprecated = sorted(set(codes) & DEPRECATED_AUDIT_TYPE_CODES)
    if deprecated:
        errors.append("audit_types deprecated codes: " + ", ".join(deprecated))
    missing = sorted(set(OFFICIAL_AUDIT_TYPE_CODES) - set(codes))
    if missing:
        errors.append("audit_types missing official codes: " + ", ".join(missing))

    known = set(codes)
    for section in ("scheduler", "scheduler_daily", "scheduler_discharge"):
        scheduler = config.get(section, {}) or {}
        unknown = sorted({str(code).strip() for code in scheduler.get("audit_type_codes", []) or []} - known)
        if unknown:
            errors.append(f"{section}.audit_type_codes unknown: " + ", ".join(unknown))
    return errors

