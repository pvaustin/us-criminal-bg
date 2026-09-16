-- Target: us_criminal_bg.silver.order_subject
-- Contract: docs/silver/ORDER_AUDIT.md
-- Pilot type-1 current subject snapshot per employer order.
-- Web app may CREATE TABLE IF NOT EXISTS (same pattern as match_decision).
-- Does not scrape, does not invent DOB, does not store hire/no-hire.

CREATE CATALOG IF NOT EXISTS us_criminal_bg;
CREATE SCHEMA IF NOT EXISTS us_criminal_bg.silver;

CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.order_subject (
  -- Natural key (type-1 current row per order)
  order_id STRING NOT NULL,
  -- Stable ref for /review/[subjectRef]; unique preferred
  subject_ref STRING NOT NULL,
  -- As entered; required. Do not invent.
  subject_name STRING NOT NULL,
  -- Optional; null when absent (honest). Never infer.
  subject_dob DATE,
  created_at TIMESTAMP NOT NULL,
  created_by STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  -- Pilot: draft | submitted | in_review
  status STRING NOT NULL
) USING DELTA;
