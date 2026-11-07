-- Target: us_criminal_bg.gold.name_match_eval
-- Contract: docs/gold/NAME_MATCH_EVAL.md
-- Human-labeled name-match eval for sf_name_match_v1.
-- Grain: (subject_ref, party_key) among latest human match_decision rows.
--
-- Source: silver.match_decision WHERE review_status='human' only.
-- system:suggestion cards are NOT ground truth and must not appear here.
-- Labels: link | reject | leave_in_review (leave_in_review is excluded from GT metrics).
-- Empty table is honest when N_human=0. Do not invent humans or court rows.
-- No hire / no-hire / risk columns. No live PII in git (warehouse only).

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE TABLE IF NOT EXISTS us_criminal_bg.gold.name_match_eval (
  subject_ref STRING NOT NULL,
  party_key STRING NOT NULL,
  -- link = human confirmed match; reject = human no-link; leave_in_review = exclude
  label STRING NOT NULL,
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  labeled_at TIMESTAMP NOT NULL,
  actor STRING NOT NULL,
  decision_id STRING NOT NULL,
  confidence_band STRING NOT NULL,
  experiment_tag STRING,
  -- Copied from the human decision (needed to score models; warehouse only)
  subject_name STRING,
  subject_dob DATE,
  party_role STRING,
  party_ordinal INT,
  raw_name STRING,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  score INT,
  reasons ARRAY<STRING> NOT NULL,
  review_status STRING NOT NULL,
  eval_name STRING NOT NULL,
  gold_schema_version STRING NOT NULL,
  refreshed_at TIMESTAMP NOT NULL
) USING DELTA;
