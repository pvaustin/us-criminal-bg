# SF HF research → `silver.court_party` (experiment-only)

**Owner:** silva silver  
**Source:** `source_system=sf_criminal_hf`, `state_code=CA`  
**Bronze:** already landed `us_criminal_bg.bronze.court_case_raw` (do not scrape)  
**Silver table:** `us_criminal_bg.silver.court_party` (same table as WI; different MERGE keys)  
**Parser:** [`sources/sf_criminal_hf/parse_party.py`](../../sources/sf_criminal_hf/parse_party.py)  
**Transforms:** [`silver/transforms/court_party_sf_criminal_hf.sql`](../../silver/transforms/court_party_sf_criminal_hf.sql) and [`court_party_sf_criminal_hf.py`](../../silver/transforms/court_party_sf_criminal_hf.py)  
**Bronze access:** [`docs/bronze/ACCESS_SF_CRIMINAL_HF.md`](../bronze/ACCESS_SF_CRIMINAL_HF.md)

This is a **research-only** sketch so name-match experiments can read defendant `raw_name` / name parts from the Hugging Face `cases.parquet` corpus that Bronze already stores. It is **not** the Wisconsin employer product path. Do not mix these rows into hire / FCRA / adverse-action copy. CC-BY-NC-4.0 on the upstream dataset — not commercial CRA use.

Warehouse apply is **coordinator-side**. This repo lands parser + SQL/Python + tests; it does not run Databricks.

## Non-goals (explicit)

| Out of scope | Why |
|--------------|-----|
| WI WCCA Silver path | `sources/wcca/*` and `silver/transforms/court_case.*` stay untouched |
| Invented parties | Blank `defendant_name` → **no row** (not a synthetic name) |
| Hire / no-hire, adverse-action UI | Research experiments only |
| `match_decision` table | Named in MATCH_REVIEW; **not created** |
| `court_case` / `court_charge` for SF | Isolated party sketch; not required for this path |
| Court scrape | Consume Bronze JSON only |
| Live PII in git | Identifier-only live grain; synthetic names in tests |

## Corpus (identifier-only live grain)

Verified Bronze load 2026-09-16 (no live full names / DOB / street in this doc):

| Item | Value |
|------|--------|
| `source_system` | `sf_criminal_hf` |
| `state_code` | `CA` |
| `ingest_run_id` | `26a31a80-a06f-4870-ab9e-cda5db38f47f` |
| `court_case_raw` rows | 77,406 |
| `defendant_name` nonempty | 77,399 / 77,406 |
| `payload_format` | `json` |
| `source_record_id` | `sf_case:{case_id}` |
| Payload keys | `case_number`, `case_id`, `defendant_name`, `filed_date`, `scraped_at`, plus load stamps `county`, `locality` |

Existing WI `silver.court_party` rows (`source_system=wcca`, live grain `51:2026CF000028`, six party rows) **must remain**. The SF MERGE/DELETE cannot match those keys.

## Field gaps vs WCCA

`cases.parquet` does **not** carry the labeled defendant block WCCA HTML SSR has. Honest nulls:

| WCCA `court_party` field | SF HF `cases.parquet` |
|--------------------------|------------------------|
| Defendant `Last, First` label | `defendant_name` string only (mostly space-separated `FIRST [MIDDLE…] LAST`, all-caps) |
| Plaintiff | **Absent** — do not invent `State of California` / City |
| AKA | **Absent** |
| DOB | **Absent** → column null + `missing_dob` |
| Sex | **Absent** → null |
| Address | **Absent** → null |
| Charges | **Absent** from this file (other HF tables not loaded) |

Race is still not a column (same as WCCA).

## Parse rules

Input: Bronze `payload` JSON. One **defendant** row, `party_ordinal=1`, when `defendant_name` is nonempty after trim. Otherwise **skip** (no invented party).

`raw_name` is the collapsed source string. Name parts:

| Shape | `name_first` / `name_middle` / `name_last` | DQ |
|-------|--------------------------------------------|----|
| `Last, First[ Middle…]` (comma present and reliable) | WCCA-style comma split | `missing_dob` only |
| 2 space tokens | first token / null / last token | `missing_dob` |
| 3 space tokens | first / middle / last | `missing_dob` |
| 4+ space tokens | first / joined inner / last (heuristic) | `missing_dob`, `ambiguous_name_parts` |
| Single token | all null (do **not** invent a comma form) | `missing_dob`, `ambiguous_name_parts`, `name_unparsed` |
| Comma present but unreliable | all null | `missing_dob`, `ambiguous_name_parts`, `name_unparsed` |

WCCA’s `Last, First` split does **not** dominate this corpus. Space-separated First-Last is a heuristic; flag `ambiguous_name_parts` liberally (always at 4+ tokens). Unreliable comma strings do **not** fall back to space order.

`payload_parse_status` = `json_cases_v1`. `dob` / `sex` / `address_raw` always null. Lineage columns match [`COURT_PARTY.md`](COURT_PARTY.md): `source_system`, `state_code`, `source_record_id`, `ingest_run_id`, `ingested_at`, `payload_sha256`, `bronze_schema_version`.

Synthetic unit-test names only (not live defendants): `JANE Q PUBLIC`, `JOHN MARSHALL FIXTURE`, `LUIS SINGLETOKENLAST`, `FIXTURE, LASTCOMMA FIRST`, `A B C D FOURTOKEN`.

## How SF MERGE avoids wiping WI parties

Natural key is `(source_system, state_code, source_record_id, party_role, party_ordinal)`.

1. Bronze read is `WHERE source_system = 'sf_criminal_hf' AND state_code = 'CA'`.
2. MERGE `WHEN MATCHED` also requires `t.source_system = 'sf_criminal_hf'`.
3. Stale-key `DELETE` requires `t.source_system = 'sf_criminal_hf' AND t.state_code = 'CA'` **and** the case key in the SF-only staged set.

A WI row is `source_system=wcca` / `state_code=WI`. It is never in the USING view and cannot satisfy the DELETE predicate.

This job does **not** widen `silver/transforms/court_case.sql` (WCCA). Keep running that WCCA job for WI HTML SSR only.

**Operator note (WCCA job unchanged in this PR):** `court_case.sql` / `court_case.py` still rank **all** Bronze sources. If that unscoped job is applied after SF parties exist, it can stage `sf_criminal_hf` keys as `unsupported_source` with **zero** parties and delete SF party rows for those keys. Do not use the WCCA transform to refresh SF. Use this dedicated SF job instead. Narrowing the WCCA job to `source_system=wcca` is a follow-up — not done here so the WI path stays untouched.

## Match / review experiments

[`MATCH_REVIEW.md`](MATCH_REVIEW.md) can score `party_role=defendant` on these rows. Every SF defendant is `dob_absent` → **review** (never invent a date; never `auto`). This is **not** the WI employer review queue and not a hire engine. `match_decision` is still **not created**.

## Tests (local)

```bash
python3 -m unittest discover -s sources/sf_criminal_hf/tests -v
python3 -m unittest discover -s sources/wcca/tests -v
python3 -m unittest discover -s silver/transforms/tests -v
```
