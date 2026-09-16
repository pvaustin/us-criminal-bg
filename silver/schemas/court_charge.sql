-- Target: us_criminal_bg.silver.court_charge
-- Contract: docs/silver/NAMING.md
-- National-first charge grain. Reads Bronze via the court_case transform; does not mutate Bronze.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.court_charge (
  -- Natural key (type-1 current row)
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  charge_count INT NOT NULL,
  -- Charge attributes (null only when the source row omitted that token)
  statute STRING,
  description STRING,
  severity STRING,
  modifier_statute STRING,
  modifier_text STRING,
  -- Bronze / Silver lineage
  ingest_run_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  payload_sha256 STRING NOT NULL,
  bronze_schema_version STRING NOT NULL,
  silver_schema_version STRING NOT NULL,
  transformed_at TIMESTAMP NOT NULL,
  transform_run_id STRING NOT NULL
) USING DELTA;
