# Gold jobs

Transforms **read** `us_criminal_bg.silver.*` and write only `us_criminal_bg.gold.*`. They do not scrape court sites, do not mutate Bronze or Silver, do not invent court records, and do not need secrets in git.

Gold is the **serving** layer (report UI, `/review`, `/metrics`). Silver remains **truth / clean**. Contract: [`docs/gold/NAMING.md`](../../docs/gold/NAMING.md) · access: [`docs/gold/ACCESS.md`](../../docs/gold/ACCESS.md).

This cloud agent does **not** apply Gold DDL/transforms in the workspace. Coordinator applies and proves live WI-thin vs SF-fat counts.

## Parser / serving unit tests (local, no Databricks)

From the repo root:

```bash
python3 -m unittest discover -s gold/transforms/tests -v
python3 -m py_compile gold/transforms/gold_mvp.py
python3 gold/transforms/gold_mvp.py --help
```

Synthetic names only (`JANE Q PUBLIC`, `FIXTURE, JANE Q`) — **not** live defendants.

## Apply DDL (Databricks SQL warehouse)

Operator-only. Statement-at-a-time apply: scripts use durable Delta scratch tables (`_gold_*`), **not** `TEMP VIEW`.

1. Open a SQL warehouse on `dbc-a0dcbe75-2647.cloud.databricks.com`.
2. Run [`gold/schemas/order_report.sql`](../schemas/order_report.sql).
3. Run [`gold/schemas/match_queue.sql`](../schemas/match_queue.sql).
4. Run [`gold/schemas/source_coverage_metrics.sql`](../schemas/source_coverage_metrics.sql).
5. Confirm `us_criminal_bg.gold.order_report`, `us_criminal_bg.gold.match_queue`, and `us_criminal_bg.gold.source_coverage_metrics` exist.

Non-secret workspace notes (same as Bronze/Silver): host `dbc-a0dcbe75-2647.cloud.databricks.com`, workspace id `7474648418210162`. Auth stays in the Databricks CLI profile / workspace — never commit `.databrickscfg` or tokens.

Optional env (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (Bronze loader used warehouse `e40cabf0355df274`).

## Run the transforms

### A. Spark SQL warehouse

Run **in this order** (each file is self-contained except the optional order_subject attach):

1. [`gold/transforms/match_queue.sql`](../transforms/match_queue.sql)
2. [`gold/transforms/source_coverage_metrics.sql`](../transforms/source_coverage_metrics.sql)
3. [`gold/transforms/order_report.sql`](../transforms/order_report.sql) — **does not** `SELECT` from `silver.order_subject` (not live). Subjects come from `match_decision`.
4. **Optional, only if** `silver.order_subject` exists: [`gold/transforms/order_subject_src_from_silver.sql`](../transforms/order_subject_src_from_silver.sql) then **re-run** `order_report.sql`.

Do **not** run `order_subject_src_from_silver.sql` when that Silver table is missing.

`search_audit` is not read.

### B. Python on a Databricks cluster

```bash
python3 gold/transforms/gold_mvp.py --apply
```

Requires a Spark session (Databricks cluster / notebook with repo on `sys.path`). Try-or-skips `order_subject`; logs that `search_audit` is never read.

## Idempotency

| Table | Re-run behavior |
|-------|-----------------|
| `gold.order_report` | `CREATE OR REPLACE` snapshot on `(subject_ref, party_key)` |
| `gold.match_queue` | `CREATE OR REPLACE` snapshot of **open** cards only |
| `gold.source_coverage_metrics` | `MERGE` on `(as_of_date, state_code, source_system)` — same day overwrites |
| Silver / Bronze | **never** written |

## Coordinator prove (identifier-only — no live names)

Live Silver 2026-09-17: WI 1 case / 8 charges / 6 parties; SF 0 cases / 77,399 defendant parties; 40 SF `match_decision` suggestion/`review` rows; `auto=0`; `order_subject` / `search_audit` not live.

```sql
-- Schema exists
SHOW TABLES IN us_criminal_bg.gold;

-- Thin WI vs fat SF on Silver (baseline)
SELECT source_system, state_code, count(*) AS n
FROM us_criminal_bg.silver.court_case
GROUP BY source_system, state_code;

SELECT source_system, state_code, count(*) AS n
FROM us_criminal_bg.silver.court_party
GROUP BY source_system, state_code;

SELECT source_system, state_code, review_status, confidence_band, count(*) AS n
FROM us_criminal_bg.silver.match_decision
GROUP BY source_system, state_code, review_status, confidence_band;

-- Gold serving
SELECT source_system, state_code, count(*) AS n,
       sum(CASE WHEN has_court_case THEN 1 ELSE 0 END) AS with_case,
       sum(charge_row_count) AS charge_rows
FROM us_criminal_bg.gold.order_report
GROUP BY source_system, state_code;

SELECT source_system, state_code, confidence_band, count(*) AS n
FROM us_criminal_bg.gold.match_queue
GROUP BY source_system, state_code, confidence_band;

SELECT as_of_date, source_system, state_code,
       case_count, party_count, nonempty_name_count,
       suggestion_row_count, open_review_count, closed_review_count
FROM us_criminal_bg.gold.source_coverage_metrics
ORDER BY source_system, state_code;
```

Expect after a clean refresh (until humans append or `order_subject` lands):

| Object | WI `wcca` | SF `sf_criminal_hf` / `CA` |
|--------|-----------|------------------------------|
| `order_report` rows | **0** | **~40**; `with_case=0`, `charge_rows=0` |
| `match_queue` rows | **0** | **~40** `review` |
| metrics `case_count` | **1** | **0** |
| metrics `party_count` | **6** | **77399** |
| metrics suggestions / open | 0 / 0 | **40** / **~40** |

If `order_report` SF rows have `has_court_case=true` or `charge_row_count>0`, Gold invented a case — **stop**. If WI metrics `case_count<>1`, Silver drift — report it. Do not paste live `raw_name` / DOB / street.

## Out of scope

Hire / no-hire, FCRA packages, `party_name_index`, scraping, Bronze/Silver writes, live PII in git.
