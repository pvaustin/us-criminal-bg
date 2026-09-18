-- Target: us_criminal_bg.gold.match_queue
-- Contract: docs/gold/NAMING.md
-- Open review cards only for /review. Reads Silver; does not mutate Bronze or
-- Silver. Grain: (subject_ref, party_key) among OPEN cards.
--
-- Open = latest match_decision per (subject_ref, party_key) has
-- review_status='suggestion' AND confidence_band IN ('review','auto').
-- A later human append closes the card. Filter WI vs SF via source_system +
-- state_code. No hire / no-hire / risk columns.
--
-- Databricks SQL requires ARRAY<STRING>, not bare ARRAY.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE TABLE IF NOT EXISTS us_criminal_bg.gold.match_queue (
  -- Open-card grain
  subject_ref STRING NOT NULL,
  party_key STRING NOT NULL,
  subject_name STRING,
  subject_dob DATE,
  -- Provenance (filter WI vs SF)
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  party_role STRING NOT NULL,
  party_ordinal INT NOT NULL,
  case_report_key STRING,
  -- Display
  raw_name STRING,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  -- Band (open cards are review | auto only)
  confidence_band STRING NOT NULL,
  score INT,
  reasons ARRAY<STRING> NOT NULL,
  score_or_reason_codes ARRAY<STRING> NOT NULL,
  -- Decision identity / age
  decision_id STRING NOT NULL,
  decided_at TIMESTAMP NOT NULL,
  age_hours DOUBLE NOT NULL,
  actor STRING NOT NULL,
  review_status STRING NOT NULL,
  experiment_tag STRING,
  notes STRING,
  ingest_run_id STRING,
  payload_sha256 STRING,
  gold_schema_version STRING NOT NULL,
  refreshed_at TIMESTAMP NOT NULL
) USING DELTA;
