"""
Push routes: /api/push
Supports manual push by single date or date range with multiple date dimensions.
"""

import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.config import decrypt_value, load_config, normalize_dify_base_url
from app.database import SessionLocal, get_app_db_type, get_db
from app.oracle_client import build_mr_text_combined, fetch_records, group_by_patient
from app.postgresql_client import fetch_pg_records
from app.schemas import ManualPushRequest, PushProgress, RetryRequest
from app.services.bulk_push_executor import BulkPushExecutor
from app.services import (
    ConfigParser,
    PushConfig,
    PushExecutor,
    PushResult,
    build_dify_payload,
    get_task_manager,
)
from app.services.record_identity import get_record_mrid, get_record_source_key
from app.models import PushLog

router = APIRouter()
logger = logging.getLogger(__name__)


KEY_PATIENT_ID = "\u60a3\u8005ID"
KEY_VISIT_NO = "\u6b21\u6570"
KEY_PATIENT_NAME = "\u60a3\u8005\u59d3\u540d"
KEY_DEPT = "\u6240\u5728\u79d1\u5ba4\u540d\u79f0"
KEY_MR_FINISH_TIME = "\u75c5\u5386\u6587\u4e66_\u5b8c\u6210\u65f6\u95f4"
KEY_MR_TITLE_TIME = "\u75c5\u5386\u6807\u9898\u65f6\u95f4"
KEY_NURSE_CREATE_TIME = "\u62a4\u7406\u8bb0\u5f55_\u521b\u5efa\u65f6\u95f4"
KEY_NURSE_TIME = "\u62a4\u7406\u8bb0\u5f55\u65f6\u95f4"
KEY_NURSE_FORM_TIME = "\u62a4\u7406\u8bb0\u5f55\u8868\u5355\u5355\u521b\u5efa\u65f6\u95f4"
KEY_ADMISSION_DATE = "\u5165\u9662\u65e5\u671f"
KEY_DISCHARGE_DATE = "\u51fa\u9662\u65e5\u671f"
KEY_DISCHARGE_TIME = "\u51fa\u9662\u65f6\u95f4"
KEY_DISCHARGE_DATETIME = "\u51fa\u9662\u65e5\u671f\u65f6\u95f4"

DATE_DIMENSION_FIELDS = {
    "query_date": [],
    "record_create_date": [
        KEY_MR_FINISH_TIME,
        KEY_MR_TITLE_TIME,
        KEY_NURSE_CREATE_TIME,
        KEY_NURSE_TIME,
        KEY_NURSE_FORM_TIME,
    ],
    "admission_date": [KEY_ADMISSION_DATE],
    "discharge_date": [KEY_DISCHARGE_DATE, KEY_DISCHARGE_TIME, KEY_DISCHARGE_DATETIME],
}


def _log_push_funnel(
    trigger_type: str,
    query_date_label: str,
    raw_rows: int,
    filtered_rows: int,
    grouped_count: int,
    result: PushResult | None = None,
) -> None:
    skipped = 0
    success = 0
    failed = 0
    skip_reason_counts: dict[str, int] = {}
    if result:
        for item in result.results:
            status = str(item.get("status", ""))
            if status == "success":
                success += 1
            elif status == "skipped":
                skipped += 1
                reason = str(item.get("skip_reason", "unknown") or "unknown")
                skip_reason_counts[reason] = int(skip_reason_counts.get(reason, 0)) + 1
            else:
                failed += 1
    logger.info(
        "[push_funnel] trigger=%s query_date=%s raw_rows=%s filtered_rows=%s grouped=%s success=%s failed=%s skipped=%s",
        trigger_type,
        query_date_label,
        raw_rows,
        filtered_rows,
        grouped_count,
        success,
        failed,
        skipped,
    )
    if skip_reason_counts:
        logger.info(
            "[push_funnel] trigger=%s query_date=%s skip_reason_counts=%s",
            trigger_type,
            query_date_label,
            skip_reason_counts,
        )


def _parse_date(date_text: str):
    return datetime.strptime(date_text, "%Y-%m-%d").date()


def _coerce_to_date(value) -> date | None:
    """将 Oracle/PG 返回的日期字段尽量解析为 date。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    # 常见格式优先匹配
    for fmt in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(text, fmt).date()
        except Exception:
            pass

    # 兜底：截取前 10 位再尝试（兼容 2026-02-06 00:00:00 等）
    head = text[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, fmt).date()
        except Exception:
            pass

    return None


def _resolve_query_dates(body: ManualPushRequest) -> list[str]:
    if body.date_from and body.date_to:
        start_date = _parse_date(body.date_from)
        end_date = _parse_date(body.date_to)
    elif body.query_date:
        start_date = _parse_date(body.query_date)
        end_date = start_date
    else:
        # 未选择日期时，按"全部日期"处理（依赖 SQL 自身范围）。
        return []

    span_days = (end_date - start_date).days + 1
    if span_days <= 0:
        raise HTTPException(status_code=422, detail="date_to must be >= date_from")
    if span_days > 120:
        raise HTTPException(status_code=422, detail="date range cannot exceed 120 days")

    return [(start_date + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(span_days)]


def _date_label(query_dates: list[str]) -> str:
    if not query_dates:
        return "ALL"
    if len(query_dates) == 1:
        return query_dates[0]
    return f"{query_dates[0]}~{query_dates[-1]}"


def _record_date_in_range(record: dict, field_candidates: list[str], date_from: str, date_to: str) -> bool:
    if not field_candidates:
        return True
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    for field_name in field_candidates:
        parsed = _coerce_to_date(record.get(field_name))
        if parsed is None:
            continue
        if start <= parsed <= end:
            return True
    return False


def _auto_inject_date_filter(sql: str, date_dimension: str) -> tuple[str, str | None]:
    """运行时自动检测 SQL 中是否引用了日期维度对应字段，若有则动态追加 BETWEEN 过滤条件。

    此函数仅操作 SQL 字符串副本，不修改用户存储的配置。
    返回 (修改后的SQL, 注入的字段表达式) 或 (原SQL, None) 表示无需/无法注入。
    """
    if not sql or date_dimension == "query_date":
        return sql, None

    sql_lower = sql.lower()
    # 若用户已在 SQL 中显式使用日期参数，优先级高于自动注入
    if ":query_date" in sql_lower or "%s" in sql_lower:
        return sql, None
    if ":date_from" in sql_lower or ":date_to" in sql_lower:
        return sql, None

    fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
    if not fields:
        return sql, None

    field_expr: str | None = None
    for field in fields:
        # 优先匹配带表别名的写法，如 a.出院日期
        alias_m = re.search(r"([a-zA-Z_]\w*\." + re.escape(field) + r")", sql)
        if alias_m:
            field_expr = alias_m.group(1)
            break
        # 其次匹配不带别名的裸字段名（前面不是点号/字母数字/下划线）
        bare_m = re.search(r"(?<![.\w])" + re.escape(field), sql)
        if bare_m:
            field_expr = field
            break

    if not field_expr:
        return sql, None  # SQL 中未引用该维度字段

    # 去掉末尾分号/空白，追加 BETWEEN 条件
    cleaned = sql.rstrip("; \t\n\r")
    connector = "AND" if re.search(r"\bwhere\b", cleaned, re.IGNORECASE) else "WHERE"
    injected_sql = (
        f"{cleaned}\n"
        f"{connector} {field_expr} BETWEEN TO_DATE(:date_from, 'yyyy-mm-dd')"
        f" AND TO_DATE(:date_to, 'yyyy-mm-dd')"
    )
    return injected_sql, field_expr


def _collect_records(
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
        # 检测 SQL 是否使用 :date_from / :date_to 做区间查询（Oracle 命名参数）
        sql_uses_date_range = (":date_from" in custom_query_sql_lower) or (":date_to" in custom_query_sql_lower)

    date_from = query_dates[0] if query_dates else ""
    date_to = query_dates[-1] if query_dates else ""

    # 自动注入日期维度过滤：当 SQL 中未使用任何日期参数、且用户选择了非 query_date 维度时，
    # 检测 SQL 是否引用了该维度的字段名（如 a.出院日期），若有则动态追加 BETWEEN 条件。
    # 此操作仅作用于运行时临时副本，不会修改用户存储的配置。
    if (
        custom_query_sql
        and date_dimension != "query_date"
        and bool(query_dates)
        and not sql_uses_query_date
        and not sql_uses_date_range
    ):
        injected_sql, injected_field = _auto_inject_date_filter(custom_query_sql, date_dimension)
        if injected_field:
            db_cfg = dict(db_cfg)  # 浅拷贝，不修改原配置
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
        # SQL 使用 :date_from/:date_to，只需调用一次数据库，区间由 SQL 自行处理
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
        # 优先使用上游唯一键 MRID（例如 b.mrid||c.form_id）去重。
        # 若旧 SQL 未返回 MRID，则回退历史组合键，兼容存量配置。
        dedupe_key = get_record_source_key(item)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(item)

    # Python 侧日期维度二次过滤策略：
    # - sql_uses_date_range=True：SQL 通过 :date_from/:date_to 已完成区间过滤，跳过 Python 过滤
    # - sql_uses_query_date=True 且 date_dimension != query_date：SQL 通过 :query_date 已按维度逐日过滤，
    #   跳过 Python 过滤（避免因 SELECT 中未包含日期字段而误过滤所有结果）
    # - 两者均不满足：SQL 未参与日期过滤，Python 侧按所选维度做二次过滤
    needs_python_filter = (
        date_dimension != "query_date"
        and bool(query_dates)
        and not sql_uses_date_range
        and not sql_uses_query_date
    )
    if needs_python_filter:
        fields = DATE_DIMENSION_FIELDS.get(date_dimension, [])
        deduped = [r for r in deduped if _record_date_in_range(r, fields, date_from, date_to)]

    return deduped, raw_rows


def _build_query_diagnostics(
    body: ManualPushRequest,
    db_cfg: dict,
    raw_rows: int,
    pre_dept_rows: int,
    filtered_rows: int,
    dept_config: dict | None,
) -> list[str]:
    diagnostics: list[str] = []
    query_sql = str((db_cfg or {}).get("query_sql") or "").strip()
    normalized_sql = query_sql.lower()

    if pre_dept_rows > 0 and filtered_rows == 0:
        mode = str((dept_config or {}).get("mode") or "include")
        dept_list = (dept_config or {}).get("list") or []
        diagnostics.append(
            f"查询命中 {pre_dept_rows} 条，但科室过滤后为 0 条（departments.mode={mode}, departments.list={len(dept_list)} 项）。请检查科室过滤配置。"
        )
        return diagnostics

    # 日期维度二次过滤导致全部丢失：raw_rows > 0 但 pre_dept_rows == 0
    # 注意：当 sql_uses_query_date=True 或 sql_uses_date_range=True 时 Python 侧已跳过过滤，
    # 若仍为 0 说明 SQL 本身返回的数据不满足该维度条件
    if raw_rows > 0 and pre_dept_rows == 0 and body.date_dimension != "query_date":
        date_from = body.date_from or body.query_date or ""
        date_to = body.date_to or body.query_date or ""
        date_range = f"{date_from}~{date_to}" if date_from != date_to else date_from
        dim_label = body.date_dimension
        dim_fields = DATE_DIMENSION_FIELDS.get(body.date_dimension, [])
        sql_has_qdate = ":query_date" in normalized_sql
        sql_has_range = (":date_from" in normalized_sql) or (":date_to" in normalized_sql)
        if sql_has_qdate or sql_has_range:
            # SQL 已负责日期过滤，Python 侧未再过滤，说明 SQL 本身返回数据不在所选范围
            diagnostics.append(
                f"数据库返回 {raw_rows} 条原始记录，但经「{dim_label}」维度过滤后为 0 条。"
                f"SQL 已通过 {':query_date' if sql_has_qdate else ':date_from/:date_to'} 过滤，"
                "请确认 SQL 的过滤条件确实绑定到出院/入院日期字段，且所选日期范围内有数据。"
            )
        else:
            diagnostics.append(
                f"数据库返回 {raw_rows} 条原始记录，但经「{dim_label}」维度过滤后为 0 条（自动注入 BETWEEN {date_range} 条件）。"
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
    if body.date_dimension != "query_date" and ":query_date" in normalized_sql:
        diagnostics.append(
            f"SQL 使用 :query_date 按「{body.date_dimension}」维度逐日查询，Python 侧不再二次过滤。"
            "请确认 SQL 的 :query_date 参数绑定到对应的日期字段（如出院日期、入院日期）。"
        )
    if body.date_dimension != "query_date" and ":query_date" not in normalized_sql:
        has_range_params = (":date_from" in normalized_sql) or (":date_to" in normalized_sql)
        dim_fields = DATE_DIMENSION_FIELDS.get(body.date_dimension, [])
        if has_range_params:
            diagnostics.append(
                f"SQL 使用 :date_from/:date_to 做「{body.date_dimension}」区间查询，系统只调用一次数据库。"
                "请确认这两个参数绑定到正确的日期字段。"
            )
        else:
            diagnostics.append(
                f"SQL 未显式使用 :query_date/:date_from/:date_to，"
                f"系统已自动检测 SQL 中「{'、'.join(dim_fields)}」字段并追加 BETWEEN 过滤条件（无需修改 SQL）；"
                f"若仍返回 0 条，请确认 SQL SELECT 或 FROM 子句中确实引用了「{'、'.join(dim_fields)}」字段，"
                "且所选日期范围内 Oracle 中确有数据。"
            )
    if "ydhl_202501" in normalized_sql:
        diagnostics.append("当前 SQL 指向 ydhl_202501 分表，请确认 2026-04-01 对应数据确实落在该表中，否则会直接返回 0 条。")

    if not diagnostics:
        diagnostics.append("未查询到数据，请重点核对源视图、JOIN 方式、科室名称是否完全匹配，以及所选日期维度与 SQL 过滤条件是否一致。")
    return diagnostics


def _flatten_to_single_records(grouped: dict) -> dict:
    """Flatten patient groups into single-record push units."""
    flattened: dict = {}
    for _, records in grouped.items():
        for record in records:
            unique_key = get_record_source_key(record)
            if unique_key in flattened:
                unique_key = f"{unique_key}::{id(record)}"
            flattened[unique_key] = [record]
    return flattened


def _prepare_push_data(body: ManualPushRequest, config: dict, data_source: str, db_cfg: dict, field_mapping: dict):
    query_dates = _resolve_query_dates(body)
    query_date_label = _date_label(query_dates)
    # 手动推送页面：未选择科室时默认"全部科室"（不再回落全局 departments 配置）
    dept_list = body.dept_filter if body.dept_filter is not None else []

    records, raw_rows = _collect_records(
        data_source=data_source,
        db_cfg=db_cfg,
        dept_list=dept_list,
        query_dates=query_dates,
        date_dimension=body.date_dimension,
    )

    dept_config = {"mode": "include", "list": dept_list or []}
    dept_field = field_mapping.get("dept", KEY_DEPT)
    pre_dept_rows = len(records)
    records = ConfigParser.filter_departments(records, dept_config, dept_field)
    filtered_rows = len(records)
    grouped = group_by_patient(records, field_mapping)
    grouped = _flatten_to_single_records(grouped)
    return query_dates, query_date_label, dept_list, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config


def _filter_grouped_records(grouped: dict, selected_record_keys: list[str] | None) -> dict:
    if not selected_record_keys:
        return grouped
    selected = set(selected_record_keys)
    return {key: value for key, value in grouped.items() if key in selected}


def _filter_already_succeeded(
    db: Session,
    grouped: dict,
) -> tuple[dict, list[dict]]:
    """过滤掉 push_log 中已有成功记录的条目，用于断点续推。

    返回 (remaining_grouped, skipped_items)。
    """
    if not grouped:
        return grouped, []
    latest_push_map = _load_latest_push_map(db, list(grouped.keys()))
    remaining: dict = {}
    skipped_items: list[dict] = []
    for key, records in grouped.items():
        latest = latest_push_map.get(key)
        if latest and str(getattr(latest, "status", "") or "") == "success":
            patient_id = str(records[0].get(KEY_PATIENT_ID, key)) if records else key
            skipped_items.append(
                {
                    "patient_id": patient_id,
                    "status": "skipped",
                    "skip_reason": "already_succeeded",
                    "error": f"已成功推送（log_id={getattr(latest, 'id', '')}，时间={getattr(latest, 'push_time', '')}）",
                    "inconsistency": False,
                    "severity": "",
                    "workflow_run_id": str(getattr(latest, "workflow_run_id", "") or ""),
                    "elapsed_ms": 0,
                }
            )
        else:
            remaining[key] = records
    if skipped_items:
        logger.info(
            "[skip_already_succeeded] skipped=%s remaining=%s",
            len(skipped_items),
            len(remaining),
        )
    return remaining, skipped_items


def _load_latest_push_map(db: Session, source_record_keys: list[str]) -> dict[str, PushLog]:
    if not source_record_keys:
        return {}

    # ORA-01795: Oracle IN 列表最多 1000 项，保守按 900 分片。
    chunk_size = 900
    if len(source_record_keys) > chunk_size:
        logger.info(
            "[query_preview] loading latest push map with chunking: keys=%s chunk_size=%s chunks=%s",
            len(source_record_keys),
            chunk_size,
            (len(source_record_keys) + chunk_size - 1) // chunk_size,
        )
    rows: list[PushLog] = []
    for i in range(0, len(source_record_keys), chunk_size):
        chunk = source_record_keys[i:i + chunk_size]
        subq = (
            db.query(
                PushLog.source_record_key.label("source_record_key"),
                func.max(PushLog.id).label("max_id"),
            )
            .filter(PushLog.source_record_key.in_(chunk))
            .group_by(PushLog.source_record_key)
            .subquery()
        )
        chunk_rows = (
            db.query(PushLog)
            .join(subq, PushLog.id == subq.c.max_id)
            .all()
        )
        rows.extend(chunk_rows)

    latest: dict[str, PushLog] = {}
    for row in rows:
        key = str(getattr(row, "source_record_key", "") or "")
        if key and key not in latest:
            latest[key] = row
    return latest


def _build_query_preview_rows(
    grouped: dict,
    field_mapping: dict,
    dept_field: str,
    latest_push_map: dict[str, PushLog],
) -> list[dict]:
    name_field = field_mapping.get("patient_name", KEY_PATIENT_NAME)
    admission_no_field = field_mapping.get("admission_no", "住院号")
    visit_field = field_mapping.get("visit_number", KEY_VISIT_NO)
    rows: list[dict] = []
    for record_key, patient_records in grouped.items():
        record = patient_records[0] if patient_records else {}
        latest = latest_push_map.get(record_key)
        rows.append(
            {
                "record_key": record_key,
                "mrid": get_record_mrid(record),
                "patient_id": str(record.get(KEY_PATIENT_ID) or ""),
                "visit_number": str(record.get(visit_field) or ""),
                "patient_name": str(record.get(name_field) or ""),
                "admission_no": str(record.get(admission_no_field) or ""),
                "dept": str(record.get(dept_field) or ""),
                "medical_document_time": str(record.get(KEY_MR_FINISH_TIME) or record.get(KEY_MR_TITLE_TIME) or ""),
                "medical_document_name": str(record.get("病历文书_名称") or record.get("病历名称") or ""),
                "nursing_record_time": str(record.get(KEY_NURSE_CREATE_TIME) or record.get(KEY_NURSE_TIME) or record.get(KEY_NURSE_FORM_TIME) or ""),
                "nursing_record_type": str(record.get("护理记录_文书类型") or record.get("护理单类型") or ""),
                # 查询预览仅用于列表展示，避免为数万条记录拼接全文导致接口变慢。
                "mr_text_preview": "",
                "pushed_before": latest is not None,
                "latest_log_id": int(getattr(latest, "id", 0) or 0) if latest else None,
                "latest_push_status": str(getattr(latest, "status", "") or "") if latest else "",
                "latest_push_time": getattr(latest, "push_time", None) if latest else None,
                "latest_reviewed_flag": int(getattr(latest, "reviewed_flag", 0) or 0) if latest else 0,
            }
        )
    rows.sort(
        key=lambda item: (
            0 if not item["pushed_before"] else 1,
            str(item.get("patient_id") or ""),
            str(item.get("medical_document_time") or ""),
            str(item.get("nursing_record_time") or ""),
        )
    )
    return rows


def _load_persisted_dify_targets(config: dict) -> list[dict]:
    """Load enabled persisted Dify targets from config.dify.targets."""
    dify_section = (config or {}).get("dify", {}) or {}
    raw_targets = dify_section.get("targets", []) or []
    persisted: list[dict] = []
    for idx, item in enumerate(raw_targets):
        t = dict(item or {})
        if not t or not bool(t.get("enabled", True)):
            continue
        api_key = ""
        try:
            api_key = decrypt_value(t.get("api_key_enc", "")) if t.get("api_key_enc") else ""
        except Exception:
            api_key = ""
        if not api_key:
            continue
        base_url = str(t.get("base_url") or "").strip()
        if not base_url:
            continue
        try:
            base_url = normalize_dify_base_url(base_url)
        except Exception:
            continue
        persisted.append(
            {
                "name": str(t.get("name") or f"target-{idx + 1}"),
                "base_url": base_url,
                "api_key": api_key,
                "workflow_input_variable": str(t.get("workflow_input_variable") or "mr_txt"),
                "workflow_output_key": str(t.get("workflow_output_key") or "aa"),
                "user_identifier": str(t.get("user_identifier") or "med-audit-system"),
                "timeout_seconds": int(t.get("timeout_seconds") or 90),
                "weight": int(t.get("weight") or 1),
                "enabled": True,
            }
        )
    return persisted


def _build_manual_dify_targets(body: ManualPushRequest, dify_cfg: dict, config: dict) -> list[dict] | None:
    targets = []
    if body.dify_targets:
        for item in body.dify_targets:
            if hasattr(item, "model_dump"):
                targets.append(item.model_dump())
            else:
                targets.append(dict(item))
    if not targets:
        targets = _load_persisted_dify_targets(config)
        if not targets:
            return None
    # Fill missing keys from default config for compatibility
    merged = []
    for t in targets:
        cfg = dict(dify_cfg)
        cfg.update(t)
        merged.append(cfg)
    unique_identities = {
        (
            normalize_dify_base_url(str(item.get("base_url") or "").strip()),
            str(item.get("api_key") or "").strip(),
        )
        for item in merged
        if str(item.get("base_url") or "").strip()
    }
    if len(merged) >= 2 and len(unique_identities) <= 1:
        raise HTTPException(
            status_code=422,
            detail="要实现真实负载分流，多个已启用的 Dify 目标必须配置为不同的 base_url 或 api_key。",
        )
    return merged


def _paginate_query_preview_rows(rows: list[dict], page: int | None, page_size: int | None) -> tuple[list[dict], dict]:
    total_rows = len(rows)
    use_paging = page is not None and page_size is not None
    if not use_paging:
        return rows, {
            "paged": False,
            "page": 1,
            "page_size": total_rows,
            "total_rows": total_rows,
            "total_pages": 1 if total_rows > 0 else 0,
        }

    total_pages = (total_rows + page_size - 1) // page_size if total_rows > 0 else 0
    safe_page = page
    if total_pages > 0:
        safe_page = min(max(page, 1), total_pages)
    else:
        safe_page = 1
    start = (safe_page - 1) * page_size
    end = start + page_size
    return rows[start:end], {
        "paged": True,
        "page": safe_page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
    }


def _should_use_bulk_executor(body: ManualPushRequest) -> bool:
    if int(body.parallel_workers or 1) > 1:
        return True
    if int(body.empty_retry_max or 0) > 0:
        return True
    if body.dify_targets:
        return True
    return False


def _effective_parallel_workers(requested_workers: int) -> tuple[int, str]:
    workers = max(1, int(requested_workers or 1))
    db_type = str(get_app_db_type() or "").lower()
    if db_type == "sqlite":
        capped = min(workers, 4)
        if capped != workers:
            return capped, "sqlite mode: workers capped to 4 to reduce database lock contention"
    return workers, ""


@router.post("/manual", summary="Manual push")
def manual_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    config = load_config()

    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = (
        ConfigParser.parse_postgresql_config(config)
        if data_source == "postgresql"
        else ConfigParser.parse_oracle_config(config)
    )
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    query_dates, query_date_label, dept_list, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config = _prepare_push_data(
        body, config, data_source, db_cfg, field_mapping
    )
    grouped_before_selected = len(grouped)
    grouped = _filter_grouped_records(grouped, body.selected_record_keys)
    grouped_after_selected = len(grouped)

    # 断点续推：过滤已成功的记录（不适用于 dry_run 和 query_preview）
    pre_skip_succeeded_items: list[dict] = []
    if body.skip_already_succeeded and not body.dry_run:
        grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)

    logger.info(
        "[manual_push] mode=%s date_dimension=%s query_dates=%s dept_count=%s dept_mode=%s dept_list_size=%s raw_rows=%s pre_dept_rows=%s filtered_rows=%s grouped_before_selected=%s grouped_after_selected=%s selected_record_keys=%s skip_already_succeeded=%s skipped_succeeded=%s dry_run=%s async_mode=%s",
        "range" if (body.date_from and body.date_to) else "single",
        body.date_dimension,
        query_dates,
        len(dept_list or []),
        str((dept_config or {}).get("mode") or "include"),
        len((dept_config or {}).get("list") or []),
        raw_rows,
        pre_dept_rows,
        filtered_rows,
        grouped_before_selected,
        grouped_after_selected,
        len(body.selected_record_keys or []),
        body.skip_already_succeeded,
        len(pre_skip_succeeded_items),
        body.dry_run,
        body.async_mode,
    )

    diagnostics = _build_query_diagnostics(body, db_cfg, raw_rows, pre_dept_rows, filtered_rows, dept_config)
    use_bulk_executor = _should_use_bulk_executor(body)

    if not grouped:
        empty_result = {
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total": len(pre_skip_succeeded_items),
            "success": 0,
            "failed": 0,
            "skipped": len(pre_skip_succeeded_items),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "grouped": 0,
            "used_bulk_executor": use_bulk_executor,
            "parallel_workers_effective": 0,
            "worker_note": "",
            "target_metrics": {},
            "empty_retry_total": 0,
            "results": pre_skip_succeeded_items,
            "diagnostics": diagnostics,
        }
        if body.dry_run:
            empty_result.update(
                {
                    "dry_run": True,
                    "total_patients": 0,
                    "total_records": 0,
                    "preview": [],
                }
            )
        return empty_result

    if body.async_mode and not body.dry_run:
        task_id = str(uuid.uuid4())[:8]
        task_manager = get_task_manager()
        task_manager.create_task(task_id)
        thread_target = _async_push_bulk if use_bulk_executor else _async_push
        thread = threading.Thread(
            target=thread_target,
            args=(
                task_id,
                body.model_dump(),
                dept_list,
                data_source,
                db_cfg,
                dify_cfg,
                config,
                push_settings,
                field_mapping,
            ),
            daemon=True,
        )
        thread.start()
        return {"task_id": task_id, "message": "async task submitted", "diagnostics": diagnostics}

    if body.dry_run:
        name_field = field_mapping.get("patient_name", KEY_PATIENT_NAME)
        preview = []
        for pid, patient_records in grouped.items():
            payload = build_dify_payload(patient_records, field_mapping, query_date_label)
            preview.append(
                {
                    "patient_id": pid,
                    "patient_name": patient_records[0].get(name_field, ""),
                    "dept": patient_records[0].get(dept_field, ""),
                    "record_count": len(patient_records),
                    "mr_text_preview": build_mr_text_combined(patient_records, field_mapping)[:500] + "...",
                    "dify_payload": payload,
                }
            )
        return {
            "dry_run": True,
            "date_dimension": body.date_dimension,
            "query_dates": query_dates,
            "total_patients": len(grouped),
            "total_records": len(records),
            "raw_rows": raw_rows,
            "filtered_rows": filtered_rows,
            "diagnostics": diagnostics,
            "preview": preview,
        }

    push_config = PushConfig(
        trigger_type="manual",
        query_date=query_date_label,
        interval_ms=push_settings["interval_ms"],
        max_retry=push_settings["max_retry"],
        notify_enabled=True,
    )
    effective_workers = 1
    worker_note = ""
    target_metrics: dict = {}
    empty_retry_total = 0
    if use_bulk_executor:
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg, config),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(grouped, push_config)
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
    else:
        executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
    _log_push_funnel("manual", query_date_label, raw_rows, filtered_rows, len(grouped), result)

    all_results = pre_skip_succeeded_items + result.results
    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "total": result.total + len(pre_skip_succeeded_items),
        "success": result.success,
        "failed": result.failed,
        "skipped": len([r for r in all_results if r.get("status") == "skipped"]),
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "used_bulk_executor": use_bulk_executor,
        "parallel_workers_effective": effective_workers,
        "worker_note": worker_note,
        "target_metrics": target_metrics,
        "empty_retry_total": empty_retry_total,
        "diagnostics": diagnostics,
        "results": all_results,
    }


@router.post("/preview", summary="Manual dry-run preview")
def preview_push(body: ManualPushRequest, db: Session = Depends(get_db)):
    body.dry_run = True
    return manual_push(body, db)


@router.post("/query-preview", summary="Manual query preview")
def query_preview(body: ManualPushRequest, db: Session = Depends(get_db)):
    config = load_config()
    data_source = ConfigParser.get_data_source_type(config)
    db_cfg = (
        ConfigParser.parse_postgresql_config(config)
        if data_source == "postgresql"
        else ConfigParser.parse_oracle_config(config)
    )
    field_mapping = ConfigParser.get_field_mapping(config, data_source)

    query_dates, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, dept_field, dept_config = _prepare_push_data(
        body, config, data_source, db_cfg, field_mapping
    )
    grouped_before_selected = len(grouped)
    grouped = _filter_grouped_records(grouped, body.selected_record_keys)
    grouped_after_selected = len(grouped)
    diagnostics = _build_query_diagnostics(body, db_cfg, raw_rows, pre_dept_rows, filtered_rows, dept_config)
    latest_push_map = _load_latest_push_map(db, list(grouped.keys()))
    all_rows = _build_query_preview_rows(grouped, field_mapping, dept_field, latest_push_map)
    rows, page_meta = _paginate_query_preview_rows(all_rows, body.page, body.page_size)

    logger.info(
        "[query_preview] mode=%s date_dimension=%s query_dates=%s dept_mode=%s dept_list_size=%s raw_rows=%s pre_dept_rows=%s filtered_rows=%s grouped_before_selected=%s grouped_after_selected=%s total_rows=%s page=%s page_size=%s selected_record_keys=%s diagnostics=%s",
        "range" if (body.date_from and body.date_to) else "single",
        body.date_dimension,
        query_dates,
        str((dept_config or {}).get("mode") or "include"),
        len((dept_config or {}).get("list") or []),
        raw_rows,
        pre_dept_rows,
        filtered_rows,
        grouped_before_selected,
        grouped_after_selected,
        len(all_rows),
        page_meta.get("page"),
        page_meta.get("page_size"),
        len(body.selected_record_keys or []),
        diagnostics,
    )

    return {
        "date_dimension": body.date_dimension,
        "query_dates": query_dates,
        "query_date_label": query_date_label,
        "raw_rows": raw_rows,
        "filtered_rows": filtered_rows,
        "grouped": len(grouped),
        "selected_count": len(body.selected_record_keys or []),
        "pushed_count": len([row for row in all_rows if row.get("pushed_before")]),
        "unpushed_count": len([row for row in all_rows if not row.get("pushed_before")]),
        "paged": bool(page_meta["paged"]),
        "page": int(page_meta["page"]),
        "page_size": int(page_meta["page_size"]),
        "total_rows": int(page_meta["total_rows"]),
        "total_pages": int(page_meta["total_pages"]),
        "diagnostics": diagnostics,
        "rows": rows,
    }


@router.post("/retry", summary="Retry failed pushes")
def retry_push(body: RetryRequest, db: Session = Depends(get_db)):
    config = load_config()
    dify_cfg = ConfigParser.parse_dify_config(config)
    push_settings = ConfigParser.get_push_settings(config)
    data_source = ConfigParser.get_data_source_type(config)
    field_mapping = ConfigParser.get_field_mapping(config, data_source)
    executor = PushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
    results = executor.execute_retry(db, body.log_ids, push_settings["max_retry"])
    return {"results": results}


@router.get("/status/{task_id}", response_model=PushProgress, summary="Get async task progress")
def get_push_status(task_id: str):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)
    if not progress:
        return PushProgress(task_id=task_id, status="not_found")
    return PushProgress(
        task_id=progress.task_id,
        status=progress.status,
        total=progress.total,
        processed=progress.processed,
        success=progress.success,
        failed=progress.failed,
        skipped=progress.skipped,
        cancelled=progress.cancelled,
    )


@router.post("/cancel/{task_id}", summary="Cancel running async task")
def cancel_push_task(task_id: str):
    task_manager = get_task_manager()
    progress = task_manager.get_task(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Task not found")
    if progress.status != "running":
        raise HTTPException(status_code=409, detail=f"Task is not running (status={progress.status})")
    ok = task_manager.cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Failed to cancel task")
    return {"message": "cancel requested", "task_id": task_id}


def _async_push(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    db = SessionLocal()
    task_manager = get_task_manager()
    try:
        body = ManualPushRequest(**body_data)
        query_dates, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, _, dept_config = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        grouped = _filter_grouped_records(grouped, body.selected_record_keys)
        # 断点续推：过滤已成功记录
        pre_skip_succeeded_items: list[dict] = []
        if body.skip_already_succeeded:
            grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)
        task_manager.update_task(task_id, total=len(grouped) + len(pre_skip_succeeded_items))
        # 已跳过的直接计入进度
        for _ in pre_skip_succeeded_items:
            task_manager.increment_processed(task_id, result_status="skipped")

        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )

        class CallbackPushExecutor(PushExecutor):
            def execute(self, db, grouped_records, push_config):
                start_time = time.time()
                result = PushResult(total=len(grouped_records))
                try:
                    for patient_id, patient_records in grouped_records.items():
                        # 检查取消标志
                        if task_manager.is_cancelled(task_id):
                            logger.info("async push cancelled by user: task_id=%s processed=%s/%s", task_id, result.success + result.failed, result.total)
                            break
                        try:
                            with db.begin_nested():
                                single_result = self._push_single_record(db, patient_id, patient_records, push_config)
                            result.results.append(single_result)
                            status = str(single_result.get("status", "failed"))
                            if status == "success":
                                result.success += 1
                                task_manager.increment_processed(task_id, result_status="success")
                            elif status == "skipped":
                                task_manager.increment_processed(task_id, result_status="skipped")
                            else:
                                result.failed += 1
                                task_manager.increment_processed(task_id, result_status="failed")
                            time.sleep(push_config.interval_ms / 1000)
                        except Exception as exc:
                            logger.error("push single patient failed: patient_id=%s err=%s", patient_id, exc, exc_info=True)
                            result.failed += 1
                            task_manager.increment_processed(task_id, result_status="failed")
                            result.results.append({"patient_id": patient_id, "status": "error", "error": str(exc)})
                    db.commit()
                except Exception:
                    db.rollback()
                    raise
                result.duration_seconds = time.time() - start_time
                return result

        executor = CallbackPushExecutor(dify_cfg, config.get("notify", {}), field_mapping)
        result = executor.execute(db, grouped, push_config)
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        # 若任务被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="completed")
    except Exception as exc:
        logger.error("async push failed: %s", exc, exc_info=True)
        if not task_manager.is_cancelled(task_id):
            task_manager.update_task(task_id, status="failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


def _async_push_bulk(task_id, body_data, dept_list, data_source, db_cfg, dify_cfg, config, push_settings, field_mapping):
    task_manager = get_task_manager()
    final_status = "failed"
    try:
        body = ManualPushRequest(**body_data)
        _, query_date_label, _, records, raw_rows, pre_dept_rows, filtered_rows, grouped, _, dept_config = _prepare_push_data(
            body, config, data_source, db_cfg, field_mapping
        )
        grouped = _filter_grouped_records(grouped, body.selected_record_keys)
        # 断点续推：过滤已成功记录
        pre_skip_succeeded_items: list[dict] = []
        if body.skip_already_succeeded:
            db = SessionLocal()
            try:
                grouped, pre_skip_succeeded_items = _filter_already_succeeded(db, grouped)
            finally:
                db.close()
        task_manager.update_task(task_id, total=len(grouped) + len(pre_skip_succeeded_items))
        # 已跳过的直接计入进度
        for _ in pre_skip_succeeded_items:
            task_manager.increment_processed(task_id, result_status="skipped")
        push_config = PushConfig(
            trigger_type="manual",
            query_date=query_date_label,
            interval_ms=push_settings["interval_ms"],
            max_retry=push_settings["max_retry"],
            notify_enabled=True,
        )
        effective_workers, worker_note = _effective_parallel_workers(body.parallel_workers)
        if worker_note:
            logger.warning("[async bulk] %s task_id=%s requested=%s effective=%s", worker_note, task_id, body.parallel_workers, effective_workers)
        executor = BulkPushExecutor(
            dify_config=dify_cfg,
            notify_config=config.get("notify", {}),
            field_mapping=field_mapping,
            dify_targets=_build_manual_dify_targets(body, dify_cfg, config),
            max_workers=effective_workers,
            empty_retry_max=body.empty_retry_max,
            empty_retry_backoff_ms=body.empty_retry_backoff_ms,
            target_strategy=body.target_strategy,
        )
        result = executor.execute(
            grouped,
            push_config,
            on_item_done=lambda status: task_manager.increment_processed(
                task_id,
                result_status="success" if status == "success" else ("skipped" if status == "skipped" else "failed"),
            ),
            stop_check=lambda: task_manager.is_cancelled(task_id),
        )
        target_metrics = executor.get_target_metrics()
        empty_retry_total = sum(int((r.get("empty_retry_count") or 0)) for r in result.results)
        logger.info(
            "[async bulk] task_id=%s target_metrics=%s empty_retry_total=%s",
            task_id,
            target_metrics,
            empty_retry_total,
        )
        _log_push_funnel("async", query_date_label, raw_rows, filtered_rows, len(grouped), result)
        final_status = "completed"
    except Exception as exc:
        logger.error("async bulk push failed: %s", exc, exc_info=True)
        final_status = "failed"
    finally:
        try:
            # 若任务已被取消，status 已由 cancel_task 设为 cancelled，不再覆盖
            if not task_manager.is_cancelled(task_id):
                task_manager.update_task(task_id, status=final_status)
        except Exception as exc:
            logger.error("async bulk push: failed to update task status: %s", exc, exc_info=True)
