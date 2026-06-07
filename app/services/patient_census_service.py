"""
患者概述与患者清单服务。
基于 jhemr.v_qybr 统一入口，支持在院/出院患者查询、统计和只读预检。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from app.oracle_client import get_oracle_connection
from app.services.config_parser import ConfigParser
from app.db_client_base import normalize_sql, build_oracle_execute_params
from app.services.audit_type_registry import AuditTypeRegistry
from app.services.data_source_loader import load_patient_bundles
from app.services.audit_precheck import summarize_bundles
from app.schemas import AuditTypeConfig

logger = logging.getLogger(__name__)

_PRECHECK_LOCK = threading.Lock()
_SUMMARY_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL_SECONDS = 300

_QYBR_REQUIRED_COLUMNS = {
    "患者ID", "次数", "住院号", "患者姓名",
    "入院日期", "出院日期",
    "所在科室编码", "所在科室名称",
    "出院科室编码", "出院科室名称",
}

_QYBR_OPTIONAL_COLUMNS = {
    "性别", "年龄", "出生日期",
    "管床医生", "管床医生编号",
    "入院诊断", "出院主诊断",
    "是否出院", "入院病情", "护理级别",
    "入院科室编码", "入院科室名称",
    "出院其他诊断1", "出院其他诊断2", "出院其他诊断3",
    "出院其他诊断4", "出院其他诊断5",
    "手术", "手术日期",
    "手术1", "手术日期1",
    "手术2", "手术日期2",
    "手术3", "手术日期3",
    "手术4", "手术日期4",
    "手术5", "手术日期5",
}

_DISCHARGE_SQL = """
SELECT
  a.患者ID AS 患者ID,
  a.次数 AS 次数,
  a.住院号 AS 住院号,
  a.患者姓名 AS 患者姓名,
  a.出生日期 AS 出生日期,
  a.性别 AS 性别,
  a.年龄 AS 年龄,
  a.入院日期 AS 入院日期,
  a.出院日期 AS 出院日期,
  a.入院诊断 AS 入院诊断,
  a.入院病情 AS 入院病情,
  a.管床医生编号 AS 管床医生编号,
  a.管床医生 AS 管床医生,
  a.护理级别 AS 护理级别,
  a.所在科室编码 AS 所在科室编码,
  a.所在科室名称 AS 所在科室名称,
  a.是否出院 AS 是否出院,
  a.入院科室编码 AS 入院科室编码,
  a.入院科室名称 AS 入院科室名称,
  a.出院科室编码 AS 出院科室编码,
  a.出院科室名称 AS 出院科室名称,
  a.出院主诊断 AS 出院主诊断,
  a.出院其他诊断1 AS 出院其他诊断1,
  a.出院其他诊断2 AS 出院其他诊断2,
  a.出院其他诊断3 AS 出院其他诊断3,
  a.出院其他诊断4 AS 出院其他诊断4,
  a.出院其他诊断5 AS 出院其他诊断5,
  a.手术 AS 手术,
  a.手术日期 AS 手术日期,
  a.手术1 AS 手术1,
  a.手术日期1 AS 手术日期1,
  a.手术2 AS 手术2,
  a.手术日期2 AS 手术日期2,
  a.手术3 AS 手术3,
  a.手术日期3 AS 手术日期3,
  a.手术4 AS 手术4,
  a.手术日期4 AS 手术日期4,
  a.手术5 AS 手术5,
  a.手术日期5 AS 手术日期5
FROM jhemr.v_qybr a
WHERE a.出院日期 >= TO_DATE(:query_date, 'yyyy-mm-dd')
  AND a.出院日期 < TO_DATE(:query_date, 'yyyy-mm-dd') + 1
"""

_INPATIENT_SQL = """
SELECT
  a.患者ID AS 患者ID,
  a.次数 AS 次数,
  a.住院号 AS 住院号,
  a.患者姓名 AS 患者姓名,
  a.出生日期 AS 出生日期,
  a.性别 AS 性别,
  a.年龄 AS 年龄,
  a.入院日期 AS 入院日期,
  a.出院日期 AS 出院日期,
  a.入院诊断 AS 入院诊断,
  a.入院病情 AS 入院病情,
  a.管床医生编号 AS 管床医生编号,
  a.管床医生 AS 管床医生,
  a.护理级别 AS 护理级别,
  a.所在科室编码 AS 所在科室编码,
  a.所在科室名称 AS 所在科室名称,
  a.是否出院 AS 是否出院,
  a.入院科室编码 AS 入院科室编码,
  a.入院科室名称 AS 入院科室名称,
  a.出院科室编码 AS 出院科室编码,
  a.出院科室名称 AS 出院科室名称,
  a.出院主诊断 AS 出院主诊断,
  a.出院其他诊断1 AS 出院其他诊断1,
  a.出院其他诊断2 AS 出院其他诊断2,
  a.出院其他诊断3 AS 出院其他诊断3,
  a.出院其他诊断4 AS 出院其他诊断4,
  a.出院其他诊断5 AS 出院其他诊断5,
  a.手术 AS 手术,
  a.手术日期 AS 手术日期,
  a.手术1 AS 手术1,
  a.手术日期1 AS 手术日期1,
  a.手术2 AS 手术2,
  a.手术日期2 AS 手术日期2,
  a.手术3 AS 手术3,
  a.手术日期3 AS 手术日期3,
  a.手术4 AS 手术4,
  a.手术日期4 AS 手术日期4,
  a.手术5 AS 手术5,
  a.手术日期5 AS 手术日期5
FROM jhemr.v_qybr a
WHERE a.出院日期 IS NULL
"""


def _ymd(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _dt_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _mask_name(name: str) -> str:
    if not name or len(name) <= 1:
        return "*"
    prefix = name[0]
    suffix = "*" if len(name) <= 2 else "*" + ("*" * (len(name) - 2))
    return prefix + suffix


def _mask_admission_no(no: str) -> str:
    if not no:
        return ""
    if len(no) <= 3:
        return no[0] + "***"
    return no[:3] + "*" * (len(no) - 3)


def _normalize_census_record(row: tuple, columns: list[str]) -> dict:
    record = dict(zip(columns, row))
    surgeries: list[dict] = []
    for idx in range(6):
        suffix = "" if idx == 0 else str(idx)
        surgery_name = str(record.get(f"手术{suffix}", "") or "").strip()
        surgery_date = _ymd(record.get(f"手术日期{suffix}"))
        if surgery_name or surgery_date:
            surgeries.append({
                "name": surgery_name,
                "date": surgery_date,
            })

    discharge_main = str(record.get("出院主诊断", "") or "").strip()

    other_diagnoses = []
    for i in range(1, 6):
        diag = str(record.get(f"出院其他诊断{i}", "") or "").strip()
        if diag:
            other_diagnoses.append(diag)

    return {
        "patient_id": str(record.get("患者ID", "") or "").strip(),
        "visit_number": str(record.get("次数", "") or "").strip(),
        "admission_no": str(record.get("住院号", "") or "").strip(),
        "patient_name": str(record.get("患者姓名", "") or "").strip(),
        "gender": str(record.get("性别", "") or "").strip(),
        "age": str(record.get("年龄", "") or "").strip(),
        "admission_date": _dt_str(record.get("入院日期")),
        "discharge_date": _dt_str(record.get("出院日期")),
        "current_dept_code": str(record.get("所在科室编码", "") or "").strip(),
        "current_dept_name": str(record.get("所在科室名称", "") or "").strip(),
        "admission_dept_code": str(record.get("入院科室编码", "") or "").strip(),
        "admission_dept_name": str(record.get("入院科室名称", "") or "").strip(),
        "discharge_dept_code": str(record.get("出院科室编码", "") or "").strip(),
        "discharge_dept_name": str(record.get("出院科室名称", "") or "").strip(),
        "doctor_code": str(record.get("管床医生编号", "") or "").strip(),
        "doctor_name": str(record.get("管床医生", "") or "").strip(),
        "admission_diagnosis": str(record.get("入院诊断", "") or "").strip(),
        "discharge_main_diagnosis": discharge_main,
        "discharge_other_diagnoses": other_diagnoses,
        "discharge_status": str(record.get("是否出院", "") or "").strip(),
        "surgeries": surgeries,
        "admission_condition": str(record.get("入院病情", "") or "").strip(),
        "nursing_level": str(record.get("护理级别", "") or "").strip(),
    }


def _apply_masking(item: dict) -> dict:
    item["patient_name"] = _mask_name(item["patient_name"])
    item["admission_no"] = _mask_admission_no(item["admission_no"])
    return item


def _assert_data_source_oracle(config: dict) -> None:
    ds_type = ConfigParser.get_data_source_type(config)
    if ds_type != "oracle":
        raise RuntimeError(f"患者清单仅支持 Oracle 数据源，当前数据源类型: {ds_type}")


def inspect_qybr_columns(config: dict) -> dict:
    _assert_data_source_oracle(config)
    oracle_cfg = ConfigParser.parse_oracle_config(config)
    conn = get_oracle_connection(oracle_cfg)
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM jhemr.v_qybr WHERE ROWNUM <= 1")
        available = {d[0] for d in cur.description}
        missing_required = sorted(_QYBR_REQUIRED_COLUMNS - available)
        missing_optional = sorted(_QYBR_OPTIONAL_COLUMNS - available)
        warnings = []
        if missing_required:
            warnings.append(f"缺少必须字段: {', '.join(missing_required)}")
        if missing_optional:
            warnings.append(f"缺少可选字段: {', '.join(missing_optional)}")
        return {
            "available_columns": sorted(available),
            "missing_required_columns": missing_required,
            "missing_optional_columns": missing_optional,
            "warnings": warnings,
        }
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        conn.close()


def get_qybr_metadata(config: dict) -> dict:
    _assert_data_source_oracle(config)
    oracle_cfg = ConfigParser.parse_oracle_config(config)
    conn = get_oracle_connection(oracle_cfg)
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM jhemr.v_qybr")
        total = int(cur.fetchone()[0] or 0)

        cur.execute("SELECT MIN(入院日期), MAX(入院日期), MIN(出院日期), MAX(出院日期) FROM jhemr.v_qybr")
        min_adm, max_adm, min_dis, max_dis = cur.fetchone()
        min_admission_date = _dt_str(min_adm)
        max_admission_date = _dt_str(max_adm)
        min_discharge_date = _dt_str(min_dis)
        max_discharge_date = _dt_str(max_dis)

        cur.execute("SELECT COUNT(*) FROM jhemr.v_qybr WHERE 出院日期 IS NULL")
        null_discharge = int(cur.fetchone()[0] or 0)
        nonnull_discharge = total - null_discharge

        cur.execute("SELECT DISTINCT 是否出院 FROM jhemr.v_qybr WHERE 是否出院 IS NOT NULL")
        status_values = sorted(str(r[0] or "").strip() for r in cur.fetchall() if r[0])

        column_info = inspect_qybr_columns(config)

        return {
            "view_name": "jhemr.v_qybr",
            "total_rows": total,
            "min_admission_date": min_admission_date,
            "max_admission_date": max_admission_date,
            "min_discharge_date": min_discharge_date,
            "max_discharge_date": max_discharge_date,
            "null_discharge_date_count": null_discharge,
            "nonnull_discharge_date_count": nonnull_discharge,
            "status_values": status_values,
            "available_columns": column_info["available_columns"],
            "missing_required_columns": column_info["missing_required_columns"],
            "missing_optional_columns": column_info["missing_optional_columns"],
            "warnings": column_info["warnings"],
        }
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        conn.close()


def _build_dept_condition(dept_filter: list[str], dept_field_code: str, dept_field_name: str) -> tuple[str, dict]:
    if not dept_filter:
        return "1=1", {}
    depts = [str(d).strip() for d in dept_filter if str(d).strip()]
    if not depts:
        return "1=1", {}
    clauses = []
    params = {}
    for i, dept in enumerate(depts):
        clauses.append(f"{dept_field_code} = :census_dept_value_{i}")
        clauses.append(f"{dept_field_name} = :census_dept_value_{i}")
        params[f"census_dept_value_{i}"] = dept
    return "(" + " OR ".join(clauses) + ")", params


def load_patient_census(
    config: dict,
    mode: str,
    query_date: str | None = None,
    dept_filter: list[str] | None = None,
    limit: int = 50,
    masking_enabled: bool = True,
) -> tuple[list[dict], int]:
    _assert_data_source_oracle(config)
    oracle_cfg = ConfigParser.parse_oracle_config(config)
    dept_list = [d for d in (dept_filter or []) if str(d).strip()]

    if mode == "discharged":
        if not query_date:
            query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        dept_cond, dept_params = _build_dept_condition(dept_list, "出院科室编码", "出院科室名称")
        base_sql = normalize_sql(_DISCHARGE_SQL)
        sql = f"SELECT * FROM ({base_sql} AND ({dept_cond}) ORDER BY a.出院日期 DESC, a.患者ID, a.次数) WHERE ROWNUM <= :census_limit"
        params = {"query_date": query_date, "census_limit": limit}
        params.update(dept_params)
    elif mode == "inpatient":
        dept_cond, dept_params = _build_dept_condition(dept_list, "所在科室编码", "所在科室名称")
        base_sql = normalize_sql(_INPATIENT_SQL)
        sql = f"SELECT * FROM ({base_sql} AND ({dept_cond}) ORDER BY a.所在科室编码, a.患者ID, a.次数) WHERE ROWNUM <= :census_limit"
        params = {"census_limit": limit}
        params.update(dept_params)
    else:
        raise ValueError(f"unsupported mode: {mode}")

    params = build_oracle_execute_params(sql, params)

    conn = get_oracle_connection(oracle_cfg)
    cur = None
    try:
        start = time.time()
        cur = conn.cursor()
        cur.execute(sql, params)
        columns = [str(d[0]) for d in cur.description]
        rows = cur.fetchall()
        elapsed_ms = int((time.time() - start) * 1000)
        logger.info(
            "patient_census mode=%s query_date=%s dept_filter=%s rows=%s elapsed_ms=%s",
            mode, query_date, dept_list, len(rows), elapsed_ms,
        )
        items = []
        for row in rows:
            item = _normalize_census_record(row, columns)
            if masking_enabled:
                item = _apply_masking(item)
            items.append(item)
        total = len(items)
        return items, total
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        conn.close()


def count_patient_census(
    config: dict,
    mode: str,
    query_date: str | None = None,
    dept_filter: list[str] | None = None,
) -> int:
    _assert_data_source_oracle(config)
    oracle_cfg = ConfigParser.parse_oracle_config(config)
    dept_list = [d for d in (dept_filter or []) if str(d).strip()]

    if mode == "discharged":
        if not query_date:
            query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        dept_cond, dept_params = _build_dept_condition(dept_list, "出院科室编码", "出院科室名称")
        sql = normalize_sql(
            f"""
            SELECT COUNT(*) AS cnt
            FROM jhemr.v_qybr a
            WHERE a.出院日期 >= TO_DATE(:query_date, 'yyyy-mm-dd')
              AND a.出院日期 < TO_DATE(:query_date, 'yyyy-mm-dd') + 1
              AND ({dept_cond})
            """
        )
        params = {"query_date": query_date}
        params.update(dept_params)
    elif mode == "inpatient":
        dept_cond, dept_params = _build_dept_condition(dept_list, "所在科室编码", "所在科室名称")
        sql = normalize_sql(
            f"""
            SELECT COUNT(*) AS cnt
            FROM jhemr.v_qybr a
            WHERE a.出院日期 IS NULL
              AND ({dept_cond})
            """
        )
        params = dept_params
    else:
        raise ValueError(f"unsupported mode: {mode}")

    execute_params = build_oracle_execute_params(sql, params)
    conn = get_oracle_connection(oracle_cfg)
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(sql, execute_params)
        return int((cur.fetchone() or [0])[0] or 0)
    finally:
        if cur:
            try:
                cur.close()
            except Exception:
                pass
        conn.close()


def summarize_patient_census(
    config: dict,
    mode: str,
    query_date: str | None = None,
    dept_filter: list[str] | None = None,
) -> dict:
    cached = _read_summary_cache(mode, query_date, dept_filter)
    if cached:
        return cached

    dept_list = [d for d in (dept_filter or []) if str(d).strip()]

    if mode == "discharged":
        if not query_date:
            query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    elif mode == "inpatient":
        query_date = ""
    else:
        raise ValueError(f"unsupported mode: {mode}")

    total = count_patient_census(config, mode, query_date or None, dept_list)
    items, sampled_total = load_patient_census(
        config, mode, query_date or None, dept_list,
        limit=5000, masking_enabled=False,
    )
    warnings = []
    if total > sampled_total:
        warnings.append("dept_counts and date_range are based on first 5000 census rows")

    dept_counts_map: dict[tuple[str, str], int] = {}
    metadata: dict = {}
    min_adm = ""
    max_adm = ""
    min_dis = ""
    max_dis = ""

    for item in items:
        code = item.get("discharge_dept_code" if mode == "discharged" else "current_dept_code", "")
        name = item.get("discharge_dept_name" if mode == "discharged" else "current_dept_name", "")
        if code or name:
            dept_counts_map[(code, name)] = dept_counts_map.get((code, name), 0) + 1

        adm = item.get("admission_date", "")
        dis = item.get("discharge_date", "")
        if adm:
            if not min_adm or adm < min_adm:
                min_adm = adm
            if not max_adm or adm > max_adm:
                max_adm = adm
        if dis:
            if not min_dis or dis < min_dis:
                min_dis = dis
            if not max_dis or dis > max_dis:
                max_dis = dis

    dept_counts = sorted(
        [{"dept_code": k[0], "dept_name": k[1], "count": v} for k, v in dept_counts_map.items()],
        key=lambda x: x["count"], reverse=True,
    )

    if mode == "discharged" and min_adm:
        metadata = {
            "min_admission_date": min_adm,
            "max_admission_date": max_adm,
            "min_discharge_date": min_dis,
            "max_discharge_date": max_dis,
        }

    result = {
        "mode": mode,
        "query_date": query_date,
        "dept_filter": dept_list,
        "total_patients": total,
        "dept_counts": dept_counts,
        "date_range": metadata,
        "warnings": warnings,
    }

    _write_summary_cache(mode, query_date, dept_filter, result)
    return result


def _read_summary_cache(mode: str, query_date: str | None, dept_filter: list[str] | None) -> dict | None:
    key = f"{mode}:{query_date or ''}:{','.join(sorted(dept_filter or []))}"
    entry = _SUMMARY_CACHE.get(key)
    if entry:
        ts, data = entry
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return data
        del _SUMMARY_CACHE[key]
    return None


def _write_summary_cache(mode: str, query_date: str | None, dept_filter: list[str] | None, data: dict) -> None:
    key = f"{mode}:{query_date or ''}:{','.join(sorted(dept_filter or []))}"
    _SUMMARY_CACHE[key] = (time.time(), data)


def precheck_by_patient_census(
    config: dict,
    mode: str,
    query_date: str | None,
    dept_filter: list[str] | None,
    audit_type_codes: list[str],
    limit_patients: int = 20,
) -> dict:
    if not _PRECHECK_LOCK.acquire(blocking=False):
        raise RuntimeError("patient census precheck is already running")

    try:
        return _precheck_by_patient_census_unlocked(
            config, mode, query_date, dept_filter, audit_type_codes, limit_patients,
        )
    finally:
        _PRECHECK_LOCK.release()


def _precheck_by_patient_census_unlocked(
    config: dict,
    mode: str,
    query_date: str | None,
    dept_filter: list[str] | None,
    audit_type_codes: list[str],
    limit_patients: int,
) -> dict:
    _assert_data_source_oracle(config)
    registry = AuditTypeRegistry(config)
    dept_list = [d for d in (dept_filter or []) if str(d).strip()]

    if mode == "discharged" and not query_date:
        query_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    _patients, patient_total = load_patient_census(
        config, mode, query_date, dept_list, limit=limit_patients, masking_enabled=False,
    )

    if not audit_type_codes:
        default_types = registry.list_default_schedule()
        audit_type_codes = [at.code for at in default_types]

    audit_type_codes = list(dict.fromkeys(str(c).strip() for c in audit_type_codes if str(c).strip()))
    if not audit_type_codes:
        return {
            "mode": mode,
            "query_date": query_date or "",
            "dept_filter": dept_list,
            "patient_total": patient_total,
            "limit_patients": limit_patients,
            "audit_results": [],
            "warnings": ["precheck is readonly", "no audit_type_codes configured"],
        }

    unknown_codes = []
    for code in audit_type_codes:
        try:
            registry.get(code)
        except KeyError:
            unknown_codes.append(code)
    if unknown_codes:
        raise ValueError(f"未知审计类型: {', '.join(unknown_codes)}")

    audit_results = []

    for code in audit_type_codes:
        result = {"audit_type_code": code, "status": "completed"}
        audit_type = registry.get(code)
        if mode == "discharged" and code == "progress_vs_nursing":
            result.update({
                "status": "skipped_heavy_source",
                "bundle_count": 0,
                "pushable_count": 0,
                "skip_count": 0,
                "source_row_counts": {},
                "skip_reason_counts": {},
                "side_counts": {},
                "sample_bundles": [],
                "warning": "discharged progress_vs_nursing precheck is skipped to avoid heavy nursing/progress SQL; scheduler/manual push still use the real audit SQL",
            })
            audit_results.append(result)
            continue
        try:
            bundles, diagnostics = load_patient_bundles(
                audit_type=audit_type,
                root_config=config,
                query_date=query_date,
                date_dimension="discharge_date" if mode == "discharged" else "query_date",
                dept_filter=dept_list,
                return_diagnostics=True,
            )
            summary = summarize_bundles(audit_type, bundles, diagnostics.get("source_row_counts"))
            result.update({
                "bundle_count": len(bundles),
                "pushable_count": summary.get("pushable_count", 0),
                "skip_count": summary.get("skip_count", 0),
                "source_row_counts": diagnostics.get("source_row_counts", {}),
                "skip_reason_counts": summary.get("skip_reason_counts", {}),
                "side_counts": summary.get("side_counts", {}),
                "sample_bundles": summary.get("sample_bundles", [])[:5],
                "status": "completed",
            })
        except Exception as exc:
            logger.error("precheck audit_type=%s failed: %s", code, exc, exc_info=True)
            result["status"] = "failed"
            result["error_code"] = "precheck_failed"
            result["error"] = "数据源预检失败，请查看服务端日志"
        audit_results.append(result)

    return {
        "mode": mode,
        "query_date": query_date or "",
        "dept_filter": dept_list,
        "patient_total": patient_total,
        "limit_patients": limit_patients,
        "audit_results": audit_results,
        "warnings": [
            "precheck is readonly",
            "precheck uses existing audit_type SQL; patient census is used for comparison only",
            "limit_patients only limits census sampling; existing audit_type source SQL may still scan by dept/date",
        ],
    }
