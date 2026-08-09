"""
012 P2 草案：Oracle 护理窄查询 Adapter（基于 17 号只读原型）。

冻结口径（012 §7.1/§7.1.1，不得在本层改写）：
- 模板 572/709 为护理记录 V1 固定范围；
- form_time 与 created_date 双时间原样保留、不得互相覆盖；
- 日常模式用 form_time 过滤；出院关系继续用 created_date 外层窗口
  （通过 date_field 参数显式选择，白名单校验，禁止拼接其他列）；
- 一张 FORM_ID 一行；正文非空门槛（HAVING）保留；
- 护理库内部正式关系 MCS_DOC_FORM.PATIENT_UID = INPATIENTS.PAT_INDEX_NO 不变。

本 adapter 未被任何生产路径调用；切换接线需另行书面批准（016 §3.2）。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from app.services.canonical_record import (
    SOURCE_STATUS_OK,
    CanonicalRecordEnvelope,
    SourceDiagnostics,
    bundle_hash,
    coerce_visit_number,
    normalize_column_name,
)

logger = logging.getLogger(__name__)

NURSING_MAPPING_VERSION_V2 = "nursing-node-map-v2-20260807"

#: 出院/日常两模式允许的时间过滤列（012 §6：daily=form_time，discharge=created_date）
NURSING_DATE_FIELD_FORM_TIME = "form_time"
NURSING_DATE_FIELD_CREATED_DATE = "created_date"
_VALID_DATE_FIELDS = frozenset({NURSING_DATE_FIELD_FORM_TIME, NURSING_DATE_FIELD_CREATED_DATE})


def build_ydhl_patient_key(patient_id: Any, visit_number: Any) -> str:
    """按旧路径契约构造 YDHL.INPATIENTS 使用的 ``患者ID_次数`` 键。"""
    patient = str(patient_id or "").strip()
    visit = coerce_visit_number(visit_number)
    if not patient or not visit:
        raise ValueError("护理内部患者键需要非空 patient_id 和 visit_number")
    return f"{patient}_{visit}"

#: 17 号只读原型（docs/sql/17_nursing_record_v2_readonly_select.sql）应用内副本。
#: 唯一改动：filtered_forms 的时间过滤列由 {date_field} 白名单占位，
#: 以同时服务 daily（form_time）与 discharge（created_date）两模式；其余逐字保留。
#: Oracle 绑定契约：:patient_key / :date_from / :date_to。
NURSING_RECORD_V2_SQL_TEMPLATE = """
WITH patient_anchor AS (
    SELECT
        i.patient_id  AS patient_key_internal,
        i.pat_index_no AS patient_uid,
        i.series       AS visit_number_internal,
        i.dept_code,
        i.dept_name
    FROM ydhl.inpatients i
    WHERE i.patient_id = :patient_key
      AND i.dept_code NOT IN (
          '030210', '030224', '030603', '030611',
          '0306', '040711', '040712', '040705'
      )
),
filtered_forms AS (
    SELECT
        a.patient_key_internal,
        a.patient_uid,
        a.visit_number_internal,
        a.dept_code,
        a.dept_name,
        f.id            AS nursing_record_id,
        f.form_time,
        f.created_date,
        f.last_updated_date AS source_updated_at,
        f.created_by,
        f.created_name,
        f.bed_no,
        f.template_code
    FROM patient_anchor a
    JOIN ydhl.mcs_doc_form f
      ON f.patient_uid = a.patient_uid
    WHERE f.is_valid = '1'
      AND f.template_code IN (572, 709)
      AND f.{date_field} >= :date_from
      AND f.{date_field} < :date_to
),
node_map AS (
    SELECT
        n.template_code,
        n.code,
        n.parent_code,
        n.seq,
        NVL(n.display_name, n.name) AS display_name,
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM ydhl.mcs_doc_nodes child
                WHERE child.template_code = n.template_code
                  AND child.parent_code = n.code
            ) THEN 0
            ELSE 1
        END AS is_leaf
    FROM ydhl.mcs_doc_nodes n
    WHERE n.template_code IN ('572', '709')
      AND (
          n.code IN (
              '00172', '00174', '00122', '00120', '00093', '00094',
              '00022', '00023', '00024', '00029', '00153', '00062',
              '00117', '00119', '00028', '00133', '00134', '00132',
              '00142', '00143', '00144', '00145', '00161', '00171',
              '00084', '00148', '00085', '00086', '00088',
              '00089', '00090', '00091', '00150', '00151', '00152',
              '00166', '00162', '00164', '00169'
          )
          OR (
              n.template_code = '572'
              AND n.parent_code IN ('00038', '00143', '00149', '00155', '00073')
          )
      )
),
selected_values AS (
    SELECT
        f.patient_key_internal,
        f.patient_uid,
        f.visit_number_internal,
        f.dept_code,
        f.dept_name,
        f.nursing_record_id,
        f.form_time,
        f.created_date,
        f.source_updated_at,
        f.created_by,
        f.created_name,
        f.bed_no,
        f.template_code,
        r.node_code,
        n.parent_code,
        n.seq,
        n.display_name,
        n.is_leaf,
        r.number_value,
        CASE
            WHEN r.string_value IS NOT NULL THEN r.string_value
            WHEN r.number_value = 1 AND n.is_leaf = 1 THEN n.display_name
            WHEN r.number_value IS NOT NULL
                THEN TRIM(TO_CHAR(r.number_value, 'FM99999999990.099'))
            ELSE NULL
        END AS node_value,
        ROW_NUMBER() OVER (
            PARTITION BY f.nursing_record_id, r.template_code, r.node_code
            ORDER BY r.inner_seq NULLS LAST, r.id
        ) AS rn
    FROM filtered_forms f
    JOIN ydhl.mcs_doc_form_records r
      ON r.form_id = f.nursing_record_id
     AND r.template_code = TO_CHAR(f.template_code)
    JOIN node_map n
      ON n.template_code = r.template_code
     AND n.code = r.node_code
    WHERE r.string_value IS NOT NULL
       OR r.number_value IS NOT NULL
),
deduplicated_values AS (
    SELECT
        patient_key_internal,
        patient_uid,
        visit_number_internal,
        dept_code,
        dept_name,
        nursing_record_id,
        form_time,
        created_date,
        source_updated_at,
        created_by,
        created_name,
        bed_no,
        template_code,
        node_code,
        parent_code,
        seq,
        display_name,
        is_leaf,
        number_value,
        node_value
    FROM selected_values
    WHERE rn = 1
)
SELECT
    v.patient_key_internal,
    v.patient_key_internal AS patient_id,
    v.patient_uid,
    v.visit_number_internal,
    v.visit_number_internal AS visit_number,
    v.nursing_record_id,
    v.form_time AS event_time,
    v.form_time,
    v.created_date AS created_at,
    v.source_updated_at,
    v.template_code,
    CASE v.template_code
        WHEN 572 THEN '一般患者护理记录单'
        WHEN 709 THEN '病重（病危）患者护理记录'
        ELSE '其他'
    END AS record_type,
    CASE v.template_code
        WHEN 572 THEN '一般患者护理记录单'
        WHEN 709 THEN '病重（病危）患者护理记录'
        ELSE '其他'
    END AS record_name,
    v.created_by AS recorder_code,
    v.created_name AS recorder_name,
    v.dept_code,
    v.dept_name,
    v.bed_no,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00093' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00153' THEN v.node_value END)
    ) AS nursing_content,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00093' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00153' THEN v.node_value END)
    ) AS content,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00172' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00022' THEN v.node_value END)
    ) AS temperature,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00174' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00023' THEN v.node_value END)
    ) AS pulse,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00122' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00024' THEN v.node_value END)
    ) AS respiration,
    COALESCE(
        CASE WHEN v.template_code = 572 THEN
            MAX(CASE WHEN v.node_code = '00117' THEN v.node_value END)
            || CASE
                WHEN MAX(CASE WHEN v.node_code = '00117' THEN v.node_value END) IS NOT NULL
                 AND MAX(CASE WHEN v.node_code = '00119' THEN v.node_value END) IS NOT NULL
                THEN ' / '
               END
            || MAX(CASE WHEN v.node_code = '00119' THEN v.node_value END)
        END,
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00028' THEN v.node_value END)
    ) AS blood_pressure,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00120' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00029' THEN v.node_value END)
    ) AS oxygen_saturation,
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00172' THEN v.node_value END) AS blood_glucose,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.parent_code = '00038' AND v.number_value = 1
                 THEN v.display_name END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00142' THEN v.node_value END)
    ) AS consciousness,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00133' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00143' THEN v.node_value END)
    ) AS oxygen_nasal_cannula,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00134' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00144' THEN v.node_value END)
    ) AS oxygen_mask,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00132' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00145' THEN v.node_value END)
    ) AS oxygen_other_name,
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00161' THEN v.node_value END) AS oxygen_other_amount,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00084' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00148' THEN v.node_value END)
    ) AS intake_name,
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00171' THEN v.node_value END) AS intake_route,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00085' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00149' THEN v.node_value END)
    ) AS intake_amount,
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00086' THEN v.node_value END) AS intake_amount_2,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00088' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00150' THEN v.node_value END)
    ) AS output_name,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00089' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00151' THEN v.node_value END)
    ) AS output_amount,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00090' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00152' THEN v.node_value END)
    ) AS output_color,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00091' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00166' THEN v.node_value END)
    ) AS output_character,
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00162' THEN v.node_value END) AS urine_amount,
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00164' THEN v.node_value END) AS vomit_amount,
    LISTAGG(
        CASE WHEN v.template_code = 572 AND v.parent_code = '00143' AND v.number_value = 1
             THEN v.display_name END,
        '，'
    ) WITHIN GROUP (ORDER BY v.seq, v.node_code) AS incision_status,
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00148' THEN v.node_value END) AS tube_care,
    LISTAGG(
        CASE WHEN v.template_code = 572 AND v.parent_code = '00149' AND v.number_value = 1
             THEN v.display_name END,
        '，'
    ) WITHIN GROUP (ORDER BY v.seq, v.node_code) AS skin_status,
    LISTAGG(
        CASE WHEN v.template_code = 572 AND v.parent_code = '00155' AND v.number_value = 1
             THEN v.display_name END,
        '，'
    ) WITHIN GROUP (ORDER BY v.seq, v.node_code) AS skin_care,
    LISTAGG(
        CASE WHEN v.template_code = 572 AND v.parent_code = '00073' AND v.number_value = 1
             THEN v.display_name END,
        '，'
    ) WITHIN GROUP (ORDER BY v.seq, v.node_code) AS high_risk,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00094' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00062' THEN v.node_value END)
    ) AS nurse_signature,
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00169' THEN v.node_value END) AS reviewer_signature,
    'nursing-node-map-v2-20260807' AS mapping_version
FROM deduplicated_values v
GROUP BY
    v.patient_key_internal,
    v.patient_uid,
    v.visit_number_internal,
    v.nursing_record_id,
    v.form_time,
    v.created_date,
    v.source_updated_at,
    v.template_code,
    v.created_by,
    v.created_name,
    v.dept_code,
    v.dept_name,
    v.bed_no
HAVING COALESCE(
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00093' THEN v.node_value END),
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00153' THEN v.node_value END)
) IS NOT NULL
"""

#: 护理信封结构化字段白名单（除信封一级字段外，其余列进 structured_fields）
_STRUCTURED_FIELD_COLUMNS = (
    "temperature", "pulse", "respiration", "blood_pressure", "oxygen_saturation",
    "blood_glucose", "consciousness", "oxygen_nasal_cannula", "oxygen_mask",
    "oxygen_other_name", "oxygen_other_amount", "intake_name", "intake_route",
    "intake_amount", "intake_amount_2", "output_name", "output_amount",
    "output_color", "output_character", "urine_amount", "vomit_amount",
    "incision_status", "tube_care", "skin_status", "skin_care", "high_risk",
    "nurse_signature", "reviewer_signature", "record_type", "recorder_name",
    "bed_no", "dept_name", "patient_uid", "form_time",
)


def build_nursing_v2_sql(date_field: str = NURSING_DATE_FIELD_FORM_TIME) -> str:
    """按运行模式生成护理 V2 SQL；date_field 白名单校验，防注入。"""
    if date_field not in _VALID_DATE_FIELDS:
        raise ValueError(f"非法护理时间过滤列: {date_field}（仅允许 {sorted(_VALID_DATE_FIELDS)}）")
    return NURSING_RECORD_V2_SQL_TEMPLATE.format(date_field=date_field)


def _row_to_envelope(row: dict[str, Any]) -> CanonicalRecordEnvelope:
    normalized = {normalize_column_name(k): v for k, v in row.items()}
    structured = {
        key: normalized.get(key)
        for key in _STRUCTURED_FIELD_COLUMNS
        if normalized.get(key) is not None
    }
    return CanonicalRecordEnvelope(
        source_system="oracle_ydhl",
        source_name="nursing",
        record_kind="nursing",
        record_subtype=str(normalized.get("record_type") or ""),
        record_id=str(normalized.get("nursing_record_id") or "").strip(),
        patient_key_internal=str(normalized.get("patient_key_internal") or "").strip(),
        visit_number_internal=coerce_visit_number(normalized.get("visit_number_internal")),
        event_time=normalized.get("event_time"),
        created_at=normalized.get("created_at"),
        source_updated_at=normalized.get("source_updated_at"),
        template_code=str(normalized.get("template_code") or ""),
        record_name=str(normalized.get("record_name") or ""),
        content=normalized.get("content"),
        structured_fields=structured,
        dept_code=str(normalized.get("dept_code") or ""),
        author_code=str(normalized.get("recorder_code") or ""),
        source_status=SOURCE_STATUS_OK,
        mapping_version=str(normalized.get("mapping_version") or NURSING_MAPPING_VERSION_V2),
    )


def fetch_nursing_records_v2(
    conn,
    patient_key: str,
    date_from,
    date_to,
    date_field: str = NURSING_DATE_FIELD_FORM_TIME,
) -> tuple[list[CanonicalRecordEnvelope], SourceDiagnostics]:
    """按内部患者键+半开时间窗拉取护理信封（一张 FORM_ID 一行）。

    date_field：daily 传 form_time，discharge 传 created_date（012 §6/§7.1.1）。
    fail-closed：数据库异常时标记 query_failed 并原样抛出。
    """
    diagnostics = SourceDiagnostics(source_name="nursing")
    started = time.monotonic()
    cursor = None
    try:
        sql = build_nursing_v2_sql(date_field)
        cursor = conn.cursor()
        cursor.execute(
            sql,
            {"patient_key": str(patient_key), "date_from": date_from, "date_to": date_to},
        )
        columns = [normalize_column_name(desc[0]) for desc in cursor.description or []]
        seen_ids: set[str] = set()
        envelopes: list[CanonicalRecordEnvelope] = []
        for raw_row in cursor.fetchall():
            diagnostics.row_count += 1
            row = dict(zip(columns, raw_row))
            envelope = _row_to_envelope(row)
            errors = envelope.validate()
            if errors:
                diagnostics.skipped_count += 1
                logger.warning(
                    "护理信封契约校验失败，跳过（bundle=%s）：%s",
                    bundle_hash(envelope.patient_key_internal, envelope.visit_number_internal),
                    "; ".join(errors),
                )
                continue
            if envelope.record_id in seen_ids:
                diagnostics.skipped_count += 1
                logger.warning("护理 FORM_ID 重复，跳过（一张表单一行约束被破坏，须停门核查）")
                continue
            seen_ids.add(envelope.record_id)
            diagnostics.valid_count += 1
            envelopes.append(envelope)
        return envelopes, diagnostics
    except Exception as exc:
        diagnostics.mark_query_failed(type(exc).__name__)
        logger.error("Oracle 护理窄查询失败（fail-closed）：%s", type(exc).__name__)
        raise
    finally:
        diagnostics.elapsed_ms = int((time.monotonic() - started) * 1000)
        if cursor is not None:
            try:
                cursor.close()
            except Exception as exc:  # noqa: BLE001 - 关闭失败仅记录
                logger.warning("关闭护理查询游标失败：%s", type(exc).__name__)
