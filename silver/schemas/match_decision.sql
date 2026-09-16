-- Target: us_criminal_bg.silver.match_decision
-- Contract: docs/silver/MATCH_REVIEW.md · docs/silver/SF_MATCH_EXPERIMENT.md
-- Append-only suggestion / human review rows (employer or research subject vs
-- one court_party card). Not a type-1 fact table. Not a hire / FCRA store.
--
-- ALWAYS APPEND. Never UPDATE / DELETE / MERGE a prior row. Never type-1
-- overwrite a human decision. `actor='system:suggestion'` is not an employment
-- action and must not silent auto-link.
--
-- Databricks SQL requires ARRAY<STRING>, not bare ARRAY.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.match_decision (
  -- Identity (uuid per append)
  decision_id STRING NOT NULL,
  -- Employer / research subject (not a court person id)
  subject_ref STRING NOT NULL,
  subject_name STRING,
  subject_dob DATE,
  -- Party card grain
  party_key STRING NOT NULL,
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  party_role STRING NOT NULL,
  party_ordinal INT NOT NULL,
  -- Display / Uma contract (copied from court_party at suggestion time)
  raw_name STRING,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  -- MATCH_REVIEW bands — auto | review | no-link
  confidence_band STRING NOT NULL,
  score INT,
  -- Reason codes from match_review_sketch (e.g. dob_absent). Never SQL NULL.
  reasons ARRAY<STRING> NOT NULL,
  -- Sketch contract: integer score as string plus reasons[]
  score_or_reason_codes ARRAY<STRING> NOT NULL,
  -- Lineage copied from the court_party row (not a new court transform run)
  ingest_run_id STRING,
  payload_sha256 STRING,
  transform_run_id STRING,
  -- Existing case grain: source_system|state_code|source_record_id
  case_report_key STRING,
  -- suggestion (system) vs human (later Uma append). Not a hire flag.
  review_status STRING NOT NULL,
  -- Isolates research batches (e.g. sf_name_only_research) from WI product rows
  experiment_tag STRING,
  notes STRING,
  decided_at TIMESTAMP NOT NULL,
  -- reviewer email, or system:suggestion
  actor STRING NOT NULL
) USING DELTA;
