"""推送查询服务 —— 数据收集、日期维度过滤、查询诊断。"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from app.oracle_client import fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.services.config_parser import ConfigParser
from app.services.record_identity import get_record_source_key
from app.services.push_date_utils import coerce_to_date, parse_date

logger = logging.getLogger(__name__)

DATE_DIMENSION_FIELDS = {
    "discharge_date": ["出院日期", "DISCHARGE_DATE"],
    "admission_date": ["入院日期", "ADMISSION_DATE"],
}

KEY_PATIENT_ID = "患者ID"
KEY_DEPT = "所在科室名称"
KEY_MR_FINISH_TIME = "病历文书_完成时间"
KEY_MR_TITLE_TIME = "病历文书_标题时间"
KEY_NURSE_CREATE_TIME = "护理记录_创建时间"
KEY_NURSE_TIME = "护理时间"
KEY_NURSE_FORM_TIME = "护理记录_护理时间"
KEY_PATIENT_NAME = "患者姓名"
KEY_VISIT_NO = "次数"


def record_date_in_range(record: dict, field_candidates: list[str], date_from: str, date_to: str) -> bool:
    if not field_candidates:
        return True
    start = parse_date(date_from)
    end = parse_date(date_to)
    for field_name in field_candidates:
        parsed = coerce_to_date(record.get(field_name))
        if parsed is None:
            continue
        if start <= parsed <= end:
            return True
    return False


def auto_inject_date_filter(sql: str, date_dimension: str) -> tuple[str, str | None]:
    if not sql or date_dimension == "query_date":
        return sql, None

    sql_lower = sql.lower()
    if ":query_date" in sql_lower or "%s" in sql_lower:
        return sql, None
    if ":date_from" in sql_lower or ":date_to" in sql_lower:
        return sql, None

    fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
    if not fields:
        return sql, None

    field_expr: str | None = None
    for field in fields:
        alias_m = re.search(r"([a-zA-Z_]\w*\." + re.escape(field) + r")", sql)
        if alias_m:
            field_expr = alias_m.group(1)
            break
        bare_m = re.search(r"(?<![.\w])" + re.escape(field), sql)
        if bare_m:
            field_expr = field
            break

    if not field_expr:
        return sql, None

    cleaned = sql.rstrip("; \t\n\r")
    connector = "AND" if re.search(r"\bwhere\b", cleaned, re.IGNORECASE) else "WHERE"
    injected_sql = (
        f"{cleaned}\n"
        f"{connector} {field_expr} >= TO_DATE(:date_from, 'yyyy-mm-dd')"
        f" AND {field_expr} < TO_DATE(:date_to, 'yyyy-mm-dd') + 1"
    )
    return injected_sql, field_expr


def collect_records(
    data_source: str,
    db_cfg: dict,
    dept_list: list[str],
    query_dates: list[str],
    date_dimension: str,
) -> tuple[list[dict], int]:
    all_records: list[dict] = []
    raw_rows = 0
    custom_query_sql = str((db_cfg or {}).get("query_sql") or "").strip()
    custom_query_sql_lower = custom_query_sql.lower()
    sql_uses_query_date = True
    sql_uses_date_range = False
    if custom_query_sql:
        sql_uses_query_date = (":query_date" in custom_query_sql_lower) or ("%s" in custom_query_sql_lower)
        sql_uses_date_range = (":date_from" in custom_query_sql_lower) or (":date_to" in custom_query_sql_lower)

    date_from = query_dates[0] if query_dates else ""
    date_to = query_dates[-1] if query_dates else ""

    if (
        custom_query_sql
        and date_dimension != "query_date"
        and bool(query_dates)
        and not sql_uses_query_date
        and not sql_uses_date_range
    ):
        injected_sql, injected_field = auto_inject_date_filter(custom_query_sql, date_dimension)
        if injected_field:
            db_cfg = dict(db_cfg)
            db_cfg["query_sql"] = injected_sql
            sql_uses_date_range = True
            logger.info(
                "[push] 自动注入日期维度过滤：date_dimension=%s field=%s date_from=%s date_to=%s",
                date_dimension,
                injected_field,
                date_from,
                date_to,
            )

    if not query_dates:
        fetch_dates = [""]
    elif sql_uses_date_range:
        fetch_dates = [date_to]
    else:
        fetch_dates = query_dates if (date_dimension == "query_date" or sql_uses_query_date) else [query_dates[-1]]

    for query_date in fetch_dates:
        day_records = (
            fetch_pg_records(db_cfg, dept_list, query_date)
            if data_source == "postgresql"
            else fetch_records(db_cfg, dept_list, query_date, date_from=date_from, date_to=date_to)
        )
        raw_rows += len(day_records)
        all_records.extend(day_records)

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in all_records:
        dedupe_key = get_record_source_key(item)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)

    needs_python_filter = (
        date_dimension != "query_date"
        and bool(query_dates)
        and not sql_uses_date_range
        and not sql_uses_query_date
    )
    if needs_python_filter:
        fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
        deduped = [r for r in deduped if record_date_in_range(r, fields, date_from, date_to)]

    return deduped, raw_rows


def build_query_diagnostics(
    date_dimension: str,
    date_from: str | None,
    date_to: str | None,
    query_date: str | None,
    db_cfg: dict,
    raw_rows: int,
    pre_dept_rows: int | None = None,
    filtered_rows: int = 0,
    dept_config: dict | None = None,
) -> list[str]:
    diagnostics: list[str] = []
    query_sql = str((db_cfg or {}).get("query_sql") or "").strip()
    normalized_sql = query_sql.lower()
    if pre_dept_rows is None:
        pre_dept_rows = raw_rows

    if pre_dept_rows > 0 and filtered_rows == 0:
        mode = str((dept_config or {}).get("mode") or "include")
        dept_list = (dept_config or {}).get("list") or []
        diagnostics.append(
            f"查询命中 {pre_dept_rows} 条，但科室过滤后为 0 条（departments.mode={mode}, departments.list={len(dept_list)} 项）。请检查科室过滤配置。"
        )
        return diagnostics

    if raw_rows > 0 and pre_dept_rows == 0 and date_dimension != "query_date":
        effective_date_from = date_from or query_date or ""
        effective_date_to = date_to or query_date or ""
        date_range = f"{effective_date_from}~{effective_date_to}" if effective_date_from != effective_date_to else effective_date_from
        dim_label = date_dimension
        dim_fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
        sql_has_qdate = ":query_date" in normalized_sql
        sql_has_range = (":date_from" in normalized_sql) or (":date_to" in normalized_sql)
        if sql_has_qdate or sql_has_range:
            diagnostics.append(
                f"数据库返回 {raw_rows} 条原始记录，但经「{dim_label}」维度过滤后为 0 条。"
                f"SQL 已通过 {':query_date' if sql_has_qdate else ':date_from/:date_to'} 过滤，"
                "请确认 SQL 的过滤条件确实绑定到出院/入院日期字段，且所选日期范围内有数据。"
            )
        else:
            diagnostics.append(
                f"数据库返回 {raw_rows} 条原始记录，但经「{dim_label}」维度过滤后为 0 条（自动注入 {date_range} 半开日期区间条件）。"
                f"请检查：① SQL 的 SELECT/FROM 中是否引用了「{'、'.join(dim_fields)}」字段（系统据此自动追加 BETWEEN 条件）；"
                "② 如果 SQL 中该字段名带表别名（如 a.出院日期），请确认别名正确；"
                "③ 所选日期范围内 Oracle 中确实有数据。"
            )
        return diagnostics

    if raw_rows > 0 or filtered_rows > 0:
        return diagnostics

    if not query_sql:
        diagnostics.append("当前使用默认查询 SQL，若按入院/出院日期推送，建议确认默认 SQL 是否满足该维度筛选。")
        return diagnostics

    if "，" in query_sql or "；" in query_sql:
        diagnostics.append("自定义 SQL 中包含中文逗号或分号，请改为英文符号，避免 Oracle 解析异常或结果不符合预期。")
    if " from jhemr.v_cybr" in normalized_sql:
        diagnostics.append("当前 SQL 使用 jhemr.v_cybr，只会返回已出院患者；若要查在院患者，请改回 jhemr.v_zybr 或对应视图。")
    if "inner join" in normalized_sql and ("ydhl" in normalized_sql or "v_hljl" in normalized_sql):
        diagnostics.append("当前 SQL 对护理表使用 INNER JOIN；只要护理记录未匹配上，当天病历就会被整体过滤。若希望保留病历侧数据，请改为 LEFT JOIN。")
    if date_dimension != "query_date" and ":query_date" in normalized_sql:
        diagnostics.append(
            f"SQL 使用 :query_date 按「{date_dimension}」维度逐日查询，Python 侧不再二次过滤。"
            "请确认 SQL 的 :query_date 参数绑定到对应的日期字段（如出院日期、入院日期）。"
        )
    if date_dimension != "query_date" and ":query_date" not in normalized_sql:
        has_range_params = (":date_from" in normalized_sql) or (":date_to" in normalized_sql)
        dim_fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
        if has_range_params:
            diagnostics.append(
                f"SQL 使用 :date_from/:date_to 做「{date_dimension}」区间查询，系统只调用一次数据库。"
                "请确认这两个参数绑定到正确的日期字段。"
            )
        else:
            diagnostics.append(
                f"SQL 未显式使用 :query_date/:date_from/:date_to，"
                f"系统已自动检测 SQL 中「{'、'.join(dim_fields)}」字段并追加半开日期区间过滤条件（无需修改 SQL）；"
                f"若仍返回 0 条，请确认 SQL SELECT 或 FROM 子句中确实引用了「{'、'.join(dim_fields)}」字段，"
                "且所选日期范围内 Oracle 中确有数据。"
            )
    if "ydhl_202501" in normalized_sql:
        effective_date_from = date_from or query_date or "所选日期"
        effective_date_to = date_to or query_date or effective_date_from
        date_label = effective_date_from if effective_date_from == effective_date_to else f"{effective_date_from}~{effective_date_to}"
        diagnostics.append(f"当前 SQL 指向 ydhl_202501 分表，请确认 {date_label} 对应数据确实落在该表中，否则会直接返回 0 条。")

    if not diagnostics:
        diagnostics.append("未查询到数据，请重点核对源视图、JOIN 方式、科室名称是否完全匹配，以及所选日期维度与 SQL 过滤条件是否一致。")
    return diagnostics
