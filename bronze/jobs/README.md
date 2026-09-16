# Bronze jobs

Weekly WCCA → Bronze job stub lives here once Databricks Jobs / notebooks are wired.

Proposed cadence: weekly. Orchestration may be a Grok Bot routine — **paused until Prasanth explicitly enables**.

Job responsibilities:
1. Create `ingest_run` row (status=running)
2. Land files under the volume path from `docs/bronze/NAMING.md`
3. Upsert `court_case_raw` on `(source_system, state_code, source_record_id)`
4. Finalize `ingest_run` (status + row_count)

No CAPTCHA bypass. Prefer `manual_upload` / `interactive_export` until paid REST is subscribed.

## `manual_upload` CLI (`load_one_case.py`)

Copies one local HTML export into the Unity Catalog volume and INSERTs `ingest_run` + `court_case_raw` via the Databricks SQL API.

This is **CAPTCHA / `manual_upload` only**. It does **not** scrape WCCA. A human exports the page, then this CLI lands it.

```bash
python3 bronze/jobs/load_one_case.py /path/to/export.html \
  --source-url 'https://wcca.wicourts.gov/...' \
  --source-record-id 'WI|wcca|{county}|{case_number}'
```

Defaults (env-overridable, not secrets):

| Env | Default |
|-----|---------|
| `DATABRICKS_CONFIG_PROFILE` | `WCCA_BRONZE` |
| `DATABRICKS_WAREHOUSE_ID` | `e40cabf0355df274` |

`databricks fs mkdir` / `cp` use `dbfs:/Volumes/...` (a bare `/Volumes` path is treated as local). Auth is the CLI profile — do not commit `.databrickscfg`, tokens, or real case HTML.

## `rest_bulk` research CLI (`load_sf_criminal_hf.py`)

Downloads the published Hugging Face `cases.parquet` (SF named corpus) into the UC volume and MERGE `court_case_raw`. **Research-only**, isolated from WI. Does **not** scrape courts, does **not** load Virginia anonymized CSVs, does **not** load Cook County.

```bash
python3 bronze/jobs/load_sf_criminal_hf.py --dry-run
python3 bronze/jobs/load_sf_criminal_hf.py
python3 bronze/jobs/load_sf_criminal_hf.py --limit 50
```

Same env defaults as the WCCA CLI (`DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID`). Do not commit parquet files. See [`docs/bronze/ACCESS_SF_CRIMINAL_HF.md`](../../docs/bronze/ACCESS_SF_CRIMINAL_HF.md).
