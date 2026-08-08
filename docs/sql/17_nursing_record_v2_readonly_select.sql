/*
  Oracle 11g read-only candidate for the nursing source used by QC.

  Result grain: one row per valid nursing FORM_ID.
  This is a parameterized SELECT body for bounded execution and review. It
  is not a database object definition. The daily mode uses FORM_TIME; the
  discharge relation must keep using CREATED_DATE in its outer date window,
  as documented in 012.

  Binds:
    :patient_key - the existing internal patient key (INPATIENTS.PATIENT_ID)
    :date_from   - inclusive FORM_TIME boundary (DATE)
    :date_to     - exclusive FORM_TIME boundary (DATE)

  Internal keys are returned only for application matching. Do not write them
  to ordinary logs, external messages, or exported documents.
*/
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
      AND f.form_time >= :date_from
      AND f.form_time < :date_to
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
