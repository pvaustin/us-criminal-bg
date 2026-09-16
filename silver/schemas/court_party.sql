-- Target: us_criminal_bg.silver.court_party
-- Contract: docs/silver/NAMING.md
-- National-first party grain. Reads Bronze HTML via the court_case transform;
-- does not mutate Bronze. Race is omitted (agency-provided subjective; matching
-- must not require it). DOB / sex / address are null unless those labels exist
-- in the payload.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.court_party (
  -- Natural key (type-1 current row)
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  -- defendant | plaintiff | aka | other ; ordinal is stable within role for this payload
  party_role STRING NOT NULL,
  party_ordinal INT NOT NULL,
  -- Attributes (raw_name required when a row is emitted)
  raw_name STRING NOT NULL,
  name_last STRING,
  name_first STRING,
  name_middle STRING,
  dob DATE,
  sex STRING,
  address_raw STRING,
  -- Bronze / Silver lineage
  ingest_run_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  payload_sha256 STRING NOT NULL,
  bronze_schema_version STRING NOT NULL,
  silver_schema_version STRING NOT NULL,
  transformed_at TIMESTAMP NOT NULL,
  transform_run_id STRING NOT NULL,
  payload_parse_status STRING NOT NULL,
  -- Databricks SQL requires ARRAY<STRING>, not bare ARRAY.
  dq_flags ARRAY<STRING> NOT NULL
) USING DELTA;
