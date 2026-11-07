-- Refresh us_criminal_bg.gold.name_match_label_pack.
-- Contract: docs/gold/NAME_MATCH_EVAL.md
--
-- Unlabeled pack for humans. `label` is always NULL here — scorer suggestions
-- are not GT. Humans fill via Uma /review, which APPENDS silver.match_decision
-- (review_status='human'); then refresh name_match_eval.
--
-- Pair kinds:
--   open_queue     = open SF cards on gold.match_queue
--                    (latest suggestion + band review|auto; not closed by human)
--   hard_negative  = same subject_ref, a silver.court_party row whose
--                    normalized last name differs (existing party; not invented)
--
-- Refresh gold.match_queue first. Scoped to sf_criminal_hf / CA.
-- One hard negative per distinct subject_ref (deterministic xxhash64).
-- Warehouse statement-at-a-time: Delta scratch, not TEMP VIEW.
-- Does not mutate Bronze or Silver. Not a hire engine.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE OR REPLACE TABLE us_criminal_bg.gold._name_match_pack_open
USING DELTA
AS
SELECT
  q.subject_ref,
  q.party_key,
  q.subject_name,
  q.subject_dob,
  q.source_system,
  q.state_code,
  q.source_record_id,
  q.party_role,
  q.party_ordinal,
  q.raw_name,
  q.name_last,
  q.name_first,
  q.name_middle,
  q.decision_id AS suggestion_decision_id,
  q.confidence_band AS suggestion_confidence_band,
  q.score AS suggestion_score,
  q.actor AS suggestion_actor,
  q.ingest_run_id,
  q.payload_sha256,
  upper(regexp_replace(coalesce(q.name_last, ''), '[^A-Za-z0-9]', '')) AS party_last_key
FROM us_criminal_bg.gold.match_queue q
WHERE q.source_system = 'sf_criminal_hf'
  AND q.state_code = 'CA';

-- Subject last-name proxy = suggested party last name. Honest for this pack:
-- SF retrieval is last-name equality, so open cards share the subject last name.
CREATE OR REPLACE TABLE us_criminal_bg.gold._name_match_pack_subjects
USING DELTA
AS
SELECT
  o.subject_ref,
  max(o.subject_name) AS subject_name,
  max(o.subject_dob) AS subject_dob,
  max(o.party_last_key) AS subj_last_key
FROM us_criminal_bg.gold._name_match_pack_open o
GROUP BY o.subject_ref;

CREATE OR REPLACE TABLE us_criminal_bg.gold._name_match_pack_parties
USING DELTA
AS
SELECT
  p.source_system,
  p.state_code,
  p.source_record_id,
  p.party_role,
  p.party_ordinal,
  concat_ws(
    '|',
    p.source_system,
    p.state_code,
    p.source_record_id,
    p.party_role,
    CAST(p.party_ordinal AS STRING)
  ) AS party_key,
  p.raw_name,
  p.name_last,
  p.name_first,
  p.name_middle,
  p.ingest_run_id,
  p.payload_sha256,
  upper(regexp_replace(coalesce(p.name_last, ''), '[^A-Za-z0-9]', '')) AS party_last_key
FROM us_criminal_bg.silver.court_party p
WHERE p.source_system = 'sf_criminal_hf'
  AND p.state_code = 'CA'
  AND p.party_role IN ('defendant', 'aka');

CREATE OR REPLACE TABLE us_criminal_bg.gold._name_match_pack_neg
USING DELTA
AS
SELECT
  s.subject_ref,
  s.subject_name,
  s.subject_dob,
  p.party_key,
  p.source_system,
  p.state_code,
  p.source_record_id,
  p.party_role,
  p.party_ordinal,
  p.raw_name,
  p.name_last,
  p.name_first,
  p.name_middle,
  p.ingest_run_id,
  p.payload_sha256
FROM us_criminal_bg.gold._name_match_pack_subjects s
INNER JOIN us_criminal_bg.gold._name_match_pack_parties p
  ON p.party_last_key <> s.subj_last_key
 AND s.subj_last_key <> ''
LEFT ANTI JOIN us_criminal_bg.gold._name_match_pack_open o
  ON o.subject_ref = s.subject_ref
 AND o.party_key = p.party_key
QUALIFY row_number() OVER (
  PARTITION BY s.subject_ref
  ORDER BY xxhash64(s.subject_ref, p.party_key)
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold.name_match_label_pack
USING DELTA
AS
SELECT
  uuid() AS pack_row_id,
  o.subject_ref,
  o.party_key,
  o.subject_name,
  o.subject_dob,
  o.source_system,
  o.state_code,
  o.source_record_id,
  o.party_role,
  o.party_ordinal,
  o.raw_name,
  o.name_last,
  o.name_first,
  o.name_middle,
  'open_queue' AS pair_kind,
  o.suggestion_decision_id,
  o.suggestion_confidence_band,
  o.suggestion_score,
  o.suggestion_actor,
  CAST(NULL AS STRING) AS label,
  CAST(NULL AS TIMESTAMP) AS labeled_at,
  CAST(NULL AS STRING) AS actor,
  'sf_name_match_v1' AS experiment_tag,
  'unlabeled pack row — not GT; label via Uma /review append to match_decision' AS notes,
  o.ingest_run_id,
  o.payload_sha256,
  'gold.name_match_label_pack.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._name_match_pack_open o
UNION ALL
SELECT
  uuid() AS pack_row_id,
  n.subject_ref,
  n.party_key,
  n.subject_name,
  n.subject_dob,
  n.source_system,
  n.state_code,
  n.source_record_id,
  n.party_role,
  n.party_ordinal,
  n.raw_name,
  n.name_last,
  n.name_first,
  n.name_middle,
  'hard_negative' AS pair_kind,
  CAST(NULL AS STRING) AS suggestion_decision_id,
  CAST(NULL AS STRING) AS suggestion_confidence_band,
  CAST(NULL AS INT) AS suggestion_score,
  CAST(NULL AS STRING) AS suggestion_actor,
  CAST(NULL AS STRING) AS label,
  CAST(NULL AS TIMESTAMP) AS labeled_at,
  CAST(NULL AS STRING) AS actor,
  'sf_name_match_v1' AS experiment_tag,
  'unlabeled hard-negative distractor — different last name; not GT' AS notes,
  n.ingest_run_id,
  n.payload_sha256,
  'gold.name_match_label_pack.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._name_match_pack_neg n;

DROP TABLE IF EXISTS us_criminal_bg.gold._name_match_pack_neg;
DROP TABLE IF EXISTS us_criminal_bg.gold._name_match_pack_parties;
DROP TABLE IF EXISTS us_criminal_bg.gold._name_match_pack_subjects;
DROP TABLE IF EXISTS us_criminal_bg.gold._name_match_pack_open;
