# Silver jobs

Transforms **read** `us_criminal_bg.bronze.*` and write only `us_criminal_bg.silver.*`. They do not scrape court sites, do not mutate Bronze, and do not need secrets in git.

Proposed cadence: after each successful Bronze ingest (weekly when Bronze is weekly). Orchestration may be a Grok Bot routine — **paused until Prasanth explicitly enables**.

## Parser unit tests (local, no Databricks)

From the repo root:

```bash
python3 -m unittest discover -s sources/wcca/tests -v
python3 -m unittest discover -s sources/sf_criminal_hf/tests -v
python3 -m unittest discover -s silver/transforms/tests -v
python3 -m py_compile sources/wcca/parse.py sources/sf_criminal_hf/parse_party.py silver/transforms/map_court_case.py silver/transforms/map_court_party_sf.py silver/transforms/court_case.py silver/transforms/court_party_sf_criminal_hf.py silver/transforms/match_review_sketch.py silver/transforms/match_decision_sf_research.py
python3 silver/transforms/court_case.py --help
python3 silver/transforms/court_party_sf_criminal_hf.py --help
python3 silver/transforms/match_decision_sf_research.py --help
```

Synthetic HTML under `sources/wcca/tests/fixtures/` is **not** a real court record.

## Apply DDL (Databricks SQL warehouse)

Operator-only. The cloud agent that added this tree does **not** apply Silver DDL in the workspace.

1. Open a SQL warehouse on `dbc-a0dcbe75-2647.cloud.databricks.com`.
2. Run [`silver/schemas/court_case.sql`](../schemas/court_case.sql) (`CREATE SCHEMA/TABLE IF NOT EXISTS`). The warehouse **rejects** `ADD COLUMN IF NOT EXISTS`. The script previews missing columns via `information_schema` and adds `case_status` / `county_name` with a compound `IF NOT EXISTS (SELECT …) THEN ALTER TABLE … ADD COLUMN …` block. If that compound statement is unavailable, run only the missing plain `ALTER TABLE … ADD COLUMN <name> STRING;` statements (skip when the column already exists).
3. Run [`silver/schemas/court_charge.sql`](../schemas/court_charge.sql).
4. Run [`silver/schemas/court_party.sql`](../schemas/court_party.sql).
5. Confirm `us_criminal_bg.silver.court_case`, `us_criminal_bg.silver.court_charge`, `us_criminal_bg.silver.court_party`, and `us_criminal_bg.silver.transform_run` exist.
6. For the SF name-only experiment, run [`silver/schemas/match_decision.sql`](../schemas/match_decision.sql). Confirm `us_criminal_bg.silver.match_decision` exists. See [`docs/silver/SF_MATCH_EXPERIMENT.md`](../../docs/silver/SF_MATCH_EXPERIMENT.md).

Non-secret workspace notes (same as Bronze): host `dbc-a0dcbe75-2647.cloud.databricks.com`, workspace id `7474648418210162`. Auth stays in the Databricks CLI profile / workspace — never commit `.databrickscfg` or tokens.

Optional env (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (Bronze loader used warehouse `e40cabf0355df274`).

## Run the transform

Both paths materialize `transform_run_id` once into `us_criminal_bg.silver._this_transform_run` (Delta scratch) and finalize with `status='running' AND transform_run_id IN (SELECT … FROM _this_transform_run)`, then drop the scratch table.

### A. Spark SQL warehouse (SSR regex)

Run [`silver/transforms/court_case.sql`](../transforms/court_case.sql).

- Parses `source_record_id` and URL `countyNo` / `caseNo`.
- Strips scripts/styles/tags from `payload` and regex-extracts caption, filing date, case status, county name, charge cores, and party cores (plaintiff / defendant / aka).
- `modifier_statute` / `modifier_text` are left **null** in SQL (use the Python job for modifiers).
- `MERGE` `court_case` on `(source_system, state_code, source_record_id)`.
- `MERGE` `court_charge` on that key plus `charge_count`; deletes stale counts for cases in the run.
- `MERGE` `court_party` on that key plus `(party_role, party_ordinal)`; deletes stale role+ordinals for cases in the run.
- Inserts one `transform_run` row per attempt (`running` → `succeeded`). `row_count` is `court_case` rows for that run id.

### B. Python parser on a Databricks cluster (complete SSR, including modifiers)

```bash
python3 silver/transforms/court_case.py --apply
```

Requires a Spark session (Databricks cluster / notebook with repo on `sys.path`). Uses `sources/wcca/parse.py` so HTML SSR and structured `application/json` script tags fill Silver; charge `Modifier:` lines populate `modifier_*`; party labeled DOB/sex/address and aka lines populate `court_party`.

Prefer this path for `html_ssr_v1` on live WCCA snapshots.

### C. SF HF research parties only (does not touch WI)

Research-only. Reads `source_system='sf_criminal_hf'` / `state_code='CA'` Bronze JSON and MERGE `court_party` defendant rows. **DELETE is scoped to those keys** so existing `wcca` / `WI` parties are not removed. Does not write `court_case` / `court_charge`. See [`docs/silver/SF_RESEARCH.md`](../../docs/silver/SF_RESEARCH.md).

SQL warehouse: [`silver/transforms/court_party_sf_criminal_hf.sql`](../transforms/court_party_sf_criminal_hf.sql). Warehouse apply is statement-at-a-time (`/api/2.0/sql/statements`), so that script uses durable Delta scratch tables (`_sf_party_cases`, `_sf_party_staged`) rather than TEMP VIEW.

```bash
python3 silver/transforms/court_party_sf_criminal_hf.py --apply
```

Do **not** use the WCCA `court_case.sql` / `court_case.py` job to refresh SF parties (that job still ranks all Bronze sources and could delete SF keys as `unsupported_source`).

### D. SF name-only match suggestions (research; does not touch WI)

Research-only. Scores a **small** subject table against `court_party` where `source_system='sf_criminal_hf'` / `state_code='CA'`, joining on **normalized last name** (not a 77k cartesian). APPENDS `actor='system:suggestion'` rows to `match_decision`. SF parties have no DOB → **`review` / `dob_absent`, never `auto`**. Not CRA / adverse action. See [`docs/silver/SF_MATCH_EXPERIMENT.md`](../../docs/silver/SF_MATCH_EXPERIMENT.md).

SQL warehouse: [`silver/transforms/match_decision_sf_research.sql`](../transforms/match_decision_sf_research.sql). Coordinator loads N subjects into `us_criminal_bg.silver._match_subject_sf_research` first.

```bash
python3 silver/transforms/match_decision_sf_research.py --apply
```

## Idempotency

| Table | Re-run behavior |
|-------|-----------------|
| `silver.court_case` | Upsert on `(source_system, state_code, source_record_id)` |
| `silver.court_charge` | Upsert on `(source_system, state_code, source_record_id, charge_count)`; extra counts for processed cases are deleted |
| `silver.court_party` | Upsert on `(source_system, state_code, source_record_id, party_role, party_ordinal)`; extra role+ordinals for processed cases are deleted |
| `silver.transform_run` | Always append a new attempt row |
| `silver.match_decision` | Always append (suggestion or human). Never MERGE / UPDATE / DELETE |

Business attributes for a given Bronze key converge; `transformed_at` / `transform_run_id` change each run (type-1 current row metadata).

## Out of scope

Person matching as a hire engine, FCRA, Gold, scraping WCCA, writing Bronze. Review-queue bands (no silent auto-link) are [`docs/silver/MATCH_REVIEW.md`](../../docs/silver/MATCH_REVIEW.md). SF name-only research job: [`docs/silver/SF_MATCH_EXPERIMENT.md`](../../docs/silver/SF_MATCH_EXPERIMENT.md).
