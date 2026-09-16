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

Operator-only. The cloud agent that added this tree does **not** apply Silver DDL in the workspace.

1. Open a SQL warehouse on `dbc-a0dcbe75-2647.cloud.databricks.com`.
2. Run [`silver/schemas/court_case.sql`](../schemas/court_case.sql) (`CREATE SCHEMA/TABLE IF NOT EXISTS`). The warehouse **rejects** `ADD COLUMN IF NOT EXISTS`. The script previews missing columns via `information_schema` and adds `case_status` / `county_name` with a compound `IF NOT EXISTS (SELECT …) THEN ALTER TABLE … ADD COLUMN …` block. If that compound statement is unavailable, run only the missing plain `ALTER TABLE … ADD COLUMN <name> STRING;` statements (skip when the column already exists).
3. Run [`silver/schemas/court_charge.sql`](../schemas/court_charge.sql).
4. Confirm `us_criminal_bg.silver.court_case`, `us_criminal_bg.silver.court_charge`, and `us_criminal_bg.silver.transform_run` exist.

Non-secret workspace notes (same as Bronze): host `dbc-a0dcbe75-2647.cloud.databricks.com`, workspace id `7474648418210162`. Auth stays in the Databricks CLI profile / workspace — never commit `.databrickscfg` or tokens.

Optional env (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (Bronze loader used warehouse `e40cabf0355df274`).

## Run the transform

Both paths materialize `transform_run_id` once into `us_criminal_bg.silver._this_transform_run` (Delta scratch) and finalize with `status='running' AND transform_run_id IN (SELECT … FROM _this_transform_run)`, then drop the scratch table.

### A. Spark SQL warehouse (SSR regex)

Run [`silver/transforms/court_case.sql`](../transforms/court_case.sql).

- Parses `source_record_id` and URL `countyNo` / `caseNo`.
- Strips scripts/styles/tags from `payload` and regex-extracts caption, filing date, case status, county name, and charge cores.
- `modifier_statute` / `modifier_text` are left **null** in SQL (use the Python job for modifiers).
- `MERGE` `court_case` on `(source_system, state_code, source_record_id)`.
- `MERGE` `court_charge` on that key plus `charge_count`; deletes stale counts for cases in the run.
- Inserts one `transform_run` row per attempt (`running` → `succeeded`). `row_count` is `court_case` rows for that run id.

### B. Python parser on a Databricks cluster (complete SSR, including modifiers)

```bash
python3 silver/transforms/court_case.py --apply
```

Requires a Spark session (Databricks cluster / notebook with repo on `sys.path`). Uses `sources/wcca/parse.py` so HTML SSR and structured `application/json` script tags fill Silver; charge `Modifier:` lines populate `modifier_*`.

Prefer this path for `html_ssr_v1` on live WCCA snapshots.

## Idempotency

| Table | Re-run behavior |
|-------|-----------------|
| `silver.court_case` | Upsert on `(source_system, state_code, source_record_id)` |
| `silver.court_charge` | Upsert on `(source_system, state_code, source_record_id, charge_count)`; extra counts for processed cases are deleted |
| `silver.transform_run` | Always append a new attempt row |

Business attributes for a given Bronze key converge; `transformed_at` / `transform_run_id` change each run (type-1 current row metadata).

## Out of scope

Person matching, FCRA, Gold, scraping WCCA, writing Bronze.
