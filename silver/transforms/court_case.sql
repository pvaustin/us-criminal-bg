-- Idempotent type-1 MERGE: bronze.court_case_raw → silver.court_case
-- Contract: docs/silver/NAMING.md
-- Identifier / URL parsing only (Spark SQL). HTML SPA facts stay null.
-- Does not mutate Bronze.
--
-- Apply after silver/schemas/court_case.sql.
-- Re-run is safe: court_case upserts on (source_system, state_code, source_record_id);
-- a new transform_run row is appended each attempt.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE OR REPLACE TEMP VIEW silver_this_transform_run AS
SELECT
  uuid() AS transform_run_id,
  concat('all_all_', date_format(current_timestamp(), 'yyyyMMdd_HHmmss'), 'Z') AS transform_run_label,
  current_timestamp() AS started_at;

INSERT INTO us_criminal_bg.silver.transform_run (
  transform_run_id,
  transform_run_label,
  state_code,
  source_system,
  started_at,
  finished_at,
  status,
  bronze_source_table,
  row_count,
  silver_schema_version,
  notes
)
SELECT
  transform_run_id,
  transform_run_label,
  CAST(NULL AS STRING),
  CAST(NULL AS STRING),
  started_at,
  CAST(NULL AS TIMESTAMP),
  'running',
  'us_criminal_bg.bronze.court_case_raw',
  CAST(NULL AS BIGINT),
  'silver.court_case.v1',
  'spark_sql identifiers_only; HTML facts left null'
FROM silver_this_transform_run;

CREATE OR REPLACE TEMP VIEW silver_court_case_staged AS
WITH ranked AS (
  SELECT
    r.source_system,
    r.state_code,
    r.source_record_id,
    r.ingest_run_id,
    r.ingested_at,
    r.source_url,
    r.payload_format,
    r.payload_sha256,
    r.extract_method,
    r.schema_version AS bronze_schema_version,
    i.status AS ingest_status,
    row_number() OVER (
      PARTITION BY r.source_system, r.state_code, r.source_record_id
      ORDER BY r.ingested_at DESC, r.ingest_run_id DESC
    ) AS rn
  FROM us_criminal_bg.bronze.court_case_raw r
  LEFT JOIN us_criminal_bg.bronze.ingest_run i
    ON r.ingest_run_id = i.ingest_run_id
),
current_bronze AS (
  SELECT *
  FROM ranked
  WHERE rn = 1
    AND (ingest_status IS NULL OR ingest_status = 'succeeded')
),
ids AS (
  SELECT
    b.*,
    CASE
      WHEN b.source_record_id RLIKE '^[0-9]+:.+'
        THEN split(b.source_record_id, ':')[0]
      WHEN b.source_record_id LIKE '%|%|%|%'
        THEN split(b.source_record_id, '[|]')[2]
      ELSE CAST(NULL AS STRING)
    END AS id_county_raw,
    CASE
      WHEN b.source_record_id RLIKE '^[0-9]+:.+'
        THEN split(b.source_record_id, ':')[1]
      WHEN b.source_record_id LIKE '%|%|%|%'
        THEN split(b.source_record_id, '[|]')[3]
      ELSE CAST(NULL AS STRING)
    END AS id_case_raw,
    parse_url(b.source_url, 'QUERY', 'countyNo') AS url_county_raw,
    parse_url(b.source_url, 'QUERY', 'caseNo') AS url_case_raw
  FROM current_bronze b
),
norm AS (
  SELECT
    i.*,
    CASE
      WHEN coalesce(i.url_county_raw, i.id_county_raw) RLIKE '^[0-9]+$'
        THEN CAST(CAST(coalesce(i.url_county_raw, i.id_county_raw) AS INT) AS STRING)
      ELSE coalesce(i.url_county_raw, i.id_county_raw)
    END AS county_code,
    upper(coalesce(i.url_case_raw, i.id_case_raw)) AS case_number
  FROM ids i
)
SELECT
  n.source_system,
  n.state_code,
  n.source_record_id,
  n.ingest_run_id,
  n.ingested_at,
  n.source_url,
  n.payload_format,
  n.payload_sha256,
  n.extract_method,
  n.bronze_schema_version,
  n.county_code,
  n.case_number,
  CASE
    WHEN n.case_number RLIKE '^[0-9]{4}[A-Z]{2}[0-9]{6}$'
      THEN regexp_extract(n.case_number, '^[0-9]{4}([A-Z]{2})[0-9]{6}$', 1)
    ELSE CAST(NULL AS STRING)
  END AS case_type,
  CAST(NULL AS DATE) AS filed_date,
  CAST(NULL AS STRING) AS caption,
  CASE
    WHEN n.source_system <> 'wcca' THEN 'unsupported_source'
    WHEN n.county_code IS NULL OR n.case_number IS NULL THEN 'identifier_error'
    ELSE 'identifiers_only'
  END AS payload_parse_status,
  filter(
    array(
      CASE WHEN n.case_number IS NULL THEN 'case_number_unparsed' END,
      CASE
        WHEN n.case_number IS NOT NULL
         AND NOT n.case_number RLIKE '^[0-9]{4}[A-Z]{2}[0-9]{6}$'
          THEN 'case_type_unparsed'
      END,
      CASE WHEN n.county_code IS NULL THEN 'county_code_unparsed' END,
      CASE
        WHEN n.url_county_raw IS NOT NULL AND n.id_county_raw IS NOT NULL
         AND CASE
               WHEN n.url_county_raw RLIKE '^[0-9]+$' THEN CAST(CAST(n.url_county_raw AS INT) AS STRING)
               ELSE n.url_county_raw
             END
          <> CASE
               WHEN n.id_county_raw RLIKE '^[0-9]+$' THEN CAST(CAST(n.id_county_raw AS INT) AS STRING)
               ELSE n.id_county_raw
             END
          THEN 'identifier_url_mismatch'
        WHEN n.url_case_raw IS NOT NULL AND n.id_case_raw IS NOT NULL
         AND upper(n.url_case_raw) <> upper(n.id_case_raw)
          THEN 'identifier_url_mismatch'
      END,
      CASE
        WHEN n.county_code IS NOT NULL
         AND NOT n.county_code RLIKE '^[0-9]+$'
         AND n.source_system = 'wcca' THEN 'invalid_county_code'
      END,
      'missing_caption',
      'missing_filed_date',
      CASE WHEN n.source_url IS NULL OR trim(n.source_url) = '' THEN 'missing_source_url' END,
      CASE WHEN n.payload_format = 'html_snapshot' THEN 'unparsed_html_spa' END,
      CASE WHEN n.source_system <> 'wcca' THEN 'unsupported_source_parser' END
    ),
    x -> x IS NOT NULL
  ) AS dq_flags,
  'silver.court_case.v1' AS silver_schema_version,
  current_timestamp() AS transformed_at,
  r.transform_run_id
FROM norm n
CROSS JOIN silver_this_transform_run r;

MERGE INTO us_criminal_bg.silver.court_case AS t
USING silver_court_case_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
WHEN MATCHED THEN UPDATE SET
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.source_url = s.source_url,
  t.payload_format = s.payload_format,
  t.payload_sha256 = s.payload_sha256,
  t.extract_method = s.extract_method,
  t.bronze_schema_version = s.bronze_schema_version,
  t.county_code = s.county_code,
  t.case_number = s.case_number,
  t.case_type = s.case_type,
  t.filed_date = s.filed_date,
  t.caption = s.caption,
  t.payload_parse_status = s.payload_parse_status,
  t.dq_flags = s.dq_flags,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id
WHEN NOT MATCHED THEN INSERT (
  source_system,
  state_code,
  source_record_id,
  ingest_run_id,
  ingested_at,
  source_url,
  payload_format,
  payload_sha256,
  extract_method,
  bronze_schema_version,
  county_code,
  case_number,
  case_type,
  filed_date,
  caption,
  payload_parse_status,
  dq_flags,
  silver_schema_version,
  transformed_at,
  transform_run_id
) VALUES (
  s.source_system,
  s.state_code,
  s.source_record_id,
  s.ingest_run_id,
  s.ingested_at,
  s.source_url,
  s.payload_format,
  s.payload_sha256,
  s.extract_method,
  s.bronze_schema_version,
  s.county_code,
  s.case_number,
  s.case_type,
  s.filed_date,
  s.caption,
  s.payload_parse_status,
  s.dq_flags,
  s.silver_schema_version,
  s.transformed_at,
  s.transform_run_id
);

UPDATE us_criminal_bg.silver.transform_run t
SET
  finished_at = current_timestamp(),
  status = 'succeeded',
  row_count = (SELECT count(*) FROM silver_court_case_staged)
WHERE t.transform_run_id = (SELECT transform_run_id FROM silver_this_transform_run);
