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
    bundle_hash,
    coerce_visit_number,
)
from app.services.data_source_loader import PatientBundle
from app.services.nursing_record_adapter import (
    NURSING_DATE_FIELD_CREATED_DATE,
    NURSING_DATE_FIELD_FORM_TIME,
    build_ydhl_patient_key,
    fetch_nursing_records_v2,
)
from app.services.progress_record_adapter import fetch_progress_records_v1
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


def _fetch_anchor_rows(
    conn,
    anchor_sql: str,
    anchor_mapping: dict[str, str],
    date_from: datetime,
    date_to: datetime,
) -> list[dict[str, Any]]:
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(anchor_sql, {"date_from": date_from, "date_to": date_to})
        columns = [str(desc[0]).strip() for desc in cursor.description or []]
        rows: list[dict[str, Any]] = []
        for raw in cursor.fetchall():
            record = dict(zip(columns, raw))
            mapped: dict[str, Any] = {}
            for canonical_key in (
                "patient_id", "visit_number", "admission_time", "discharge_time",
                "dept_code", "dept_name", "patient_name", "admission_no",
            ):
                column = str(anchor_mapping.get(canonical_key) or canonical_key)
                value = record.get(column)
                if value is None:
                    # Oracle 大小写不敏感防御
                    value = record.get(column.upper(), record.get(column.lower()))
                mapped[canonical_key] = value
            rows.append(mapped)
        return rows
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
        "sources": {},
    }
    normalized_dept_filter = {
        str(value or "").strip() for value in (dept_filter or []) if str(value or "").strip()
    }
    started = time.monotonic()

    oracle_cfg = ConfigParser.parse_oracle_config(root_config)
    oracle_conn = get_oracle_connection(oracle_cfg)
    vastbase_conn = get_emr_vastbase_connection(root_config)
    try:
        anchors = _fetch_anchor_rows(oracle_conn, anchor_sql, anchor_mapping, date_from, date_to)
        logger.info(
            "[dual_source_loader] code=%s mode=%s query_date=%s anchors=%s",
            audit_type.code, run_mode, query_date, len(anchors),
        )

        bundles: list[PatientBundle] = []
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
                logger.warning("[dual_source_loader] 锚点缺键跳过（禁止猜键）")
                continue

            if run_mode == RUN_MODE_DISCHARGE:
                admission_time = anchor.get("admission_time")
                discharge_time = anchor.get("discharge_time")
                if not isinstance(admission_time, datetime) or not isinstance(discharge_time, datetime):
                    diagnostics["skipped_records"] += 1
                    logger.warning(
                        "[dual_source_loader] 出院锚点缺入/出院时间跳过（bundle=%s）",
                        bundle_hash(patient_id, visit_number),
                    )
                    continue
                if not date_from <= discharge_time < date_to:
                    diagnostics["skipped_records"] += 1
                    diagnostics["discharge_date_filtered_anchors"] = int(
                        diagnostics.get("discharge_date_filtered_anchors", 0)
                    ) + 1
                    continue
                progress_from, progress_to = admission_time, discharge_time + timedelta(days=1)
                nursing_date_field = NURSING_DATE_FIELD_CREATED_DATE
            else:
                progress_from, progress_to = date_from, date_to
                nursing_date_field = NURSING_DATE_FIELD_FORM_TIME

            # required 源查询失败：异常直接上抛，整批 fail-closed（012 §8.2.5）
            progress_envelopes, progress_diag = fetch_progress_records_v1(
                vastbase_conn, patient_id, visit_number, progress_from, progress_to,
            )
            nursing_patient_key = build_ydhl_patient_key(patient_id, visit_number)
            nursing_envelopes, nursing_diag = fetch_nursing_records_v2(
                oracle_conn, nursing_patient_key, progress_from, progress_to, date_field=nursing_date_field,
            )
            diagnostics["source_row_counts"]["progress"] += progress_diag.row_count
            diagnostics["source_row_counts"]["nursing"] += nursing_diag.row_count

            if run_mode == RUN_MODE_DISCHARGE:
                # 复刻旧 SQL：TO_CHAR(病历标题时间)=TO_CHAR(护理记录时间)。
                # V_HLJL 的“护理记录时间”来自 created_date；LEFT 语义只影响
                # 护理是否附着，不得删除病程候选。
                progress_days = {_date_key(item.event_time) for item in progress_envelopes}
                progress_days.discard("")
                nursing_before = len(nursing_envelopes)
                nursing_envelopes = [
                    item for item in nursing_envelopes
                    if _date_key(item.created_at) in progress_days
                ]
                diagnostics.setdefault("relation_filtered_counts", {})["nursing_created_date_not_progress_day"] = (
                    int(diagnostics.get("relation_filtered_counts", {}).get(
                        "nursing_created_date_not_progress_day", 0
                    ))
                    + nursing_before - len(nursing_envelopes)
                )

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
                logger.warning(
                    "双源候选缺少必需源，跳过（bundle=%s）：%s",
                    bundle_hash(patient_id, visit_number),
                    "; ".join(violations),
                )
                continue

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
            )
            bundles.append(bundle)

        diagnostics["elapsed_ms"] = int((time.monotonic() - started) * 1000)
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
            try:
                conn.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("关闭双源 %s 连接失败：%s", name, type(exc).__name__)
