"""
012 P2 草案：双源 loader（病程=Vastbase V1 + 护理=Oracle V2，flag 默认 off）。

仅在 audit_type.payload.source_flags 指向新源时由 load_patient_bundles 顶部
分发进入；旧路径（关联/分组/fanout）完全不受影响。

范围约束（KISS/YAGNI，草案）：
- 仅支持 progress_source=vastbase_v1 且 nursing_source=oracle_v1 的**全双源**模式；
  单源混合切换（P5 先切病程）需另行实现，当前 fail-closed 拒绝；
- 锚点来自 audit_type.payload.dual_source.anchor_query_sql（Oracle V_QYBR 系），
  经 validate_configurable_sql 校验；绑定契约 :date_from / :date_to；
- 时间窗由 RelationPolicy 决定：daily 双侧 query_date 单日（护理 form_time）；
  discharge 病程入院→出院+1（护理 created_date）；
- 任一 required 源查询失败整批 fail-closed（异常上抛，不写成 0 条）；
- 缺锚点键/时间的记录跳过并计数，禁止猜键。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

from app.db_client_base import validate_configurable_sql
from app.emr_vastbase_client import get_emr_vastbase_connection
from app.oracle_client import get_oracle_connection
from app.schemas import AuditTypeConfig
from app.services.config_parser import ConfigParser
from app.services.canonical_record import (
    CanonicalRecordEnvelope,
    SourceDiagnostics,
    coerce_visit_number,
)
from app.services.data_source_loader import PatientBundle
from app.services.nursing_record_adapter import (
    DEFAULT_NURSING_BATCH_SIZE,
    NURSING_DATE_FIELD_CREATED_DATE,
    NURSING_DATE_FIELD_FORM_TIME,
    build_ydhl_patient_key,
    fetch_nursing_records_v2_batch,
)
from app.services.progress_record_adapter import (
    DEFAULT_PROGRESS_BATCH_SIZE,
    fetch_progress_records_v1_batch,
)
from app.services.progress_nursing_multi_source_builder import register_dual_source_builder
from app.services.relation_policy import (
    RUN_MODE_DAILY,
    RUN_MODE_DISCHARGE,
    get_relation_policy,
    validate_required_sources,
)
from app.services.source_feature_flags import (
    NURSING_SOURCE_ORACLE_V1,
    PROGRESS_SOURCE_VASTBASE_V1,
    SourceFlags,
)

logger = logging.getLogger(__name__)

#: 锚点查询必须输出的最小字段（经 anchor_field_mapping 映射后）
_ANCHOR_REQUIRED_KEYS = ("patient_id", "visit_number")
_ANCHOR_SUPPORTED_KEYS = _ANCHOR_REQUIRED_KEYS + (
    "admission_time", "discharge_time", "dept_code", "dept_name",
    "patient_name", "admission_no", "gender", "birth_date",
    "admission_date", "discharge_date", "admission_diagnosis",
    "discharge_main_diagnosis", "admission_condition", "nursing_level",
    "admission_dept_name", "discharge_dept_name", "attending_doctor",
    "attending_doctor_name", "attending_doctor_userid", "doctor_id",
    "nurse_head_userid", "nurse_head_name",
)
_DEFAULT_BATCH_SIZE = min(DEFAULT_PROGRESS_BATCH_SIZE, DEFAULT_NURSING_BATCH_SIZE)
_MAX_BATCH_SIZE = 200
_DEFAULT_MAX_ANCHORS = 5000
_DEFAULT_MAX_SECONDS = 120


def _resolve_run_mode(audit_run_mode: str, date_dimension: str) -> str:
    if "discharge" in str(audit_run_mode or ""):
        return RUN_MODE_DISCHARGE
    if str(audit_run_mode or "") == "" and str(date_dimension or "") == "discharge_date":
        return RUN_MODE_DISCHARGE
    return RUN_MODE_DAILY


def _day_window(query_date: str) -> tuple[datetime, datetime]:
    base = datetime.strptime(query_date, "%Y-%m-%d")
    return base, base + timedelta(days=1)


def _date_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else ""


def _envelope_to_record(envelope: CanonicalRecordEnvelope) -> dict[str, Any]:
    """信封序列化为 PatientBundle.sources 记录字典（时间保持原生类型）。"""
    return {
        "record_id": envelope.record_id,
        "record_kind": envelope.record_kind,
        "record_subtype": envelope.record_subtype,
        "record_name": envelope.record_name,
        "content": envelope.content,
        "event_time": envelope.event_time,
        "created_at": envelope.created_at,
        "signed_at": envelope.signed_at,
        "source_updated_at": envelope.source_updated_at,
        "template_code": envelope.template_code,
        "dept_code": envelope.dept_code,
        "author_code": envelope.author_code,
        "source_status": envelope.source_status,
        "mapping_version": envelope.mapping_version,
        "structured_fields": dict(envelope.structured_fields or {}),
    }


def _guard_global_record_ids(
    source_name: str,
    records_by_key: dict[tuple[str, str], list[CanonicalRecordEnvelope]],
    seen_ids: set[str],
) -> None:
    """跨数据库查询分片校验稳定记录 ID，重复时整批 fail-closed。"""
    for records in records_by_key.values():
        for envelope in records:
            record_id = str(envelope.record_id or "").strip()
            if record_id in seen_ids:
                raise ValueError(f"{source_name} source duplicate record_id across batches")
            seen_ids.add(record_id)


def _fetch_anchor_rows(
    conn,
    anchor_sql: str,
    anchor_mapping: dict[str, str],
    date_from: datetime,
    date_to: datetime,
    required_keys: tuple[str, ...] = _ANCHOR_REQUIRED_KEYS,
) -> tuple[list[dict[str, Any]], int]:
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(anchor_sql, {"date_from": date_from, "date_to": date_to})
        columns = [str(desc[0]).strip() for desc in cursor.description or []]
        available = {str(column).strip().lower() for column in columns}
        required = list(required_keys)
        missing = []
        for canonical_key in required:
            actual = str(anchor_mapping.get(canonical_key) or canonical_key).strip().lower()
            if actual not in available:
                missing.append(canonical_key)
        if missing:
            raise ValueError("anchor query missing required columns: " + ", ".join(missing))
        rows: list[dict[str, Any]] = []
        unique: dict[tuple[str, str], dict[str, Any]] = {}
        duplicate_count = 0
        for raw in cursor.fetchall():
            record = dict(zip(columns, raw))
            mapped: dict[str, Any] = {}
            for canonical_key in _ANCHOR_SUPPORTED_KEYS:
                column = str(anchor_mapping.get(canonical_key) or canonical_key)
                value = record.get(column)
                if value is None:
                    # Oracle 大小写不敏感防御
                    value = record.get(column.upper(), record.get(column.lower()))
                mapped[canonical_key] = value
            patient = str(mapped.get("patient_id") or "").strip()
            visit = coerce_visit_number(mapped.get("visit_number"))
            if not patient or not visit:
                rows.append(mapped)
                continue
            key = (patient, visit)
            previous = unique.get(key)
            if previous is None:
                unique[key] = mapped
                rows.append(mapped)
            elif previous == mapped:
                duplicate_count += 1
            else:
                raise ValueError("anchor query returned conflicting rows for one business key")
        return rows, duplicate_count
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("关闭锚点查询游标失败：%s", type(exc).__name__)


def load_patient_bundles_dual_source(
    audit_type: AuditTypeConfig,
    root_config: dict,
    query_date: str,
    date_dimension: str = "query_date",
    dept_filter: list[str] | None = None,
    return_diagnostics: bool = False,
    flags: SourceFlags | None = None,
    audit_run_mode: str = "",
) -> list[PatientBundle] | tuple[list[PatientBundle], dict]:
    """全双源模式加载：锚点 + Vastbase 病程 + Oracle 护理，各源独立数组。"""
    register_dual_source_builder()

    if flags is None:
        from app.services.source_feature_flags import resolve_source_flags

        payload_cfg = audit_type.payload.model_dump() if hasattr(audit_type.payload, "model_dump") else dict(audit_type.payload or {})
        flags = resolve_source_flags(payload_cfg)
    if flags.progress_source != PROGRESS_SOURCE_VASTBASE_V1 or flags.nursing_source != NURSING_SOURCE_ORACLE_V1:
        # P5 分阶段单源切换未实现：混合 flag 必须 fail-closed，禁止半新半旧拼装
        raise ValueError(
            "双源 loader 仅支持 progress_source=vastbase_v1 且 nursing_source=oracle_v1；"
            f"当前 progress_source={flags.progress_source}, nursing_source={flags.nursing_source}。"
            "单源分阶段切换（012 P5）需另行批准后实现"
        )
    payload_cfg = audit_type.payload.model_dump() if hasattr(audit_type.payload, "model_dump") else dict(audit_type.payload or {})
    dual_cfg = dict(payload_cfg.get("dual_source") or {})
    anchor_sql = validate_configurable_sql(str(dual_cfg.get("anchor_query_sql") or ""), "dual_source.anchor_query_sql")
    anchor_mapping = dict(dual_cfg.get("anchor_field_mapping") or {})

    run_mode = _resolve_run_mode(audit_run_mode, date_dimension)
    policy = get_relation_policy(audit_type.code, run_mode)  # 未知组合 fail-closed
    date_from, date_to = _day_window(query_date)

    diagnostics: dict[str, Any] = {
        "source_row_counts": {"progress": 0, "nursing": 0},
        "skipped_records": 0,
        "dual_source": True,
        "run_mode": run_mode,
        "relation_policy_version": policy.version,
        "source_query_counts": {"anchor": 0, "progress": 0, "nursing": 0},
        "duplicate_anchor_count": 0,
        "relation_matched_counts": {"progress": 0, "nursing": 0},
        "sources": {
            source: {
                "row_count": 0,
                "valid_count": 0,
                "skipped_count": 0,
                "elapsed_ms": 0,
                "retry_count": 0,
                "query_failed": False,
                "error_code": None,
            }
            for source in ("progress", "nursing")
        },
    }
    normalized_dept_filter = {
        str(value or "").strip() for value in (dept_filter or []) if str(value or "").strip()
    }
    started = time.monotonic()

    batch_cfg = dict(dual_cfg.get("batch") or {})
    try:
        def _batch_limit(name: str, default: int, upper: int | None = None) -> int:
            raw = batch_cfg.get(name, default)
            if isinstance(raw, bool):
                raise ValueError(name)
            value = int(raw)
            if value <= 0 or (upper is not None and value > upper):
                raise ValueError(name)
            return value

        batch_size = _batch_limit("size", _DEFAULT_BATCH_SIZE, _MAX_BATCH_SIZE)
        max_anchors = _batch_limit("max_anchors", _DEFAULT_MAX_ANCHORS)
        max_seconds = _batch_limit("max_seconds", _DEFAULT_MAX_SECONDS)
    except (TypeError, ValueError) as exc:
        raise ValueError("dual_source.batch.size/max_anchors/max_seconds must be positive integers") from exc

    oracle_conn = None
    vastbase_conn = None
    try:
        oracle_cfg = ConfigParser.parse_oracle_config(root_config)
        vastbase_cfg = ConfigParser.parse_emr_vastbase_config(root_config)
        oracle_conn = get_oracle_connection(oracle_cfg)
        vastbase_conn = get_emr_vastbase_connection(vastbase_cfg)
        required_anchor_keys = _ANCHOR_REQUIRED_KEYS + (("admission_time", "discharge_time") if run_mode == RUN_MODE_DISCHARGE else ())
        anchors, duplicate_count = _fetch_anchor_rows(
            oracle_conn, anchor_sql, anchor_mapping, date_from, date_to,
            required_keys=required_anchor_keys,
        )
        diagnostics["source_query_counts"]["anchor"] = 1
        diagnostics["duplicate_anchor_count"] = duplicate_count
        diagnostics["anchor_count"] = len(anchors)
        logger.info(
            "[dual_source_loader] code=%s mode=%s query_date=%s anchors=%s",
            audit_type.code, run_mode, query_date, len(anchors),
        )

        eligible_anchors: list[tuple[dict[str, Any], str, str]] = []
        for anchor in anchors:
            if normalized_dept_filter:
                anchor_depts = {
                    str(anchor.get("dept_code") or "").strip(),
                    str(anchor.get("dept_name") or "").strip(),
                }
                anchor_depts.discard("")
                if not anchor_depts.intersection(normalized_dept_filter):
                    diagnostics["skipped_records"] += 1
                    diagnostics["dept_filtered_anchors"] = int(
                        diagnostics.get("dept_filtered_anchors", 0)
                    ) + 1
                    continue

            patient_id = str(anchor.get("patient_id") or "").strip()
            visit_number = coerce_visit_number(anchor.get("visit_number"))
            if not patient_id or not visit_number:
                diagnostics["skipped_records"] += 1
                diagnostics["missing_key_anchors"] = int(
                    diagnostics.get("missing_key_anchors", 0)
                ) + 1
                continue

            if run_mode == RUN_MODE_DISCHARGE:
                admission_time = anchor.get("admission_time")
                discharge_time = anchor.get("discharge_time")
                if not isinstance(admission_time, datetime) or not isinstance(discharge_time, datetime):
                    diagnostics["skipped_records"] += 1
                    diagnostics["discharge_time_missing_anchors"] = int(
                        diagnostics.get("discharge_time_missing_anchors", 0)
                    ) + 1
                    continue
                if not date_from <= discharge_time < date_to:
                    diagnostics["skipped_records"] += 1
                    diagnostics["discharge_date_filtered_anchors"] = int(
                        diagnostics.get("discharge_date_filtered_anchors", 0)
                    ) + 1
                    continue
                eligible_anchors.append((anchor, patient_id, visit_number))
            else:
                eligible_anchors.append((anchor, patient_id, visit_number))

        if len(eligible_anchors) > max_anchors:
            diagnostics["stopped_reason"] = "max_anchors_exceeded_after_filters"
            raise RuntimeError("dual-source eligible anchor limit exceeded; fail-closed")
        diagnostics["eligible_anchor_count"] = len(eligible_anchors)

        bundles: list[PatientBundle] = []
        seen_source_record_ids: dict[str, set[str]] = {
            "progress": set(),
            "nursing": set(),
        }

        def _check_budget() -> None:
            if time.monotonic() - started > max_seconds:
                diagnostics["stopped_reason"] = "max_seconds_exceeded"
                raise TimeoutError("dual-source loader time budget exceeded; fail-closed")

        def _accumulate_source_diag(source: str, source_diag: SourceDiagnostics) -> None:
            target = diagnostics["sources"][source]
            for key in ("row_count", "valid_count", "skipped_count", "elapsed_ms", "retry_count"):
                target[key] += int(getattr(source_diag, key, 0) or 0)
            target["query_failed"] = bool(target["query_failed"] or source_diag.query_failed)
            if source_diag.error_code:
                target["error_code"] = source_diag.error_code

        def _append_bundle(
            anchor: dict[str, Any],
            patient_id: str,
            visit_number: str,
            progress_envelopes,
            nursing_envelopes,
        ) -> None:
            filtered_count = 0
            if run_mode == RUN_MODE_DISCHARGE:
                # 复刻旧 SQL：护理 created_date 必须与病程 event_time 同自然日；LEFT 语义保留病程。
                progress_days = {_date_key(item.event_time) for item in progress_envelopes}
                progress_days.discard("")
                nursing_before = len(nursing_envelopes)
                nursing_envelopes = [
                    item for item in nursing_envelopes
                    if _date_key(item.created_at) in progress_days
                ]
                filtered = nursing_before - len(nursing_envelopes)
                filtered_count = filtered
                diagnostics.setdefault("relation_filtered_counts", {})["nursing_created_date_not_progress_day"] = (
                    int(diagnostics.get("relation_filtered_counts", {}).get(
                        "nursing_created_date_not_progress_day", 0
                    )) + filtered
                )
            diagnostics["relation_matched_counts"]["progress"] += len(progress_envelopes)
            diagnostics["relation_matched_counts"]["nursing"] += len(nursing_envelopes)
            available_sources = set()
            if progress_envelopes:
                available_sources.add("progress")
            if nursing_envelopes:
                available_sources.add("nursing")
            violations = validate_required_sources(policy, available_sources, set())
            if violations:
                diagnostics["skipped_records"] += 1
                missing_counts = diagnostics.setdefault("required_source_missing_counts", {})
                for source_name in policy.required_sources:
                    if source_name not in available_sources:
                        missing_counts[source_name] = int(missing_counts.get(source_name, 0)) + 1
                return

            group_values = {
                key: value for key, value in anchor.items()
                if value not in (None, "")
            }
            group_values["patient_id"] = patient_id
            group_values["visit_number"] = visit_number
            bundle = PatientBundle(
                bundle_id=f"{patient_id}::{visit_number}",
                group_values=group_values,
                sources={
                    "progress": [_envelope_to_record(e) for e in progress_envelopes],
                    "nursing": [_envelope_to_record(e) for e in nursing_envelopes],
                },
                primary_source="progress",
                query_date=query_date,
                relation_metadata={
                    "policy_version": policy.version,
                    "edge_types": list(policy.relation_edges),
                    "progress_count": len(progress_envelopes),
                    "nursing_count": len(nursing_envelopes),
                    "matched_counts": {
                        "progress": len(progress_envelopes),
                        "nursing": len(nursing_envelopes),
                    },
                    "filtered_counts": {
                        "nursing_created_date_not_progress_day": filtered_count,
                    },
                    "filtered_nursing_count": filtered_count,
                    "mapping_versions": {
                        "progress": str((progress_envelopes[0].mapping_version if progress_envelopes else "") or ""),
                        "nursing": str((nursing_envelopes[0].mapping_version if nursing_envelopes else "") or ""),
                    },
                },
            )
            bundles.append(bundle)

        if run_mode == RUN_MODE_DAILY:
            for offset in range(0, len(eligible_anchors), batch_size):
                _check_budget()
                chunk = eligible_anchors[offset:offset + batch_size]
                visits = [(patient_id, visit_number) for _, patient_id, visit_number in chunk]
                progress_by_key, progress_diag = fetch_progress_records_v1_batch(
                    vastbase_conn, visits, date_from, date_to, batch_size=batch_size,
                )
                nursing_by_key, nursing_diag = fetch_nursing_records_v2_batch(
                    oracle_conn, visits, date_from, date_to,
                    date_field=NURSING_DATE_FIELD_FORM_TIME, batch_size=batch_size,
                )
                _guard_global_record_ids(
                    "progress", progress_by_key, seen_source_record_ids["progress"],
                )
                _guard_global_record_ids(
                    "nursing", nursing_by_key, seen_source_record_ids["nursing"],
                )
                diagnostics["source_query_counts"]["progress"] += 1
                diagnostics["source_query_counts"]["nursing"] += 1
                _accumulate_source_diag("progress", progress_diag)
                _accumulate_source_diag("nursing", nursing_diag)
                diagnostics["source_row_counts"]["progress"] += progress_diag.row_count
                diagnostics["source_row_counts"]["nursing"] += nursing_diag.row_count
                _check_budget()
                for anchor, patient_id, visit_number in chunk:
                    _append_bundle(
                        anchor, patient_id, visit_number,
                        progress_by_key.get((patient_id, visit_number), []),
                        nursing_by_key.get((build_ydhl_patient_key(patient_id, visit_number), visit_number), []),
                    )
        else:
            for offset in range(0, len(eligible_anchors), batch_size):
                _check_budget()
                chunk = eligible_anchors[offset:offset + batch_size]
                visits = []
                for source_anchor, patient_id, visit_number in chunk:
                    # 逐目标窗口随绑定参数传入，保持出院全住院期语义。
                    admission_time = source_anchor["admission_time"]
                    discharge_time = source_anchor["discharge_time"]
                    visits.append((patient_id, visit_number, admission_time, discharge_time + timedelta(days=1)))
                progress_by_key, progress_diag = fetch_progress_records_v1_batch(
                    vastbase_conn, visits, date_from, date_to, batch_size=batch_size,
                )
                nursing_by_key, nursing_diag = fetch_nursing_records_v2_batch(
                    oracle_conn, visits, date_from, date_to,
                    date_field=NURSING_DATE_FIELD_CREATED_DATE, batch_size=batch_size,
                )
                _guard_global_record_ids(
                    "progress", progress_by_key, seen_source_record_ids["progress"],
                )
                _guard_global_record_ids(
                    "nursing", nursing_by_key, seen_source_record_ids["nursing"],
                )
                diagnostics["source_row_counts"]["progress"] += progress_diag.row_count
                diagnostics["source_row_counts"]["nursing"] += nursing_diag.row_count
                diagnostics["source_query_counts"]["progress"] += 1
                diagnostics["source_query_counts"]["nursing"] += 1
                _accumulate_source_diag("progress", progress_diag)
                _accumulate_source_diag("nursing", nursing_diag)
                _check_budget()
                for anchor, patient_id, visit_number in chunk:
                    _append_bundle(
                        anchor, patient_id, visit_number,
                        progress_by_key.get((patient_id, visit_number), []),
                        nursing_by_key.get((build_ydhl_patient_key(patient_id, visit_number), visit_number), []),
                    )

        diagnostics["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        if diagnostics.get("required_source_missing_counts"):
            logger.warning(
                "[dual_source_loader] code=%s mode=%s 必需源缺失汇总=%s skipped=%s",
                audit_type.code,
                run_mode,
                diagnostics["required_source_missing_counts"],
                diagnostics["skipped_records"],
            )
        logger.info(
            "[dual_source_loader] code=%s bundles=%s progress_rows=%s nursing_rows=%s elapsed_ms=%s",
            audit_type.code, len(bundles),
            diagnostics["source_row_counts"]["progress"],
            diagnostics["source_row_counts"]["nursing"],
            diagnostics["elapsed_ms"],
        )
        if return_diagnostics:
            return bundles, diagnostics
        return bundles
    finally:
        for conn, name in ((oracle_conn, "oracle"), (vastbase_conn, "vastbase")):
            if conn is None:
                continue
            try:
                conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("关闭双源 %s 连接失败：%s", name, type(exc).__name__)
