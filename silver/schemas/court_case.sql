-- Target: us_criminal_bg.silver.court_case
-- Contract: docs/silver/NAMING.md
-- Reads Bronze; does not mutate Bronze.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.transform_run (
  transform_run_id STRING NOT NULL,
  transform_run_label STRING,
  state_code STRING,
  source_system STRING,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  status STRING NOT NULL,
  bronze_source_table STRING NOT NULL,
  row_count BIGINT,
  silver_schema_version STRING NOT NULL,
  notes STRING
) USING DELTA;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.court_case (
  -- Natural key (type-1 current row)
  source_system STRING NOT NULL,
  state_code STRING NOT NULL,
  source_record_id STRING NOT NULL,
  -- Bronze lineage (payload omitted; join back via key / ingest_run_id / sha256)
  ingest_run_id STRING NOT NULL,
  ingested_at TIMESTAMP NOT NULL,
  source_url STRING,
  payload_format STRING NOT NULL,
  payload_sha256 STRING NOT NULL,
  extract_method STRING NOT NULL,
  bronze_schema_version STRING NOT NULL,
  -- Analytics-ready attributes
  county_code STRING,
  case_number STRING,
  case_type STRING,
  filed_date DATE,
  caption STRING,
  case_status STRING,
  county_name STRING,
  payload_parse_status STRING NOT NULL,
  -- Databricks SQL requires an ARRAY element type (ARRAY<STRING>, not bare ARRAY).
  dq_flags ARRAY<STRING> NOT NULL,
  silver_schema_version STRING NOT NULL,
  transformed_at TIMESTAMP NOT NULL,
  transform_run_id STRING NOT NULL
) USING DELTA;

-- Existing v1 tables from PR #3 need case_status / county_name.
-- This warehouse rejects `ADD COLUMN IF NOT EXISTS` (PARSE_SYNTAX_ERROR near EXISTS).
-- Guard with information_schema; skip when the column already exists.
-- If compound IF is unavailable, run the preview SELECT below and execute only
-- the missing `ALTER TABLE ... ADD COLUMN <name> STRING;` statements (plain ADD
-- COLUMN, no IF NOT EXISTS). Duplicate-column errors mean the column is present.

SELECT requested.column_name AS missing_court_case_column
FROM (
  SELECT 'case_status' AS column_name
  UNION ALL
  SELECT 'county_name'
) requested
LEFT JOIN us_criminal_bg.information_schema.columns c
  ON lower(c.table_schema) = 'silver'
 AND lower(c.table_name) = 'court_case'
 AND lower(c.column_name) = requested.column_name
WHERE c.column_name IS NULL;

BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM us_criminal_bg.information_schema.columns
    WHERE lower(table_schema) = 'silver'
      AND lower(table_name) = 'court_case'
      AND lower(column_name) = 'case_status'
  ) THEN
    ALTER TABLE us_criminal_bg.silver.court_case ADD COLUMN case_status STRING;
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM us_criminal_bg.information_schema.columns
    WHERE lower(table_schema) = 'silver'
      AND lower(table_name) = 'court_case'
      AND lower(column_name) = 'county_name'
  ) THEN
    ALTER TABLE us_criminal_bg.silver.court_case ADD COLUMN county_name STRING;
  END IF;
END;
