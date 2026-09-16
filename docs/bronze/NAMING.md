# Bronze naming and layout (national-first)

**Owner:** brian bronze  
**Consumers:** silva silver (and later Gold)  
**Repo:** https://github.com/pvaustin/us-criminal-bg  
**Databricks workspace (non-secret):** `dbc-a0dcbe75-2647.cloud.databricks.com` (workspace ID `7474648418210162`)

This doc is the durable contract for Bronze identifiers. State is a **dimension / module**, never the top-level product prefix.

## Principles

1. **National-first.** Catalogs, schemas, top-level repo folders, and job names describe the US court-source product. Do not make `wi` (or any state) the only top-level product prefix.
2. **State as dimension.** Persist `state_code` (ISO-3166-2 subdivision without country, e.g. `WI`). State-specific adapters live under `states/<state_code_lower>/` and/or `sources/<source_id>/`.
3. **Raw / near-raw only.** Bronze lands source payloads plus lineage. No Silver cleanses, match scores, or FCRA outputs here.
4. **Idempotent weekly runs.** Re-running the same logical extract must converge (same keys overwrite or skip; run metadata always appends).

## Unity Catalog / object names

| Layer | Name | Notes |
|-------|------|--------|
| Catalog | `us_criminal_bg` | Product catalog (create if missing) |
| Schema | `bronze` | All Bronze tables / volumes |
| Volume (optional file landing) | `us_criminal_bg.bronze.court_source` | Path layout below |

### Tables (MVP)

| Table | Purpose |
|-------|---------|
| `us_criminal_bg.bronze.court_case_raw` | One row per extracted case payload (or search-hit payload) |
| `us_criminal_bg.bronze.ingest_run` | One row per ingest attempt (success or controlled failure) |
| `us_criminal_bg.bronze.source_snapshot_file` | Optional: file-oriented landing index when payloads are stored as objects |

Do **not** create `wi_*` catalogs/schemas. Wisconsin appears only as `state_code = 'WI'` and in source/module paths.

### Volume / object path layout

```
/Volumes/us_criminal_bg/bronze/court_source/
  state_code=<ST>/
    source_system=<source_id>/
      ingest_date=<YYYY-MM-DD>/
        ingest_run_id=<id>/
          *.json
```

Example: `.../state_code=WI/source_system=wcca/ingest_date=2026-09-15/ingest_run_id=.../case_....json`

## Source systems

| `source_system` | State(s) | Access mode (MVP) | Scale path |
|-----------------|----------|-------------------|------------|
| `wcca` | WI | Low-volume interactive / manual export from https://wcca.wicourts.gov/ — CAPTCHA expected; **do not bypass** | Paid WCCA REST bulk subscription (~$12,500/yr CCAP agreement) — document only until subscribed |

Other states: architecture multi-state-ready; **no live scrape targets** until product expands scope.

## `ingest_run` identity

- **`ingest_run_id`**: ULID or UUID string generated at job start (stable for the whole run).
- **Human label** (optional column `ingest_run_label`): `{source_system}_{state_code}_{YYYYMMDD}_{HHMMSS}Z` for logs only — not a join key.
- Partition / filter columns for ops: `state_code`, `source_system`, `ingest_date` (UTC date of run start).

## Reserved lineage columns (Silver must preserve / may join on)

Every Bronze payload table includes at least:

| Column | Type (logical) | Meaning |
|--------|----------------|---------|
| `ingest_run_id` | string | FK-ish to `ingest_run` |
| `ingested_at` | timestamp (UTC) | Row write time |
| `state_code` | string | e.g. `WI` |
| `source_system` | string | e.g. `wcca` |
| `source_record_id` | string | Best-effort native id from source when present; else deterministic hash of natural key fields |
| `source_url` | string null | Request URL or UI deep link if known |
| `payload_format` | string | e.g. `json`, `html_snapshot` |
| `payload` | string / variant | Raw / near-raw body |
| `payload_sha256` | string | Hex digest of canonical payload bytes |
| `extract_method` | string | `interactive_export` \| `manual_upload` \| `rest_bulk` (future) |
| `schema_version` | string | Bronze contract version, e.g. `bronze.court_case_raw.v1` |

### Natural keys (WI / WCCA MVP)

When available from the source hit/detail:

- Prefer `source_record_id` = stable WCCA case identifier if exposed.
- Else compose: `WI|wcca|{county_code_or_name}|{case_number}` (document exact composition in `sources/wcca/` when first real sample lands).

**Dedupe for Bronze load:** unique on `(source_system, state_code, source_record_id)` within a merge/upsert; always append a new `ingest_run` row. Do not invent SCD2 on Bronze — that is Silver’s concern if needed.

## Repo layout (national-first)

```
docs/
  bronze/
    NAMING.md          ← this file (contract)
    ACCESS.md          ← source access modes, ToS, paid REST notes
sources/
  wcca/                ← WI WCCA adapter + sample fixtures (no secrets)
states/
  wi/                  ← thin WI module notes / county lists if needed
bronze/
  schemas/             ← table DDLs / Spark schema stubs
  jobs/                ← weekly ingest job/notebook stubs
  fixtures/            ← synthetic or redacted shape samples only (never fabricated court facts claimed as real)
```

## Out of scope (do not put in Bronze)

- Silver transforms, person matching, hire/no-hire, FCRA adverse-action packages
- Invented or hallucinated court records
- Secrets, PATs, cookies, CAPTCHA tokens in git or chat

## Versioning

Bump `schema_version` when reserved columns or payload envelope change. Append a short changelog section below.

### Changelog

- `2026-09-15` — Initial national-first contract (MVP: WCCA → Bronze).
