-- Target: us_criminal_bg.gold.name_match_label_pack
-- Contract: docs/gold/NAME_MATCH_EVAL.md
-- Unlabeled worksheet for humans (Uma /review). Not ground truth.
-- Grain: (subject_ref, party_key) in one pack refresh.
--
-- Built from open SF gold.match_queue cards plus hard-negative distractors
-- (same subject_ref, different last-name party already on silver.court_party).
-- `label` is NULL / empty until a human appends to silver.match_decision.
-- Do not invent court rows. Do not copy live PII into git.
-- No hire / no-hire / risk columns.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE TABLE IF NOT EXISTS us_criminal_bg.gold.name_match_label_pack (
  pack_row_id STRING NOT NULL,
  subject_ref STRING NOT NULL,
  party_key STRING NOT NULL,
  subject_name STRING,
  subject_dob DATE,
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  party_role STRING NOT NULL,
  party_ordinal INT NOT NULL,
  raw_name STRING,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  -- open_queue = live SF suggestion card; hard_negative = different last name
  pair_kind STRING NOT NULL,
  suggestion_decision_id STRING,
  suggestion_confidence_band STRING,
  suggestion_score INT,
  suggestion_actor STRING,
  -- EMPTY for humans. Do not pre-fill from the scorer.
  label STRING,
  labeled_at TIMESTAMP,
  actor STRING,
  experiment_tag STRING,
  notes STRING,
  ingest_run_id STRING,
  payload_sha256 STRING,
  gold_schema_version STRING NOT NULL,
  refreshed_at TIMESTAMP NOT NULL
) USING DELTA;
