"""
电子病历海量库客户端 —— 通过 psycopg2 连接 Vastbase（PostgreSQL 协议）
读取 jhemr.v_blws 视图，用于病程文书和出院记录查询。
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_FIELD_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")


def _validate_field_name(name: str) -> str:
    """白名单校验字段名，防止 SQL 注入。"""
    if not name or not _FIELD_NAME_RE.match(name):
        raise ValueError(f"非法字段名: {name!r}，仅允许英文字母/数字/下划线且以字母或下划线开头")
    return name


def _get_field(cfg: dict, key: str, default: str) -> str:
    return _validate_field_name(cfg.get(key, default) or default)


def _build_event_time_expr(ftime_field: str, rtime_field: str, fstime_field: str, cdate_field: str) -> str:
    """构建事件时间 COALESCE 表达式。timestamp 字段用 COALESCE 直接回退，不走 NULLIF。"""
    return (
        f"COALESCE(NULLIF({ftime_field},''), NULLIF({rtime_field},''), "
        f"{fstime_field}, {cdate_field})"
    )


def _build_kind_filter(type_field: str, title_field: str, template_field: str, document_kind: str) -> str:
    """按 document_kind 构建 SQL 过滤片段。"""
    if document_kind == "discharge":
        return f"AND COALESCE({template_field},'') = '出院记录'"
    if document_kind == "progress":
        return f"AND COALESCE({template_field},'') LIKE '%%病程%%'"
    if document_kind == "first_progress":
        return f"AND COALESCE({template_field},'') LIKE '%%首次病程%%'"
    return ""


def _coerce_record(rec: dict) -> dict:
    """将记录值转为安全字符串。"""
    for k in list(rec.keys()):
        v = rec[k]
        if v is None:
            rec[k] = ""
        elif hasattr(v, "strftime"):
            rec[k] = v.strftime("%Y-%m-%d %H:%M:%S")
        else:
            rec[k] = str(v).strip()
    return rec


def _resolve_document_kind(source_name: str, explicit_kind: str) -> str:
    """根据 source_name 推断默认 document_kind。"""
    if explicit_kind:
        return explicit_kind
    if source_name == "first_progress":
        return "first_progress"
    if source_name == "discharge":
        return "discharge"
    if source_name == "progress":
        return "progress"
    return "all"


def get_emr_vastbase_connection(config: dict):
    """获取海量库连接。调用方负责关闭。"""
    import psycopg2
    host = config.get("host", "")
    port = int(config.get("port", 5432) or 5432)
    database = config.get("database", "")
    username = config.get("username", "")
    password = config.get("password", "")
    connect_timeout = int(config.get("connect_timeout_seconds", 10) or 10)
    if not host or not database:
        raise ValueError("海量库 host 和 database 不能为空")
    conn_params = dict(
        host=host,
        port=port,
        dbname=database,
        user=username,
        password=password,
        connect_timeout=connect_timeout,
    )
    sslmode = config.get("sslmode")
    if sslmode:
        conn_params["sslmode"] = sslmode
    conn = psycopg2.connect(**conn_params)
    conn.set_session(readonly=True, autocommit=True)
    statement_timeout_ms = int(config.get("statement_timeout_ms", 60000) or 60000)
    try:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {statement_timeout_ms}")
    except Exception:
        logger.debug("SET statement_timeout 失败，忽略")
    return conn


def test_emr_vastbase_connection(config: dict) -> dict:
    """测试连接 + 字段诊断。"""
    start = time.time()
    try:
        conn = get_emr_vastbase_connection(config)
    except Exception as exc:
        elapsed = int((time.time() - start) * 1000)
        return {"status": "error", "message": str(exc), "elapsed_ms": elapsed}
    try:
        schema = config.get("schema", "jhemr") or "jhemr"
        view = config.get("view", "v_blws") or "v_blws"
        if not _FIELD_NAME_RE.match(schema) or not _FIELD_NAME_RE.match(view):
            return {"status": "error", "message": f"非法 schema/view 名: {schema}.{view}"}
        elapsed = int((time.time() - start) * 1000)
        result: dict[str, Any] = {"status": "up", "latency_ms": elapsed}

        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                (schema, view),
            )
            columns = [row[0] for row in cur.fetchall()]
            result["columns"] = columns
            result["column_count"] = len(columns)

            required_fields = [
                _get_field(config, "patient_id_field", "patient_id"),
                _get_field(config, "visit_id_field", "visit_id"),
                _get_field(config, "content_field", "progress_message"),
                _get_field(config, "dept_field", "dept_name"),
            ]
            missing = [f for f in required_fields if f not in columns]
            result["missing_columns"] = missing
            result["columns_ok"] = len(missing) == 0

            try:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{view}" WHERE 1 = 0')
                result["view_accessible"] = True
            except Exception:
                result["view_accessible"] = False

            try:
                cur.execute(
                    f'SELECT 1 FROM "{schema}"."{view}" LIMIT %s', (1,)
                )
                rows = cur.fetchall()
                result["sample_rows"] = len(rows)
                result["message_readable"] = True
            except Exception:
                result["sample_rows"] = 0
                result["message_readable"] = False

        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_base_sql_fields(config: dict) -> tuple[str, str, str, str, str, str, str, str, str, str, str, str, str]:
    """读取并校验所有字段名，返回 (pid, vid, dept, content, title, type, template, rtime, ftime, fstime, cdate, doctor, status) 字段名。"""
    pid = _get_field(config, "patient_id_field", "patient_id")
    vid = _get_field(config, "visit_id_field", "visit_id")
    dept = _get_field(config, "dept_field", "dept_name")
    content = _get_field(config, "content_field", "progress_message")
    title = _get_field(config, "title_field", "progress_title_name")
    typ = _get_field(config, "type_field", "progress_type_name")
    template = _get_field(config, "template_field", "progress_template_name")
    rtime = _get_field(config, "record_time_field", "record_time_format")
    ftime = _get_field(config, "finish_time_field", "finish_time_format")
    fstime = _get_field(config, "first_save_time_field", "first_save_time")
    cdate = _get_field(config, "create_date_field", "create_date")
    doctor = _get_field(config, "doctor_field", "doctor_name")
    status = _get_field(config, "status_field", "progress_status")
    return pid, vid, dept, content, title, typ, template, rtime, ftime, fstime, cdate, doctor, status


def _validate_schema_view(config: dict) -> tuple[str, str]:
    schema = config.get("schema", "jhemr") or "jhemr"
    view = config.get("view", "v_blws") or "v_blws"
    if not _FIELD_NAME_RE.match(schema) or not _FIELD_NAME_RE.match(view):
        raise ValueError(f"非法 schema/view: {schema}.{view}")
    return schema, view


def fetch_emr_documents_by_visits(
    config: dict,
    patient_keys: list[tuple[str, str]],
    document_kind: str = "all",
) -> dict[tuple[str, str], list[dict]]:
    """按患者住院次批量查询文书。返回 {(patient_id, visit_number): [records]}。

    document_kind:
        all            - 所有文书
        discharge      - 仅出院记录
        progress       - 排除出院记录的病程文书
        first_progress - 首次病程/入院记录
    """
    if not patient_keys:
        return {}

    pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, status_f = _build_base_sql_fields(config)
    schema, view = _validate_schema_view(config)
    max_records = int(config.get("max_records", 50000) or 50000)
    batch_size = int(config.get("batch_size", 500) or 500)

    event_time_expr = _build_event_time_expr(ftime_f, rtime_f, fstime_f, cdate_f)
    record_name_expr = f"COALESCE(NULLIF({title_f},''), NULLIF({tmpl_f},''), NULLIF({type_f},''))"
    kind_filter = _build_kind_filter(type_f, title_f, tmpl_f, document_kind)

    result: dict[tuple[str, str], list[dict]] = {}
    total_rows = 0

    for batch_start in range(0, len(patient_keys), batch_size):
        batch = patient_keys[batch_start:batch_start + batch_size]
        placeholders = ",".join(["(%s,%s)"] * len(batch))
        flat_params: list[Any] = []
        for pid, vid in batch:
            flat_params.extend([pid, vid])

        sql = f"""
            WITH target(pid, vid) AS (VALUES {placeholders})
            SELECT
                b.{pid_f} AS patient_id,
                b.{vid_f} AS visit_number,
                b.{dept_f} AS dept,
                {event_time_expr} AS event_time,
                {record_name_expr} AS record_name,
                b.{type_f} AS record_type,
                b.{content_f} AS content,
                b.{doctor_f} AS creator,
                b.{status_f} AS status,
                b.inp_no AS admission_no,
                b.progress_guid AS document_id,
                b.doctor_guid AS creator_id,
                b.state AS state,
                b.msg_type AS message_type
            FROM "{schema}"."{view}" b
            JOIN target t ON b.{pid_f} = t.pid AND b.{vid_f} = t.vid
            WHERE b.{content_f} IS NOT NULL
            {kind_filter}
            ORDER BY b.{pid_f}, b.{vid_f}, {event_time_expr}
        """

        conn = None
        try:
            conn = get_emr_vastbase_connection(config)
            with conn.cursor() as cur:
                cur.execute(sql, flat_params)
                columns = [desc[0].lower() for desc in cur.description]
                rows = cur.fetchmany(max_records - total_rows + 1)
                if len(rows) > (max_records - total_rows):
                    logger.warning("海量库查询结果超过 max_records=%d，已截断", max_records)
                    rows = rows[:max_records - total_rows]

            for row in rows:
                rec = _coerce_record(dict(zip(columns, row)))
                pid_val = rec.get("patient_id", "")
                vn_val = rec.get("visit_number", "")
                if not pid_val:
                    continue
                result.setdefault((pid_val, vn_val), []).append(rec)
                total_rows += 1

            if total_rows >= max_records:
                break
        except Exception:
            logger.exception("海量库查询失败: host=%s db=%s kind=%s batch=%d", config.get("host"), config.get("database"), document_kind, batch_start)
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    logger.info(
        "海量库查询完成: %d 患者住院次, 共 %d 条记录, kind=%s",
        len(result), total_rows, document_kind,
    )
    return result


def fetch_emr_records(
    config: dict,
    dept_list: list[str],
    query_date: str,
    document_kind: str = "all",
    source_name: str = "",
) -> list[dict[str, Any]]:
    """按日期和科室查询文书，用于新质控。返回字典列表。

    document_kind: all/progress/first_progress/discharge
    source_name: 用于推断 document_kind（当 document_kind 为空时）
    """
    if not query_date:
        return []

    resolved_kind = _resolve_document_kind(source_name, document_kind)

    pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, _ = _build_base_sql_fields(config)
    schema, view = _validate_schema_view(config)
    max_records = int(config.get("max_records", 50000) or 50000)

    event_time_expr = _build_event_time_expr(ftime_f, rtime_f, fstime_f, cdate_f)
    record_name_expr = f"COALESCE(NULLIF({title_f},''), NULLIF({tmpl_f},''), NULLIF({type_f},''))"
    kind_filter = _build_kind_filter(type_f, title_f, tmpl_f, resolved_kind)

    # 科室过滤
    params: list[Any] = []
    dept_filter_sql = ""
    if dept_list:
        dept_placeholders = ",".join(["%s"] * len(dept_list))
        dept_filter_sql = f"AND {dept_f} IN ({dept_placeholders})"
        params.extend(dept_list)

    params.append(query_date)

    sql = f"""
        SELECT
            {pid_f} AS patient_id,
            {vid_f} AS visit_number,
            {dept_f} AS dept,
            {event_time_expr} AS event_time,
            {record_name_expr} AS record_name,
            {type_f} AS record_type,
            {content_f} AS content,
            {doctor_f} AS creator,
            inp_no AS admission_no,
            progress_guid AS document_id,
            doctor_guid AS creator_id,
            state AS state,
            msg_type AS message_type
        FROM "{schema}"."{view}"
        WHERE {content_f} IS NOT NULL
          {dept_filter_sql}
          {kind_filter}
          AND LEFT(COALESCE(NULLIF({ftime_f},''), NULLIF({rtime_f},'')), 10) = %s
        ORDER BY {pid_f}, {vid_f}, {event_time_expr}
    """

    conn = None
    try:
        conn = get_emr_vastbase_connection(config)
        with conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [desc[0].lower() for desc in cur.description]
            rows = cur.fetchmany(max_records + 1)
            if len(rows) > max_records:
                logger.warning("海量库按日期查询结果超过 max_records=%d，已截断", max_records)
                rows = rows[:max_records]
        result = [_coerce_record(dict(zip(columns, row))) for row in rows]
        logger.info("海量库按日期查询完成: %d 条记录, date=%s, depts=%s, kind=%s", len(result), query_date, dept_list, resolved_kind)
        return result
    except Exception:
        logger.exception("海量库按日期查询失败: host=%s db=%s", config.get("host"), config.get("database"))
        raise
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
