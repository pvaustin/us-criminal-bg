# Silver jobs

Transforms **read** `us_criminal_bg.bronze.*` and write only `us_criminal_bg.silver.*`. They do not scrape court sites, do not mutate Bronze, and do not need secrets in git.

Proposed cadence: after each successful Bronze ingest (weekly when Bronze is weekly). Orchestration may be a Grok Bot routine — **paused until Prasanth explicitly enables**.

## Parser unit tests (local, no Databricks)

From the repo root:

```bash
python3 -m unittest discover -s sources/wcca/tests -v
python3 -m unittest discover -s silver/transforms/tests -v
python3 -m py_compile sources/wcca/parse.py silver/transforms/map_court_case.py silver/transforms/court_case.py
python3 silver/transforms/court_case.py --help
```

Synthetic HTML under `sources/wcca/tests/fixtures/` is **not** a real court record.

## Apply DDL (Databricks SQL warehouse)

Operator-only. The cloud agent that added this tree did **not** apply Silver DDL in the workspace.

1. Open a SQL warehouse on `dbc-a0dcbe75-2647.cloud.databricks.com`.
2. Run [`silver/schemas/court_case.sql`](../schemas/court_case.sql) (`CREATE SCHEMA/TABLE IF NOT EXISTS`).
3. Confirm `us_criminal_bg.silver.court_case` and `us_criminal_bg.silver.transform_run` exist.

Non-secret workspace notes (same as Bronze): host `dbc-a0dcbe75-2647.cloud.databricks.com`, workspace id `7474648418210162`. Auth stays in the Databricks CLI profile / workspace — never commit `.databrickscfg` or tokens.

Optional env (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (Bronze loader used warehouse `e40cabf0355df274`).

## Run the transform

### A. Spark SQL, identifiers only (SQL warehouse)

Run [`silver/transforms/court_case.sql`](../transforms/court_case.sql).

- Parses `source_record_id` and URL `countyNo` / `caseNo`.
- Leaves `filed_date` / `caption` null (HTML SPA facts are not guessed in SQL).
- `MERGE` on `(source_system, state_code, source_record_id)` — type-1 overwrite.
- Inserts one `transform_run` row per attempt (`running` → `succeeded`).
- Re-running for the same Bronze keys updates the same `court_case` row; it does not duplicate it.

### B. Python parser on a Databricks cluster (optional HTML/JSON embeds)

```bash
python3 silver/transforms/court_case.py --apply
```

Requires a Spark session (Databricks cluster / notebook with repo on `sys.path`). Uses `sources/wcca/parse.py` so structured `application/json` script tags can fill caption / filed_date when those keys are explicitly present; otherwise same null + DQ behavior as SQL.

## Idempotency

| Table | Re-run behavior |
|-------|-----------------|
| `silver.court_case` | Upsert on `(source_system, state_code, source_record_id)` |
| `silver.transform_run` | Always append a new attempt row |

Business attributes for a given Bronze key converge; `transformed_at` / `transform_run_id` change each run (type-1 current row metadata).

## Out of scope

Person matching, FCRA, Gold, scraping WCCA, writing Bronze.
