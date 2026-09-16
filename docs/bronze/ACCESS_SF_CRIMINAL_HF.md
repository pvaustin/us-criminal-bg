# San Francisco — Hugging Face `sf_criminal_court` (research notes)

**Status:** Research-only named corpus. **Live Bronze load complete (2026-09-16).** **Not** employer product. **Not** for commercial CRA / FCRA claims. **Isolated from the WI WCCA product path.** CC-BY-NC-4.0 (non-commercial).

Third-party Hugging Face redistribution of public San Francisco Superior Court scrapes plus open DA feeds. **Not** an official bulk license from the Court or the City/County of San Francisco. Loader downloads the **published** `cases.parquet` only — it does **not** scrape court websites.

## Provenance

- **Dataset:** https://huggingface.co/datasets/cfahlgren1/sf_criminal_court
- **Publisher on HF:** `cfahlgren1` (not this repo)
- **What it is:** Linked SF County criminal-court tables. Card states `cases` / `calendar` / `attorneys` / `register_of_actions` were scraped from public SF Superior Court criminal case pages; `da_arrests` and `da_prosecuted` come from SF DA open-data feeds; charge-disposition files are derived from a rule 10.500 spreadsheet (anonymized Court IDs, later matched).
- **License:** [CC-BY-NC-4.0](https://huggingface.co/datasets/cfahlgren1/sf_criminal_court) — non-commercial use only. Do not use this corpus for employer screening, CRA reports, or other commercial claims.
- **This spike lands:** `cases.parquet` only (77,406 rows). Other parquet files on the dataset card are **out of scope** for the Bronze name-match experiment.

Hard rule: **published Hugging Face files only.** Do **not** scrape SF Superior Court or DA websites. Do **not** invent records. Do **not** load Cook County. Do **not** load anonymized Virginia public CSVs.

## Identifiers

| Identifier | Value |
|------------|--------|
| `source_system` | `sf_criminal_hf` |
| `state_code` | `CA` |
| `extract_method` | `rest_bulk` — published parquet download from Hugging Face, **not** a court scrape |
| `source_record_id` | `sf_case:{case_id}` (landed grain). If `case_id` is missing, `sf_case:{case_number}`. |

Dedupe Bronze on `(source_system, state_code, source_record_id)`. Documented in [`NAMING.md`](NAMING.md).

Volume layout (NAMING contract):

```
/Volumes/us_criminal_bg/bronze/court_source/
  state_code=CA/source_system=sf_criminal_hf/ingest_date=<YYYY-MM-DD>/ingest_run_id=<id>/
    cases.parquet
```

CLI `databricks fs` paths must be `dbfs:/Volumes/...` (bare `/Volumes` is local to the CLI).

## Field inventory — `cases.parquet` (named; usable for `court_party` experiments)

Verified from the Hugging Face dataset card + the 2026-09-16 Bronze load. Card wording is “filing date”; the parquet column is `filed_date`.

| Field | Type (HF) | Notes |
|-------|-----------|--------|
| `case_number` | string | Public SF Superior Court case number (e.g. `CRI…` shape) |
| `case_id` | int64 | Court case id; used in `source_record_id` = `sf_case:{case_id}` |
| `defendant_name` | string | **Present.** Named field for `court_party` / name-match experiments. Preserve in Bronze `payload` JSON. Do not drop. Nonempty **77,399 / 77,406** on the live load. |
| `filed_date` | string | File date; may be null |
| `scraped_at` | string | Third-party scrape timestamp; lineage of the HF file, not an official Court export time |

Bronze `payload` is JSON of those five parquet columns **plus** load-time locality stamps (not in the parquet file):

| Extra payload key | Value | Why |
|-------------------|--------|-----|
| `county` | `San Francisco` | Locality for `court_party` experiments |
| `locality` | `SF` | Short locality code |

`payload_format` = `json`.

This file is a **named** corpus (unlike virginiacourtdata.org public CSVs). It is still **research-only** and CC-BY-NC.

Other dataset tables (not loaded here): register of actions, attorneys, calendar, DA arrest/prosecuted feeds, rule 10.500 match/disposition files, judicial assignment dimensions. See the HF card.

## Live Bronze proof (2026-09-16)

Full `cases.parquet` landed in one run. **No Free Edition batching needed.**

| Item | Verified value |
|------|----------------|
| `source_system` | `sf_criminal_hf` |
| `state_code` | `CA` |
| `ingest_run_id` | `26a31a80-a06f-4870-ab9e-cda5db38f47f` |
| Volume file | `/Volumes/us_criminal_bg/bronze/court_source/state_code=CA/source_system=sf_criminal_hf/ingest_date=2026-09-16/ingest_run_id=26a31a80-a06f-4870-ab9e-cda5db38f47f/cases.parquet` |
| `court_case_raw` rows | **77,406** (full file) |
| Parquet fields | `case_number`, `case_id`, `defendant_name`, `filed_date`, `scraped_at` |
| `defendant_name` nonempty | **77,399 / 77,406** |
| `source_record_id` | `sf_case:{case_id}` |
| Payload | JSON preserves `defendant_name`; `county=San Francisco`; `locality=SF` |

Isolation counts **after** this load (WI path untouched; Cook not loaded):

| `source_system` | `state_code` | `court_case_raw` rows |
|-----------------|--------------|------------------------|
| `sf_criminal_hf` | `CA` | 77,406 |
| `wcca` | `WI` | 1 |
| `cook_sao_open` | — | 0 |

## Loader

[`bronze/jobs/load_sf_criminal_hf.py`](../../bronze/jobs/load_sf_criminal_hf.py) downloads published `cases.parquet`, copies it to the UC volume, and INSERTs `ingest_run` + MERGE `court_case_raw`. Mapping helpers: [`sources/sf_criminal_hf/map.py`](../../sources/sf_criminal_hf/map.py).

- Env-overridable profile / warehouse (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (same defaults as the WCCA `manual_upload` CLI).
- No tokens, cookies, or parquet files in git.
- Does not touch `source_system=wcca` / `state_code=WI` rows.
- Re-run MERGE key is `(source_system, state_code, source_record_id)` with `source_record_id=sf_case:{case_id}`.

## Status

- Named `court_party` research corpus **is landed** (proof above). **Isolate from WI employer MVP** (WCCA CAPTCHA / manual_upload / paid REST unchanged).
- VA named export remains a separate gated path ([`ACCESS_VA_COURT_DATA.md`](ACCESS_VA_COURT_DATA.md)); Prasanth requests that account; **no** anonymized VA load.
- Cook County is **out of scope** (`cook_sao_open` row count 0 after this load).
