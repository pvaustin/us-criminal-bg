# Silver naming and layout (national-first)

**Owner:** silva silver  
**Upstream:** brian bronze (`docs/bronze/NAMING.md`)  
**Repo:** https://github.com/pvaustin/us-criminal-bg  
**Databricks workspace (non-secret):** `dbc-a0dcbe75-2647.cloud.databricks.com` (workspace ID `7474648418210162`)

This doc is the durable contract for Silver identifiers and transforms. It **mirrors** Bronze national-first principles: state is a **dimension / module**, never the top-level product prefix. Silver **reads** Bronze; it never writes Bronze.

HTML snapshot parseability (what SSR text can and cannot fill) is documented in [`docs/silver/WCCA_HTML_SSR.md`](WCCA_HTML_SSR.md).

## Principles

1. **National-first.** Catalogs, schemas, top-level repo folders, and job names describe the US court-source product. Do not make `wi` (or any state) the only top-level product prefix. No `wi_*` product tables, catalogs, or schemas.
2. **State as dimension.** Persist `state_code` (ISO-3166-2 subdivision without country, e.g. `WI`). Source-specific parsers live under `sources/<source_id>/` (MVP: `sources/wcca/parse.py`).
3. **Analytics-ready, not matched.** Silver cleanses and types Bronze payloads into current-row case facts plus lineage. No person-matching, hire/no-hire, FCRA packages, or Gold.
4. **Do not invent court facts.** Fill a column only from identifiers, URL query params, explicit JSON keys, or the documented WCCA HTML SSR regexes in `docs/silver/WCCA_HTML_SSR.md`. If a field is not clearly present, store `NULL` and set `dq_flags` / an honest `payload_parse_status`. Unrelated page chrome (home titles, script bundles) is not a caption.
5. **Idempotent transforms.** Re-running the same Bronze keys must converge on one Silver case row and the current set of charge rows (type-1 overwrite). `transform_run` always **appends**.
6. **Never scrape.** Transforms consume already-landed Bronze rows only. No HTTP to WCCA or any court site.

## Unity Catalog / object names

| Layer | Name | Notes |
|-------|------|--------|
| Catalog | `us_criminal_bg` | Same product catalog as Bronze |
| Schema | `silver` | All Silver tables |
| Volume | *(none for MVP)* | Payloads stay in Bronze / `us_criminal_bg.bronze.court_source` |

Do **not** create `wi_*` catalogs/schemas. Wisconsin appears only as `state_code = 'WI'` and in source/module paths (`sources/wcca/`, `states/wi/`).

### Tables

| Table | Purpose |
|-------|---------|
| `us_criminal_bg.silver.court_case` | One **current** analytics-ready case row per natural key |
| `us_criminal_bg.silver.court_charge` | One **current** charge row per case count number |
| `us_criminal_bg.silver.transform_run` | One row per Silver transform **attempt** (success or failure) |

Person entities, events, and match keys remain out of scope. Charges are in because WCCA HTML SSR exposes a stable count/statute/description/severity grid.

## Natural keys and SCD

### `court_case`

- **Natural key:** `(source_system, state_code, source_record_id)` — same grain as Bronze `court_case_raw` dedupe.
- **SCD:** Type-1 overwrite. MVP does **not** keep Silver history. Re-ingest of the same key replaces attributes and lineage pointers (`ingest_run_id`, `payload_sha256`, …). Bronze remains the payload archive.
- **Bronze duplicates:** If multiple `court_case_raw` rows share the natural key (loader used INSERT), Silver takes `ingested_at DESC` (then `ingest_run_id DESC`) as current.
- **`ingest_run` join:** Left-join `us_criminal_bg.bronze.ingest_run`. Rows whose ingest `status` is present and not `succeeded` are skipped. Missing `ingest_run` metadata does **not** block the case row.

### `court_charge`

- **Natural key:** `(source_system, state_code, source_record_id, charge_count)` — type-1 MERGE.
- `charge_count` is the source **Count no.** (not a dense array index).
- Re-running a case replaces matching counts and **deletes** counts that disappeared for that case in the current Bronze payload.
- Lineage columns (`ingest_run_id`, `ingested_at`, `payload_sha256`, `transform_run_id`) match the parent case row used for the run.

### `transform_run`

- **Identity:** `transform_run_id` (UUID string) generated at job start and materialized once into `us_criminal_bg.silver._this_transform_run` (1-row Delta scratch; dropped at end of job).
- **Human label:** `{source_system_or_all}_{state_code_or_all}_{YYYYMMDD}_{HHMMSS}Z` — logs only, not a join key.
- Always **append**. Never upsert transform runs.
- `row_count` is the number of `court_case` rows stamped with this `transform_run_id`.

## Lineage (Bronze → Silver)

Reserved Bronze columns from `docs/bronze/NAMING.md` map as follows. Raw **`payload` is not copied** into Silver: it is not analytics-ready and can be large HTML. Join back to Bronze with `(source_system, state_code, source_record_id)` and/or `ingest_run_id` + `payload_sha256`.

| Bronze column | Silver `court_case` column | Preserved? | Notes |
|---------------|----------------------------|------------|--------|
| `ingest_run_id` | `ingest_run_id` | yes | FK-ish to `bronze.ingest_run` (current Bronze row used) |
| `ingested_at` | `ingested_at` | yes | Bronze row write time (not Silver transform time) |
| `state_code` | `state_code` | yes | Part of natural key |
| `source_system` | `source_system` | yes | Part of natural key |
| `source_record_id` | `source_record_id` | yes | Part of natural key |
| `source_url` | `source_url` | yes | |
| `payload_format` | `payload_format` | yes | |
| `payload` | *(omitted)* | no | Stays in `bronze.court_case_raw`; parsed then dropped |
| `payload_sha256` | `payload_sha256` | yes | Integrity / join-back to payload |
| `extract_method` | `extract_method` | yes | |
| `schema_version` | `bronze_schema_version` | yes | Renamed so it does not collide with `silver_schema_version` |

Silver-owned `court_case` columns:

| Column | Type (logical) | Meaning |
|--------|----------------|---------|
| `county_code` | string null | Source county identifier (WCCA: `countyNo`) |
| `county_name` | string null | From SSR title `{caseNo} Case Details in {County} County` only |
| `case_number` | string null | Source case number (WCCA: `caseNo`) |
| `case_type` | string null | **Identifier-derived** CCAP two-letter code when `case_number` matches `YYYYTTNNNNNN` (e.g. `CF` from `2026CF000028`). Not the SSR label `Case type Criminal`. Null if the pattern does not match. |
| `filed_date` | date null | JSON `filedDate` / `filingDate` / `dateFiled`, or SSR `Filing date MM-DD-YYYY` |
| `caption` | string null | JSON `caption` / `caseCaption`, or SSR `State of Wisconsin vs. {Name}` |
| `case_status` | string null | SSR `Case status {text}` |
| `payload_parse_status` | string | See status vocabulary below |
| `dq_flags` | array\<string\> | Sorted, deterministic flag names; empty array if clean |
| `silver_schema_version` | string | e.g. `silver.court_case.v2` |
| `transformed_at` | timestamp (UTC) | Silver write time |
| `transform_run_id` | string | FK-ish to `silver.transform_run` |

Silver-owned `court_charge` columns:

| Column | Type (logical) | Meaning |
|--------|----------------|---------|
| `charge_count` | int | Source count number (MERGE key part) |
| `statute` | string null | Statute token from the charges grid |
| `description` | string null | Offense description |
| `severity` | string null | e.g. `Felony`, `Misdemeanor A` |
| `modifier_statute` | string null | From `Modifier: {statute} {text}` (Python path; SQL leaves null) |
| `modifier_text` | string null | Remainder of the Modifier line |
| `silver_schema_version` | string | `silver.court_charge.v1` |

### `payload_parse_status` vocabulary

| Value | When |
|-------|------|
| `html_ssr_v1` | Caption **and** filed_date **and** ≥1 charge parsed from HTML SSR (and/or JSON caption/date plus SSR charges) |
| `html_ssr_partial` | Some SSR fields parsed, but not the full caption + filed_date + ≥1 charge trio |
| `structured_facts` | At least one of `filed_date` / `caption` taken from a structured JSON embed or `payload_format=json` object, and no SSR case text |
| `identifiers_only` | County / case number parsed from `source_record_id` and/or URL; no structured or SSR case facts from payload |
| `identifier_error` | Natural identifiers could not be parsed |
| `unsupported_source` | No Silver parser for `source_system` (national-first passthrough: keys + lineage, facts null) |

### `dq_flags` vocabulary

| Flag | Meaning |
|------|---------|
| `case_number_unparsed` | Could not obtain `case_number` |
| `case_type_unparsed` | `case_number` present but not `YYYYTTNNNNNN` |
| `county_code_unparsed` | Could not obtain `county_code` |
| `identifier_url_mismatch` | URL `countyNo`/`caseNo` disagree with `source_record_id` (after light normalization) |
| `invalid_county_code` | WCCA county token is not numeric |
| `missing_caption` | `caption` is null |
| `missing_charges` | HTML SSR case text was found but zero charge rows parsed |
| `missing_filed_date` | `filed_date` is null |
| `missing_source_url` | Bronze `source_url` is null/blank |
| `unparsed_html_spa` | `payload_format=html_snapshot` and no SSR case text and no recognized structured JSON case object |
| `unsupported_source_parser` | `source_system` other than `wcca` |

Flags are **omitted** when they do not apply (successful caption parse does not carry `missing_caption`; JSON-only payloads do not get `unparsed_html_spa`).

## WCCA identifier + SSR contract (WI MVP)

Live Bronze sample (workspace proof; **not** a fixture of defendant identity):

- `source_system=wcca`, `state_code=WI`
- `source_record_id=51:2026CF000028` → `{countyNo}:{caseNo}`
- `source_url` query params `countyNo` and `caseNo` are reliable structured inputs
- `payload_format=html_snapshot` with **server-rendered** title, caption, filing date, status, and charges grid — not an empty SPA shell

Parser input precedence (`sources/wcca/parse.py`):

1. Parse `source_record_id` (`countyNo:caseNo` **or** Bronze composed form `WI|wcca|{county}|{case_number}`).
2. Parse URL query `countyNo` / `caseNo`.
3. If both parsed and they **disagree**, set `identifier_url_mismatch` and **prefer URL params** (explicitly documented as reliable).
4. Payload: structured JSON embeds when present; otherwise / in addition, HTML SSR regex after stripping scripts/styles/tags. No live fetch. No invented fields.

Expected Silver attributes for that live Bronze grain after this parser (no defendant PII in this contract):

| Field | Expected |
|-------|----------|
| `county_code` | `51` |
| `case_number` | `2026CF000028` |
| `case_type` | `CF` |
| `county_name` | present from title pattern `{caseNo} Case Details in {County} County` |
| `caption` | present (`State of Wisconsin vs. …`) |
| `filed_date` | `YYYY-MM-DD` from the `Filing date` label (live snapshot uses `MM-DD-YYYY`) |
| `case_status` | present from the `Case status` label |
| `payload_parse_status` | `html_ssr_v1` when caption + filed_date + ≥1 charge succeed |
| `court_charge` | N rows keyed by source count number (statute / description / severity; optional modifier on Python path) |
| DQ | `missing_caption` / `missing_filed_date` / `unparsed_html_spa` omitted when those fields parse |

## DQ rules (row-level)

1. Natural-key columns are NOT NULL (inherited from Bronze; `charge_count` NOT NULL on `court_charge`).
2. `dq_flags` is NOT NULL (use `array()` empty, never SQL `NULL`).
3. Missing facts → null column + flag; do not default dates, names, or charges.
4. `case_type` may be filled from the case-number pattern without lifting `payload_parse_status` by itself (it is not a payload fact).
5. Transforms must not UPDATE/INSERT/DELETE `us_criminal_bg.bronze.*`.

## Repo layout (national-first)

```
docs/
  bronze/NAMING.md
  silver/NAMING.md          ← this file (contract)
  silver/WCCA_HTML_SSR.md   ← what HTML snapshots can/cannot fill
sources/
  wcca/parse.py             ← WI WCCA identifier / URL / SSR / JSON parser
  wcca/tests/               ← synthetic fixtures; never claimed as real court records
silver/
  schemas/                  ← Unity Catalog DDL (court_case, court_charge, transform_run)
  transforms/               ← Spark SQL + Python MERGE
  jobs/README.md            ← how to run
```

## Out of scope (do not put in Silver)

- Person matching, defendant graphs, hire/no-hire, FCRA adverse-action packages, Gold marts
- Invented or hallucinated court records; county-name lookup tables that can be wrong
- Secrets, PATs, cookies, CAPTCHA tokens in git or chat
- Scraping WCCA or mutating Bronze
- Databricks apply of DDL/transform by the cloud agent that opened this PR (operator applies in-workspace)

## Versioning

Bump `silver_schema_version` when Silver columns or parse-status/flag vocabularies change. Append a short changelog section below.

### Changelog

- `2026-09-16` — `silver.court_case.v2` + `silver.court_charge.v1`: HTML SSR parser for caption / filed_date / case_status / county_name / charges; statuses `html_ssr_v1` and `html_ssr_partial`.
- `2026-09-15` — Initial national-first Silver contract (MVP: `court_case` + `transform_run`, WCCA identifiers).
