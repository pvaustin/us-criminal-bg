-- Dedicated type-1 MERGE: bronze.court_case_raw (sf_criminal_hf / CA JSON)
--   → silver.court_party (defendant ordinal 1 only)
-- Research-only name-match sketch. Parallel to the WCCA HTML SSR path.
-- Contract: docs/silver/SF_RESEARCH.md · docs/silver/COURT_PARTY.md
--
-- HARD SCOPE: this script filters Bronze to
--   source_system = 'sf_criminal_hf' AND state_code = 'CA'
-- MERGE WHEN MATCHED requires t.source_system = 'sf_criminal_hf'
-- DELETE requires t.source_system = 'sf_criminal_hf' AND t.state_code = 'CA'
-- WI `wcca` party rows are never in the USING set and cannot match DELETE.
--
-- Does not write court_case / court_charge. Does not mutate Bronze.
-- Does not scrape. Blank defendant_name → no party row (no invented party).
-- Prefer the Python job (court_party_sf_criminal_hf.py) for name-part DQ;
-- this SQL mirrors first/last/middle heuristics for the warehouse.
--
-- Apply after silver/schemas/court_party.sql.
-- transform_run_id is materialized once into _this_transform_run (same
-- scratch pattern as silver/transforms/court_case.sql).
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: TEMP VIEW does
-- not persist across calls. Stage cases/parties in durable Delta scratch
-- tables (_sf_party_cases, _sf_party_staged) and DROP them at end.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE OR REPLACE TABLE us_criminal_bg.silver._this_transform_run
USING DELTA
AS
SELECT
  uuid() AS transform_run_id,
  concat(
    'sf_criminal_hf_CA_',
    date_format(current_timestamp(), 'yyyyMMdd_HHmmss'),
    'Z'
  ) AS transform_run_label,
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
  'CA',
  'sf_criminal_hf',
  started_at,
  CAST(NULL AS TIMESTAMP),
  'running',
  'us_criminal_bg.bronze.court_case_raw',
  CAST(NULL AS BIGINT),
  'silver.court_party.v1',
  'spark_sql json_cases_v1 court_party; source_system=sf_criminal_hf state_code=CA only; does not delete wcca parties'
FROM us_criminal_bg.silver._this_transform_run;

-- Current SF/CA Bronze keys in this run (including blank-name cases).
-- Used so stale SF party rows can be deleted without touching wcca/WI.
CREATE OR REPLACE TABLE us_criminal_bg.silver._sf_party_cases
USING DELTA
AS
SELECT
  r.source_system,
  r.state_code,
  r.source_record_id,
  r.ingest_run_id,
  r.ingested_at,
  r.payload,
  r.payload_sha256,
  r.schema_version AS bronze_schema_version,
  r.payload_format
FROM (
  SELECT
    r.source_system,
    r.state_code,
    r.source_record_id,
    r.ingest_run_id,
    r.ingested_at,
    r.payload,
    r.payload_sha256,
    r.schema_version,
    r.payload_format,
    i.status AS ingest_status,
    row_number() OVER (
      PARTITION BY r.source_system, r.state_code, r.source_record_id
      ORDER BY r.ingested_at DESC, r.ingest_run_id DESC
    ) AS rn
  FROM us_criminal_bg.bronze.court_case_raw r
  LEFT JOIN us_criminal_bg.bronze.ingest_run i
    ON r.ingest_run_id = i.ingest_run_id
  WHERE r.source_system = 'sf_criminal_hf'
    AND r.state_code = 'CA'
    AND lower(r.payload_format) = 'json'
    AND (i.status IS NULL OR i.status = 'succeeded')
) r
WHERE r.rn = 1;

CREATE OR REPLACE TABLE us_criminal_bg.silver._sf_party_staged
USING DELTA
AS
WITH named AS (
  SELECT
    c.source_system,
    c.state_code,
    c.source_record_id,
    c.ingest_run_id,
    c.ingested_at,
    c.payload_sha256,
    c.bronze_schema_version,
    nullif(
      trim(
        regexp_replace(
          coalesce(get_json_object(c.payload, '$.defendant_name'), ''),
          '[ \\t\\n\\r]+',
          ' '
        )
      ),
      ''
    ) AS raw_name
  FROM us_criminal_bg.silver._sf_party_cases c
),
tokenized AS (
  SELECT
    n.*,
    instr(n.raw_name, ',') AS comma_at,
    split(n.raw_name, ' ') AS toks,
    nullif(trim(split(n.raw_name, ',')[0]), '') AS comma_last,
    nullif(
      trim(split(trim(substring(n.raw_name, instr(n.raw_name, ',') + 1)), ' ')[0]),
      ''
    ) AS comma_first,
    CASE
      WHEN n.raw_name LIKE '%,%'
       AND size(
         split(trim(substring(n.raw_name, instr(n.raw_name, ',') + 1)), ' ')
       ) > 1
        THEN nullif(
          trim(
            regexp_replace(
              trim(substring(n.raw_name, instr(n.raw_name, ',') + 1)),
              '^[^ ]+ +',
              ''
            )
          ),
          ''
        )
      ELSE CAST(NULL AS STRING)
    END AS comma_middle
  FROM named n
  WHERE n.raw_name IS NOT NULL
),
parted AS (
  SELECT
    t.source_system,
    t.state_code,
    t.source_record_id,
    'defendant' AS party_role,
    1 AS party_ordinal,
    t.raw_name,
    CASE
      WHEN t.comma_at > 0 THEN t.comma_last
      WHEN size(t.toks) >= 2 THEN t.toks[size(t.toks) - 1]
      ELSE CAST(NULL AS STRING)
    END AS name_last,
    CASE
      WHEN t.comma_at > 0 THEN t.comma_first
      WHEN size(t.toks) >= 2 THEN t.toks[0]
      ELSE CAST(NULL AS STRING)
    END AS name_first,
    CASE
      WHEN t.comma_at > 0 THEN t.comma_middle
      WHEN size(t.toks) >= 3
        THEN nullif(concat_ws(' ', slice(t.toks, 2, size(t.toks) - 2)), '')
      ELSE CAST(NULL AS STRING)
    END AS name_middle,
    CAST(NULL AS DATE) AS dob,
    CAST(NULL AS STRING) AS sex,
    CAST(NULL AS STRING) AS address_raw,
    t.ingest_run_id,
    t.ingested_at,
    t.payload_sha256,
    t.bronze_schema_version,
    CASE
      WHEN t.comma_at > 0 AND (t.comma_last IS NULL OR t.comma_first IS NULL)
        THEN true
      WHEN t.comma_at = 0 AND size(t.toks) = 1 THEN true
      WHEN t.comma_at = 0 AND size(t.toks) >= 4 THEN true
      ELSE false
    END AS name_ambiguous
  FROM tokenized t
)
SELECT
  p.source_system,
  p.state_code,
  p.source_record_id,
  p.party_role,
  p.party_ordinal,
  p.raw_name,
  p.name_last,
  p.name_first,
  p.name_middle,
  p.dob,
  p.sex,
  p.address_raw,
  p.ingest_run_id,
  p.ingested_at,
  p.payload_sha256,
  p.bronze_schema_version,
  'silver.court_party.v1' AS silver_schema_version,
  current_timestamp() AS transformed_at,
  r.transform_run_id,
  'json_cases_v1' AS payload_parse_status,
  filter(
    array(
      'missing_dob',
      CASE WHEN p.name_ambiguous THEN 'ambiguous_name_parts' END,
      CASE
        WHEN p.name_last IS NULL AND p.name_first IS NULL THEN 'name_unparsed'
      END
    ),
    x -> x IS NOT NULL
  ) AS dq_flags
FROM parted p
CROSS JOIN us_criminal_bg.silver._this_transform_run r
WHERE p.source_system = 'sf_criminal_hf'
  AND p.state_code = 'CA';

MERGE INTO us_criminal_bg.silver.court_party AS t
USING us_criminal_bg.silver._sf_party_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
 AND t.party_role = s.party_role
 AND t.party_ordinal = s.party_ordinal
WHEN MATCHED AND t.source_system = 'sf_criminal_hf' THEN UPDATE SET
  t.raw_name = s.raw_name,
  t.name_last = s.name_last,
  t.name_first = s.name_first,
  t.name_middle = s.name_middle,
  t.dob = s.dob,
  t.sex = s.sex,
  t.address_raw = s.address_raw,
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.payload_sha256 = s.payload_sha256,
  t.bronze_schema_version = s.bronze_schema_version,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id,
  t.payload_parse_status = s.payload_parse_status,
  t.dq_flags = s.dq_flags
WHEN NOT MATCHED AND s.source_system = 'sf_criminal_hf' THEN INSERT (
  source_system,
  state_code,
  source_record_id,
  party_role,
  party_ordinal,
  raw_name,
  name_last,
  name_first,
  name_middle,
  dob,
  sex,
  address_raw,
  ingest_run_id,
  ingested_at,
  payload_sha256,
  bronze_schema_version,
  silver_schema_version,
  transformed_at,
  transform_run_id,
  payload_parse_status,
  dq_flags
) VALUES (
  s.source_system,
  s.state_code,
  s.source_record_id,
  s.party_role,
  s.party_ordinal,
  s.raw_name,
  s.name_last,
  s.name_first,
  s.name_middle,
  s.dob,
  s.sex,
  s.address_raw,
  s.ingest_run_id,
  s.ingested_at,
  s.payload_sha256,
  s.bronze_schema_version,
  s.silver_schema_version,
  s.transformed_at,
  s.transform_run_id,
  s.payload_parse_status,
  s.dq_flags
);

-- Type-1: drop party_role+ordinal rows that disappeared for SF/CA cases
-- processed this run. Must not match wcca / WI keys.
DELETE FROM us_criminal_bg.silver.court_party t
WHERE t.source_system = 'sf_criminal_hf'
  AND t.state_code = 'CA'
  AND EXISTS (
    SELECT 1 FROM us_criminal_bg.silver._sf_party_cases s
    WHERE t.source_system = s.source_system
      AND t.state_code = s.state_code
      AND t.source_record_id = s.source_record_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM us_criminal_bg.silver._sf_party_staged p
    WHERE t.source_system = p.source_system
      AND t.state_code = p.state_code
      AND t.source_record_id = p.source_record_id
      AND t.party_role = p.party_role
      AND t.party_ordinal = p.party_ordinal
  );

UPDATE us_criminal_bg.silver.transform_run t
SET
  finished_at = current_timestamp(),
  status = 'succeeded',
  row_count = (
    SELECT count(*)
    FROM us_criminal_bg.silver.court_party c
    WHERE c.transform_run_id = t.transform_run_id
  )
WHERE t.status = 'running'
  AND t.transform_run_id IN (
    SELECT transform_run_id FROM us_criminal_bg.silver._this_transform_run
  );

DROP TABLE IF EXISTS us_criminal_bg.silver._sf_party_cases;
DROP TABLE IF EXISTS us_criminal_bg.silver._sf_party_staged;
DROP TABLE IF EXISTS us_criminal_bg.silver._this_transform_run;
