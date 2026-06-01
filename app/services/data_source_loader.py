"""
多数据源加载与患者分组。
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any

from app.oracle_client import fetch_records
from app.postgresql_client import fetch_pg_records
from app.emr_vastbase_client import fetch_emr_records
from app.schemas import AuditTypeConfig
from app.services.config_parser import ConfigParser
from app.services.source_field_contract import normalize_source_record, should_attach_followup_progress

logger = logging.getLogger(__name__)


@dataclass
class PatientBundle:
    """单个患者/住院次的多源数据包。"""

    bundle_id: str
    group_values: dict[str, str]
    sources: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    source_field_mappings: dict[str, dict[str, str]] = field(default_factory=dict)
    primary_source: str = "primary"
    query_date: str = ""


def _merge_source_mapping(base_mapping: dict[str, str], source_mapping: dict[str, str]) -> dict[str, str]:
    merged = copy.deepcopy(base_mapping or {})
    merged.update(copy.deepcopy(source_mapping or {}))
    return merged


def _record_group_values(record: dict[str, Any], field_mapping: dict[str, str], group_key: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key in group_key or ["patient_id", "visit_number"]:
        mapped_key = str((field_mapping or {}).get(key) or key)
        value = record.get(mapped_key)
        if value in (None, "") and mapped_key != key:
            value = record.get(key)
        values[key] = str(value or "").strip()
    return values


def _bundle_id_from_values(values: dict[str, str], group_key: list[str]) -> str:
    ordered = [str(values.get(key, "") or "").strip() for key in group_key or ["patient_id", "visit_number"]]
    return "::".join(ordered)


def _get_progress_followup_days(audit_type: AuditTypeConfig) -> int:
    payload = audit_type.payload.model_dump() if hasattr(audit_type.payload, "model_dump") else dict(audit_type.payload or {})
    try:
        return int(payload.get("progress_followup_days", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _get_anchor_sources(audit_type: AuditTypeConfig) -> set[str]:
    """返回可创建推送 bundle 的源；其他源仅作为上下文附加。"""
    payload = audit_type.payload.model_dump() if hasattr(audit_type.payload, "model_dump") else dict(audit_type.payload or {})
    builder = str(payload.get("builder") or "").strip()
    if builder in {"lab_exam_progress_nursing", "lab_exam_structured_progress_nursing"}:
        return {"lab", "exam"}
    return set()


def _fetch_source_records(
    data_source: str,
    root_config: dict,
    source_cfg: dict,
    dept_filter: list[str] | None,
    query_date: str,
    source_name: str = "",
) -> list[dict[str, Any]]:
    backend = str(source_cfg.get("backend", "default") or "default").strip()

    if backend == "emr_vastbase":
        emr_cfg = ConfigParser.parse_emr_vastbase_config(root_config)
        if not emr_cfg.get("enabled"):
            logger.warning("source backend=emr_vastbase 但海量库未启用，返回空结果")
            return []
        document_kind = str(source_cfg.get("document_kind", "") or "").strip()
        return fetch_emr_records(emr_cfg, dept_filter or [], query_date, document_kind=document_kind, source_name=source_name)

    if backend == "oracle":
        effective_source = "oracle"
    elif backend == "postgresql":
        effective_source = "postgresql"
    else:
        effective_source = data_source

    base_cfg = (
        ConfigParser.parse_postgresql_config(root_config)
        if effective_source == "postgresql"
        else ConfigParser.parse_oracle_config(root_config)
    )
    base_mapping = ConfigParser.get_field_mapping(root_config, effective_source)
    merged_cfg = copy.deepcopy(base_cfg)
    merged_cfg["query_sql"] = source_cfg.get("query_sql", "")
    merged_cfg["field_mapping"] = _merge_source_mapping(base_mapping, source_cfg.get("field_mapping", {}))

    if effective_source == "postgresql":
        return fetch_pg_records(merged_cfg, dept_filter or [], query_date)
    return fetch_records(merged_cfg, dept_filter or [], query_date)


def _build_join_key_value(record: dict[str, Any], field_mapping: dict[str, str], join_key: str) -> str:
    """从记录中提取关联键的值。"""
    mapped_key = str((field_mapping or {}).get(join_key) or join_key)
    return str(record.get(mapped_key, "") or "").strip()


def _apply_join_rules(
    records_by_source: dict[str, list[dict[str, Any]]],
    field_mappings_by_source: dict[str, dict[str, str]],
    join_rules: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """应用关联规则，将多个数据源的记录按关联键合并。

    Args:
        records_by_source: 各数据源的记录列表
        field_mappings_by_source: 各数据源的字段映射
        join_rules: 关联规则列表

    Returns:
        合并后的记录列表（key 为 left_source 名称）
    """
    if not join_rules:
        return records_by_source

    result = copy.deepcopy(records_by_source)

    for rule in join_rules:
        left_source = rule.get("left_source", "")
        right_source = rule.get("right_source", "")
        join_keys = rule.get("join_keys", [])
        join_type = rule.get("join_type", "inner")

        if not left_source or not right_source or not join_keys:
            continue
        if left_source not in result:
            continue
        # 右侧源不存在时：inner join 清空左侧，left join 保留左侧
        if right_source not in result:
            if join_type == "inner":
                result[left_source] = []
            continue

        left_records = result.get(left_source, [])
        right_records = result.get(right_source, [])
        left_mapping = field_mappings_by_source.get(left_source, {})
        right_mapping = field_mappings_by_source.get(right_source, {})

        # 构建右侧记录的索引（关联键值 -> 记录列表）
        right_index: dict[str, list[dict[str, Any]]] = {}
        for right_record in right_records:
            key_parts = []
            for jk in join_keys:
                key_value = _build_join_key_value(right_record, right_mapping, jk.get("right", ""))
                key_parts.append(key_value)
            index_key = "::".join(key_parts)
            right_index.setdefault(index_key, []).append(right_record)

        # 合并记录
        merged_records: list[dict[str, Any]] = []
        for left_record in left_records:
            key_parts = []
            for jk in join_keys:
                key_value = _build_join_key_value(left_record, left_mapping, jk.get("left", ""))
                key_parts.append(key_value)
            index_key = "::".join(key_parts)

            matched_rights = right_index.get(index_key, [])
            if matched_rights:
                # 内连接：左侧记录与右侧记录合并（右侧字段不覆盖左侧已有字段）
                for right_record in matched_rights:
                    merged = copy.deepcopy(left_record)
                    for key, value in right_record.items():
                        if key not in merged:
                            merged[key] = value
                        else:
                            # 冲突字段以 right_source.key 保留
                            merged[f"{right_source}.{key}"] = value
                    merged_records.append(merged)
            elif join_type == "left":
                # 左连接：保留左侧记录
                merged_records.append(copy.deepcopy(left_record))

        result[left_source] = merged_records
        # 右侧数据源已被合并到左侧，清空
        if join_type == "inner":
            result[right_source] = []

    return result


def load_patient_bundles(
    audit_type: AuditTypeConfig,
    root_config: dict,
    query_date: str,
    date_dimension: str = "query_date",
    dept_filter: list[str] | None = None,
    return_diagnostics: bool = False,
) -> list[PatientBundle] | tuple[list[PatientBundle], dict]:
    """按审计类型配置加载多源数据，并按 group_key 合并。

    Args:
        return_diagnostics: 若为 True，返回 (bundles, diagnostics) 元组

    Returns:
        默认返回 bundles 列表；return_diagnostics=True 时返回 (bundles, diagnostics)
    """
    if date_dimension != "query_date":
        logger.warning(
            "audit_type=%s 当前多源加载仅显式透传 query_date，date_dimension=%s 需在 SQL 内自行处理",
            audit_type.code,
            date_dimension,
        )

    data_source = ConfigParser.get_data_source_type(root_config)
    bundles: dict[str, PatientBundle] = {}
    required_sources: set[str] = set()
    source_names = list((audit_type.sources or {}).keys())
    diagnostics: dict[str, Any] = {"source_row_counts": {}, "skipped_records": 0}
    primary_candidates = [name for name in source_names if name != "patient"]
    primary_source = "primary" if "primary" in primary_candidates else (primary_candidates[0] if primary_candidates else "primary")
    patient_records_by_bundle_id: dict[str, list[dict[str, Any]]] = {}
    patient_field_mapping: dict[str, str] = {}
    context_records_by_source: dict[str, dict[str, list[dict[str, Any]]]] = {}
    context_field_mappings: dict[str, dict[str, str]] = {}
    followup_days = _get_progress_followup_days(audit_type)
    anchor_sources = _get_anchor_sources(audit_type)

    # 获取关联规则配置
    join_rules = []
    if hasattr(audit_type, "join_rules") and audit_type.join_rules:
        join_rules = [rule.model_dump() if hasattr(rule, "model_dump") else dict(rule) for rule in audit_type.join_rules]

    for source_name, source in (audit_type.sources or {}).items():
        source_dict = source.model_dump() if hasattr(source, "model_dump") else dict(source or {})
        field_mapping = _merge_source_mapping(
            ConfigParser.get_field_mapping(root_config, data_source),
            source_dict.get("field_mapping", {}) or {},
        )
        is_context_only = bool(anchor_sources) and source_name not in anchor_sources and source_name != "patient"
        is_alternative_anchor = bool(anchor_sources) and source_name in anchor_sources
        if bool(source_dict.get("required", True)) and not is_context_only and not is_alternative_anchor:
            required_sources.add(source_name)

        records = _fetch_source_records(
            data_source=data_source,
            root_config=root_config,
            source_cfg=source_dict,
            dept_filter=dept_filter,
            query_date=query_date,
            source_name=source_name,
        )
        diagnostics["source_row_counts"][source_name] = len(records)
        logger.info(
            "[audit_type_loader] code=%s source=%s query_date=%s rows=%s",
            audit_type.code,
            source_name,
            query_date,
            len(records),
        )

        for record in records:
            canonical, errors = normalize_source_record(
                source_name=source_name,
                record=record,
                field_mapping=field_mapping,
                query_date=query_date,
            )
            if errors:
                diagnostics["skipped_records"] += 1
                logger.info(
                    "[audit_type_loader] skip source=%s code=%s reason=%s",
                    source_name,
                    audit_type.code,
                    ";".join(errors),
                )
                continue

            merged_record = copy.deepcopy(record)
            merged_record.update(canonical)
            group_values = _record_group_values(merged_record, field_mapping, audit_type.group_key)
            bundle_id = _bundle_id_from_values(group_values, audit_type.group_key)
            if not bundle_id.strip(":"):
                continue
            if (
                source_name == "progress"
                and "audit_date" in (audit_type.group_key or [])
                and should_attach_followup_progress(
                    merged_record.get("audit_date", ""),
                    query_date,
                    followup_days,
                )
            ):
                group_values["audit_date"] = query_date
                merged_record["is_followup_progress"] = True
            bundle_id = _bundle_id_from_values(group_values, audit_type.group_key)
            if not bundle_id.strip(":"):
                continue
            if source_name == "patient":
                patient_records_by_bundle_id.setdefault(bundle_id, []).append(merged_record)
                patient_field_mapping = field_mapping
                continue
            if is_context_only:
                context_records_by_source.setdefault(source_name, {}).setdefault(bundle_id, []).append(merged_record)
                context_field_mappings[source_name] = field_mapping
                continue
            if bundle_id not in bundles:
                bundles[bundle_id] = PatientBundle(
                    bundle_id=bundle_id,
                    group_values=group_values,
                    sources={},
                    source_field_mappings={},
                    primary_source=primary_source,
                    query_date=query_date,
                )
            bundle = bundles[bundle_id]
            bundle.sources.setdefault(source_name, []).append(merged_record)
            bundle.source_field_mappings[source_name] = field_mapping

    # 应用关联规则（如果有）
    if join_rules:
        # 在单个 bundle 内应用关联规则，避免跨患者/住院次错误合并
        for bundle in list(bundles.values()):
            # 收集参与关联的源（排除 patient 和 context-only 源）
            join_source_names = set()
            for rule in join_rules:
                join_source_names.add(rule.get("left_source", ""))
                join_source_names.add(rule.get("right_source", ""))
            join_source_names.discard("")

            # 只对参与关联的源执行 join
            records_for_join: dict[str, list[dict[str, Any]]] = {}
            mappings_for_join: dict[str, dict[str, str]] = {}
            for source_name in join_source_names:
                if source_name in bundle.sources:
                    records_for_join[source_name] = bundle.sources[source_name]
                if source_name in bundle.source_field_mappings:
                    mappings_for_join[source_name] = bundle.source_field_mappings[source_name]

            if not records_for_join:
                continue

            merged = _apply_join_rules(records_for_join, mappings_for_join, join_rules)

            # 将合并结果写回 bundle，同时保留未参与关联的源（patient、context 等）
            for source_name, records in merged.items():
                bundle.sources[source_name] = records

            # 内连接时右侧源被清空后，从 bundle 中移除空源
            empty_sources = [name for name, records in bundle.sources.items() if not records and name in join_source_names]
            for name in empty_sources:
                del bundle.sources[name]

        # join_rules 处理后，仍然挂载 patient 和 context 源
        for source_name, records_by_bundle_id in context_records_by_source.items():
            for bundle_id, context_records in records_by_bundle_id.items():
                bundle = bundles.get(bundle_id)
                if not bundle:
                    continue
                bundle.sources.setdefault(source_name, []).extend(context_records)
                bundle.source_field_mappings[source_name] = context_field_mappings.get(source_name, {})

        for bundle_id, patient_records in patient_records_by_bundle_id.items():
            bundle = bundles.get(bundle_id)
            if not bundle:
                continue
            bundle.sources["patient"] = patient_records
            bundle.source_field_mappings["patient"] = patient_field_mapping
    else:
        # 原有逻辑：合并上下文和患者记录
        for source_name, records_by_bundle_id in context_records_by_source.items():
            for bundle_id, context_records in records_by_bundle_id.items():
                bundle = bundles.get(bundle_id)
                if not bundle:
                    continue
                bundle.sources.setdefault(source_name, []).extend(context_records)
                bundle.source_field_mappings[source_name] = context_field_mappings.get(source_name, {})

        for bundle_id, patient_records in patient_records_by_bundle_id.items():
            bundle = bundles.get(bundle_id)
            if not bundle:
                continue
            bundle.sources["patient"] = patient_records
            bundle.source_field_mappings["patient"] = patient_field_mapping

    filtered: list[PatientBundle] = []
    missing_required_count = 0
    for bundle in bundles.values():
        if anchor_sources and not any(bundle.sources.get(source_name) for source_name in anchor_sources):
            missing_required_count += 1
            logger.info(
                "[audit_type_loader] skip bundle=%s code=%s missing_anchor_sources=%s reason=missing_anchor_sources",
                bundle.bundle_id,
                audit_type.code,
                ",".join(sorted(anchor_sources)),
            )
            continue
        missing_required = [source_name for source_name in required_sources if not bundle.sources.get(source_name)]
        if missing_required:
            missing_required_count += 1
            logger.info(
                "[audit_type_loader] skip bundle=%s code=%s missing_required=%s reason=missing_required_sources",
                bundle.bundle_id,
                audit_type.code,
                ",".join(missing_required),
            )
            continue
        filtered.append(bundle)

    filtered.sort(key=lambda item: item.bundle_id)
    diagnostics["missing_required_bundles"] = missing_required_count
    if return_diagnostics:
        return filtered, diagnostics
    return filtered
