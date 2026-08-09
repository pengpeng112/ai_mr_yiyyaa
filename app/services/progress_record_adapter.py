"""
012 P2 草案：Vastbase 标准病程 Adapter（基于 16 号只读原型）。

冻结口径（012 §3.3/§7.2/§7.3，不得在本层改写）：
- 范围固定 mr_class IN ('EMR10.00.01','EMR10.00.02','EMR10.00.03')；
- event_time 固定为原生 caption_date_time，禁止对时间 TO_CHAR 过滤；
- 半开时间窗 [date_from, date_to)；先筛键再左关联解码正文；
- 正文缺失保留记录并标记 missing_content，不得静默丢行；
- record_id = file_unique_id；内部关联键 = patient_id + visit_id。

本 adapter 未被任何生产路径调用；切换接线需另行书面批准（016 §3.2）。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Any

from app.services.canonical_record import (
    SOURCE_STATUS_MISSING_CONTENT,
    SOURCE_STATUS_OK,
    CanonicalRecordEnvelope,
    SourceDiagnostics,
    bundle_hash,
    coerce_visit_number,
    normalize_column_name,
)

logger = logging.getLogger(__name__)

PROGRESS_MAPPING_VERSION_V1 = "progress-scope-mapping-v1-20260808"

#: 冻结的三类病程范围（012 §0/§7.3）
PROGRESS_MR_CLASSES_V1 = ("EMR10.00.01", "EMR10.00.02", "EMR10.00.03")

# Daily 双源加载默认按固定大小分片，避免把 anchor 数量直接变成数据库往返次数。
DEFAULT_PROGRESS_BATCH_SIZE = 50
MAX_PROGRESS_BATCH_SIZE = 200


def _parse_db_datetime(value: Any) -> datetime | date | Any | None:
    """兼容 Vastbase 实际返回的时间字符串，非法值留给契约 fail-closed。"""
    if value is None or isinstance(value, (datetime, date)):
        return value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        return value

#: 16 号只读原型（docs/sql/16_vastbase_progress_record_v1_readonly_select.sql）应用内副本。
#: psycopg2 绑定契约：%(patient_id)s / %(visit_number)s / %(date_from)s / %(date_to)s。
PROGRESS_RECORD_V1_SQL = """
WITH target_visits (patient_id, visit_id) AS (
    VALUES (
        CAST(%(patient_id)s AS varchar),
        CAST(%(visit_number)s AS numeric)
    )
),
filtered_index AS (
    SELECT
        i.patient_id,
        i.visit_id,
        i.file_unique_id,
        i.caption_date_time,
        i.create_date_time,
        i.first_mr_sign_date_time,
        i.last_modify_date_time,
        i.mr_class,
        i.topic,
        i.creator_id,
        i.dept_code
    FROM jhemr.jhmr_file_index i
    JOIN target_visits t
      ON t.patient_id = i.patient_id
     AND t.visit_id = i.visit_id
    WHERE i.delete_flag = 0
      AND i.mr_class IN (
          'EMR10.00.01',
          'EMR10.00.02',
          'EMR10.00.03'
      )
      AND i.caption_date_time >= %(date_from)s
      AND i.caption_date_time < %(date_to)s
)
SELECT
    i.patient_id AS patient_key_internal,
    i.visit_id AS visit_number_internal,
    i.file_unique_id AS progress_record_id,
    i.caption_date_time AS event_time,
    i.create_date_time AS created_at,
    i.first_mr_sign_date_time AS signed_at,
    i.last_modify_date_time AS source_updated_at,
    i.mr_class AS progress_class_code,
    CASE
        WHEN i.topic LIKE '%%术后首程%%' OR i.topic LIKE '%%术后首次病程%%'
            THEN 'postop_first_progress'
        WHEN i.topic LIKE '%%首次病程%%'
            THEN 'first_progress'
        WHEN i.topic LIKE '%%查房%%'
            THEN 'ward_round'
        WHEN i.topic LIKE '%%日常病程%%'
            THEN 'daily_progress'
        ELSE 'progress_other'
    END AS record_subtype,
    i.topic AS progress_title,
    CASE
        WHEN c.file_unique_id IS NULL THEN NULL
        ELSE jhemr.safe_convert_from26(c.mr_content)
    END AS progress_content,
    i.creator_id AS author_code,
    i.dept_code,
    CASE
        WHEN c.file_unique_id IS NULL THEN 'missing_content'
        ELSE 'ok'
    END AS source_status
FROM filtered_index i
LEFT JOIN jhfile.jhmr_file_content_text c
  ON c.file_unique_id = i.file_unique_id
"""


def _row_to_envelope(row: dict[str, Any]) -> CanonicalRecordEnvelope:
    normalized = {normalize_column_name(k): v for k, v in row.items()}
    status = str(normalized.get("source_status") or SOURCE_STATUS_OK).strip()
    if status not in (SOURCE_STATUS_OK, SOURCE_STATUS_MISSING_CONTENT):
        status = SOURCE_STATUS_MISSING_CONTENT
    return CanonicalRecordEnvelope(
        source_system="vastbase_jhemr",
        source_name="progress",
        record_kind="progress",
        record_subtype=str(normalized.get("record_subtype") or "progress_other"),
        record_id=str(normalized.get("progress_record_id") or "").strip(),
        patient_key_internal=str(normalized.get("patient_key_internal") or "").strip(),
        visit_number_internal=coerce_visit_number(normalized.get("visit_number_internal")),
        event_time=_parse_db_datetime(normalized.get("event_time")),
        created_at=_parse_db_datetime(normalized.get("created_at")),
        signed_at=_parse_db_datetime(normalized.get("signed_at")),
        source_updated_at=_parse_db_datetime(normalized.get("source_updated_at")),
        template_code=str(normalized.get("progress_class_code") or ""),
        record_name=str(normalized.get("progress_title") or ""),
        content=normalized.get("progress_content"),
        dept_code=str(normalized.get("dept_code") or ""),
        author_code=str(normalized.get("author_code") or ""),
        source_status=status,
        mapping_version=PROGRESS_MAPPING_VERSION_V1,
    )


def _validate_progress_identity(
    envelope: CanonicalRecordEnvelope,
    expected: set[tuple[str, str]],
) -> bool:
    """确认数据库返回行仍属于本次请求的 patient+visit 集合。"""
    if not expected:
        return True
    identity = (
        str(envelope.patient_key_internal or "").strip(),
        coerce_visit_number(envelope.visit_number_internal),
    )
    return identity in expected


def _consume_progress_rows(
    rows: list[tuple[Any, ...]],
    columns: list[str],
    diagnostics: SourceDiagnostics,
    expected: set[tuple[str, str]],
    seen_ids: set[str] | None = None,
) -> list[CanonicalRecordEnvelope]:
    seen_ids = seen_ids if seen_ids is not None else set()
    envelopes: list[CanonicalRecordEnvelope] = []
    for raw_row in rows:
        diagnostics.row_count += 1
        row = dict(zip(columns, raw_row))
        envelope = _row_to_envelope(row)
        if not _validate_progress_identity(envelope, expected):
            diagnostics.skipped_count += 1
            diagnostics.error_code = "identity_mismatch"
            logger.error("病程返回行身份不匹配，fail-closed 跳过（来源哈希=%s）", bundle_hash(
                envelope.patient_key_internal, envelope.visit_number_internal,
            ))
            raise ValueError("progress source identity mismatch")
        errors = envelope.validate()
        if errors:
            diagnostics.skipped_count += 1
            logger.warning(
                "病程信封契约校验失败，跳过（bundle=%s）：%s",
                bundle_hash(envelope.patient_key_internal, envelope.visit_number_internal),
                "; ".join(errors),
            )
            continue
        if envelope.record_id in seen_ids:
            diagnostics.skipped_count += 1
            diagnostics.error_code = "duplicate_record_id"
            logger.error("病程 record_id 重复，fail-closed（稳定 ID 重复必须为 0）")
            raise ValueError("progress source duplicate record_id")
        seen_ids.add(envelope.record_id)
        diagnostics.valid_count += 1
        envelopes.append(envelope)
    return envelopes


def fetch_progress_records_v1(
    conn,
    patient_id: str,
    visit_number: Any,
    date_from,
    date_to,
) -> tuple[list[CanonicalRecordEnvelope], SourceDiagnostics]:
    """按患者+住院次+半开时间窗拉取标准病程信封。

    fail-closed：数据库异常时标记 query_failed 并原样抛出，
    调用方不得把异常当作 0 行（012 §5.2/§8.2.5）。
    """
    diagnostics = SourceDiagnostics(source_name="progress")
    started = time.monotonic()
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            PROGRESS_RECORD_V1_SQL,
            {
                "patient_id": str(patient_id),
                "visit_number": coerce_visit_number(visit_number),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        columns = [normalize_column_name(desc[0]) for desc in cursor.description or []]
        expected = {(str(patient_id).strip(), coerce_visit_number(visit_number))}
        return _consume_progress_rows(cursor.fetchall(), columns, diagnostics, expected), diagnostics
    except Exception as exc:
        diagnostics.query_failed = True
        if not diagnostics.error_code:
            diagnostics.error_code = type(exc).__name__
        logger.error("Vastbase 标准病程查询失败（fail-closed）：%s", type(exc).__name__)
        raise
    finally:
        diagnostics.elapsed_ms = int((time.monotonic() - started) * 1000)
        if cursor is not None:
            try:
                cursor.close()
            except Exception as exc:  # noqa: BLE001 - 关闭失败仅记录
                logger.warning("关闭病程查询游标失败：%s", type(exc).__name__)


def _progress_batch_sql(size: int) -> str:
    """生成带每目标时间窗的多 patient+visit target CTE。"""
    if size <= 0:
        raise ValueError("progress batch size must be positive")
    values = ",\n".join(
        f"        (CAST(%(patient_id_{i})s AS varchar), CAST(%(visit_number_{i})s AS numeric), %(date_from_{i})s, %(date_to_{i})s)"
        for i in range(size)
    )
    sql = PROGRESS_RECORD_V1_SQL.replace(
        "WITH target_visits (patient_id, visit_id) AS (",
        "WITH target_visits (patient_id, visit_id, date_from, date_to) AS (",
    ).replace(
        "VALUES (\n        CAST(%(patient_id)s AS varchar),\n        CAST(%(visit_number)s AS numeric)\n    )",
        "VALUES\n" + values,
    )
    sql = sql.replace(
        "AND i.caption_date_time >= %(date_from)s\n      AND i.caption_date_time < %(date_to)s",
        "AND i.caption_date_time >= t.date_from\n      AND i.caption_date_time < t.date_to",
    )
    if (
        "WITH target_visits (patient_id, visit_id, date_from, date_to)" not in sql
        or "i.caption_date_time >= t.date_from" not in sql
        or "%(patient_id)s" in sql
        or "%(date_from)s" in sql
    ):
        raise RuntimeError("progress batch SQL template drift detected")
    return sql


def fetch_progress_records_v1_batch(
    conn,
    visits: list[tuple[str, Any] | tuple[str, Any, Any, Any]],
    date_from,
    date_to,
    batch_size: int = DEFAULT_PROGRESS_BATCH_SIZE,
) -> tuple[dict[tuple[str, str], list[CanonicalRecordEnvelope]], SourceDiagnostics]:
    """按 patient+visit 分片批量取病程；单 bundle API 保持不变。"""
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or batch_size <= 0
        or batch_size > MAX_PROGRESS_BATCH_SIZE
    ):
        raise ValueError(f"progress batch_size must be an integer in [1, {MAX_PROGRESS_BATCH_SIZE}]")
    normalized: list[tuple[str, str, Any, Any]] = []
    target_windows: dict[tuple[str, str], tuple[Any, Any]] = {}
    for item in visits or []:
        if len(item) >= 4:
            patient_id, visit_number, local_from, local_to = item[:4]
        else:
            patient_id, visit_number = item[:2]
            local_from, local_to = date_from, date_to
        patient = str(patient_id or "").strip()
        visit = coerce_visit_number(visit_number)
        if not patient or not visit:
            continue
        key = (patient, visit)
        window = (local_from, local_to)
        previous_window = target_windows.get(key)
        if previous_window is None:
            target_windows[key] = window
            normalized.append((patient, visit, local_from, local_to))
        elif previous_window != window:
            raise ValueError("progress batch contains conflicting windows for one business key")
    if not normalized:
        return {}, SourceDiagnostics(source_name="progress")
    diagnostics = SourceDiagnostics(source_name="progress")
    started = time.monotonic()
    result: dict[tuple[str, str], list[CanonicalRecordEnvelope]] = {
        (patient, visit): [] for patient, visit, _, _ in normalized
    }
    seen_ids: set[str] = set()
    try:
        for offset in range(0, len(normalized), batch_size):
            chunk = normalized[offset:offset + batch_size]
            cursor = None
            try:
                cursor = conn.cursor()
                params: dict[str, Any] = {}
                for index, (patient_id, visit_number, local_from, local_to) in enumerate(chunk):
                    params[f"patient_id_{index}"] = patient_id
                    params[f"visit_number_{index}"] = visit_number
                    params[f"date_from_{index}"] = local_from
                    params[f"date_to_{index}"] = local_to
                cursor.execute(_progress_batch_sql(len(chunk)), params)
                columns = [normalize_column_name(desc[0]) for desc in cursor.description or []]
                expected = {(patient, visit) for patient, visit, _, _ in chunk}
                envelopes = _consume_progress_rows(
                    cursor.fetchall(), columns, diagnostics, expected, seen_ids=seen_ids,
                )
                for envelope in envelopes:
                    key = (str(envelope.patient_key_internal).strip(), coerce_visit_number(envelope.visit_number_internal))
                    result.setdefault(key, []).append(envelope)
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception as exc:  # noqa: BLE001 - 关闭失败仅记录
                        logger.warning("关闭病程批量查询游标失败：%s", type(exc).__name__)
        return result, diagnostics
    except Exception as exc:
        diagnostics.query_failed = True
        if not diagnostics.error_code:
            diagnostics.error_code = type(exc).__name__
        logger.error("Vastbase 标准病程批量查询失败（fail-closed）：%s", type(exc).__name__)
        raise
    finally:
        diagnostics.elapsed_ms = int((time.monotonic() - started) * 1000)
