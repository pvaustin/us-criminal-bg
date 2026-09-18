-- Target: us_criminal_bg.gold.order_report
-- Contract: docs/gold/NAMING.md
-- Serving snapshot for the employer report UI. Reads Silver; does not mutate
-- Bronze or Silver. Grain: (subject_ref, party_key).
--
-- order_id is an ATTRIBUTE (LEFT JOIN silver.order_subject when live), not the
-- grain — that table is DDL-only / not live as of 2026-09-17.
-- SF court_case / court_charge are absent: has_court_case=false and charge
-- arrays empty. Do not invent court rows. No hire / no-hire / risk columns.
--
-- Databricks SQL requires ARRAY<STRING>, not bare ARRAY.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE TABLE IF NOT EXISTS us_criminal_bg.gold.order_report (
  -- Serving grain
  subject_ref STRING NOT NULL,
  party_key STRING NOT NULL,
  -- Order (null when order_subject missing or unmatched)
  order_id STRING,
  order_status STRING,
  order_created_by STRING,
  order_updated_at TIMESTAMP,
  order_subject_table_present BOOLEAN NOT NULL,
  -- Subject snapshot: prefer order_subject, else match_decision
  subject_name STRING,
  subject_dob DATE,
  subject_source STRING NOT NULL,
  -- Party card (provenance always present from match_decision)
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  party_role STRING NOT NULL,
  party_ordinal INT NOT NULL,
  raw_name STRING,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  party_dob DATE,
  party_row_present BOOLEAN NOT NULL,
  party_payload_parse_status STRING,
  party_dq_flags ARRAY<STRING> NOT NULL,
  -- Case (LEFT JOIN silver.court_case — honest nulls when missing, e.g. SF)
  case_report_key STRING NOT NULL,
  has_court_case BOOLEAN NOT NULL,
  county_code STRING,
  case_number STRING,
  case_type STRING,
  filed_date DATE,
  caption STRING,
  case_status STRING,
  county_name STRING,
  case_payload_parse_status STRING,
  case_dq_flags ARRAY<STRING> NOT NULL,
  -- Charge summary (aggregated; empty when silver.court_charge has no rows)
  has_court_charge BOOLEAN NOT NULL,
  charge_row_count INT NOT NULL,
  charge_statutes ARRAY<STRING> NOT NULL,
  charge_severities ARRAY<STRING> NOT NULL,
  charge_descriptions ARRAY<STRING> NOT NULL,
  -- Latest match_decision (rank: decided_at DESC, human-on-tie, decision_id DESC)
  latest_decision_id STRING,
  latest_review_status STRING,
  latest_confidence_band STRING,
  latest_score INT,
  latest_reasons ARRAY<STRING> NOT NULL,
  latest_score_or_reason_codes ARRAY<STRING> NOT NULL,
  latest_decided_at TIMESTAMP,
  latest_actor STRING,
  latest_experiment_tag STRING,
  latest_notes STRING,
  current_confidence_band STRING,
  current_review_status STRING,
  is_open_review BOOLEAN NOT NULL,
  -- Latest human append (null if none)
  human_decision_id STRING,
  human_confidence_band STRING,
  human_score INT,
  human_reasons ARRAY<STRING> NOT NULL,
  human_decided_at TIMESTAMP,
  human_actor STRING,
  -- Lineage / as-of
  ingest_run_id STRING,
  payload_sha256 STRING,
  party_transform_run_id STRING,
  party_ingested_at TIMESTAMP,
  party_transformed_at TIMESTAMP,
  case_transformed_at TIMESTAMP,
  gold_schema_version STRING NOT NULL,
  refreshed_at TIMESTAMP NOT NULL
) USING DELTA;
