-- Target: us_criminal_bg.silver.search_audit
-- Contract: docs/silver/ORDER_AUDIT.md
-- Append-only log of every search/match attempt.
-- Never store secrets, tokens, or full court payloads.
-- Web app may CREATE TABLE IF NOT EXISTS (same pattern as match_decision).
-- Always APPEND. Never UPDATE/DELETE a prior attempt.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.search_audit (
  audit_id STRING NOT NULL,
  -- Null if the search started outside an order
  order_id STRING,
  subject_ref STRING NOT NULL,
  initiated_by STRING NOT NULL,
  initiated_at TIMESTAMP NOT NULL,
  -- Snapshot at search time; name as entered; DOB null if absent
  subject_name STRING NOT NULL,
  subject_dob DATE,
  query_source_system STRING,
  query_state_code STRING,
  query_source_record_id STRING,
  -- Small JSON of non-secret query params
  query_params_json STRING,
  -- ok | empty | error | no_matchable_parties
  result_status STRING NOT NULL,
  -- Counts by band, party_keys, error code — no secrets, no full PII dump
  result_summary_json STRING,
  -- Databricks SQL requires ARRAY<STRING>, not bare ARRAY. May be empty.
  party_keys_returned ARRAY<STRING>,
  -- Honest short error; never tokens
  error_message STRING
) USING DELTA;
