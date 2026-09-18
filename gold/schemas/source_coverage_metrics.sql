-- Target: us_criminal_bg.gold.source_coverage_metrics
-- Contract: docs/gold/NAMING.md
-- Refreshable /metrics counts by state_code + source_system. Reads Silver;
-- does not mutate Bronze or Silver. Grain: (as_of_date, state_code, source_system).
--
-- Always include both pilot sources (wcca/WI and sf_criminal_hf/CA) even when
-- one has zero cases. No hire / no-hire / risk columns.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold;

CREATE TABLE IF NOT EXISTS us_criminal_bg.gold.source_coverage_metrics (
  as_of_date DATE NOT NULL,
  state_code STRING NOT NULL,
  source_system STRING NOT NULL,
  case_count BIGINT NOT NULL,
  party_count BIGINT NOT NULL,
  nonempty_name_count BIGINT NOT NULL,
  suggestion_row_count BIGINT NOT NULL,
  open_review_count BIGINT NOT NULL,
  closed_review_count BIGINT NOT NULL,
  gold_schema_version STRING NOT NULL,
  refreshed_at TIMESTAMP NOT NULL
) USING DELTA;
