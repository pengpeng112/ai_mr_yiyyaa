/*
  Vastbase/PostgreSQL-protocol read-only prototype for progress records.

  psycopg2 bind contract:
    %(patient_id)s    - existing patient key
    %(visit_number)s  - existing visit number
    %(date_from)s     - inclusive CAPTION_DATE_TIME boundary
    %(date_to)s       - exclusive CAPTION_DATE_TIME boundary

  Scope and event time are frozen by the hospital:
    MR_CLASS IN ('EMR10.00.01', 'EMR10.00.02', 'EMR10.00.03')
    event_time = CAPTION_DATE_TIME

  This is a bounded SELECT prototype. It does not create or replace a view.
*/
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
        WHEN i.topic LIKE '%术后首程%' OR i.topic LIKE '%术后首次病程%'
            THEN 'postop_first_progress'
        WHEN i.topic LIKE '%首次病程%'
            THEN 'first_progress'
        WHEN i.topic LIKE '%查房%'
            THEN 'ward_round'
        WHEN i.topic LIKE '%日常病程%'
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
