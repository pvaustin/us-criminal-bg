# Silver `court_party`

**Owner:** silva silver  
**Table:** `us_criminal_bg.silver.court_party`  
**Schema version:** `silver.court_party.v1`  
**DDL:** [`silver/schemas/court_party.sql`](../../silver/schemas/court_party.sql)  
**Parsers:** [`sources/wcca/parse.py`](../../sources/wcca/parse.py) (`parse_parties_from_ssr_text`) · [`sources/sf_criminal_hf/parse_party.py`](../../sources/sf_criminal_hf/parse_party.py) (research JSON defendants)  
**Transforms:** WCCA — [`silver/transforms/court_case.sql`](../../silver/transforms/court_case.sql) / [`court_case.py`](../../silver/transforms/court_case.py). SF research (parallel, does not delete WI) — [`silver/transforms/court_party_sf_criminal_hf.sql`](../../silver/transforms/court_party_sf_criminal_hf.sql) / [`court_party_sf_criminal_hf.py`](../../silver/transforms/court_party_sf_criminal_hf.py)  
**Contracts:** [`NAMING.md`](NAMING.md) · [`WCCA_HTML_SSR.md`](WCCA_HTML_SSR.md) · [`MATCH_REVIEW.md`](MATCH_REVIEW.md) · [`SF_RESEARCH.md`](SF_RESEARCH.md) · [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md)

Analytics-ready **party facts** extracted from already-landed Bronze (WCCA `html_snapshot` HTML, plus a research-only SF HF JSON path). Type-1 current row. Not a person graph, not a hire decision.

## Purpose / non-goals

**Purpose.** One current Silver row per party role + ordinal on a court case, parsed from already-landed Bronze so downstream analytics and Uma’s review queue can join parties without re-reading payloads. WCCA HTML SSR (and caption) is the WI product path. SF HF JSON defendants are a **research-only** parallel path ([`SF_RESEARCH.md`](SF_RESEARCH.md)) — not the employer MVP.

**Non-goals (explicit):**

| Out of scope | Why |
|--------------|-----|
| Identity graph / person-id | Rows are source parties, not linked people |
| Hire / no-hire, FCRA packages | Silver facts only. Serving marts: [`docs/gold/NAMING.md`](../gold/NAMING.md) |
| Race column | Agency-provided and subjective; **matching must not require it**. The HTML `Race` label is ignored even when present |
| Scrape / HTTP to WCCA | Transforms consume Bronze only |
| Bronze writes | No INSERT/UPDATE/DELETE on `us_criminal_bg.bronze.*` |
| Silent auto-link | Matching is a review-queue design (`MATCH_REVIEW.md`), not this table |

## Schema

DDL: `silver/schemas/court_party.sql`. Databricks SQL requires `ARRAY<STRING>` (not bare `ARRAY`).

**MERGE key (type-1):** `(source_system, state_code, source_record_id, party_role, party_ordinal)`

Re-running a case upserts matching role+ordinal rows and **deletes** role+ordinals that disappeared for that case in the current Bronze payload (same stale-key pattern as `court_charge`).

`party_role` is one of `defendant` \| `plaintiff` \| `aka` \| `other`. The WCCA parser emits the first three; `other` is reserved and not produced today.

| Column | Type | Null | Meaning |
|--------|------|------|---------|
| `source_system` | `STRING` | NOT NULL | MERGE key. WI MVP: `wcca`. Research: `sf_criminal_hf` |
| `state_code` | `STRING` | NOT NULL | MERGE key. WI MVP: `WI`. Research: `CA` |
| `source_record_id` | `STRING` | NOT NULL | MERGE key. WCCA: `{countyNo}:{caseNo}`. SF research: `sf_case:{case_id}` |
| `party_role` | `STRING` | NOT NULL | MERGE key. `defendant` \| `plaintiff` \| `aka` \| `other` |
| `party_ordinal` | `INT` | NOT NULL | MERGE key. 1-based, stable **within role** for this payload (document order) |
| `raw_name` | `STRING` | NOT NULL | Source name string; required on every emitted row |
| `name_last` | `STRING` | null | WCCA: split only when `Last, First[ Middle…]` is reliable. SF research: also first/last space tokens |
| `name_first` | `STRING` | null | Same |
| `name_middle` | `STRING` | null | Same; trailing AKA-type tokens stripped on `aka` rows |
| `dob` | `DATE` | null | Labeled `Date of birth` only |
| `sex` | `STRING` | null | Labeled `Sex Male\|Female\|Unknown` only |
| `address_raw` | `STRING` | null | Labeled `Address` text only (not street/city/zip columns) |
| `ingest_run_id` | `STRING` | NOT NULL | Bronze lineage |
| `ingested_at` | `TIMESTAMP` | NOT NULL | Bronze row write time |
| `payload_sha256` | `STRING` | NOT NULL | Join-back to `bronze.court_case_raw.payload` |
| `bronze_schema_version` | `STRING` | NOT NULL | Bronze `schema_version` renamed |
| `silver_schema_version` | `STRING` | NOT NULL | `silver.court_party.v1` |
| `transformed_at` | `TIMESTAMP` | NOT NULL | Silver write time |
| `transform_run_id` | `STRING` | NOT NULL | FK-ish to `silver.transform_run` |
| `payload_parse_status` | `STRING` | NOT NULL | WCCA: `html_ssr_v1` for labeled / caption-plaintiff rows; `html_ssr_partial` when defendant name is caption fallback. SF research: `json_cases_v1` |
| `dq_flags` | `ARRAY<STRING>` | NOT NULL | Sorted flag names; empty array if clean (never SQL `NULL`) |

Race is **not** a column.

### Party `dq_flags`

| Flag | When |
|------|------|
| `ambiguous_name_parts` | `raw_name` present but name-part split was not reliable (WCCA: omitted on organizational plaintiff `State of Wisconsin`. SF: single-token, unreliable comma, or 4+ space tokens) |
| `missing_dob` | **Defendant** row with no labeled `Date of birth` (always on SF HF defendants — corpus has no DOB) |
| `name_unparsed` | SF research: `raw_name` present but first/last parts left null (single token or unreliable comma). Not used on WCCA rows |
| `defendant_from_caption` | Defendant `raw_name` taken from caption `vs.` because `Defendant name` was absent |
| `dob_unparsed` | `Date of birth` label present but token was not a valid date (Python path) |

Flags are omitted when they do not apply.

## Extraction rules

Input: stripped WCCA HTML SSR text plus caption. No invented facts. **Honest nulls:** if a label is absent, the column is null (plus a flag when that is a defendant DOB).

| Role | Source | Row grain | Attributes |
|------|--------|-----------|------------|
| **plaintiff** | Caption `State of Wisconsin vs. …` | Always ordinal **1** when the caption matches | `raw_name` = `State of Wisconsin`. Name parts / dob / sex / address stay **null** (organization, not a person split) |
| **defendant** | Labeled `Defendant name {Last, First M}` | Ordinal **1** (Python: extra labeled names become ordinal 2+) | DOB / sex / `address_raw` only when those **labels** exist on the defendant block. If `Defendant name` is missing, caption name after `vs.` is used and flagged `defendant_from_caption` (`payload_parse_status=html_ssr_partial`) |
| **aka** | `Also known as` section | **One row per also-known-as person name** in document order | `Last, First[ M]` only. Skip the `Name Type Date of birth` header, court-activity / JUSTIS / Fingerprint / calendar text, and a duplicate of the defendant (or plaintiff) `raw_name`. DOB / sex / address stay **null** on aka rows (those labels belong to the defendant block) |
| **other** | — | Not emitted by the WCCA parser | Reserved |

**Address ZIP stop.** `address_raw` is collapsed labeled `Address` text through city/ZIP. It **stops before** `Branch ID`, `DA case`, `Charges`, `Responsible`, `Attorneys`, `JUSTIS`, `Fingerprint`, hearings/calendar, and other party-stop headings in `sources/wcca/parse.py` (`ADDRESS_LABEL_RE` / `_PARTY_STOP_CORE`). Do not keep street+branch chrome.

**AKA split + trailing tokens.** Person names are split on `Last,` (Python: line + regex; SQL: space + `Last,` lookahead). Strip trailing delimiter leftovers `Also` / `AKA` / `Alias` / `Maiden` / `Type` (the `TJ Also` glitch). Last-token skip list includes header words (`name`, `type`, `date`, `birth`, …).

**Name parts.** Fill `name_last` / `name_first` / `name_middle` only for reliable `Last, First[ Middle…]`. No `First Last` guessing. Org plaintiff stays unsplit. Otherwise null + `ambiguous_name_parts`.

**DOB / sex.** `dob` is DATE from `Date of birth MM-DD-YYYY` (or `/`) only — never filing date, caption, or inference. `sex` from `Sex Male\|Female\|Unknown` only. Unlabeled → null. Bad DOB token → `dob_unparsed` (Python).

**Race.** Often labeled on WCCA SSR. **Not stored.** Matching must not require it.

Prefer the **Python** job for party name-part / aka DQ. Spark SQL is a warehouse stand-in: comma-split name parts, same plaintiff / defendant / aka cores, weaker aka hygiene.

## San Francisco research corpus (`sf_criminal_hf`)

Parallel path. Full note: [`SF_RESEARCH.md`](SF_RESEARCH.md). Isolated from WI: the SF transform filters Bronze to `source_system='sf_criminal_hf'` and `state_code='CA'`, and DELETE is additionally gated on those literals so existing `wcca` / `WI` party rows (live grain `51:2026CF000028`) are not removed.

| Role | Source | Row grain | Attributes |
|------|--------|-----------|------------|
| **defendant** | JSON `defendant_name` | Ordinal **1** when nonempty after trim; **skip** blank names (no invented party) | `raw_name` from payload. Comma → `Last, First[ Middle…]`. Else first/last tokens + joined middle. `dob` / `sex` / `address_raw` **null**. `payload_parse_status=json_cases_v1` |
| **plaintiff** / **aka** | — | Not emitted | Corpus has no plaintiff or AKA fields |

Name-shape note (identifier-only; no live names in git): almost all source strings are space-separated `FIRST [MIDDLE…] LAST` (all-caps). WCCA `Last, First` does **not** dominate. Flag `ambiguous_name_parts` on single-token and 4+ token heuristics. Gaps vs WCCA: no DOB, AKA, sex, address, plaintiff, or charges in `cases.parquet`.

This path does **not** write `court_case` / `court_charge`. It is **not** employer-product copy. Coordinator applies the SF SQL/Python job after this PR.

## Lineage

`payload` is **not** copied into Silver. Join back to `us_criminal_bg.bronze.court_case_raw` with the case natural key and/or `ingest_run_id` + `payload_sha256`. WCCA party lineage matches the **parent `court_case` row** used for that run. SF research parties copy lineage from the Bronze case row directly (this path does not write `court_case`).

| Column | Source | Notes |
|--------|--------|-------|
| `ingest_run_id` | `bronze.court_case_raw.ingest_run_id` | FK-ish to `bronze.ingest_run` |
| `ingested_at` | `bronze.court_case_raw.ingested_at` | Bronze write time, not Silver transform time |
| `source_system` | Bronze / MERGE key | `wcca` (WI MVP) or `sf_criminal_hf` (CA research) |
| `state_code` | Bronze / MERGE key | `WI` or `CA` |
| `source_record_id` | Bronze / MERGE key | e.g. `51:2026CF000028` |
| `payload_sha256` | `bronze.court_case_raw.payload_sha256` | Integrity / payload join-back |
| `bronze_schema_version` | Bronze `schema_version` | Renamed to avoid colliding with `silver_schema_version` |
| `transform_run_id` | `silver.transform_run` | Generated at job start; materialized in `_this_transform_run` |

`transformed_at` / `transform_run_id` change each run; business attributes for a given MERGE key converge.

## Live example (`51:2026CF000028`)

Warehouse proof grain (identifier only — **no live full names, DOB, or street in git**):

- `source_system=wcca`, `state_code=WI`, `source_record_id=51:2026CF000028`
- `payload_format=html_snapshot` with labeled defendant block + also-known-as person lines

| `party_role` | Count | Field samples (truncated) |
|--------------|------:|---------------------------|
| `plaintiff` | **1** | `raw_name` = `State of Wisconsin`. `name_last` / `name_first` / `name_middle` / `dob` / `sex` / `address_raw` = null. `party_ordinal=1` |
| `defendant` | **1** | `raw_name` shape `Last, First[ M]` — this doc keeps **last/first initials only**. `dob` present = **yes** (labeled). `sex` present = **yes** (labeled). `address_raw` shape `…, WI 53405` (street omitted; stops before Branch ID / DA case). HTML `Race` label **not stored**. Typical `dq_flags` = `[]`. `payload_parse_status=html_ssr_v1` |
| `aka` | **4** | Four person names `Last, First[ M]` in document order (`party_ordinal` 1…4). Trailing `Also` / `AKA` / `Alias` stripped. `dob` / `sex` / `address_raw` = null. Not the `Name Type Date of birth` header |

Example keys (no PII):

- Party: `wcca|WI|51:2026CF000028|defendant|1`
- Case report: `wcca|WI|51:2026CF000028`

Synthetic fixtures under `sources/wcca/tests/fixtures/` are **not** this live grain.

## How `MATCH_REVIEW.md` consumes `court_party`

Sketch helper: [`silver/transforms/match_review_sketch.py`](../../silver/transforms/match_review_sketch.py) (pure Python, synthetic examples). SF name-only warehouse job (same bands, last-name retrieve, append `match_decision`): [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md). **No silent auto-link.**

1. Filter to `party_role IN ('defendant', 'aka')` before scoring. Plaintiff (`State of Wisconsin`) and `other` are **no-link** (`party_role_not_matchable`).
2. Score one employer subject against **one** `court_party` row. AKA is a separate card (`aka_alias_row`).
3. **No silent auto-link.** MVP default is `review` (or `no-link`). The only written `auto` rule is suggestion-only: exact last+first **or** exact `raw_name` **and** matching DOB when **both** DOBs are present. `auto` must not attach a report or fire employment action.
4. Missing DOB (subject, party, or both) → reason `dob_absent` → **review**. Never a hard fail. Never invent a date. Both DOBs present and unequal → `dob_conflict` → **no-link**.
5. Race is not a signal. `sex` / `address_raw` are display-only.

Every review-queue card (every band) must carry at least:

| Field | From |
|-------|------|
| `party_key` | `source_system\|state_code\|source_record_id\|party_role\|party_ordinal` |
| `confidence_band` | `auto` \| `review` \| `no-link` |
| `score_or_reason_codes` | Sketch score + `reasons[]` |
| `raw_name`, name parts, `party_role`, `party_ordinal` | `court_party` |
| `ingest_run_id`, `payload_sha256`, `transform_run_id` | Lineage |
| `case_report_key` | `source_system\|state_code\|source_record_id` |

`required_provenance()` in the sketch helper is the dict contract. No hire / adverse-action control on the card.

## Uma report/review attach

Attach using **existing** case/charge keys only. **No new report identity grain** (no match-report id, person-id, or FCRA package key).

| Object | Key | Join |
|--------|-----|------|
| Case report | `source_system\|state_code\|source_record_id` | `us_criminal_bg.silver.court_case` |
| Charges (optional drill-in) | that key + `charge_count` | `us_criminal_bg.silver.court_charge` |
| Party card | `party_key` (role + ordinal) | `us_criminal_bg.silver.court_party` |

Example: `wcca|WI|51:2026CF000028` → case + charges; party cards keep their own `party_key`.

Later human/suggestion rows belong in append-only `us_criminal_bg.silver.match_decision` ([`MATCH_REVIEW.md`](MATCH_REVIEW.md); SF experiment: [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md)).

## Open follow-ups

| Item | Status |
|------|--------|
| Create `us_criminal_bg.silver.match_decision` | DDL + SF research job in [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md). Append-only. Warehouse apply coordinator-side. Not a hire engine |
| Charge `modifier_*` on the SQL path | Python fills `modifier_statute` / `modifier_text` from `Modifier:` lines. [`court_case.sql`](../../silver/transforms/court_case.sql) leaves them **null** |
| SF HF research parties | Dedicated transform [`court_party_sf_criminal_hf.sql`](../../silver/transforms/court_party_sf_criminal_hf.sql). Gaps / experiment-only: [`SF_RESEARCH.md`](SF_RESEARCH.md). Warehouse apply coordinator-side |
| SQL vs Python party DQ | SQL comma-splits name parts and uses a `Last,` lookahead for aka. Prefer Python for aka header collapse, trailing-`Also` strip, and `dob_unparsed` |
| Extra labeled `Defendant name` | Python can emit defendant ordinal 2+; SQL takes the first labeled name only |
| `other` role | Reserved in the enum; WCCA criminal captions do not emit it |
| Caption over-capture | Caption must stop before `Case summary` / `Filing date` (fixed for case SSR; plaintiff still comes from that caption) |
| Address / aka over-capture | Must not swallow Branch ID, DA case, JUSTIS, Fingerprint, hearings, or the `Name Type Date of birth` header |
| Warehouse regex escapes | Party Spark SQL must not use ANSI-invalid `\\b` / `\\'` (fixed in `court_party` apply). Re-run `silver/schemas/court_party.sql` then full `silver/transforms/court_case.sql` |
| Race | If a later version stores a raw agency race label, document it as subjective; matching must still not require it |

Warehouse apply of this table is **coordinator-side**. This doc does not scrape, does not write Bronze, and does not produce a hire decision.
