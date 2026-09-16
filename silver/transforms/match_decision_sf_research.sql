-- Research-only: score a SMALL subject list against SF HF court_party
-- defendants (source_system=sf_criminal_hf, state_code=CA) and APPEND
-- suggestion rows to us_criminal_bg.silver.match_decision.
--
-- Contract: docs/silver/SF_MATCH_EXPERIMENT.md · docs/silver/MATCH_REVIEW.md
-- Bands MUST match silver/transforms/match_review_sketch.py
--   (REVIEW_MIN = 50; auto only when exact last+first or raw_name AND dob_match).
-- SF parties have no DOB → dob_absent → review. auto is unreachable.
--
-- HARD SCOPE:
--   court_party filter source_system = 'sf_criminal_hf' AND state_code = 'CA'
--   last-name (normalized) equality join — not a 77k cartesian product
--   INSERT INTO match_decision only (append). Never MERGE/UPDATE/DELETE.
--   Does not write court_case / court_charge / court_party.
--   Does not touch wcca / WI rows. Does not scrape. Not CRA / adverse action.
--
-- Apply AFTER silver/schemas/match_decision.sql.
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: use durable Delta
-- scratch (_match_decision_sf_staged), not TEMP VIEW. Do NOT drop the subject
-- table (coordinator input). DROP only the staged scoring table.
--
-- Coordinator: insert N research subjects into
--   us_criminal_bg.silver._match_subject_sf_research
-- (subject_ref, subject_name, subject_dob). Do not commit live names to git.
-- Then run this script. Report band counts without pasting live full names.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

-- Coordinator-owned input. Empty until subjects are inserted.
CREATE TABLE IF NOT EXISTS us_criminal_bg.silver._match_subject_sf_research (
  subject_ref STRING NOT NULL,
  subject_name STRING NOT NULL,
  subject_dob DATE
) USING DELTA;

-- Example only (synthetic fixture names — not live defendants). Coordinator
-- replaces with N warehouse subjects; never paste live PII into git:
-- INSERT INTO us_criminal_bg.silver._match_subject_sf_research
--   (subject_ref, subject_name, subject_dob)
-- VALUES
--   ('synthetic-subject-1', 'Jane Q Public', CAST(NULL AS DATE)),
--   ('synthetic-subject-2', 'Luis Singletokenlast', CAST(NULL AS DATE));

CREATE OR REPLACE TABLE us_criminal_bg.silver._match_decision_sf_staged
USING DELTA
AS
WITH
subj AS (
  SELECT
    s.subject_ref,
    s.subject_name,
    s.subject_dob,
    trim(regexp_replace(trim(s.subject_name), '\\s+', ' ')) AS collapsed_name
  FROM us_criminal_bg.silver._match_subject_sf_research s
),
subj_keys AS (
  SELECT
    subject_ref,
    subject_name,
    subject_dob,
    collapsed_name,
    nullif(
      upper(
        regexp_replace(
          CASE
            WHEN instr(collapsed_name, ',') > 0 THEN trim(split(collapsed_name, ',')[0])
            ELSE element_at(split(collapsed_name, ' '), -1)
          END,
          '[^A-Za-z0-9]',
          ''
        )
      ),
      ''
    ) AS last_key,
    nullif(
      upper(
        regexp_replace(
          CASE
            WHEN instr(collapsed_name, ',') > 0 THEN
              split(trim(substring_index(collapsed_name, ',', -1)), ' ')[0]
            WHEN size(split(collapsed_name, ' ')) >= 2 THEN split(collapsed_name, ' ')[0]
            ELSE CAST(NULL AS STRING)
          END,
          '[^A-Za-z0-9]',
          ''
        )
      ),
      ''
    ) AS first_key,
    nullif(upper(regexp_replace(collapsed_name, '[^A-Za-z0-9]', '')), '') AS raw_key
  FROM subj
),
parties AS (
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
    p.ingest_run_id,
    p.payload_sha256,
    p.transform_run_id,
    nullif(upper(regexp_replace(coalesce(p.name_last, ''), '[^A-Za-z0-9]', '')), '') AS last_key,
    nullif(upper(regexp_replace(coalesce(p.name_first, ''), '[^A-Za-z0-9]', '')), '') AS first_key,
    nullif(upper(regexp_replace(coalesce(p.raw_name, ''), '[^A-Za-z0-9]', '')), '') AS raw_key
  FROM us_criminal_bg.silver.court_party p
  WHERE p.source_system = 'sf_criminal_hf'
    AND p.state_code = 'CA'
    AND p.party_role IN ('defendant', 'aka')
),
joined AS (
  SELECT
    s.subject_ref,
    s.subject_name,
    s.subject_dob,
    s.last_key AS subj_last_key,
    s.first_key AS subj_first_key,
    s.raw_key AS subj_raw_key,
    p.*
  FROM subj_keys s
  INNER JOIN parties p
    ON s.last_key = p.last_key
  WHERE s.last_key IS NOT NULL
    AND p.last_key IS NOT NULL
),
scored AS (
  SELECT
    j.*,
    -- After last-name join, last names match (same rule as sketch last_name_match).
    CAST(40 AS INT) AS last_pts,
    CASE
      WHEN j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL
        AND j.subj_first_key = j.first_key THEN 30
      WHEN j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL
        AND substr(j.subj_first_key, 1, 1) = substr(j.first_key, 1, 1) THEN 15
      ELSE 0
    END AS first_pts,
    CASE
      WHEN j.subject_dob IS NOT NULL AND j.dob IS NOT NULL AND j.subject_dob = j.dob THEN 30
      ELSE 0
    END AS dob_pts,
    CASE
      WHEN j.subject_dob IS NOT NULL AND j.dob IS NOT NULL AND j.subject_dob <> j.dob THEN true
      ELSE false
    END AS dob_conflict,
    (j.subj_last_key = j.last_key
      AND j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL
      AND j.subj_first_key = j.first_key)
      OR (j.subj_raw_key IS NOT NULL AND j.raw_key IS NOT NULL AND j.subj_raw_key = j.raw_key)
      AS exact_name,
    CASE
      WHEN j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL
        AND j.subj_first_key = j.first_key THEN 'first_name_match'
      WHEN j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL
        AND substr(j.subj_first_key, 1, 1) = substr(j.first_key, 1, 1) THEN 'first_initial_match'
      WHEN j.subj_first_key IS NOT NULL AND j.first_key IS NOT NULL THEN 'first_name_mismatch'
      WHEN j.subj_first_key IS NOT NULL OR j.first_key IS NOT NULL THEN 'first_name_unparsed'
      ELSE CAST(NULL AS STRING)
    END AS first_reason,
    CASE
      WHEN j.subj_raw_key IS NOT NULL AND j.raw_key IS NOT NULL
        AND j.subj_raw_key = j.raw_key THEN 'raw_name_match'
      ELSE CAST(NULL AS STRING)
    END AS raw_reason,
    CASE
      WHEN j.subject_dob IS NOT NULL AND j.dob IS NOT NULL AND j.subject_dob = j.dob THEN 'dob_match'
      WHEN j.subject_dob IS NOT NULL AND j.dob IS NOT NULL THEN 'dob_conflict'
      ELSE 'dob_absent'
    END AS dob_reason,
    CASE WHEN j.party_role = 'aka' THEN 'aka_alias_row' ELSE CAST(NULL AS STRING) END AS aka_reason
  FROM joined j
)
SELECT
  uuid() AS decision_id,
  subject_ref,
  subject_name,
  subject_dob,
  concat_ws('|', source_system, state_code, source_record_id, party_role, party_ordinal) AS party_key,
  source_system,
  state_code,
  source_record_id,
  party_role,
  party_ordinal,
  raw_name,
  name_last,
  name_first,
  name_middle,
  CASE
    WHEN dob_conflict THEN 'no-link'
    WHEN exact_name AND dob_reason = 'dob_match' THEN 'auto'
    WHEN CASE WHEN dob_conflict THEN 0 ELSE last_pts + first_pts + dob_pts END >= 50 THEN 'review'
    ELSE 'no-link'
  END AS confidence_band,
  CASE WHEN dob_conflict THEN 0 ELSE last_pts + first_pts + dob_pts END AS score,
  filter(
    array(
      'last_name_match',
      first_reason,
      raw_reason,
      dob_reason,
      aka_reason
    ),
    x -> x IS NOT NULL
  ) AS reasons,
  concat(
    array(
      CAST(CASE WHEN dob_conflict THEN 0 ELSE last_pts + first_pts + dob_pts END AS STRING)
    ),
    filter(
      array(
        'last_name_match',
        first_reason,
        raw_reason,
        dob_reason,
        aka_reason
      ),
      x -> x IS NOT NULL
    )
  ) AS score_or_reason_codes,
  ingest_run_id,
  payload_sha256,
  transform_run_id,
  concat_ws('|', source_system, state_code, source_record_id) AS case_report_key,
  'suggestion' AS review_status,
  'sf_name_only_research' AS experiment_tag,
  'research-only SF name-match; not CRA/adverse action; party DOB always null so auto is unreachable' AS notes,
  current_timestamp() AS decided_at,
  'system:suggestion' AS actor
FROM scored;

-- Default: persist review + auto only (SF auto should be 0). To keep last-name
-- equal no-link negatives for prove, remove the confidence_band predicate.
INSERT INTO us_criminal_bg.silver.match_decision (
  decision_id, subject_ref, subject_name, subject_dob,
  party_key, source_system, state_code, source_record_id,
  party_role, party_ordinal, raw_name, name_last, name_first, name_middle,
  confidence_band, score, reasons, score_or_reason_codes,
  ingest_run_id, payload_sha256, transform_run_id, case_report_key,
  review_status, experiment_tag, notes, decided_at, actor
)
SELECT
  decision_id, subject_ref, subject_name, subject_dob,
  party_key, source_system, state_code, source_record_id,
  party_role, party_ordinal, raw_name, name_last, name_first, name_middle,
  confidence_band, score, reasons, score_or_reason_codes,
  ingest_run_id, payload_sha256, transform_run_id, case_report_key,
  review_status, experiment_tag, notes, decided_at, actor
FROM us_criminal_bg.silver._match_decision_sf_staged
WHERE confidence_band IN ('review', 'auto');

DROP TABLE IF EXISTS us_criminal_bg.silver._match_decision_sf_staged;
