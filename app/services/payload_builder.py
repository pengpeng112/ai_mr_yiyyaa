"""
Build structured payload and plain text for Dify input.
"""

from __future__ import annotations

from typing import Any, Dict, List

# Chinese key aliases (unicode escaped to avoid encoding issues)
K_PATIENT_ID = "\u60a3\u8005ID"
K_VISIT_NO = "\u6b21\u6570"
K_ADMISSION_NO = "\u4f4f\u9662\u53f7"
K_PATIENT_NAME = "\u60a3\u8005\u59d3\u540d"
K_GENDER = "\u6027\u522b"
K_BIRTH_DATE = "\u51fa\u751f\u65e5\u671f"
K_ADMISSION_DATE = "\u5165\u9662\u65e5\u671f"
K_DISCHARGE_DATE = "\u51fa\u9662\u65e5\u671f"
K_BED_NO = "\u5e8a\u53f7"
K_DEPT = "\u6240\u5728\u79d1\u5ba4\u540d\u79f0"
K_ADMISSION_DIAGNOSIS = "\u5165\u9662\u8bca\u65ad"
K_DISCHARGE_MAIN_DIAGNOSIS = "\u51fa\u9662\u4e3b\u8bca\u65ad"
K_ADMISSION_CONDITION = "\u5165\u9662\u75c5\u60c5"
K_NURSING_LEVEL_ORDER = "\u533b\u5631\u62a4\u7406\u7ea7\u522b"
K_NURSING_LEVEL = "\u62a4\u7406\u7ea7\u522b"
K_ATTENDING_DOCTOR = "\u7ba1\u5e8a\u533b\u751f"
K_IS_DISCHARGED = "\u662f\u5426\u51fa\u9662"
K_ADMISSION_DEPT_NAME = "\u5165\u9662\u79d1\u5ba4\u540d\u79f0"
K_DISCHARGE_DEPT_NAME = "\u51fa\u9662\u79d1\u5ba4\u540d\u79f0"
K_SURGERY = "\u624b\u672f"
K_ID_CARD = "\u8eab\u4efd\u8bc1\u53f7"
K_ID_CARD_ALT = "\u8eab\u4efd\u8bc1"
K_ADDRESS = "\u4f4f\u5740"
K_ADDRESS_ALT = "\u5bb6\u5ead\u4f4f\u5740"
K_PHONE = "\u8054\u7cfb\u7535\u8bdd"
K_PHONE_ALT = "\u624b\u673a\u53f7"

K_MR_FINISH_TIME = "\u75c5\u5386\u6587\u4e66_\u5b8c\u6210\u65f6\u95f4"
K_MR_TITLE_TIME = "\u75c5\u5386\u6807\u9898\u65f6\u95f4"
K_MR_NAME = "\u75c5\u5386\u6587\u4e66_\u540d\u79f0"
K_MR_NAME_ALT = "\u75c5\u5386\u540d\u79f0"
K_MR_SIGNED_DOCTOR = "\u75c5\u5386\u6587\u4e66_\u7b7e\u540d\u533b\u5e08"
K_MR_CREATOR = "\u75c5\u5386\u521b\u5efa\u4eba"
K_CREATOR = "\u521b\u5efa\u4eba"
K_MR_CONTENT = "\u75c5\u5386\u6587\u4e66_\u5185\u5bb9"
K_MR_CONTENT_ALT = "\u75c5\u5386\u5185\u5bb9"

K_NURSE_RECORD_TIME = "\u62a4\u7406\u8bb0\u5f55_\u521b\u5efa\u65f6\u95f4"
K_NURSE_RECORD_TIME_ALT = "\u62a4\u7406\u8bb0\u5f55\u65f6\u95f4"
K_NURSE_FORM_TIME = "\u62a4\u7406\u8bb0\u5f55\u8868\u5355\u5355\u521b\u5efa\u65f6\u95f4"
K_NURSE_TYPE = "\u62a4\u7406\u8bb0\u5f55_\u6587\u4e66\u7c7b\u578b"
K_NURSE_TYPE_ALT = "\u62a4\u7406\u5355\u7c7b\u578b"
K_NURSE_RECORDER = "\u62a4\u7406\u8bb0\u5f55_\u8bb0\u5f55\u4eba"
K_NURSE_RECORDER_ALT = "\u62a4\u7406\u8bb0\u5f55\u4eba"
K_RECORDER = "\u8bb0\u5f55\u4eba"
K_NURSE_CONTENT = "\u62a4\u7406\u8bb0\u5f55_\u5185\u5bb9"
K_NURSE_CONTENT_ALT = "\u75c5\u60c5\u89c2\u5bdf\u53ca\u62a4\u7406\u63aa\u65bd"

K_TEMP = "\u62a4\u7406\u8bb0\u5f55_\u4f53\u6e29"
K_TEMP_ALT = "\u4f53\u6e29"
K_PULSE = "\u62a4\u7406\u8bb0\u5f55_\u5fc3\u7387\u8109\u640f"
K_PULSE_ALT = "\u5fc3\u7387\u8109\u640f"
K_RESP = "\u62a4\u7406\u8bb0\u5f55_\u547c\u5438"
K_RESP_ALT = "\u547c\u5438"
K_BP = "\u62a4\u7406\u8bb0\u5f55_\u8840\u538b"
K_BP_ALT = "\u8840\u538b"
K_SPO2 = "\u62a4\u7406\u8bb0\u5f55_\u8840\u6c27\u9971\u548c\u5ea6"
K_SPO2_ALT = "\u8840\u6c27\u9971\u548c\u5ea6"
K_BG = "\u62a4\u7406\u8bb0\u5f55_\u8840\u7cd6"
K_BG_ALT = "\u8840\u7cd6"
K_CONSCIOUS = "\u62a4\u7406\u8bb0\u5f55_\u610f\u8bc6\u795e\u5fd7"
K_CONSCIOUS_ALT = "\u610f\u8bc6\u795e\u5fd7"
K_SKIN = "\u62a4\u7406\u8bb0\u5f55_\u76ae\u80a4\u60c5\u51b5"
K_SKIN_ALT = "\u76ae\u80a4\u60c5\u51b5"
K_WOUND = "\u62a4\u7406\u8bb0\u5f55_\u5200\u53e3\u60c5\u51b5"
K_WOUND_ALT = "\u5200\u53e3\u60c5\u51b5"
K_TUBE = "\u62a4\u7406\u8bb0\u5f55_\u7ba1\u9053\u62a4\u7406"
K_TUBE_ALT = "\u7ba1\u9053\u62a4\u7406"
K_HIGH_RISK = "\u62a4\u7406\u8bb0\u5f55_\u9ad8\u5371\u98ce\u9669"
K_HIGH_RISK_ALT = "\u9ad8\u5371\u98ce\u9669"

K_OXY_NASAL = "\u62a4\u7406\u8bb0\u5f55_\u6c27\u7597_\u9f3b\u5bfc\u7ba1"
K_OXY_NASAL_ALT = "\u6c27\u7597_\u9f3b\u5bfc\u7ba1"
K_OXY_MASK = "\u62a4\u7406\u8bb0\u5f55_\u6c27\u7597_\u9762\u7f69"
K_OXY_MASK_ALT = "\u6c27\u7597_\u9762\u7f69"
K_INTAKE = "\u62a4\u7406\u8bb0\u5f55_\u5165\u91cf\u60c5\u51b5"
K_INTAKE_ALT = "\u5165\u91cf\u60c5\u51b5"
K_OUTPUT = "\u62a4\u7406\u8bb0\u5f55_\u51fa\u91cf\u60c5\u51b5"
K_OUTPUT_ALT = "\u51fa\u91cf\u60c5\u51b5"
K_URINE = "\u62a4\u7406\u8bb0\u5f55_\u5c3f\u91cf"
K_URINE_ALT = "\u5c3f\u91cf"
K_INTAKE_NAME = "\u62a4\u7406\u8bb0\u5f55_\u5165\u91cf_\u540d\u79f0"
K_INTAKE_NAME_ALT = "\u5165\u91cf_\u540d\u79f0"
K_INTAKE_ROUTE = "\u62a4\u7406\u8bb0\u5f55_\u5165\u91cf_\u9014\u5f84"
K_INTAKE_ROUTE_ALT = "\u5165\u91cf_\u9014\u5f84"
K_INTAKE_VALUE = "\u62a4\u7406\u8bb0\u5f55_\u5165\u91cf_\u91cf"
K_INTAKE_VALUE_ALT = "\u5165\u91cf_\u91cf"
K_OUTPUT_NAME = "\u62a4\u7406\u8bb0\u5f55_\u51fa\u91cf_\u540d\u79f0"
K_OUTPUT_NAME_ALT = "\u51fa\u91cf_\u540d\u79f0"
K_OUTPUT_VALUE = "\u62a4\u7406\u8bb0\u5f55_\u51fa\u91cf_\u91cf"
K_OUTPUT_VALUE_ALT = "\u51fa\u91cf_\u91cf"


def build_dify_payload(
    patient_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str] | None = None,
    query_date: str = "",
) -> Dict[str, Any]:
    if not patient_records:
        return {
            "request_id": "",
            "audit_date": query_date,
            "match_rule": "patient_id + visit_number + date",
            "patient_info": {},
            "medical_documents": [],
            "nursing_records": [],
        }

    mapping = field_mapping or {}
    first = patient_records[0]

    patient_id = _pick(first, mapping.get("patient_id"), K_PATIENT_ID, "patient_id")
    visit_number = _pick(first, mapping.get("visit_number"), K_VISIT_NO, "visit_number")
    request_id = "_".join([part for part in [patient_id, visit_number, query_date] if part])

    return {
        "request_id": request_id,
        "audit_date": query_date,
        "match_rule": "patient_id + visit_number + date",
        "patient_info": {
            "patient_id": patient_id,
            "visit_number": visit_number,
            "admission_no": _pick(first, mapping.get("admission_no"), K_ADMISSION_NO, "admission_no"),
            "patient_name": _pick(first, mapping.get("patient_name"), K_PATIENT_NAME, "patient_name"),
            "gender": _pick(first, K_GENDER, "gender"),
            "birth_date": _pick(first, K_BIRTH_DATE, "birth_date"),
            "admission_date": _pick(first, K_ADMISSION_DATE, "admission_date"),
            "discharge_date": _pick(first, K_DISCHARGE_DATE, "discharge_date"),
            "is_discharged": _pick(first, K_IS_DISCHARGED, "is_discharged"),
            "bed_no": _pick(first, K_BED_NO, "BED_NO", "bed_no"),
            "admission_diagnosis": _pick(first, K_ADMISSION_DIAGNOSIS, "admission_diagnosis"),
            "discharge_main_diagnosis": _pick(first, K_DISCHARGE_MAIN_DIAGNOSIS, "discharge_main_diagnosis"),
            "admission_condition": _pick(first, K_ADMISSION_CONDITION, "admission_condition"),
            "nursing_level_order": _pick(first, K_NURSING_LEVEL_ORDER, K_NURSING_LEVEL, "nursing_level"),
            "department": _pick(first, mapping.get("dept"), K_DEPT, "department"),
            "admission_dept_name": _pick(first, K_ADMISSION_DEPT_NAME, "admission_dept_name"),
            "discharge_dept_name": _pick(first, K_DISCHARGE_DEPT_NAME, "discharge_dept_name"),
            "surgery": _pick(first, K_SURGERY, "surgery"),
            "id_card": _pick(first, K_ID_CARD, K_ID_CARD_ALT, "id_card", "idcard"),
            "address": _pick(first, K_ADDRESS, K_ADDRESS_ALT, "address"),
            "phone": _pick(first, K_PHONE, K_PHONE_ALT, "phone"),
            "attending_doctor": _pick(first, K_ATTENDING_DOCTOR, "attending_doctor"),
        },
        "medical_documents": _build_medical_documents(patient_records),
        "nursing_records": _build_nursing_records(patient_records),
    }


def build_dify_mr_text(
    patient_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str] | None = None,
    query_date: str = "",
) -> str:
    payload = build_dify_payload(patient_records, field_mapping, query_date)
    patient_info = payload.get("patient_info", {}) or {}
    medical_documents = payload.get("medical_documents", []) or []
    nursing_records = payload.get("nursing_records", []) or []

    lines = [
        f"审核日期: {payload.get('audit_date', '')}",
        f"患者ID: {patient_info.get('patient_id', '')}",
        f"住院次数: {patient_info.get('visit_number', '')}",
        f"住院号: {patient_info.get('admission_no', '')}",
        f"患者姓名: {patient_info.get('patient_name', '')}",
        f"所在科室: {patient_info.get('department', '')}",
        "",
        "[病历文书]",
    ]
    for index, item in enumerate(medical_documents, start=1):
        lines.extend(
            [
                f"{index}. 时间: {item.get('document_time', '')}",
                f"   名称: {item.get('document_name', '')}",
                f"   医师: {item.get('signed_doctor', '')}",
                f"   内容: {item.get('content', '')}",
            ]
        )

    lines.extend(["", "[护理记录]"])
    for index, item in enumerate(nursing_records, start=1):
        vitals = item.get("vitals", {}) or {}
        assessment = item.get("assessment", {}) or {}
        supportive = item.get("supportive_care", {}) or {}
        lines.extend(
            [
                f"{index}. 时间: {item.get('record_time', '')}",
                f"   类型: {item.get('record_type', '')}",
                f"   记录人: {item.get('recorder', '')}",
                f"   内容: {item.get('content', '')}",
                "   生命体征: "
                + _join_pairs(
                    {
                        "temperature": vitals.get("temperature", ""),
                        "heart_rate_pulse": vitals.get("heart_rate_pulse", ""),
                        "respiratory_rate": vitals.get("respiratory_rate", ""),
                        "blood_pressure": vitals.get("blood_pressure", ""),
                        "oxygen_saturation": vitals.get("oxygen_saturation", ""),
                        "blood_glucose": vitals.get("blood_glucose", ""),
                    }
                ),
                "   评估: "
                + _join_pairs(
                    {
                        "consciousness": assessment.get("consciousness", ""),
                        "skin_condition": assessment.get("skin_condition", ""),
                        "wound_condition": assessment.get("wound_condition", ""),
                        "tube_care": assessment.get("tube_care", ""),
                        "high_risk": assessment.get("high_risk", ""),
                    }
                ),
                "   出入量: "
                + _join_pairs(
                    {
                        "intake": supportive.get("intake", ""),
                        "output": supportive.get("output", ""),
                        "urine_volume": supportive.get("urine_volume", ""),
                        "oxygen_nasal_cannula": supportive.get("oxygen_nasal_cannula", ""),
                        "oxygen_mask": supportive.get("oxygen_mask", ""),
                    }
                ),
            ]
        )

    return "\n".join(line for line in lines if line is not None).strip()


def _build_medical_documents(patient_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    seen = set()
    for record in patient_records:
        item = {
            "document_time": _pick(record, K_MR_FINISH_TIME, K_MR_TITLE_TIME, "document_time"),
            "document_name": _pick(record, K_MR_NAME, K_MR_NAME_ALT, "document_name"),
            "signed_doctor": _pick(record, K_MR_SIGNED_DOCTOR, K_MR_CREATOR, K_CREATOR, "signed_doctor"),
            "content": _pick(record, K_MR_CONTENT, K_MR_CONTENT_ALT, "content"),
        }
        key = tuple(item.values())
        if not item["content"] and not item["document_time"] and not item["document_name"]:
            continue
        if key in seen:
            continue
        seen.add(key)
        documents.append(item)
    return documents


def _build_nursing_records(patient_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    nursing_records: List[Dict[str, Any]] = []
    seen = set()
    for record in patient_records:
        item = {
            "record_time": _pick(record, K_NURSE_RECORD_TIME, K_NURSE_RECORD_TIME_ALT, K_NURSE_FORM_TIME, "record_time"),
            "record_type": _pick(record, K_NURSE_TYPE, K_NURSE_TYPE_ALT, "record_type"),
            "recorder": _pick(record, K_NURSE_RECORDER, K_NURSE_RECORDER_ALT, K_RECORDER, "recorder"),
            "content": _pick(record, K_NURSE_CONTENT, K_NURSE_CONTENT_ALT, "content"),
            "vitals": {
                "temperature": _pick(record, K_TEMP, K_TEMP_ALT, "temperature"),
                "heart_rate_pulse": _pick(record, K_PULSE, K_PULSE_ALT, "heart_rate_pulse"),
                "respiratory_rate": _pick(record, K_RESP, K_RESP_ALT, "respiratory_rate"),
                "blood_pressure": _pick(record, K_BP, K_BP_ALT, "blood_pressure"),
                "oxygen_saturation": _pick(record, K_SPO2, K_SPO2_ALT, "oxygen_saturation"),
                "blood_glucose": _pick(record, K_BG, K_BG_ALT, "blood_glucose"),
            },
            "assessment": {
                "consciousness": _pick(record, K_CONSCIOUS, K_CONSCIOUS_ALT, "consciousness"),
                "skin_condition": _pick(record, K_SKIN, K_SKIN_ALT, "skin_condition"),
                "wound_condition": _pick(record, K_WOUND, K_WOUND_ALT, "wound_condition"),
                "tube_care": _pick(record, K_TUBE, K_TUBE_ALT, "tube_care"),
                "high_risk": _pick(record, K_HIGH_RISK, K_HIGH_RISK_ALT, "high_risk"),
            },
            "supportive_care": {
                "oxygen_nasal_cannula": _pick(record, K_OXY_NASAL, K_OXY_NASAL_ALT, "oxygen_nasal_cannula"),
                "oxygen_mask": _pick(record, K_OXY_MASK, K_OXY_MASK_ALT, "oxygen_mask"),
                "intake": _build_intake_text(record),
                "output": _build_output_text(record),
                "urine_volume": _pick(record, K_URINE, K_URINE_ALT, "urine_volume"),
            },
        }
        key = (
            item["record_time"],
            item["record_type"],
            item["recorder"],
            item["content"],
            tuple(item["vitals"].values()),
            tuple(item["assessment"].values()),
            tuple(item["supportive_care"].values()),
        )
        if not item["content"] and not item["record_time"] and not item["record_type"]:
            continue
        if key in seen:
            continue
        seen.add(key)
        nursing_records.append(item)
    return nursing_records


def _pick(record: Dict[str, Any], *keys: str | None) -> str:
    for key in keys:
        if not key:
            continue
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _build_intake_text(record: Dict[str, Any]) -> str:
    direct = _pick(record, K_INTAKE, K_INTAKE_ALT, "intake")
    if direct:
        return direct
    parts = [
        _pick(record, K_INTAKE_NAME, K_INTAKE_NAME_ALT),
        _pick(record, K_INTAKE_ROUTE, K_INTAKE_ROUTE_ALT),
        _pick(record, K_INTAKE_VALUE, K_INTAKE_VALUE_ALT),
    ]
    return " ".join([p for p in parts if p]).strip()


def _build_output_text(record: Dict[str, Any]) -> str:
    direct = _pick(record, K_OUTPUT, K_OUTPUT_ALT, "output")
    if direct:
        return direct
    parts = [
        _pick(record, K_OUTPUT_NAME, K_OUTPUT_NAME_ALT),
        _pick(record, K_OUTPUT_VALUE, K_OUTPUT_VALUE_ALT),
    ]
    return " ".join([p for p in parts if p]).strip()


def _join_pairs(values: Dict[str, Any]) -> str:
    pairs = []
    for key, value in values.items():
        text = str(value or "").strip()
        if text:
            pairs.append(f"{key}:{text}")
    return " | ".join(pairs) if pairs else "-"
