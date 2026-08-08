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
_KIND_FILTER_RE = re.compile(
    r"^AND\s+COALESCE\(([a-zA-Z_][a-zA-Z0-9_]{0,63}),\s*''\)\s+(=|LIKE)\s+'[^']{1,100}'$",
    re.IGNORECASE,
)
_KIND_FILTER_IN_RE = re.compile(
    r"^AND\s+COALESCE\(([a-zA-Z_][a-zA-Z0-9_]{0,63}),\s*''\)\s+IN\s+"
    r"\(\s*'[^']{1,100}'(?:\s*,\s*'[^']{1,100}'){0,19}\s*\)$",
    re.IGNORECASE,
)

# 003-B：瞬态错误重试 / 总截止时间
_DEFAULT_BATCH_MAX_RETRIES = 2
_DEFAULT_TOTAL_DEADLINE_SECONDS = 300


class VastbaseQueryError(RuntimeError):
    """海量库查询失败，携带稳定错误码。"""

    def __init__(self, error_code: str, message: str, *, batch_index: int | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.batch_index = batch_index


def _is_transient_db_error(exc: BaseException) -> bool:
    name = type(exc).__name__
    msg = str(exc).lower()
    if "querycanceled" in name.lower() or "canceling statement" in msg or "statement timeout" in msg:
        return True
    if "operationalerror" in name.lower() and any(
        token in msg for token in ("connection", "server closed", "could not connect", "timeout", "broken pipe")
    ):
        return True
    if "interfaceerror" in name.lower():
        return True
    return False


def _classify_vastbase_error(exc: BaseException) -> str:
    if isinstance(exc, VastbaseQueryError):
        return exc.error_code
    name = type(exc).__name__
    msg = str(exc).lower()
    if "querycanceled" in name.lower() or "statement timeout" in msg or "canceling statement" in msg:
        return "VASTBASE_STATEMENT_TIMEOUT"
    if "operationalerror" in name.lower() or "interfaceerror" in name.lower():
        return "VASTBASE_CONNECTION_TRANSIENT"
    if "permission" in msg or "privilege" in msg:
        return "VASTBASE_PERMISSION"
    if "syntax" in msg or "undefinedcolumn" in name.lower() or "does not exist" in msg:
        return "VASTBASE_SQL_OR_SCHEMA"
    return "VASTBASE_QUERY_FAILED"


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
    if document_kind == "admission":
        return f"AND COALESCE({template_field},'') = '入院记录'"
    if document_kind == "surgery":
        return f"AND COALESCE({template_field},'') LIKE '%%手术记录%%'"
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
    if source_name == "admission":
        return "admission"
    if source_name == "surgery":
        return "surgery"
    if source_name == "progress":
        return "progress"
    return "all"


def _validate_kind_filter(kind_filter: str, allowed_fields: set[str] | None = None) -> str:
    value = str(kind_filter or "").strip()
    if not value:
        return ""
    match = _KIND_FILTER_RE.fullmatch(value) or _KIND_FILTER_IN_RE.fullmatch(value)
    if not match or (allowed_fields is not None and match.group(1) not in allowed_fields):
        raise ValueError("kind_filter 仅允许受控文书字段的单一 AND/COALESCE 比较")
    return value


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
    kind_filter: str = "",
    source_name: str = "",
) -> dict[tuple[str, str], list[dict]]:
    """按患者住院次批量查询文书。返回 {(patient_id, visit_number): [records]}。

    document_kind:
        all            - 所有文书
        discharge      - 仅出院记录
        progress       - 排除出院记录的病程文书
        first_progress - 首次病程/入院记录
    kind_filter:
        自定义文书过滤 SQL 片段，不为空时覆盖 document_kind 自动生成的过滤。
    """
    if not patient_keys:
        return {}

    pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, status_f = _build_base_sql_fields(config)
    schema, view = _validate_schema_view(config)
    max_records = int(config.get("max_records", 50000) or 50000)
    batch_size = min(max(int(config.get("batch_size", 500) or 500), 1), 5000)
    max_retries = min(max(int(config.get("batch_max_retries", _DEFAULT_BATCH_MAX_RETRIES) or 0), 0), 5)
    total_deadline_s = min(
        max(int(config.get("total_deadline_seconds", _DEFAULT_TOTAL_DEADLINE_SECONDS) or 60), 30),
        1800,
    )

    event_time_expr = _build_event_time_expr(ftime_f, rtime_f, fstime_f, cdate_f)
    record_name_expr = f"COALESCE(NULLIF({title_f},''), NULLIF({tmpl_f},''), NULLIF({type_f},''))"
    resolved_kind = _resolve_document_kind(source_name, document_kind) if source_name else document_kind
    effective_kind_filter = _validate_kind_filter(kind_filter, {type_f, title_f, tmpl_f}) if kind_filter else _build_kind_filter(type_f, title_f, tmpl_f, resolved_kind)

    result: dict[tuple[str, str], list[dict]] = {}
    total_rows = 0
    started = time.monotonic()
    batch_timings: list[float] = []
    total_batches = (len(patient_keys) + batch_size - 1) // batch_size if patient_keys else 0

    for batch_index, batch_start in enumerate(range(0, len(patient_keys), batch_size)):
        if time.monotonic() - started > total_deadline_s:
            raise VastbaseQueryError(
                "VASTBASE_TOTAL_DEADLINE",
                f"海量库查询超过总截止时间 {total_deadline_s}s（已完成批 {batch_index}/{total_batches}）",
                batch_index=batch_index,
            )
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
            {effective_kind_filter}
            ORDER BY b.{pid_f}, b.{vid_f}, {event_time_expr}
        """

        attempt = 0
        while True:
            if time.monotonic() - started > total_deadline_s:
                result.clear()
                raise VastbaseQueryError(
                    "VASTBASE_TOTAL_DEADLINE",
                    f"海量库查询超过总截止时间 {total_deadline_s}s（批 {batch_index + 1}/{total_batches}）",
                    batch_index=batch_index,
                )
            conn = None
            batch_t0 = time.monotonic()
            try:
                conn = get_emr_vastbase_connection(config)
                with conn.cursor() as cur:
                    cur.execute(sql, flat_params)
                    columns = [desc[0].lower() for desc in cur.description]
                    rows = cur.fetchmany(max_records - total_rows + 1)
                    if len(rows) > (max_records - total_rows):
                        raise VastbaseQueryError(
                            "VASTBASE_MAX_RECORDS_EXCEEDED",
                            f"海量库查询结果超过 max_records={max_records}，拒绝返回部分结果",
                            batch_index=batch_index,
                        )

                if time.monotonic() - started > total_deadline_s:
                    raise VastbaseQueryError(
                        "VASTBASE_TOTAL_DEADLINE",
                        f"海量库查询超过总截止时间 {total_deadline_s}s（批 {batch_index + 1}/{total_batches}）",
                        batch_index=batch_index,
                    )

                for row in rows:
                    rec = _coerce_record(dict(zip(columns, row)))
                    pid_val = rec.get("patient_id", "")
                    vn_val = rec.get("visit_number", "")
                    if not pid_val:
                        continue
                    result.setdefault((pid_val, vn_val), []).append(rec)
                    total_rows += 1

                batch_timings.append(time.monotonic() - batch_t0)
                break
            except Exception as exc:
                code = _classify_vastbase_error(exc)
                transient = _is_transient_db_error(exc)
                logger.exception(
                    "海量库查询失败: host=%s db=%s kind=%s batch=%d/%d keys=%d attempt=%d code=%s transient=%s",
                    config.get("host"),
                    config.get("database"),
                    document_kind,
                    batch_index + 1,
                    total_batches,
                    len(batch),
                    attempt + 1,
                    code,
                    transient,
                )
                if transient and attempt < max_retries:
                    attempt += 1
                    sleep_seconds = min(2 ** attempt, 8)
                    if time.monotonic() - started + sleep_seconds > total_deadline_s:
                        result.clear()
                        raise VastbaseQueryError(
                            "VASTBASE_TOTAL_DEADLINE",
                            f"海量库重试将超过总截止时间 {total_deadline_s}s",
                            batch_index=batch_index,
                        ) from exc
                    time.sleep(sleep_seconds)
                    continue
                # v1 整类原子：丢弃已取内存结果，不部分提交
                result.clear()
                if isinstance(exc, VastbaseQueryError):
                    raise
                raise VastbaseQueryError(
                    code,
                    f"海量库查询失败 batch={batch_index + 1}/{total_batches} code={code}: {exc}",
                    batch_index=batch_index,
                ) from exc
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        if total_rows >= max_records and batch_index + 1 < total_batches:
            result.clear()
            raise VastbaseQueryError(
                "VASTBASE_MAX_RECORDS_EXCEEDED",
                f"海量库查询达到 max_records={max_records} 且仍有未查询批次，拒绝返回部分结果",
                batch_index=batch_index,
            )

    slowest = max(batch_timings) if batch_timings else 0.0
    logger.info(
        "海量库查询完成: keys=%d batches=%d batch_size=%d rows=%d kind=%s elapsed=%.2fs slowest_batch=%.2fs",
        len(patient_keys),
        len(batch_timings),
        batch_size,
        total_rows,
        document_kind,
        time.monotonic() - started,
        slowest,
    )
    return result


def fetch_emr_documents_by_visits_and_date(
    config: dict,
    patient_keys: list[tuple[str, str]],
    query_date: str,
    document_kind: str = "all",
    kind_filter: str = "",
    source_name: str = "",
) -> dict[tuple[str, str], list[dict]]:
    """按患者住院次 + 指定日期查询文书（在院日增量模式专用）。

    与 fetch_emr_documents_by_visits 的区别：SQL 层直接按文书日期过滤，
    避免拉取全部历史文书后在 Python 端过滤的性能问题。
    """
    if not patient_keys or not query_date:
        return {}

    pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, status_f = _build_base_sql_fields(config)
    schema, view = _validate_schema_view(config)
    max_records = int(config.get("max_records", 50000) or 50000)
    batch_size = min(max(int(config.get("batch_size", 500) or 500), 1), 5000)

    event_time_expr = _build_event_time_expr(ftime_f, rtime_f, fstime_f, cdate_f)
    record_name_expr = f"COALESCE(NULLIF({title_f},''), NULLIF({tmpl_f},''), NULLIF({type_f},''))"
    resolved_kind = _resolve_document_kind(source_name, document_kind) if source_name else document_kind
    effective_kind_filter = _validate_kind_filter(kind_filter, {type_f, title_f, tmpl_f}) if kind_filter else _build_kind_filter(type_f, title_f, tmpl_f, resolved_kind)
    date_cond = f"AND LEFT(COALESCE(NULLIF({ftime_f},''), NULLIF({rtime_f},'')), 10) = %s"

    result: dict[tuple[str, str], list[dict]] = {}
    total_rows = 0

    for batch_start in range(0, len(patient_keys), batch_size):
        batch = patient_keys[batch_start:batch_start + batch_size]
        placeholders = ",".join(["(%s,%s)"] * len(batch))
        flat_params: list[Any] = []
        for pid, vid in batch:
            flat_params.extend([pid, vid])
        flat_params.append(query_date)

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
            {effective_kind_filter}
            {date_cond}
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
                    raise VastbaseQueryError(
                        "VASTBASE_MAX_RECORDS_EXCEEDED",
                        f"海量库按日期查询超过 max_records={max_records}，拒绝返回部分结果",
                        batch_index=batch_start // batch_size if batch_size else 0,
                    )

            for row in rows:
                rec = _coerce_record(dict(zip(columns, row)))
                pid_val = rec.get("patient_id", "")
                vn_val = rec.get("visit_number", "")
                if not pid_val:
                    continue
                result.setdefault((pid_val, vn_val), []).append(rec)
                total_rows += 1

            if total_rows >= max_records and batch_start + batch_size < len(patient_keys):
                raise VastbaseQueryError(
                    "VASTBASE_MAX_RECORDS_EXCEEDED",
                    f"海量库按日期查询达到 max_records={max_records} 且仍有未查询批次",
                    batch_index=batch_start // batch_size if batch_size else 0,
                )
        except Exception as exc:
            code = _classify_vastbase_error(exc)
            logger.exception(
                "海量库按日期+患者查询失败: host=%s db=%s date=%s code=%s",
                config.get("host"),
                config.get("database"),
                query_date,
                code,
            )
            result.clear()
            if isinstance(exc, VastbaseQueryError):
                raise
            raise VastbaseQueryError(
                code,
                f"海量库按日期+患者查询失败 code={code}: {exc}",
                batch_index=batch_start // batch_size if batch_size else 0,
            ) from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    logger.info(
        "海量库按日期+患者查询完成: %d 患者住院次, 共 %d 条记录, date=%s",
        len(result), total_rows, query_date,
    )
    return result


def fetch_emr_records(
    config: dict,
    dept_list: list[str],
    query_date: str,
    document_kind: str = "all",
    source_name: str = "",
    kind_filter: str = "",
) -> list[dict[str, Any]]:
    """按日期和科室查询文书，用于新质控。返回字典列表。

    document_kind: all/progress/first_progress/discharge/admission/surgery
    source_name: 用于推断 document_kind（当 document_kind 为空时）
    kind_filter: 自定义文书过滤 SQL，不为空时直接使用（覆盖自动生成的过滤）
    """
    if not query_date:
        return []

    resolved_kind = _resolve_document_kind(source_name, document_kind)

    pid_f, vid_f, dept_f, content_f, title_f, type_f, tmpl_f, rtime_f, ftime_f, fstime_f, cdate_f, doctor_f, _ = _build_base_sql_fields(config)
    schema, view = _validate_schema_view(config)
    max_records = int(config.get("max_records", 50000) or 50000)

    event_time_expr = _build_event_time_expr(ftime_f, rtime_f, fstime_f, cdate_f)
    record_name_expr = f"COALESCE(NULLIF({title_f},''), NULLIF({tmpl_f},''), NULLIF({type_f},''))"
    effective_kind_filter = _validate_kind_filter(kind_filter, {type_f, title_f, tmpl_f}) if kind_filter else _build_kind_filter(type_f, title_f, tmpl_f, resolved_kind)

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
          {effective_kind_filter}
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
