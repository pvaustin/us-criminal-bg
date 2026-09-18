-- OPTIONAL. Run ONLY when us_criminal_bg.silver.order_subject exists.
-- Contract: docs/gold/NAMING.md
--
-- Replaces the empty _gold_order_subject_src fallback, then the operator
-- MUST re-run gold/transforms/order_report.sql so order_id / subject snapshot
-- attach onto (subject_ref, party_key) report rows.
--
-- Do not run this file when the Silver table is missing (statement will fail).
-- Python gold_mvp.py --apply try-or-skips this step.
-- Does not invent subjects. Does not mutate Bronze or Silver court facts.
-- search_audit is not read.

CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_order_subject_src
USING DELTA
AS
SELECT
  order_id,
  subject_ref,
  subject_name,
  subject_dob,
  created_at,
  created_by,
  updated_at,
  status
FROM us_criminal_bg.silver.order_subject;
