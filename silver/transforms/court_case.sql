-- Idempotent type-1 MERGE: bronze.court_case_raw → silver.court_case + silver.court_charge
-- Contract: docs/silver/NAMING.md
-- Parses identifiers from source_record_id / URL, then HTML SSR labels from payload
-- text after scripts/styles/tags are stripped (see docs/silver/WCCA_HTML_SSR.md).
-- Charge modifier_* columns are left null in this SQL path; the Python job fills them.
-- Does not mutate Bronze.
--
-- Apply after silver/schemas/court_case.sql and silver/schemas/court_charge.sql.
-- Re-run is safe: court_case upserts on (source_system, state_code, source_record_id);
-- court_charge upserts on those plus charge_count; stale charge counts for cases in
-- this run are deleted. A new transform_run row is appended each attempt.
--
-- transform_run_id is materialized once into a 1-row Delta table. A TEMP VIEW
-- over uuid()/current_timestamp() is re-evaluated on every query, and Databricks
-- SQL warehouses reject UPDATE ... WHERE col = (SELECT uuid() ...) with
-- INVALID_NON_DETERMINISTIC_EXPRESSIONS.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE OR REPLACE TABLE us_criminal_bg.silver._this_transform_run
USING DELTA
AS
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
  'silver.court_case.v2',
  'spark_sql html_ssr_v1; charge modifiers null (use Python job)'
FROM us_criminal_bg.silver._this_transform_run;

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
    r.payload,
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
),
ssr AS (
  SELECT
    n.*,
    CASE
      WHEN n.case_number RLIKE '^[0-9]{4}[A-Z]{2}[0-9]{6}$'
        THEN regexp_extract(n.case_number, '^[0-9]{4}([A-Z]{2})[0-9]{6}$', 1)
      ELSE CAST(NULL AS STRING)
    END AS case_type,
    trim(
      regexp_replace(
        regexp_replace(
          regexp_replace(
            regexp_replace(
              regexp_replace(
                regexp_replace(
                  regexp_replace(
                    regexp_replace(
                      regexp_replace(
                        regexp_replace(
                          regexp_replace(
                            coalesce(n.payload, ''),
                            '(?is)<(script|style|noscript)\\b[^>]*>.*?</\\1>',
                            ' '
                          ),
                          '(?s)<!--.*?-->',
                          ' '
                        ),
                        '(?i)&gt;|&#62;|&#x3e;',
                        '[[GT]]'
                      ),
                      '(?i)&lt;|&#60;|&#x3c;',
                      '[[LT]]'
                    ),
                    '(?i)<br\\s*/?>|</(?:p|div|tr|td|th|h[1-6]|li|table|thead|tbody|section|header|article)>',
                    ' '
                  ),
                  '</?[A-Za-z][A-Za-z0-9]*[^>]*>',
                  ' '
                ),
                '\\[\\[GT\\]\\]',
                '>'
              ),
              '\\[\\[LT\\]\\]',
              '<'
            ),
            '(?i)&nbsp;',
            ' '
          ),
          '(?i)&amp;',
          '&'
        ),
        '\\s+',
        ' '
      )
    ) AS ssr_text
  FROM norm n
),
extracted AS (
  SELECT
    s.*,
    nullif(
      trim(
        regexp_extract(
          s.ssr_text,
          '(?i)(State of Wisconsin vs\\.? .+?)(?= Case summary| Filing date| Case type| Case status| Defendant| Charges| Count no\\.|$)',
          1
        )
      ),
      ''
    ) AS caption,
    coalesce(
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, 'Filing date\\s*:?\\s*([0-9]{1,2}-[0-9]{1,2}-[0-9]{4})', 1),
          ''
        ),
        'MM-dd-yyyy'
      ),
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, 'Filing date\\s*:?\\s*([0-9]{1,2}-[0-9]{1,2}-[0-9]{4})', 1),
          ''
        ),
        'M-d-yyyy'
      ),
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, 'Filing date\\s*:?\\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', 1),
          ''
        ),
        'MM/dd/yyyy'
      )
    ) AS filed_date,
    nullif(
      trim(
        regexp_extract(
          s.ssr_text,
          'Case status\\s*:?\\s*(.+?)(?= Defendant| Date of birth| Address| Charges| Count no\\.| Filing date| Case type| Branch| Responsible|$)',
          1
        )
      ),
      ''
    ) AS case_status,
    nullif(
      trim(regexp_extract(s.ssr_text, 'Case Details in (.+?) County', 1)),
      ''
    ) AS county_name,
    filter(
      split(
        CASE
          WHEN s.ssr_text RLIKE '(?i)Count no\\.? Statute Description Severity'
            THEN coalesce(
              regexp_extract(
                s.ssr_text,
                '(?i)Count no\\.? Statute Description Severity(?: Disposition)?(.*)$',
                1
              ),
              ''
            )
          ELSE ''
        END,
        '(?=[0-9]+ [0-9]{3}\\.[0-9]{2,4}(?:\\([^)]+\\))*)'
      ),
      x -> trim(x) RLIKE '^[0-9]+ [0-9]{3}\\.[0-9]{2,4}'
    ) AS charge_raws
  FROM ssr s
)
SELECT
  e.source_system,
  e.state_code,
  e.source_record_id,
  e.ingest_run_id,
  e.ingested_at,
  e.source_url,
  e.payload_format,
  e.payload_sha256,
  e.extract_method,
  e.bronze_schema_version,
  e.county_code,
  e.case_number,
  e.case_type,
  e.filed_date,
  e.caption,
  e.case_status,
  e.county_name,
  e.charge_raws,
  CASE
    WHEN e.source_system <> 'wcca' THEN 'unsupported_source'
    WHEN e.county_code IS NULL OR e.case_number IS NULL THEN 'identifier_error'
    WHEN e.caption IS NOT NULL
     AND e.filed_date IS NOT NULL
     AND coalesce(size(e.charge_raws), 0) >= 1 THEN 'html_ssr_v1'
    WHEN e.caption IS NOT NULL
      OR e.filed_date IS NOT NULL
      OR e.case_status IS NOT NULL
      OR e.county_name IS NOT NULL
      OR coalesce(size(e.charge_raws), 0) >= 1 THEN 'html_ssr_partial'
    ELSE 'identifiers_only'
  END AS payload_parse_status,
  filter(
    array(
      CASE WHEN e.case_number IS NULL THEN 'case_number_unparsed' END,
      CASE
        WHEN e.case_number IS NOT NULL
         AND NOT e.case_number RLIKE '^[0-9]{4}[A-Z]{2}[0-9]{6}$'
          THEN 'case_type_unparsed'
      END,
      CASE WHEN e.county_code IS NULL THEN 'county_code_unparsed' END,
      CASE
        WHEN e.url_county_raw IS NOT NULL AND e.id_county_raw IS NOT NULL
         AND CASE
               WHEN e.url_county_raw RLIKE '^[0-9]+$' THEN CAST(CAST(e.url_county_raw AS INT) AS STRING)
               ELSE e.url_county_raw
             END
          <> CASE
               WHEN e.id_county_raw RLIKE '^[0-9]+$' THEN CAST(CAST(e.id_county_raw AS INT) AS STRING)
               ELSE e.id_county_raw
             END
          THEN 'identifier_url_mismatch'
        WHEN e.url_case_raw IS NOT NULL AND e.id_case_raw IS NOT NULL
         AND upper(e.url_case_raw) <> upper(e.id_case_raw)
          THEN 'identifier_url_mismatch'
      END,
      CASE
        WHEN e.county_code IS NOT NULL
         AND NOT e.county_code RLIKE '^[0-9]+$'
         AND e.source_system = 'wcca' THEN 'invalid_county_code'
      END,
      CASE WHEN e.caption IS NULL THEN 'missing_caption' END,
      CASE WHEN e.filed_date IS NULL THEN 'missing_filed_date' END,
      CASE
        WHEN e.payload_format = 'html_snapshot'
         AND (
           e.caption IS NOT NULL
           OR e.filed_date IS NOT NULL
           OR e.case_status IS NOT NULL
           OR e.county_name IS NOT NULL
           OR e.ssr_text RLIKE '(?i)Case Details in .+ County'
           OR e.ssr_text RLIKE '(?i)Count no\\.? Statute Description Severity'
         )
         AND coalesce(size(e.charge_raws), 0) = 0
          THEN 'missing_charges'
      END,
      CASE WHEN e.source_url IS NULL OR trim(e.source_url) = '' THEN 'missing_source_url' END,
      CASE
        WHEN e.payload_format = 'html_snapshot'
         AND e.caption IS NULL
         AND e.filed_date IS NULL
         AND e.case_status IS NULL
         AND e.county_name IS NULL
         AND coalesce(size(e.charge_raws), 0) = 0
         AND NOT e.ssr_text RLIKE '(?i)Case Details in .+ County'
         AND NOT e.ssr_text RLIKE '(?i)Count no\\.? Statute Description Severity'
          THEN 'unparsed_html_spa'
      END,
      CASE WHEN e.source_system <> 'wcca' THEN 'unsupported_source_parser' END
    ),
    x -> x IS NOT NULL
  ) AS dq_flags,
  'silver.court_case.v2' AS silver_schema_version,
  current_timestamp() AS transformed_at,
  r.transform_run_id
FROM extracted e
CROSS JOIN us_criminal_bg.silver._this_transform_run r;

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
  t.case_status = s.case_status,
  t.county_name = s.county_name,
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
  case_status,
  county_name,
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
  s.case_status,
  s.county_name,
  s.payload_parse_status,
  s.dq_flags,
  s.silver_schema_version,
  s.transformed_at,
  s.transform_run_id
);

CREATE OR REPLACE TEMP VIEW silver_court_charge_staged AS
SELECT
  s.source_system,
  s.state_code,
  s.source_record_id,
  CAST(regexp_extract(trim(x.charge_raw), '^([0-9]+)', 1) AS INT) AS charge_count,
  regexp_extract(
    trim(x.charge_raw),
    '^[0-9]+ ([0-9]{3}\\.[0-9]{2,4}(?:\\([^)]+\\))*)',
    1
  ) AS statute,
  trim(
    regexp_replace(
      regexp_replace(
        trim(x.charge_raw),
        '^[0-9]+ [0-9]{3}\\.[0-9]{2,4}(?:\\([^)]+\\))*\\s+',
        ''
      ),
      '\\s+(Felony|Misdemeanor|Misd\\.?|Forfeiture|Ordinance)(?: [A-Z0-9]{1,3})?.*$',
      ''
    )
  ) AS description,
  regexp_extract(
    trim(x.charge_raw),
    '(Felony|Misdemeanor|Misd\\.?|Forfeiture|Ordinance)(?: [A-Z0-9]{1,3})?',
    0
  ) AS severity,
  CAST(NULL AS STRING) AS modifier_statute,
  CAST(NULL AS STRING) AS modifier_text,
  s.ingest_run_id,
  s.ingested_at,
  s.payload_sha256,
  s.bronze_schema_version,
  'silver.court_charge.v1' AS silver_schema_version,
  s.transformed_at,
  s.transform_run_id
FROM silver_court_case_staged s
LATERAL VIEW explode(s.charge_raws) x AS charge_raw
WHERE x.charge_raw IS NOT NULL
  AND trim(x.charge_raw) <> ''
  AND regexp_extract(trim(x.charge_raw), '^([0-9]+)', 1) RLIKE '^[0-9]+$';

MERGE INTO us_criminal_bg.silver.court_charge AS t
USING silver_court_charge_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
 AND t.charge_count = s.charge_count
WHEN MATCHED THEN UPDATE SET
  t.statute = s.statute,
  t.description = s.description,
  t.severity = s.severity,
  t.modifier_statute = s.modifier_statute,
  t.modifier_text = s.modifier_text,
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.payload_sha256 = s.payload_sha256,
  t.bronze_schema_version = s.bronze_schema_version,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id
WHEN NOT MATCHED THEN INSERT (
  source_system,
  state_code,
  source_record_id,
  charge_count,
  statute,
  description,
  severity,
  modifier_statute,
  modifier_text,
  ingest_run_id,
  ingested_at,
  payload_sha256,
  bronze_schema_version,
  silver_schema_version,
  transformed_at,
  transform_run_id
) VALUES (
  s.source_system,
  s.state_code,
  s.source_record_id,
  s.charge_count,
  s.statute,
  s.description,
  s.severity,
  s.modifier_statute,
  s.modifier_text,
  s.ingest_run_id,
  s.ingested_at,
  s.payload_sha256,
  s.bronze_schema_version,
  s.silver_schema_version,
  s.transformed_at,
  s.transform_run_id
);

-- Type-1: drop charge_count rows that disappeared for cases processed this run.
DELETE FROM us_criminal_bg.silver.court_charge t
WHERE EXISTS (
  SELECT 1 FROM silver_court_case_staged s
  WHERE t.source_system = s.source_system
    AND t.state_code = s.state_code
    AND t.source_record_id = s.source_record_id
)
AND NOT EXISTS (
  SELECT 1 FROM silver_court_charge_staged c
  WHERE t.source_system = c.source_system
    AND t.state_code = c.state_code
    AND t.source_record_id = c.source_record_id
    AND t.charge_count = c.charge_count
);

-- Finalize using the materialized id (constant row), not a uuid() temp view.
-- row_count is taken from court_case rows stamped with this run id (MERGE target),
-- so the UPDATE subquery does not re-evaluate the staged view's current_timestamp().
UPDATE us_criminal_bg.silver.transform_run t
SET
  finished_at = current_timestamp(),
  status = 'succeeded',
  row_count = (
    SELECT count(*)
    FROM us_criminal_bg.silver.court_case c
    WHERE c.transform_run_id = t.transform_run_id
  )
WHERE t.status = 'running'
  AND t.transform_run_id IN (
    SELECT transform_run_id FROM us_criminal_bg.silver._this_transform_run
  );

DROP TABLE IF EXISTS us_criminal_bg.silver._this_transform_run;
