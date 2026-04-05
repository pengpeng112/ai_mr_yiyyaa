"""
结构化 Dify payload 组装。
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_dify_payload(
    patient_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str] | None = None,
    query_date: str = "",
) -> Dict[str, Any]:
    """按患者聚合记录，构建适合 Dify 解析的结构化 JSON。"""
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

    patient_id = _pick(first, mapping.get("patient_id", "患者ID"), "患者ID")
    visit_number = _pick(first, mapping.get("visit_number", "次数"), "次数")
    request_id = "_".join([part for part in [patient_id, visit_number, query_date] if part])

    payload = {
        "request_id": request_id,
        "audit_date": query_date,
        "match_rule": "patient_id + visit_number + date",
        "patient_info": {
            "patient_id": patient_id,
            "visit_number": visit_number,
            "admission_no": _pick(first, mapping.get("admission_no", "住院号"), "住院号"),
            "patient_name": _pick(first, mapping.get("patient_name", "患者姓名"), "患者姓名"),
            "gender": _pick(first, "性别"),
            "birth_date": _pick(first, "出生日期"),
            "admission_date": _pick(first, "入院日期"),
            "bed_no": _pick(first, "床号", "BED_NO"),
            "admission_diagnosis": _pick(first, "入院诊断"),
            "admission_condition": _pick(first, "入院病情"),
            "nursing_level_order": _pick(first, "医嘱护理级别", "护理级别"),
            "department": _pick(first, mapping.get("dept", "所在科室名称"), "所在科室名称"),
            "attending_doctor": _pick(first, "管床医生"),
        },
        "medical_documents": _build_medical_documents(patient_records),
        "nursing_records": _build_nursing_records(patient_records),
    }
    return payload


def build_dify_mr_text(
    patient_records: List[Dict[str, Any]],
    field_mapping: Dict[str, str] | None = None,
    query_date: str = "",
) -> str:
    """构建兼容旧版重试路径的纯文本病历摘要。"""
    payload = build_dify_payload(patient_records, field_mapping, query_date)
    patient_info = payload.get("patient_info", {}) or {}
    medical_documents = payload.get("medical_documents", []) or []
    nursing_records = payload.get("nursing_records", []) or []

    lines = [
        f"核查日期: {payload.get('audit_date', '')}",
        f"患者ID: {patient_info.get('patient_id', '')}",
        f"住院次数: {patient_info.get('visit_number', '')}",
        f"住院号: {patient_info.get('admission_no', '')}",
        f"患者姓名: {patient_info.get('patient_name', '')}",
        f"所在科室: {patient_info.get('department', '')}",
        "",
        "[病历文书]",
    ]

    for index, item in enumerate(medical_documents, start=1):
        lines.extend([
            f"{index}. 时间: {item.get('document_time', '')}",
            f"   名称: {item.get('document_name', '')}",
            f"   医师: {item.get('signed_doctor', '')}",
            f"   内容: {item.get('content', '')}",
        ])

    lines.extend(["", "[护理记录]"])
    for index, item in enumerate(nursing_records, start=1):
        lines.extend([
            f"{index}. 时间: {item.get('record_time', '')}",
            f"   类型: {item.get('record_type', '')}",
            f"   记录人: {item.get('recorder', '')}",
            f"   内容: {item.get('content', '')}",
        ])

    return "\n".join(line for line in lines if line is not None).strip()


def _build_medical_documents(patient_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    seen = set()
    for record in patient_records:
        item = {
            "document_time": _pick(record, "病历文书_完成时间", "病历标题时间"),
            "document_name": _pick(record, "病历文书_名称", "病历名称"),
            "signed_doctor": _pick(record, "病历文书_签名医师", "病历创建人", "创建人"),
            "content": _pick(record, "病历文书_内容", "病历内容"),
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
            "record_time": _pick(record, "护理记录_创建时间", "护理记录时间", "护理记录表单单创建时间"),
            "record_type": _pick(record, "护理记录_文书类型", "护理单类型"),
            "recorder": _pick(record, "护理记录_记录人", "护理记录人", "记录人"),
            "content": _pick(record, "护理记录_内容", "病情观察及护理措施"),
            "vitals": {
                "temperature": _pick(record, "护理记录_体温", "体温"),
                "heart_rate_pulse": _pick(record, "护理记录_心率脉搏", "心率脉搏"),
                "respiratory_rate": _pick(record, "护理记录_呼吸", "呼吸"),
                "blood_pressure": _pick(record, "护理记录_血压", "血压"),
                "oxygen_saturation": _pick(record, "护理记录_血氧饱和度", "血氧饱和度"),
                "blood_glucose": _pick(record, "护理记录_血糖", "血糖"),
            },
            "assessment": {
                "consciousness": _pick(record, "护理记录_意识神志", "意识神志"),
                "skin_condition": _pick(record, "护理记录_皮肤情况", "皮肤情况"),
                "wound_condition": _pick(record, "护理记录_刀口情况", "刀口情况"),
                "tube_care": _pick(record, "护理记录_管道护理", "管道护理"),
                "high_risk": _pick(record, "护理记录_高危风险", "高危风险"),
            },
            "supportive_care": {
                "oxygen_nasal_cannula": _pick(record, "护理记录_氧疗_鼻导管", "氧疗_鼻导管"),
                "oxygen_mask": _pick(record, "护理记录_氧疗_面罩", "氧疗_面罩"),
                "intake": _pick(record, "护理记录_入量情况", "入量情况"),
                "output": _pick(record, "护理记录_出量情况", "出量情况"),
                "urine_volume": _pick(record, "护理记录_尿量", "尿量"),
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


def _pick(record: Dict[str, Any], *keys: str) -> str:
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
