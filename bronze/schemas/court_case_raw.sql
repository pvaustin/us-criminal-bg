-- Target: us_criminal_bg.bronze.court_case_raw
-- Contract: docs/bronze/NAMING.md

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.bronze;

CREATE TABLE IF NOT EXISTS us_criminal_bg.bronze.ingest_run (
  ingest_run_id STRING NOT NULL,
  ingest_run_label STRING,
  state_code STRING NOT NULL,
  source_system STRING NOT NULL,
  extract_method STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  status STRING NOT NULL,
  row_count BIGINT,
  notes STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS us_criminal_bg.bronze.court_case_raw (
  ingest_run_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  state_code STRING NOT NULL,
  source_system STRING NOT NULL,
  source_record_id STRING NOT NULL,
  source_url STRING,
  payload_format STRING NOT NULL,
  payload STRING NOT NULL,
  payload_sha256 STRING NOT NULL,
  extract_method STRING NOT NULL,
  schema_version STRING NOT NULL
) USING DELTA;
