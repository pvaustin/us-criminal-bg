-- Refresh us_criminal_bg.gold.order_report from Silver.
-- Contract: docs/gold/NAMING.md · docs/gold/ACCESS.md
--
-- Grain: (subject_ref, party_key). Driver = distinct pairs on match_decision
-- (latest row after rank). order_id is an attribute via LEFT JOIN of
-- _gold_order_subject_src, which is empty unless the operator (or Python
-- --apply) loaded silver.order_subject.
--
-- SF has no silver.court_case / court_charge: has_court_case=false,
-- charge_row_count=0, charge arrays empty. Do not invent court rows.
-- WI with zero match_decision rows yields zero order_report rows (honest).
--
-- Does not mutate Bronze or Silver. Does not read search_audit.
-- No hire / no-hire.
--
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: use durable Delta
-- scratch tables, not TEMP VIEW.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

-- Probe only (never SELECT FROM silver.order_subject — that table is not live).
CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_order_subject_probe
USING DELTA
AS
SELECT
  CAST(count(*) > 0 AS BOOLEAN) AS order_subject_table_present
FROM us_criminal_bg.information_schema.tables
WHERE lower(table_schema) = 'silver'
  AND lower(table_name) = 'order_subject';

-- Empty fallback when silver.order_subject is missing. CREATE TABLE IF NOT
-- EXISTS so a prior order_subject_src_from_silver load is kept.
CREATE TABLE IF NOT EXISTS us_criminal_bg.gold._gold_order_subject_src (
  order_id STRING,
  subject_ref STRING,
  subject_name STRING,
  subject_dob DATE,
  created_at TIMESTAMP,
  created_by STRING,
  updated_at TIMESTAMP,
  status STRING
) USING DELTA;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_match_latest
USING DELTA
AS
SELECT
  md.decision_id,
  md.subject_ref,
  md.subject_name,
  md.subject_dob,
  md.party_key,
  md.source_system,
  md.state_code,
  md.source_record_id,
  md.party_role,
  md.party_ordinal,
  md.raw_name,
  md.name_last,
  md.name_first,
  md.name_middle,
  md.confidence_band,
  md.score,
  md.reasons,
  md.score_or_reason_codes,
  md.ingest_run_id,
  md.payload_sha256,
  md.transform_run_id,
  md.case_report_key,
  md.review_status,
  md.experiment_tag,
  md.notes,
  md.decided_at,
  md.actor
FROM us_criminal_bg.silver.match_decision md
QUALIFY row_number() OVER (
  PARTITION BY md.subject_ref, md.party_key
  ORDER BY
    md.decided_at DESC,
    CASE WHEN md.review_status = 'human' THEN 0 ELSE 1 END,
    md.decision_id DESC
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_match_human
USING DELTA
AS
SELECT
  md.subject_ref,
  md.party_key,
  md.decision_id AS human_decision_id,
  md.confidence_band AS human_confidence_band,
  md.score AS human_score,
  md.reasons AS human_reasons,
  md.decided_at AS human_decided_at,
  md.actor AS human_actor
FROM us_criminal_bg.silver.match_decision md
WHERE md.review_status = 'human'
QUALIFY row_number() OVER (
  PARTITION BY md.subject_ref, md.party_key
  ORDER BY md.decided_at DESC, md.decision_id DESC
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_charge_summary
USING DELTA
AS
SELECT
  source_system,
  state_code,
  source_record_id,
  count(*) AS charge_row_count,
  transform(
    array_sort(
      collect_list(
        named_struct(
          'charge_count', charge_count,
          'statute', statute,
          'severity', severity,
          'description', description
        )
      )
    ),
    x -> x.statute
  ) AS charge_statutes,
  transform(
    array_sort(
      collect_list(
        named_struct(
          'charge_count', charge_count,
          'statute', statute,
          'severity', severity,
          'description', description
        )
      )
    ),
    x -> x.severity
  ) AS charge_severities,
  transform(
    array_sort(
      collect_list(
        named_struct(
          'charge_count', charge_count,
          'statute', statute,
          'severity', severity,
          'description', description
        )
      )
    ),
    x -> x.description
  ) AS charge_descriptions
FROM us_criminal_bg.silver.court_charge
GROUP BY source_system, state_code, source_record_id;

CREATE OR REPLACE TABLE us_criminal_bg.gold.order_report
USING DELTA
AS
SELECT
  l.subject_ref,
  l.party_key,
  os.order_id,
  os.status AS order_status,
  os.created_by AS order_created_by,
  os.updated_at AS order_updated_at,
  probe.order_subject_table_present,
  CASE
    WHEN os.subject_ref IS NOT NULL THEN os.subject_name
    ELSE l.subject_name
  END AS subject_name,
  CASE
    WHEN os.subject_ref IS NOT NULL THEN os.subject_dob
    ELSE l.subject_dob
  END AS subject_dob,
  CASE
    WHEN os.subject_ref IS NOT NULL THEN 'order_subject'
    ELSE 'match_decision'
  END AS subject_source,
  l.source_system,
  l.state_code,
  l.source_record_id,
  l.party_role,
  l.party_ordinal,
  coalesce(p.raw_name, l.raw_name) AS raw_name,
  coalesce(p.name_last, l.name_last) AS name_last,
  coalesce(p.name_first, l.name_first) AS name_first,
  coalesce(p.name_middle, l.name_middle) AS name_middle,
  p.dob AS party_dob,
  (p.source_record_id IS NOT NULL) AS party_row_present,
  p.payload_parse_status AS party_payload_parse_status,
  coalesce(p.dq_flags, CAST(array() AS ARRAY<STRING>)) AS party_dq_flags,
  coalesce(
    l.case_report_key,
    concat_ws('|', l.source_system, l.state_code, l.source_record_id)
  ) AS case_report_key,
  (c.source_record_id IS NOT NULL) AS has_court_case,
  c.county_code,
  c.case_number,
  c.case_type,
  c.filed_date,
  c.caption,
  c.case_status,
  c.county_name,
  c.payload_parse_status AS case_payload_parse_status,
  coalesce(c.dq_flags, CAST(array() AS ARRAY<STRING>)) AS case_dq_flags,
  (coalesce(chg.charge_row_count, 0) > 0) AS has_court_charge,
  coalesce(chg.charge_row_count, 0) AS charge_row_count,
  coalesce(chg.charge_statutes, CAST(array() AS ARRAY<STRING>)) AS charge_statutes,
  coalesce(chg.charge_severities, CAST(array() AS ARRAY<STRING>)) AS charge_severities,
  coalesce(chg.charge_descriptions, CAST(array() AS ARRAY<STRING>)) AS charge_descriptions,
  l.decision_id AS latest_decision_id,
  l.review_status AS latest_review_status,
  l.confidence_band AS latest_confidence_band,
  l.score AS latest_score,
  coalesce(l.reasons, CAST(array() AS ARRAY<STRING>)) AS latest_reasons,
  coalesce(l.score_or_reason_codes, CAST(array() AS ARRAY<STRING>)) AS latest_score_or_reason_codes,
  l.decided_at AS latest_decided_at,
  l.actor AS latest_actor,
  l.experiment_tag AS latest_experiment_tag,
  l.notes AS latest_notes,
  l.confidence_band AS current_confidence_band,
  l.review_status AS current_review_status,
  (
    l.review_status = 'suggestion'
    AND l.confidence_band IN ('review', 'auto')
  ) AS is_open_review,
  h.human_decision_id,
  h.human_confidence_band,
  h.human_score,
  coalesce(h.human_reasons, CAST(array() AS ARRAY<STRING>)) AS human_reasons,
  h.human_decided_at,
  h.human_actor,
  coalesce(p.ingest_run_id, l.ingest_run_id) AS ingest_run_id,
  coalesce(p.payload_sha256, l.payload_sha256) AS payload_sha256,
  coalesce(p.transform_run_id, l.transform_run_id) AS party_transform_run_id,
  p.ingested_at AS party_ingested_at,
  p.transformed_at AS party_transformed_at,
  c.transformed_at AS case_transformed_at,
  'gold.order_report.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._gold_match_latest l
CROSS JOIN us_criminal_bg.gold._gold_order_subject_probe probe
LEFT JOIN us_criminal_bg.gold._gold_order_subject_src os
  ON os.subject_ref = l.subject_ref
LEFT JOIN us_criminal_bg.gold._gold_match_human h
  ON h.subject_ref = l.subject_ref
 AND h.party_key = l.party_key
LEFT JOIN us_criminal_bg.silver.court_party p
  ON p.source_system = l.source_system
 AND p.state_code = l.state_code
 AND p.source_record_id = l.source_record_id
 AND p.party_role = l.party_role
 AND p.party_ordinal = l.party_ordinal
LEFT JOIN us_criminal_bg.silver.court_case c
  ON c.source_system = l.source_system
 AND c.state_code = l.state_code
 AND c.source_record_id = l.source_record_id
LEFT JOIN us_criminal_bg.gold._gold_charge_summary chg
  ON chg.source_system = l.source_system
 AND chg.state_code = l.state_code
 AND chg.source_record_id = l.source_record_id;

DROP TABLE IF EXISTS us_criminal_bg.gold._gold_charge_summary;
DROP TABLE IF EXISTS us_criminal_bg.gold._gold_match_human;
DROP TABLE IF EXISTS us_criminal_bg.gold._gold_match_latest;
-- Keep _gold_order_subject_src and _gold_order_subject_probe for the optional
-- order_subject load + re-run. Safe to DROP manually after apply.
