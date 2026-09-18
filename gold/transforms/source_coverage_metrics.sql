-- Refresh us_criminal_bg.gold.source_coverage_metrics from Silver.
-- Contract: docs/gold/NAMING.md · docs/gold/ACCESS.md
--
-- Grain: (as_of_date, state_code, source_system). Same-day MERGE overwrite.
-- Universe always includes both pilot sources (wcca/WI, sf_criminal_hf/CA)
-- even when one has zero cases (SF court_case is empty today).
--
-- Metrics: cases, parties, nonempty raw_name, suggestion volume,
-- open vs closed reviews (same open rule as match_queue).
-- Does not mutate Bronze or Silver. No hire / no-hire.
--
-- Warehouse /api/2.0/sql/statements is statement-at-a-time: use durable Delta
-- scratch tables, not TEMP VIEW.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_source_universe
USING DELTA
AS
SELECT source_system, state_code
FROM VALUES
  ('wcca', 'WI'),
  ('sf_criminal_hf', 'CA')
AS t(source_system, state_code)
UNION
SELECT DISTINCT source_system, state_code
FROM us_criminal_bg.silver.court_case
UNION
SELECT DISTINCT source_system, state_code
FROM us_criminal_bg.silver.court_party
UNION
SELECT DISTINCT source_system, state_code
FROM us_criminal_bg.silver.match_decision;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_match_latest_metrics
USING DELTA
AS
SELECT
  md.subject_ref,
  md.party_key,
  md.source_system,
  md.state_code,
  md.review_status,
  md.confidence_band
FROM us_criminal_bg.silver.match_decision md
QUALIFY row_number() OVER (
  PARTITION BY md.subject_ref, md.party_key
  ORDER BY
    md.decided_at DESC,
    CASE WHEN md.review_status = 'human' THEN 0 ELSE 1 END,
    md.decision_id DESC
) = 1;

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_source_coverage_staged
USING DELTA
AS
SELECT
  current_date() AS as_of_date,
  u.state_code,
  u.source_system,
  coalesce(c.case_count, 0) AS case_count,
  coalesce(p.party_count, 0) AS party_count,
  coalesce(p.nonempty_name_count, 0) AS nonempty_name_count,
  coalesce(s.suggestion_row_count, 0) AS suggestion_row_count,
  coalesce(o.open_review_count, 0) AS open_review_count,
  coalesce(cl.closed_review_count, 0) AS closed_review_count,
  'gold.source_coverage_metrics.v1' AS gold_schema_version,
  current_timestamp() AS refreshed_at
FROM us_criminal_bg.gold._gold_source_universe u
LEFT JOIN (
  SELECT source_system, state_code, count(*) AS case_count
  FROM us_criminal_bg.silver.court_case
  GROUP BY source_system, state_code
) c
  ON c.source_system = u.source_system
 AND c.state_code = u.state_code
LEFT JOIN (
  SELECT
    source_system,
    state_code,
    count(*) AS party_count,
    sum(CASE WHEN trim(coalesce(raw_name, '')) <> '' THEN 1 ELSE 0 END) AS nonempty_name_count
  FROM us_criminal_bg.silver.court_party
  GROUP BY source_system, state_code
) p
  ON p.source_system = u.source_system
 AND p.state_code = u.state_code
LEFT JOIN (
  SELECT
    source_system,
    state_code,
    count(*) AS suggestion_row_count
  FROM us_criminal_bg.silver.match_decision
  WHERE review_status = 'suggestion'
  GROUP BY source_system, state_code
) s
  ON s.source_system = u.source_system
 AND s.state_code = u.state_code
LEFT JOIN (
  SELECT
    source_system,
    state_code,
    count(*) AS open_review_count
  FROM us_criminal_bg.gold._gold_match_latest_metrics
  WHERE review_status = 'suggestion'
    AND confidence_band IN ('review', 'auto')
  GROUP BY source_system, state_code
) o
  ON o.source_system = u.source_system
 AND o.state_code = u.state_code
LEFT JOIN (
  SELECT
    source_system,
    state_code,
    count(*) AS closed_review_count
  FROM us_criminal_bg.gold._gold_match_latest_metrics
  WHERE review_status = 'human'
  GROUP BY source_system, state_code
) cl
  ON cl.source_system = u.source_system
 AND cl.state_code = u.state_code;

MERGE INTO us_criminal_bg.gold.source_coverage_metrics t
USING us_criminal_bg.gold._gold_source_coverage_staged s
ON t.as_of_date = s.as_of_date
 AND t.state_code = s.state_code
 AND t.source_system = s.source_system
WHEN MATCHED THEN UPDATE SET
  t.case_count = s.case_count,
  t.party_count = s.party_count,
  t.nonempty_name_count = s.nonempty_name_count,
  t.suggestion_row_count = s.suggestion_row_count,
  t.open_review_count = s.open_review_count,
  t.closed_review_count = s.closed_review_count,
  t.gold_schema_version = s.gold_schema_version,
  t.refreshed_at = s.refreshed_at
WHEN NOT MATCHED THEN INSERT (
  as_of_date,
  state_code,
  source_system,
  case_count,
  party_count,
  nonempty_name_count,
  suggestion_row_count,
  open_review_count,
  closed_review_count,
  gold_schema_version,
  refreshed_at
) VALUES (
  s.as_of_date,
  s.state_code,
  s.source_system,
  s.case_count,
  s.party_count,
  s.nonempty_name_count,
  s.suggestion_row_count,
  s.open_review_count,
  s.closed_review_count,
  s.gold_schema_version,
  s.refreshed_at
);

DROP TABLE IF EXISTS us_criminal_bg.gold._gold_source_coverage_staged;
DROP TABLE IF EXISTS us_criminal_bg.gold._gold_match_latest_metrics;
DROP TABLE IF EXISTS us_criminal_bg.gold._gold_source_universe;
