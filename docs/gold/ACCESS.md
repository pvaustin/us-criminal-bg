# Gold access and serving notes

**Owner:** silva silver (store) / Uma (UI reads)  
**Contract:** [`NAMING.md`](NAMING.md)  
**Catalog:** `us_criminal_bg.gold`  
**Warehouse apply:** coordinator-side only. This repo does not run Databricks.

**Gold = serving. Silver = truth / clean.** Report, `/review`, and `/metrics` should read Gold. If a card needs a fact Gold did not project (full charge drill-in, Bronze payload, append history), join Silver (and Bronze for payload) with the keys Gold already carries. Do not “fix” Silver by writing Gold.

## Who reads what

| UI | Gold table | Typical filter |
|----|------------|----------------|
| Employer **report** (one subject × party card) | `order_report` | `subject_ref = :ref` (optional `party_key`) |
| **`/review`** open queue | `match_queue` | `source_system` + `state_code` (WI vs SF), sort `score DESC`, `age_hours` |
| **`/metrics`** | `source_coverage_metrics` | latest `as_of_date`, both pilot sources |

WI vs SF (pilot source banner — provenance, **not** a verdict):

```sql
-- WI product path
WHERE source_system = 'wcca' AND state_code = 'WI'

-- SF HF research corpus (in pilot; label as third-party HF redistribution)
WHERE source_system = 'sf_criminal_hf' AND state_code = 'CA'
```

Do not show hire / no-hire / adverse-action controls on any of these reads.

## Apply order (operator)

1. [`gold/schemas/order_report.sql`](../../gold/schemas/order_report.sql)
2. [`gold/schemas/match_queue.sql`](../../gold/schemas/match_queue.sql)
3. [`gold/schemas/source_coverage_metrics.sql`](../../gold/schemas/source_coverage_metrics.sql)
4. [`gold/transforms/match_queue.sql`](../../gold/transforms/match_queue.sql)
5. [`gold/transforms/source_coverage_metrics.sql`](../../gold/transforms/source_coverage_metrics.sql)
6. [`gold/transforms/order_report.sql`](../../gold/transforms/order_report.sql) — works **without** `silver.order_subject`
7. Optional, **only if** `silver.order_subject` exists: [`gold/transforms/order_subject_src_from_silver.sql`](../../gold/transforms/order_subject_src_from_silver.sql) then **re-run** step 6

Python cluster path: `python3 gold/transforms/gold_mvp.py --apply` (try-or-skip `order_subject`; never reads `search_audit`).

Scratch tables are Delta (`_gold_*`), not TEMP VIEW. Safe to leave or `DROP` after a run; the next refresh `CREATE OR REPLACE`s them.

Auth stays in the Databricks CLI profile / workspace. Never commit `.databrickscfg` or tokens. Non-secret host / warehouse notes match Silver (`DATABRICKS_WAREHOUSE_ID` used by Bronze: `e40cabf0355df274`).

## Coordinator prove (identifier-only)

Do **not** paste live full names, DOB, or street. Expected shape vs live Silver 2026-09-17:

| Check | WI `wcca` | SF `sf_criminal_hf` / `CA` |
|-------|-----------|------------------------------|
| Silver cases | 1 | 0 |
| Silver charges | 8 | 0 |
| Silver parties | 6 | 77,399 defendants |
| Silver `match_decision` | 0 | 40 suggestion / review; auto = 0 |
| `gold.order_report` | **0** (no subject/decision yet — honest) | **~40** distinct `(subject_ref, party_key)`; **every** row `has_court_case=false`, `charge_row_count=0` |
| `gold.match_queue` | **0** | **~40** open (until a human append); `confidence_band='review'` |
| `gold.source_coverage_metrics` | `case_count=1`, `party_count=6`, suggestions/open/closed = 0 | `case_count=0`, `party_count=77399`, `suggestion_row_count=40`, `open_review_count≈40`, `closed_review_count=0` |

SQL to run after apply is in [`gold/jobs/README.md`](../../gold/jobs/README.md).

## Non-goals

No scrape, no Bronze/Silver writes, no live PII in git, no `party_name_index`, no hire engine.
