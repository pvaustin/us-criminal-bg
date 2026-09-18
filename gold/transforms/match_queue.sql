-- Refresh us_criminal_bg.gold.match_queue from silver.match_decision.
-- Contract: docs/gold/NAMING.md · docs/gold/ACCESS.md
--
-- Open definition: latest row per (subject_ref, party_key) has
--   review_status = 'suggestion'
--   AND confidence_band IN ('review', 'auto')
-- A later human append (review_status='human') closes the card.
-- Rank: decided_at DESC, prefer human on timestamp ties, decision_id DESC.
--
-- Filterable WI vs SF via source_system + state_code.
-- Does not mutate Bronze or Silver. No hire / no-hire.
--
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: use durable Delta
-- scratch tables, not TEMP VIEW.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_match_latest
USING DELTA
AS
SELECT
  md.decision_id,
  md.subject_ref,
  md.subject_name,
  md.subject_dob,
  md.party_key,
  md.source_system,
  md.state_code,
  md.source_record_id,
  md.party_role,
  md.party_ordinal,
  md.raw_name,
  md.name_last,
  md.name_first,
  md.name_middle,
  md.confidence_band,
  md.score,
  md.reasons,
  md.score_or_reason_codes,
  md.ingest_run_id,
  md.payload_sha256,
  md.case_report_key,
  md.review_status,
  md.experiment_tag,
  md.notes,
  md.decided_at,
  md.actor
FROM us_criminal_bg.silver.match_decision md
QUALIFY row_number() OVER (
  PARTITION BY md.subject_ref, md.party_key
  ORDER BY
    md.decided_at DESC,
    CASE WHEN md.review_status = 'human' THEN 0 ELSE 1 END,
    md.decision_id DESC
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold.match_queue
USING DELTA
AS
SELECT
  l.subject_ref,
  l.party_key,
  l.subject_name,
  l.subject_dob,
  l.source_system,
  l.state_code,
  l.source_record_id,
  l.party_role,
  l.party_ordinal,
  l.case_report_key,
  l.raw_name,
  l.name_last,
  l.name_first,
  l.name_middle,
  l.confidence_band,
  l.score,
  coalesce(l.reasons, CAST(array() AS ARRAY<STRING>)) AS reasons,
  coalesce(l.score_or_reason_codes, CAST(array() AS ARRAY<STRING>)) AS score_or_reason_codes,
  l.decision_id,
  l.decided_at,
  CAST(
    (unix_timestamp(current_timestamp()) - unix_timestamp(l.decided_at)) AS DOUBLE
  ) / 3600.0 AS age_hours,
  l.actor,
  l.review_status,
  l.experiment_tag,
  l.notes,
  l.ingest_run_id,
  l.payload_sha256,
  'gold.match_queue.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._gold_match_latest l
WHERE l.review_status = 'suggestion'
  AND l.confidence_band IN ('review', 'auto');

DROP TABLE IF EXISTS us_criminal_bg.gold._gold_match_latest;
