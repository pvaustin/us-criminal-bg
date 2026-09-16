-- Idempotent type-1 MERGE: bronze.court_case_raw → silver.court_case
--   + silver.court_charge + silver.court_party
-- Contract: docs/silver/NAMING.md
-- Parses identifiers from source_record_id / URL, then HTML SSR labels from payload
-- text after scripts/styles/tags are stripped (see docs/silver/WCCA_HTML_SSR.md).
-- Charge modifier_* columns are left null in this SQL path; the Python job fills them.
-- Party name parts are comma-split best-effort; prefer the Python job for aka/name DQ.
-- Does not mutate Bronze.
--
-- Apply after silver/schemas/court_case.sql, court_charge.sql, and court_party.sql.
-- Re-run is safe: court_case upserts on (source_system, state_code, source_record_id);
-- court_charge upserts on those plus charge_count; court_party upserts on those plus
-- (party_role, party_ordinal). Stale charge counts and party ordinals for cases in
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
    ) AS charge_raws,
    nullif(
      trim(
        regexp_extract(
          s.ssr_text,
          '(?i)Defendant name\\s*:?\\s*(.+?)(?= Date of birth| Sex| Race| Address| Also known as| Charges| Count no\\.| Filing date| Case type| Case status|$)',
          1
        )
      ),
      ''
    ) AS defendant_name_labeled,
    coalesce(
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, '(?i)Date of birth\\s*:?\\s*([0-9]{1,2}-[0-9]{1,2}-[0-9]{4})', 1),
          ''
        ),
        'MM-dd-yyyy'
      ),
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, '(?i)Date of birth\\s*:?\\s*([0-9]{1,2}-[0-9]{1,2}-[0-9]{4})', 1),
          ''
        ),
        'M-d-yyyy'
      ),
      try_to_date(
        nullif(
          regexp_extract(s.ssr_text, '(?i)Date of birth\\s*:?\\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{4})', 1),
          ''
        ),
        'MM/dd/yyyy'
      )
    ) AS party_dob,
    nullif(
      trim(
        regexp_extract(
          s.ssr_text,
          '(?i)(?:^| )Sex\\s*:?\\s*(Male|Female|Unknown)\\b',
          1
        )
      ),
      ''
    ) AS party_sex,
    nullif(
      trim(
        regexp_extract(
          s.ssr_text,
          '(?i)Address\\s*:?\\s*(.+?)(?= Also known as| Charges| Count no\\.| Court records| Court activit| Warrants| This is not the official| Phone| Prosecut| Defense| Responsible| Race| Sex| Date of birth| Branch| DA case| Attorneys?| JUSTIS| Fingerprint| Hearings?| Calendar|$)',
          1
        )
      ),
      ''
    ) AS party_address,
    filter(
      transform(
        filter(
          split(
            coalesce(
              nullif(
                trim(
                  regexp_extract(
                    s.ssr_text,
                    '(?i)Also known as\\s+(.*?)(?= Charges| Count no\\.| Court records| Court activit| Warrants| This is not the official| Branch| DA case| Attorneys?| JUSTIS| Fingerprint| Responsible| Hearings?| Calendar|$)',
                    1
                  )
                ),
                ''
              ),
              ''
            ),
            '(?=\\b[A-Za-z][A-Za-z.\\'\\-]+,)'
          ),
          x -> trim(x) RLIKE '^[A-Za-z][A-Za-z.\\'\\-]+,\\s*[A-Za-z]'
            AND NOT lower(trim(x)) RLIKE '^(name|type|date)\\b'
        ),
        x -> trim(
          regexp_replace(
            regexp_extract(
              trim(x),
              '^([A-Za-z][A-Za-z.\\'\\-]+,\\s*[A-Za-z][A-Za-z.\\'\\-]*(?:\\s+[A-Za-z][A-Za-z.\\'\\-]*)?)',
              1
            ),
            '(?i)\\s+(AKA|Alias|Maiden|Type)$',
            ''
          )
        )
      ),
      x -> x IS NOT NULL AND trim(x) <> ''
       AND lower(trim(x)) NOT IN ('name', 'also known as', 'type', 'date of birth')
       AND NOT lower(x) LIKE '%date of birth%'
       AND NOT lower(x) LIKE '%branch id%'
       AND length(x) <= 80
       AND size(split(x, ' ')) <= 6
    ) AS aka_raws
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
  e.defendant_name_labeled,
  e.party_dob,
  e.party_sex,
  e.party_address,
  e.aka_raws,
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

CREATE OR REPLACE TEMP VIEW silver_court_party_staged AS
WITH base AS (
  SELECT
    s.source_system,
    s.state_code,
    s.source_record_id,
    s.ingest_run_id,
    s.ingested_at,
    s.payload_sha256,
    s.bronze_schema_version,
    s.transformed_at,
    s.transform_run_id,
    nullif(
      trim(
        regexp_extract(coalesce(s.caption, ''), '(?i)^(State of Wisconsin)\\s+vs', 1)
      ),
      ''
    ) AS plaintiff_raw,
    coalesce(
      s.defendant_name_labeled,
      nullif(
        trim(
          regexp_extract(
            coalesce(s.caption, ''),
            '(?i)State of Wisconsin\\s+vs\\.?\\s+(.+)$',
            1
          )
        ),
        ''
      )
    ) AS defendant_raw,
    CASE
      WHEN s.defendant_name_labeled IS NULL
       AND nullif(
             trim(
               regexp_extract(
                 coalesce(s.caption, ''),
                 '(?i)State of Wisconsin\\s+vs\\.?\\s+(.+)$',
                 1
               )
             ),
             ''
           ) IS NOT NULL
        THEN true
      ELSE false
    END AS defendant_from_caption,
    s.party_dob,
    s.party_sex,
    s.party_address,
    coalesce(s.aka_raws, array()) AS aka_raws
  FROM silver_court_case_staged s
),
unioned AS (
  SELECT
    b.source_system,
    b.state_code,
    b.source_record_id,
    'plaintiff' AS party_role,
    1 AS party_ordinal,
    b.plaintiff_raw AS raw_name,
    CAST(NULL AS DATE) AS dob,
    CAST(NULL AS STRING) AS sex,
    CAST(NULL AS STRING) AS address_raw,
    'html_ssr_v1' AS payload_parse_status,
    false AS defendant_from_caption,
    b.ingest_run_id,
    b.ingested_at,
    b.payload_sha256,
    b.bronze_schema_version,
    b.transformed_at,
    b.transform_run_id
  FROM base b
  WHERE b.plaintiff_raw IS NOT NULL
  UNION ALL
  SELECT
    b.source_system,
    b.state_code,
    b.source_record_id,
    'defendant' AS party_role,
    1 AS party_ordinal,
    b.defendant_raw AS raw_name,
    b.party_dob AS dob,
    b.party_sex AS sex,
    b.party_address AS address_raw,
    CASE
      WHEN b.defendant_from_caption THEN 'html_ssr_partial'
      ELSE 'html_ssr_v1'
    END AS payload_parse_status,
    b.defendant_from_caption,
    b.ingest_run_id,
    b.ingested_at,
    b.payload_sha256,
    b.bronze_schema_version,
    b.transformed_at,
    b.transform_run_id
  FROM base b
  WHERE b.defendant_raw IS NOT NULL
  UNION ALL
  SELECT
    b.source_system,
    b.state_code,
    b.source_record_id,
    'aka' AS party_role,
    CAST(x.aka_pos + 1 AS INT) AS party_ordinal,
    trim(x.aka_raw) AS raw_name,
    CAST(NULL AS DATE) AS dob,
    CAST(NULL AS STRING) AS sex,
    CAST(NULL AS STRING) AS address_raw,
    'html_ssr_v1' AS payload_parse_status,
    false AS defendant_from_caption,
    b.ingest_run_id,
    b.ingested_at,
    b.payload_sha256,
    b.bronze_schema_version,
    b.transformed_at,
    b.transform_run_id
  FROM base b
  LATERAL VIEW posexplode(b.aka_raws) x AS aka_pos, aka_raw
  WHERE trim(x.aka_raw) <> ''
    AND lower(trim(x.aka_raw)) <> lower(coalesce(b.defendant_raw, ''))
    AND lower(trim(x.aka_raw)) <> lower(coalesce(b.plaintiff_raw, ''))
    AND trim(x.aka_raw) RLIKE '^[A-Za-z].*,\\s*[A-Za-z]'
    AND NOT lower(trim(x.aka_raw)) RLIKE '^(name|type|date)\\b'
    AND length(trim(x.aka_raw)) <= 80
)
SELECT
  u.source_system,
  u.state_code,
  u.source_record_id,
  u.party_role,
  u.party_ordinal,
  u.raw_name,
  CASE
    WHEN u.raw_name LIKE '%,%' THEN nullif(trim(split(u.raw_name, ',')[0]), '')
    ELSE CAST(NULL AS STRING)
  END AS name_last,
  CASE
    WHEN u.raw_name LIKE '%,%'
      THEN nullif(trim(split(trim(split(u.raw_name, ',')[1]), ' ')[0]), '')
    ELSE CAST(NULL AS STRING)
  END AS name_first,
  CASE
    WHEN u.raw_name LIKE '%,%'
     AND size(split(trim(split(u.raw_name, ',')[1]), ' ')) > 1
      THEN nullif(
        trim(regexp_replace(trim(split(u.raw_name, ',')[1]), '^[^ ]+\\s+', '')),
        ''
      )
    ELSE CAST(NULL AS STRING)
  END AS name_middle,
  u.dob,
  u.sex,
  u.address_raw,
  u.ingest_run_id,
  u.ingested_at,
  u.payload_sha256,
  u.bronze_schema_version,
  'silver.court_party.v1' AS silver_schema_version,
  u.transformed_at,
  u.transform_run_id,
  u.payload_parse_status,
  filter(
    array(
      CASE
        WHEN u.party_role <> 'plaintiff'
         AND u.raw_name NOT LIKE '%,%'
         AND NOT lower(u.raw_name) RLIKE '^state of wisconsin$'
          THEN 'ambiguous_name_parts'
      END,
      CASE WHEN u.party_role = 'defendant' AND u.dob IS NULL THEN 'missing_dob' END,
      CASE
        WHEN u.party_role = 'defendant' AND u.defendant_from_caption
          THEN 'defendant_from_caption'
      END
    ),
    x -> x IS NOT NULL
  ) AS dq_flags
FROM unioned u;

MERGE INTO us_criminal_bg.silver.court_party AS t
USING silver_court_party_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
 AND t.party_role = s.party_role
 AND t.party_ordinal = s.party_ordinal
WHEN MATCHED THEN UPDATE SET
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
WHEN NOT MATCHED THEN INSERT (
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

-- Type-1: drop party_role+ordinal rows that disappeared for cases processed this run.
DELETE FROM us_criminal_bg.silver.court_party t
WHERE EXISTS (
  SELECT 1 FROM silver_court_case_staged s
  WHERE t.source_system = s.source_system
    AND t.state_code = s.state_code
    AND t.source_record_id = s.source_record_id
)
AND NOT EXISTS (
  SELECT 1 FROM silver_court_party_staged p
  WHERE t.source_system = p.source_system
    AND t.state_code = p.state_code
    AND t.source_record_id = p.source_record_id
    AND t.party_role = p.party_role
    AND t.party_ordinal = p.party_ordinal
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
