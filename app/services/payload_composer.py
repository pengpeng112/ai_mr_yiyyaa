"""按审计类型构造 Dify payload 与文本输入。

命名约定（ADR-4）：
- builder 返回字典字段统一使用 ``mr_text``（本地存储语义）。
- Dify 端输入变量默认 ``mr_txt``，由 ``dify_pusher`` 基于
  ``workflow_input_variable`` 将 ``mr_text`` 重映射后发送。
- 禁止在 builder 输出字典中直接使用 ``mr_txt``，避免 ``PushLog.mr_text`` 写空。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas import AuditTypeConfig
from app.services.builder_registry import get_builder, has_builder, register_builder
from app.services.frontpage_surgery_payload_builder import build_frontpage_surgery_first_progress_payload
from app.services.lab_exam_payload_builder import (
    build_lab_exam_progress_nursing_payload,
    build_lab_exam_structured_progress_nursing_payload,
)
from app.services.payload_builder import build_dify_mr_text, build_dify_payload

if TYPE_CHECKING:
    from app.services.data_source_loader import PatientBundle
else:
    PatientBundle = Any


def _pick(record: dict[str, Any], *keys: str | None) -> str:
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


def _first_source_record(bundle: PatientBundle) -> tuple[dict[str, Any], dict[str, str]]:
    for source_name in [bundle.primary_source, *bundle.sources.keys()]:
        records = bundle.sources.get(source_name) or []
        if records:
            return records[0], bundle.source_field_mappings.get(source_name, {})
    return {}, {}


def _extract_patient_info(bundle: PatientBundle) -> dict[str, str]:
    first_record, mapping = _first_source_record(bundle)
    return {
        "patient_id": bundle.group_values.get("patient_id", "") or _pick(first_record, mapping.get("patient_id"), "patient_id", "患者ID"),
        "visit_number": bundle.group_values.get("visit_number", "") or _pick(first_record, mapping.get("visit_number"), "visit_number", "次数"),
        "patient_name": _pick(first_record, mapping.get("patient_name"), "patient_name", "患者姓名"),
        "dept": _pick(first_record, mapping.get("dept"), "dept", "所在科室名称"),
        "admission_no": _pick(first_record, mapping.get("admission_no"), "admission_no", "住院号"),
        "attending_doctor_userid": _pick(first_record, "attending_doctor_userid", "attending_doctor_id", "doctor_id", "管床医生编号", "管床医生ID", "管床医师编号"),
        "attending_doctor_name": _pick(first_record, "attending_doctor_name", "attending_doctor", "doctor_name", "管床医生", "管床医师"),
        "nurse_head_userid": _pick(first_record, "nurse_head_userid", "nurse_head_id", "护士长ID"),
        "nurse_head_name": _pick(first_record, "nurse_head_name", "护士长"),
    }


def _format_record(record: dict[str, Any]) -> str:
    pairs = []
    for key, value in record.items():
        text = str(value or "").strip()
        if text:
            pairs.append(f"{key}: {text}")
    return "\n".join(pairs)


def _flatten_records_to_text(source_name: str, records: list[dict[str, Any]]) -> str:
    if not records:
        return f"[{source_name}] 无数据"
    sections = []
    for index, record in enumerate(records, start=1):
        sections.append(f"## {source_name} #{index}\n{_format_record(record)}")
    return "\n\n".join(sections)


def _default_template(source_names: list[str]) -> str:
    parts = []
    for source_name in source_names:
        parts.append(f"[{source_name}]\n{{{source_name}}}")
    return "\n\n".join(parts)


def compose(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> tuple[dict[str, Any], str]:
    """根据审计类型 builder 组装 payload 与 mr_text。"""
    payload_cfg = audit_type.payload or {}
    builder = str(payload_cfg.get("builder") or "generic_multi_source").strip()

    def _legacy_progress_nursing(
        _audit_type: AuditTypeConfig,
        _bundle: PatientBundle,
        _query_date: str,
    ) -> tuple[dict[str, Any], str]:
        patient_records = _bundle.sources.get(_bundle.primary_source) or next(iter(_bundle.sources.values()), [])
        field_mapping = _bundle.source_field_mappings.get(_bundle.primary_source, {})
        return (
            build_dify_payload(patient_records, field_mapping, _query_date),
            build_dify_mr_text(patient_records, field_mapping, _query_date),
        )

    def _generic_multi_source(
        _audit_type: AuditTypeConfig,
        _bundle: PatientBundle,
        _query_date: str,
    ) -> tuple[dict[str, Any], str]:
        patient_info = _extract_patient_info(_bundle)
        source_names = list(_bundle.sources.keys())
        rendered_sources = {
            source_name: _flatten_records_to_text(source_name, _bundle.sources.get(source_name, []))
            for source_name in source_names
        }
        text_template = str((_audit_type.payload or {}).get("text_template") or "").strip()
        if not text_template:
            text_template = _default_template(source_names)
        try:
            mr_text = text_template.format(**rendered_sources).strip()
        except KeyError:
            mr_text = _default_template(source_names).format(**rendered_sources).strip()

        payload = {
            "request_id": f"{_audit_type.code}:{_bundle.bundle_id}:{_query_date}",
            "audit_date": _query_date,
            "audit_type_code": _audit_type.code,
            "audit_type_name": _audit_type.name,
            "patient_info": patient_info,
            "sources": {
                source_name: {
                    "count": len(_bundle.sources.get(source_name, [])),
                    "records": _bundle.sources.get(source_name, []),
                    "text": rendered_sources.get(source_name, ""),
                }
                for source_name in source_names
            },
            "extra_fields": (_audit_type.payload or {}).get("extra_fields", {}) or {},
            "mr_text": mr_text,
        }
        return payload, mr_text

    def _build_admission_first_progress_payload(
        _audit_type: AuditTypeConfig,
        _bundle: PatientBundle,
        _query_date: str,
    ) -> tuple[dict[str, Any], str]:
        """入院记录 + 首次病程核查。总字数 ≤ 4000。"""
        patient_info = _extract_patient_info(_bundle)
        admission_records = _bundle.sources.get("admission", [])
        progress_records = _bundle.sources.get("progress", [])

        admission_text = ""
        for rec in admission_records[:1]:
            content = str(rec.get("content", "") or "")
            if len(content) > 2000:
                content = content[:2000]
            admission_text = f"【入院记录】\n创建时间: {rec.get('event_time', '')}\n创建人: {rec.get('creator', '')}\n{content}"

        progress_text = ""
        for rec in progress_records[:1]:
            content = str(rec.get("content", "") or "")
            if len(content) > 2000:
                content = content[:2000]
            progress_text = f"【首次病程记录】\n创建时间: {rec.get('event_time', '')}\n创建人: {rec.get('creator', '')}\n{content}"

        mr_text = f"{admission_text}\n\n{progress_text}".strip()
        if len(mr_text) > 4000:
            mr_text = mr_text[:4000]

        payload = {
            "request_id": f"{_audit_type.code}:{_bundle.bundle_id}:{_query_date}",
            "audit_date": _query_date,
            "audit_type_code": _audit_type.code,
            "audit_type_name": _audit_type.name,
            "patient_info": patient_info,
            "mr_text": mr_text,
        }
        return payload, mr_text

    def _build_surgery_chain_payload(
        _audit_type: AuditTypeConfig,
        _bundle: PatientBundle,
        _query_date: str,
    ) -> tuple[dict[str, Any], str]:
        """围手术期核查：术后首次病程 + 手术记录 + 术前小结。总字数 ≤ 5000。"""
        patient_info = _extract_patient_info(_bundle)
        # 单源模式：所有记录在 perioperative 源中，按 record_type 区分
        all_records = _bundle.sources.get("perioperative", []) or _bundle.sources.get("progress", []) + _bundle.sources.get("surgery", [])
        all_records.sort(key=lambda r: str(r.get("event_time", "") or ""))

        all_records.sort(key=lambda r: str(r.get("event_time", "") or ""))

        parts = []
        total = 0
        max_total = 5000
        # 手术记录优先，其次术前小结，再次术后病程
        for rec in all_records:
            if len(parts) >= 3:
                break
            rtype = str(rec.get("record_type", "") or rec.get("record_name", "") or "")
            content = str(rec.get("content", "") or "")
            if not content:
                continue
            limit = min(2000, max_total - total - 50)
            if limit <= 0:
                break
            if len(content) > limit:
                content = content[:limit]
            label = rtype if rtype else "围手术期文书"
            text = f"【{label}】\n时间: {rec.get('event_time', '')}\n创建人: {rec.get('creator', '')}\n{content}"
            parts.append(text)
            total += len(text)

        mr_text = "\n\n".join(parts).strip()
        if len(mr_text) > max_total:
            mr_text = mr_text[:max_total]

        payload = {
            "request_id": f"{_audit_type.code}:{_bundle.bundle_id}:{_query_date}",
            "audit_date": _query_date,
            "audit_type_code": _audit_type.code,
            "audit_type_name": _audit_type.name,
            "patient_info": patient_info,
            "mr_text": mr_text,
        }
        return payload, mr_text

    def _build_discharge_frontpage_payload(
        _audit_type: AuditTypeConfig,
        _bundle: PatientBundle,
        _query_date: str,
    ) -> tuple[dict[str, Any], str]:
        """出院记录 + 病案首页核查。总字数 ≤ 5000。"""
        patient_info = _extract_patient_info(_bundle)
        discharge_records = _bundle.sources.get("discharge", [])
        frontpage_records = _bundle.sources.get("frontpage", [])

        discharge_text = ""
        for rec in discharge_records[:1]:
            content = str(rec.get("content", "") or "")
            if len(content) > 3000:
                content = content[:3000]
            discharge_text = f"【出院记录】\n创建时间: {rec.get('event_time', '')}\n创建人: {rec.get('creator', '')}\n{content}"

        frontpage_text = ""
        for rec in frontpage_records[:1]:
            # 病案首页只取关键字段，不取全文
            key_fields = {
                "入院诊断": rec.get("admission_diagnosis", "") or rec.get("入院诊断", ""),
                "出院主诊断": rec.get("discharge_main_diagnosis", "") or rec.get("出院主诊断", ""),
                "手术名称": rec.get("surgery_name", "") or rec.get("手术名称", ""),
                "手术日期": rec.get("surgery_date", "") or rec.get("手术日期", ""),
            }
            lines = ["【病案首页关键字段】"]
            for k, v in key_fields.items():
                if v:
                    lines.append(f"{k}: {v}")
            frontpage_text = "\n".join(lines)

        mr_text = f"{discharge_text}\n\n{frontpage_text}".strip()
        if len(mr_text) > 5000:
            mr_text = mr_text[:5000]

        payload = {
            "request_id": f"{_audit_type.code}:{_bundle.bundle_id}:{_query_date}",
            "audit_date": _query_date,
            "audit_type_code": _audit_type.code,
            "audit_type_name": _audit_type.name,
            "patient_info": patient_info,
            "mr_text": mr_text,
        }
        return payload, mr_text

    defaults = {
        "legacy_progress_nursing": _legacy_progress_nursing,
        "generic_multi_source": _generic_multi_source,
        "lab_exam_progress_nursing": build_lab_exam_progress_nursing_payload,
        "lab_exam_structured_progress_nursing": build_lab_exam_structured_progress_nursing_payload,
        "frontpage_surgery_first_progress": build_frontpage_surgery_first_progress_payload,
        "admission_first_progress": _build_admission_first_progress_payload,
        "surgery_chain": _build_surgery_chain_payload,
        "discharge_frontpage": _build_discharge_frontpage_payload,
    }
    for name, handler in defaults.items():
        if not has_builder(name):
            register_builder(name, handler)

    selected_builder = get_builder(builder)
    return selected_builder(audit_type, bundle, query_date)
