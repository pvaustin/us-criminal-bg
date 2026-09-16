# San Francisco — Hugging Face `sf_criminal_court` (research notes)

**Status:** Research-only named corpus. **Not** employer product. **Not** for commercial CRA / FCRA claims. **Isolated from the WI WCCA product path.** CC-BY-NC-4.0 (non-commercial).

Third-party Hugging Face redistribution of public San Francisco Superior Court scrapes plus open DA feeds. **Not** an official bulk license from the Court or the City/County of San Francisco. Loader downloads the **published** `cases.parquet` only — it does **not** scrape court websites.

## Provenance

- **Dataset:** https://huggingface.co/datasets/cfahlgren1/sf_criminal_court
- **Publisher on HF:** `cfahlgren1` (not this repo)
- **What it is:** Linked SF County criminal-court tables. Card states `cases` / `calendar` / `attorneys` / `register_of_actions` were scraped from public SF Superior Court criminal case pages; `da_arrests` and `da_prosecuted` come from SF DA open-data feeds; charge-disposition files are derived from a rule 10.500 spreadsheet (anonymized Court IDs, later matched).
- **License:** [CC-BY-NC-4.0](https://huggingface.co/datasets/cfahlgren1/sf_criminal_court) — non-commercial use only. Do not use this corpus for employer screening, CRA reports, or other commercial claims.
- **This spike lands:** `cases.parquet` only (~77,406 rows). Other parquet files on the dataset card are **out of scope** for the Bronze name-match experiment.

Hard rule: **published Hugging Face files only.** Do **not** scrape SF Superior Court or DA websites. Do **not** invent records. Do **not** load Cook County. Do **not** load anonymized Virginia public CSVs.

## Identifiers

| Identifier | Value |
|------------|--------|
| `source_system` | `sf_criminal_hf` |
| `state_code` | `CA` |
| `extract_method` | `rest_bulk` — published parquet download from Hugging Face, **not** a court scrape |

**`source_record_id`:** prefer `case_id` (stringified) when present; else `case_number`. Documented in [`NAMING.md`](NAMING.md). Dedupe Bronze on `(source_system, state_code, source_record_id)`.

Volume layout (NAMING contract):

```
/Volumes/us_criminal_bg/bronze/court_source/
  state_code=CA/source_system=sf_criminal_hf/ingest_date=<YYYY-MM-DD>/ingest_run_id=<id>/
    cases.parquet
```

CLI `databricks fs` paths must be `dbfs:/Volumes/...` (bare `/Volumes` is local to the CLI).

## Field inventory — `cases.parquet` (named; usable for `court_party` experiments)

Verified from the Hugging Face dataset card + datasets-server `cases` config (~77,406 rows). Card wording is “filing date”; the parquet column is `filed_date`.

| Field | Type (HF) | Notes |
|-------|-----------|--------|
| `case_number` | string | Public SF Superior Court case number (e.g. `CRI…` shape) |
| `case_id` | int64 | Court case id; preferred `source_record_id` |
| `defendant_name` | string | **Present.** This is the named field for `court_party` / name-match experiments. Preserve in Bronze `payload` JSON. Do not drop. |
| `filed_date` | string | File date; may be null |
| `scraped_at` | string | Third-party scrape timestamp; lineage of the HF file, not an official Court export time |

Bronze `payload` is JSON of those five columns (near-raw row). `payload_format` = `json`.

This file is a **named** corpus (unlike virginiacourtdata.org public CSVs). It is still **research-only** and CC-BY-NC.

Other dataset tables (not loaded here): register of actions, attorneys, calendar, DA arrest/prosecuted feeds, rule 10.500 match/disposition files, judicial assignment dimensions. See the HF card.

## Loader

[`bronze/jobs/load_sf_criminal_hf.py`](../../bronze/jobs/load_sf_criminal_hf.py) downloads published `cases.parquet`, copies it to the UC volume, and INSERTs `ingest_run` + MERGE `court_case_raw`. Mapping helpers: [`sources/sf_criminal_hf/map.py`](../../sources/sf_criminal_hf/map.py).

- Env-overridable profile / warehouse (not secrets): `DATABRICKS_CONFIG_PROFILE`, `DATABRICKS_WAREHOUSE_ID` (same defaults as the WCCA `manual_upload` CLI).
- No tokens, cookies, or parquet files in git.
- Does not touch `source_system=wcca` / `state_code=WI` rows.

## Status

- Research spike for named `court_party` experiments. **Isolate from WI employer MVP** (WCCA CAPTCHA / manual_upload / paid REST unchanged).
- VA named export remains a separate gated path ([`ACCESS_VA_COURT_DATA.md`](ACCESS_VA_COURT_DATA.md)); Prasanth requests that account; **no** anonymized VA load.
- Cook County is **out of scope**.
