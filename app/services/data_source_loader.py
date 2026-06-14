"""
多数据源加载与患者分组。
"""
from __future__ import annotations

import copy
import logging
import math
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

from app.oracle_client import fetch_records, get_oracle_connection
from app.postgresql_client import fetch_pg_records
from app.emr_vastbase_client import fetch_emr_records, fetch_emr_documents_by_visits, fetch_emr_documents_by_visits_and_date
from app.schemas import AuditTypeConfig
from app.db_client_base import normalize_sql, validate_configurable_sql, build_oracle_execute_params
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


def _is_fanout_source(source_cfg: dict) -> bool:
    return str(source_cfg.get("load_strategy") or "bulk").strip().lower() == "fanout"


def _source_backend(source_cfg: dict) -> str:
    """返回源级后端配置；backend=default 视为未覆盖，兼容旧配置里的 data_source。"""
    backend = str(source_cfg.get("backend", "") or "").strip()
    if backend and backend != "default":
        return backend
    source_type = str(source_cfg.get("data_source", "") or "").strip()
    if source_type and source_type != "default":
        return source_type
    return "default"


def _effective_source_type(data_source: str, source_cfg: dict) -> str:
    backend = _source_backend(source_cfg)
    if backend == "oracle":
        return "oracle"
    if backend == "postgresql":
        return "postgresql"
    if backend == "emr_vastbase":
        return "emr_vastbase"
    return data_source


def _source_db_config(data_source: str, root_config: dict, source_cfg: dict) -> tuple[str, dict, dict]:
    effective_source = _effective_source_type(data_source, source_cfg)
    base_cfg = (
        ConfigParser.parse_postgresql_config(root_config)
        if effective_source == "postgresql"
        else ConfigParser.parse_oracle_config(root_config)
    )
    base_mapping = ConfigParser.get_field_mapping(root_config, effective_source)
    merged_cfg = copy.deepcopy(base_cfg)
    merged_cfg["query_sql"] = source_cfg.get("query_sql", "")
    merged_cfg["field_mapping"] = _merge_source_mapping(base_mapping, source_cfg.get("field_mapping", {}))
    return effective_source, merged_cfg, merged_cfg["field_mapping"]


def _fetch_inpatient_emr_records(
    root_config: dict,
    source_cfg: dict,
    query_date: str,
    dept_filter: list[str] | None,
    source_name: str,
) -> list[dict[str, Any]]:
    """在院日增量模式：Oracle v_qybr 查在院患者 → Vastbase v_blws 按日期查文书。

    与 _fetch_discharged_emr_records 的区别：
    - Oracle WHERE: 出院日期 IS NULL（当前在院患者）
    - Vastbase 使用 fetch_emr_documents_by_visits_and_date SQL 层按 query_date 过滤
    - 科室过滤仅用所在科室（在院患者无出院科室）
    """
    emr_cfg = ConfigParser.parse_emr_vastbase_config(root_config)
    if not emr_cfg.get("enabled"):
        logger.warning("在院模式：emr_vastbase 未启用，返回空结果 source=%s", source_name)
        return []

    oracle_cfg = ConfigParser.parse_oracle_config(root_config)
    if not oracle_cfg.get("host"):
        logger.warning("在院模式：Oracle 未配置，无法查询在院患者 source=%s", source_name)
        return []

    dept_list = [str(d).strip() for d in (dept_filter or []) if str(d).strip()]

    dept_cond = ""
    dept_params: dict[str, Any] = {}
    if dept_list:
        clauses = []
        for i, dept in enumerate(dept_list):
            param_key = f"inpat_dept_{i}"
            clauses.append(
                f'(a."所在科室编码" = :{param_key} OR a."所在科室名称" = :{param_key})'
            )
            dept_params[param_key] = dept
        dept_cond = " AND (" + " OR ".join(clauses) + ")"

    sql = normalize_sql(
        f"""
        SELECT a."患者ID" AS patient_id,
               a."次数" AS visit_number,
               a."住院号" AS admission_no,
               a."患者姓名" AS patient_name,
               a."所在科室名称" AS dept
        FROM jhemr.v_qybr a
        WHERE a."出院日期" IS NULL
          {dept_cond}
        """
    )

    params: dict[str, Any] = {}
    params.update(dept_params)
    execute_params = build_oracle_execute_params(sql, params)

    conn = None
    cur = None
    patient_keys: list[tuple[str, str]] = []
    patient_info: dict[tuple[str, str], dict[str, str]] = {}
    try:
        conn = get_oracle_connection(oracle_cfg)
        cur = conn.cursor()
        cur.execute(sql, execute_params)
        for row in cur:
            pid = str(row[0] or "").strip()
            vid = str(row[1] or "").strip()
            if not pid:
                continue
            patient_keys.append((pid, vid))
            patient_info[(pid, vid)] = {
                "patient_id": pid,
                "visit_number": vid,
                "admission_no": str(row[2] or ""),
                "patient_name": str(row[3] or ""),
                "dept": str(row[4] or ""),
            }
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            conn.close()

    if not patient_keys:
        logger.info("[inpatient_emr] query_date=%s 无在院患者 source=%s", query_date, source_name)
        return []

    logger.info(
        "[inpatient_emr] query_date=%s 在院患者=%d 开始查询 Vastbase 当天文书 source=%s",
        query_date, len(patient_keys), source_name,
    )

    document_kind = str(source_cfg.get("document_kind", "") or "").strip()
    kind_filter = str(source_cfg.get("kind_filter", "") or "").strip()

    docs_by_visit = fetch_emr_documents_by_visits_and_date(
        emr_cfg,
        patient_keys,
        query_date=query_date,
        document_kind=document_kind,
        kind_filter=kind_filter,
    )

    result: list[dict[str, Any]] = []
    for (pid, vid), docs in docs_by_visit.items():
        info = patient_info.get((pid, vid), {})
        for doc in docs:
            if info.get("patient_name") and not doc.get("patient_name"):
                doc["patient_name"] = info["patient_name"]
            if info.get("dept") and not doc.get("dept"):
                doc["dept"] = info["dept"]
            if info.get("admission_no") and not doc.get("admission_no"):
                doc["admission_no"] = info["admission_no"]
            result.append(doc)

    logger.info(
        "[inpatient_emr] source=%s 在院患者=%d 当天文书=%d query_date=%s",
        source_name, len(patient_keys), len(result), query_date,
    )
    return result


def _fetch_discharged_emr_records(
    root_config: dict,
    source_cfg: dict,
    query_date: str,
    dept_filter: list[str] | None,
    source_name: str,
) -> list[dict[str, Any]]:
    """出院终末模式：先从 Oracle v_qybr 查出院患者，再从 Vastbase v_blws 查文书。

    跨库两步查询：
    1. Oracle jhemr.v_qybr 按出院日期=query_date 获取患者列表
    2. Vastbase jhemr.v_blws 按 patient_id+visit_id 获取文书（含 kind_filter）
    3. 合并患者人口学信息到文书记录
    """
    emr_cfg = ConfigParser.parse_emr_vastbase_config(root_config)
    if not emr_cfg.get("enabled"):
        logger.warning("出院终末模式：emr_vastbase 未启用，返回空结果 source=%s", source_name)
        return []

    oracle_cfg = ConfigParser.parse_oracle_config(root_config)
    if not oracle_cfg.get("host"):
        logger.warning("出院终末模式：Oracle 未配置，无法查询出院患者 source=%s", source_name)
        return []

    dept_list = [str(d).strip() for d in (dept_filter or []) if str(d).strip()]

    dept_cond = ""
    dept_params: dict[str, Any] = {}
    if dept_list:
        clauses = []
        for i, dept in enumerate(dept_list):
            param_key = f"disch_dept_{i}"
            clauses.append(
                f'(a."所在科室编码" = :{param_key} OR a."所在科室名称" = :{param_key}'
                f' OR a."出院科室编码" = :{param_key} OR a."出院科室名称" = :{param_key})'
            )
            dept_params[param_key] = dept
        dept_cond = " AND (" + " OR ".join(clauses) + ")"

    sql = normalize_sql(
        f"""
        SELECT a."患者ID" AS patient_id,
               a."次数" AS visit_number,
               a."住院号" AS admission_no,
               a."患者姓名" AS patient_name,
               a."所在科室名称" AS dept,
               a."出院科室名称" AS discharge_dept,
               a."入院科室名称" AS admission_dept
        FROM jhemr.v_qybr a
        WHERE a."出院日期" >= TO_DATE(:query_date, 'yyyy-mm-dd')
          AND a."出院日期" < TO_DATE(:query_date, 'yyyy-mm-dd') + 1
          {dept_cond}
        """
    )

    params: dict[str, Any] = {"query_date": query_date}
    params.update(dept_params)
    execute_params = build_oracle_execute_params(sql, params)

    conn = None
    cur = None
    patient_keys: list[tuple[str, str]] = []
    patient_info: dict[tuple[str, str], dict[str, str]] = {}
    try:
        conn = get_oracle_connection(oracle_cfg)
        cur = conn.cursor()
        cur.execute(sql, execute_params)
        for row in cur:
            pid = str(row[0] or "").strip()
            vid = str(row[1] or "").strip()
            if not pid:
                continue
            patient_keys.append((pid, vid))
            patient_info[(pid, vid)] = {
                "patient_id": pid,
                "visit_number": vid,
                "admission_no": str(row[2] or ""),
                "patient_name": str(row[3] or ""),
                "dept": str(row[4] or ""),
                "discharge_dept_name": str(row[5] or ""),
                "admission_dept_name": str(row[6] or ""),
            }
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        if conn:
            conn.close()

    if not patient_keys:
        logger.info(
            "[discharge_emr] query_date=%s 无出院患者 source=%s",
            query_date, source_name,
        )
        return []

    logger.info(
        "[discharge_emr] query_date=%s 出院患者=%d 开始查询 Vastbase 文书 source=%s",
        query_date, len(patient_keys), source_name,
    )

    document_kind = str(source_cfg.get("document_kind", "") or "").strip()
    kind_filter = str(source_cfg.get("kind_filter", "") or "").strip()

    docs_by_visit = fetch_emr_documents_by_visits(
        emr_cfg,
        patient_keys,
        document_kind=document_kind,
        kind_filter=kind_filter,
    )

    result: list[dict[str, Any]] = []
    for (pid, vid), docs in docs_by_visit.items():
        info = patient_info.get((pid, vid), {})
        for doc in docs:
            if info.get("patient_name") and not doc.get("patient_name"):
                doc["patient_name"] = info["patient_name"]
            if info.get("dept") and not doc.get("dept"):
                doc["dept"] = info["dept"]
            if info.get("admission_no") and not doc.get("admission_no"):
                doc["admission_no"] = info["admission_no"]
            result.append(doc)

    logger.info(
        "[discharge_emr] source=%s 出院患者=%d 文书记录=%d query_date=%s",
        source_name, len(patient_keys), len(result), query_date,
    )
    return result


def _fetch_source_records(
    data_source: str,
    root_config: dict,
    source_cfg: dict,
    dept_filter: list[str] | None,
    query_date: str,
    source_name: str = "",
    date_dimension: str = "query_date",
) -> list[dict[str, Any]]:
    backend = _source_backend(source_cfg)

    if backend == "emr_vastbase":
        if date_dimension == "discharge_date":
            return _fetch_discharged_emr_records(root_config, source_cfg, query_date, dept_filter, source_name)
        if date_dimension == "inpatient_date":
            return _fetch_inpatient_emr_records(root_config, source_cfg, query_date, dept_filter, source_name)
        emr_cfg = ConfigParser.parse_emr_vastbase_config(root_config)
        if not emr_cfg.get("enabled"):
            logger.warning("source backend=emr_vastbase 但海量库未启用，返回空结果")
            return []
        document_kind = str(source_cfg.get("document_kind", "") or "").strip()
        kind_filter = str(source_cfg.get("kind_filter", "") or "").strip()
        return fetch_emr_records(emr_cfg, dept_filter or [], query_date, document_kind=document_kind, source_name=source_name, kind_filter=kind_filter)

    effective_source, merged_cfg, _field_mapping = _source_db_config(data_source, root_config, source_cfg)

    if effective_source == "postgresql":
        return fetch_pg_records(merged_cfg, dept_filter or [], query_date)
    return fetch_records(merged_cfg, dept_filter or [], query_date)


def _render_fanout_template(template: Any, values: dict[str, str]) -> str:
    text = "" if template is None else str(template)
    try:
        return text.format(**values)
    except KeyError as exc:
        raise ValueError(f"fanout_params 模板变量不存在: {exc}") from exc


def _build_fanout_params(bundle: PatientBundle, source_cfg: dict, query_date: str) -> dict[str, str]:
    patient_id = str(bundle.group_values.get("patient_id", "") or "").strip()
    visit_number = str(bundle.group_values.get("visit_number", "") or "").strip()
    try:
        parsed_query_date = datetime.strptime(query_date, "%Y-%m-%d")
    except ValueError:
        parsed_query_date = None
    fanout_window_days = int(source_cfg.get("fanout_date_window_days") or 61)
    if parsed_query_date:
        computed_date_from = (parsed_query_date - timedelta(days=fanout_window_days)).strftime("%Y-%m-%d")
    else:
        computed_date_from = query_date
    values = {
        "patient_id": patient_id,
        "visit_number": visit_number,
        "patient_key": f"{patient_id}_{visit_number}" if patient_id or visit_number else "",
        "query_date": query_date,
        "date_from": computed_date_from,
        "date_to": query_date,
    }
    for key, template in (source_cfg.get("fanout_params") or {}).items():
        values[str(key)] = _render_fanout_template(template, values)
    return values


def _oracle_fanout_worker(
    root_config: dict,
    source_cfg: dict,
    sql: str,
    bundles: list[PatientBundle],
    query_date: str,
) -> list[tuple[str, list[dict[str, Any]], str, int, bool]]:
    """使用单个 Oracle 连接串行处理一组 bundle，返回 (bundle_id, records, error, elapsed_ms, truncated)。"""
    base_cfg = ConfigParser.parse_oracle_config(root_config)
    conn = get_oracle_connection(base_cfg)
    timeout_ms = int(source_cfg.get("fanout_bundle_timeout_seconds") or 0) * 1000
    max_records = int(source_cfg.get("fanout_max_records_per_bundle") or 0)
    original_timeout = None
    timeout_supported = False
    results: list[tuple[str, list[dict[str, Any]], str, int, bool]] = []
    try:
        if timeout_ms:
            try:
                original_timeout = conn.callTimeout
                conn.callTimeout = timeout_ms
                timeout_supported = True
            except Exception as exc:
                logger.debug("Oracle callTimeout not available for fanout: %s", exc)
        for bundle in bundles:
            start = time.time()
            cur = None
            try:
                params = _build_fanout_params(bundle, source_cfg, query_date)
                execute_params = build_oracle_execute_params(sql, params)
                cur = conn.cursor()
                cur.execute(sql, execute_params)
                columns = [str(desc[0]).lower() for desc in cur.description]
                rows = cur.fetchall()
                truncated = False
                if max_records > 0 and len(rows) > max_records:
                    rows = rows[:max_records]
                    truncated = True
                records = [dict(zip(columns, row)) for row in rows]
                # fanout SQL 通常只查文书表，需补充分组字段供 normalize 使用。
                for record in records:
                    record.setdefault("患者ID", params.get("patient_id", ""))
                    record.setdefault("次数", params.get("visit_number", ""))
                    record.setdefault("patient_id", params.get("patient_id", ""))
                    record.setdefault("visit_number", params.get("visit_number", ""))
                elapsed = int((time.time() - start) * 1000)
                results.append((bundle.bundle_id, records, "", elapsed, truncated))
            except Exception as exc:
                elapsed = int((time.time() - start) * 1000)
                results.append((bundle.bundle_id, [], str(exc)[:500], elapsed, False))
            finally:
                if cur is not None:
                    try:
                        cur.close()
                    except Exception:
                        pass
    finally:
        if timeout_supported:
            try:
                conn.callTimeout = original_timeout
            except Exception:
                pass
        conn.close()
    return results


def _attach_fanout_source(
    bundles: dict[str, PatientBundle],
    data_source: str,
    root_config: dict,
    audit_type: AuditTypeConfig,
    source_name: str,
    source_cfg: dict,
    field_mapping: dict[str, str],
    query_date: str,
    diagnostics: dict[str, Any],
) -> None:
    effective_source = _effective_source_type(data_source, source_cfg)
    stats = {
        "bundles": len(bundles),
        "success": 0,
        "failed": 0,
        "rows": 0,
        "duration_ms": 0,
        "truncated": 0,
    }
    diagnostics.setdefault("fanout", {})[source_name] = stats
    diagnostics["source_row_counts"][source_name] = 0
    if not bundles:
        return
    if effective_source != "oracle":
        stats["failed"] = len(bundles)
        logger.warning(
            "[audit_type_loader] fanout source only supports oracle currently: code=%s source=%s backend=%s",
            audit_type.code,
            source_name,
            effective_source,
        )
        return

    query_sql = normalize_sql(source_cfg.get("query_sql") or "")
    validate_configurable_sql(query_sql, f"fanout source {source_name} SQL")
    if "{dept_filter}" in query_sql:
        query_sql = query_sql.format(dept_filter="1=1")
    workers = max(1, min(int(source_cfg.get("fanout_max_workers") or 1), len(bundles)))
    bundle_list = list(bundles.values())
    chunk_size = max(1, math.ceil(len(bundle_list) / workers))
    chunks = [bundle_list[index:index + chunk_size] for index in range(0, len(bundle_list), chunk_size)]
    started = time.time()
    logger.info(
        "[audit_type_loader] fanout_start code=%s source=%s bundles=%s workers=%s",
        audit_type.code,
        source_name,
        len(bundle_list),
        workers,
    )
    fanout_results: list[tuple[str, list[dict[str, Any]], str, int, bool]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_oracle_fanout_worker, root_config, source_cfg, query_sql, chunk, query_date): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            chunk = futures[future]
            try:
                fanout_results.extend(future.result())
            except Exception as exc:
                logger.warning(
                    "[audit_type_loader] fanout_worker_error code=%s source=%s bundles=%s err=%s",
                    audit_type.code,
                    source_name,
                    len(chunk),
                    str(exc)[:500],
                    exc_info=True,
                )
                fanout_results.extend((bundle.bundle_id, [], str(exc)[:500], 0, False) for bundle in chunk)

    for bundle_id, records, error, elapsed_ms, truncated in fanout_results:
        stats["duration_ms"] += elapsed_ms
        if truncated:
            stats["truncated"] += 1
            logger.warning(
                "[audit_type_loader] fanout_bundle_truncated code=%s source=%s bundle=%s rows=%s",
                audit_type.code,
                source_name,
                bundle_id,
                len(records),
            )
        if elapsed_ms >= 5000:
            logger.warning(
                "[audit_type_loader] fanout_bundle_slow code=%s source=%s bundle=%s duration_ms=%s rows=%s",
                audit_type.code,
                source_name,
                bundle_id,
                elapsed_ms,
                len(records),
            )
        if error:
            stats["failed"] += 1
            logger.warning(
                "[audit_type_loader] fanout_bundle_error code=%s source=%s bundle=%s err=%s",
                audit_type.code,
                source_name,
                bundle_id,
                error,
            )
            continue
        stats["success"] += 1
        stats["rows"] += len(records)
        diagnostics["source_row_counts"][source_name] += len(records)
        bundle = bundles.get(bundle_id)
        if not bundle:
            continue
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
            bundle.sources.setdefault(source_name, []).append(merged_record)
            bundle.source_field_mappings[source_name] = field_mapping
    total_ms = int((time.time() - started) * 1000)
    stats["wall_duration_ms"] = total_ms
    logger.info(
        "[audit_type_loader] fanout_done code=%s source=%s bundles=%s success=%s failed=%s rows=%s duration_ms=%s wall_duration_ms=%s truncated=%s",
        audit_type.code,
        source_name,
        stats["bundles"],
        stats["success"],
        stats["failed"],
        stats["rows"],
        stats["duration_ms"],
        total_ms,
        stats["truncated"],
    )


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
        logger.info(
            "audit_type=%s 使用 date_dimension=%s 加载数据",
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
    fanout_sources: list[tuple[str, dict[str, Any], dict[str, str]]] = []
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

        if _is_fanout_source(source_dict):
            fanout_sources.append((source_name, source_dict, field_mapping))
            diagnostics["source_row_counts"][source_name] = 0
            logger.info(
                "[audit_type_loader] defer fanout source code=%s source=%s",
                audit_type.code,
                source_name,
            )
            continue

        records = _fetch_source_records(
            data_source=data_source,
            root_config=root_config,
            source_cfg=source_dict,
            dept_filter=dept_filter,
            query_date=query_date,
            source_name=source_name,
            date_dimension=date_dimension,
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

    for source_name, source_dict, field_mapping in fanout_sources:
        _attach_fanout_source(
            bundles=bundles,
            data_source=data_source,
            root_config=root_config,
            audit_type=audit_type,
            source_name=source_name,
            source_cfg=source_dict,
            field_mapping=field_mapping,
            query_date=query_date,
            diagnostics=diagnostics,
        )

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
    missing_source_counts: dict[str, int] = {}
    missing_examples: list[dict[str, str]] = []
    for bundle in bundles.values():
        if anchor_sources and not any(bundle.sources.get(source_name) for source_name in anchor_sources):
            missing_required_count += 1
            for src in anchor_sources:
                missing_source_counts[src] = missing_source_counts.get(src, 0) + 1
            if len(missing_examples) < 5:
                missing_examples.append({"bundle_id": bundle.bundle_id, "missing": f"anchor:{','.join(sorted(anchor_sources))}"})
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
            for src in missing_required:
                missing_source_counts[src] = missing_source_counts.get(src, 0) + 1
            if len(missing_examples) < 5:
                missing_examples.append({"bundle_id": bundle.bundle_id, "missing": ",".join(missing_required)})
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
    diagnostics["missing_source_counts"] = missing_source_counts
    diagnostics["missing_bundle_examples"] = missing_examples
    if return_diagnostics:
        return filtered, diagnostics
    return filtered
