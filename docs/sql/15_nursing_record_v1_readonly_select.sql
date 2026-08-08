/*
  Oracle 11g read-only prototype for one nursing form per row.

  Bind contract:
    :patient_key  - existing internal composite key used by
                    YDHL.INPATIENTS.PATIENT_ID
    :date_from    - inclusive FORM_TIME boundary
    :date_to      - exclusive FORM_TIME boundary

  This is a SELECT body for review and bounded performance testing. It does
  not create or replace a database view. The application must not write the
  internal patient/visit keys to ordinary logs or external messages.
*/
WITH target_patient AS (
    SELECT
        :patient_key AS patient_key_internal
    FROM DUAL
),
patient_anchor AS (
    SELECT
        i.PAT_INDEX_NO AS patient_uid,
        i.PATIENT_ID AS patient_key_internal,
        i.SERIES AS visit_number_internal,
        i.DEPT_CODE AS dept_code
    FROM YDHL.INPATIENTS i
    JOIN target_patient t
      ON t.patient_key_internal = i.PATIENT_ID
),
filtered_forms AS (
    SELECT
        a.patient_key_internal,
        a.visit_number_internal,
        a.dept_code,
        f.ID AS nursing_record_id,
        f.PATIENT_UID AS patient_uid,
        f.FORM_TIME AS form_time,
        f.CREATED_DATE AS created_date,
        f.CREATED_NAME AS recorder_name,
        f.TEMPLATE_CODE AS template_code
    FROM patient_anchor a
    JOIN YDHL.MCS_DOC_FORM f
      ON f.PATIENT_UID = a.patient_uid
    WHERE f.IS_VALID = '1'
      AND f.TEMPLATE_CODE IN (572, 709)
      AND f.FORM_TIME >= :date_from
      AND f.FORM_TIME < :date_to
),
selected_values AS (
    SELECT
        f.patient_key_internal,
        f.visit_number_internal,
        f.dept_code,
        f.nursing_record_id,
        f.form_time,
        f.created_date,
        f.recorder_name,
        f.template_code,
        r.NODE_CODE AS node_code,
        CASE
            WHEN r.STRING_VALUE IS NOT NULL THEN r.STRING_VALUE
            WHEN r.NUMBER_VALUE = 1 THEN NVL(n.DISPLAY_NAME, n.NAME)
            WHEN r.NUMBER_VALUE IS NOT NULL
                THEN TRIM(TO_CHAR(r.NUMBER_VALUE, 'FM99999999990.099'))
            ELSE NULL
        END AS node_value
    FROM filtered_forms f
    JOIN YDHL.MCS_DOC_FORM_RECORDS r
      ON r.FORM_ID = f.nursing_record_id
     AND r.TEMPLATE_CODE = TO_CHAR(f.template_code)
     AND r.NODE_CODE IN (
         '00172', '00174', '00122', '00120', '00093', '00094',
         '00022', '00023', '00024', '00029', '00153', '00062'
     )
     AND (r.STRING_VALUE IS NOT NULL OR r.NUMBER_VALUE IS NOT NULL)
    LEFT JOIN YDHL.MCS_DOC_NODES n
      ON n.TEMPLATE_CODE = r.TEMPLATE_CODE
     AND n.CODE = r.NODE_CODE
)
SELECT
    v.patient_key_internal,
    v.visit_number_internal,
    v.nursing_record_id,
    v.form_time AS event_time,
    v.form_time,
    v.created_date,
    v.template_code,
    CASE v.template_code
        WHEN 572 THEN '一般患者护理记录单'
        WHEN 709 THEN '病重（病危）患者护理记录'
        ELSE '其他'
    END AS record_type,
    v.recorder_name,
    v.dept_code,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00093' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00153' THEN v.node_value END)
    ) AS nursing_content,
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
    CAST(NULL AS VARCHAR2(100)) AS blood_pressure,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00120' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00029' THEN v.node_value END)
    ) AS oxygen_saturation,
    COALESCE(
        MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00094' THEN v.node_value END),
        MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00062' THEN v.node_value END)
    ) AS nurse_signature
FROM selected_values v
GROUP BY
    v.patient_key_internal,
    v.visit_number_internal,
    v.nursing_record_id,
    v.form_time,
    v.created_date,
    v.template_code,
    v.recorder_name,
    v.dept_code
HAVING COALESCE(
    MAX(CASE WHEN v.template_code = 572 AND v.node_code = '00093' THEN v.node_value END),
    MAX(CASE WHEN v.template_code = 709 AND v.node_code = '00153' THEN v.node_value END)
) IS NOT NULL
