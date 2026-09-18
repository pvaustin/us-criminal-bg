-- Refresh us_criminal_bg.gold.name_match_eval from silver.match_decision.
-- Contract: docs/gold/NAME_MATCH_EVAL.md
--
-- HUMAN ONLY. review_status='suggestion' is not GT (live 2026-09-18: 40
-- suggestion cards, 0 human rows → this table is empty until Uma appends).
-- Latest human row per (subject_ref, party_key). Scoped to SF research
-- (sf_criminal_hf / CA). WI match_decision is not an input to this eval.
--
-- Label mapping (honest; do not invent humans):
--   confidence_band = 'auto'    → link            (human confirmed match)
--   confidence_band = 'no-link' → reject          (human said not a match)
--   anything else (incl. review)→ leave_in_review (exclude from GT metrics)
--
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: durable Delta
-- scratch, not TEMP VIEW. Does not mutate Bronze or Silver.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE OR REPLACE TABLE us_criminal_bg.gold._name_match_human_latest
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
  md.party_role,
  md.party_ordinal,
  md.raw_name,
  md.name_last,
  md.name_first,
  md.name_middle,
  md.confidence_band,
  md.score,
  md.reasons,
  md.review_status,
  md.experiment_tag,
  md.decided_at,
  md.actor
FROM us_criminal_bg.silver.match_decision md
WHERE md.review_status = 'human'
  AND md.source_system = 'sf_criminal_hf'
  AND md.state_code = 'CA'
QUALIFY row_number() OVER (
  PARTITION BY md.subject_ref, md.party_key
  ORDER BY
    md.decided_at DESC,
    md.decision_id DESC
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold.name_match_eval
USING DELTA
AS
SELECT
  h.subject_ref,
  h.party_key,
  CASE
    WHEN h.confidence_band = 'auto' THEN 'link'
    WHEN h.confidence_band = 'no-link' THEN 'reject'
    ELSE 'leave_in_review'
  END AS label,
  h.source_system,
  h.state_code,
  h.decided_at AS labeled_at,
  h.actor,
  h.decision_id,
  h.confidence_band,
  h.experiment_tag,
  h.subject_name,
  h.subject_dob,
  h.party_role,
  h.party_ordinal,
  h.raw_name,
  h.name_last,
  h.name_first,
  h.name_middle,
  h.score,
  coalesce(h.reasons, CAST(array() AS ARRAY<STRING>)) AS reasons,
  h.review_status,
  'sf_name_match_v1' AS eval_name,
  'gold.name_match_eval.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._name_match_human_latest h;

DROP TABLE IF EXISTS us_criminal_bg.gold._name_match_human_latest;
