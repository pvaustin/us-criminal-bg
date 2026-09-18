# SF name-only match / review experiment

**Owner:** silva silver (store + scorer) / Uma (review UI)  
**Facts:** `us_criminal_bg.silver.court_party` (`source_system=sf_criminal_hf`, `state_code=CA`)  
**Decisions:** append-only `us_criminal_bg.silver.match_decision`  
**Bands:** [`MATCH_REVIEW.md`](MATCH_REVIEW.md) via [`silver/transforms/match_review_sketch.py`](../../silver/transforms/match_review_sketch.py) — **no parallel band system**  
**Job:** [`silver/transforms/match_decision_sf_research.sql`](../../silver/transforms/match_decision_sf_research.sql) · [`match_decision_sf_research.py`](../../silver/transforms/match_decision_sf_research.py)  
**DDL:** [`silver/schemas/match_decision.sql`](../../silver/schemas/match_decision.sql)  
**Corpus note:** [`SF_RESEARCH.md`](SF_RESEARCH.md)

Research-only name-match against already-landed SF HF defendants. **Not** the Wisconsin employer product. **Not** a CRA / FCRA / adverse-action system. **Not** a hire / no-hire signal. Uma owns the UI; this repo delivers the Silver store and a stable query contract.

Warehouse apply is **coordinator-side**. This repo does not run Databricks.

## Critical SF fact

SF `court_party` defendants have **no DOB** (honest null + `missing_dob` on the party row).

| Rule | Result |
|------|--------|
| Exact last+first (or exact normalized `raw_name`) | **`review`** with reason `dob_absent` |
| `auto` | **Unreachable.** `auto` requires both subject and party DOBs present **and** equal (`dob_match`). Party DOB is always null. |
| Last-name mismatch | **`no-link`** (`last_name_mismatch`). The job does not retrieve these rows (last-name equality join). |
| Silent auto-link | **Forbidden.** Suggestion rows use `actor='system:suggestion'` and `review_status='suggestion'`. They do not attach a report or fire employment action. |

This experiment is a **name-only review queue**, not a hire engine.

## Non-goals (explicit)

| Out of scope | Why |
|--------------|-----|
| WI WCCA path | `sources/wcca/*`, `silver/transforms/court_case.*`, `map_court_case.py` stay untouched |
| Invented court rows | Score existing `court_party` only |
| Hire / no-hire, adverse-action UI | Research experiments only; CC-BY-NC-4.0 upstream is not commercial CRA use |
| Mixing into WI employer product claims | `experiment_tag='sf_name_only_research'` isolates these suggestion rows |
| Live PII in git | Synthetic fixtures in tests; live prove reports **counts + keys**, not full names |
| Uma UI | Contract + store only |
| Full cartesian vs ~77,399 defendants | Last-name (normalized) equality first |

## Corpus (identifier-only)

Verified Bronze load 2026-09-16 (no live full names / DOB / street in this doc):

| Item | Value |
|------|--------|
| `source_system` | `sf_criminal_hf` |
| `state_code` | `CA` |
| `ingest_run_id` | `26a31a80-a06f-4870-ab9e-cda5db38f47f` |
| nonempty defendants | **77,399** / 77,406 Bronze rows |
| `source_record_id` | `sf_case:{case_id}` |
| party DOB / AKA / sex / address | **Absent** |

## How scoring works

1. Filter `court_party` to `source_system='sf_criminal_hf'` AND `state_code='CA'` AND `party_role IN ('defendant','aka')`.
2. Parse the subject name with the sketch helper (`First Last` or `Last, First`).
3. Retrieve candidates by **normalized last-name equality** (`alnum` + upper). Not a cartesian product.
4. Score each pair with `score_subject_against_party` (same `auto` / `review` / `no-link` rules as WI).
5. **APPEND** rows to `match_decision` with `actor='system:suggestion'`. Never MERGE / UPDATE / DELETE prior decisions.

Default persist: **`review` + `auto`** (SF `auto` should be zero). Optional `--persist-no-link` / SQL comment keeps last-name-equal negatives (e.g. first-name mismatch) for warehouse prove.

Python is the source of truth for bands. Warehouse SQL mirrors the same rules (`REVIEW_MIN = 50`) as a statement-at-a-time stand-in.

## `us_criminal_bg.silver.match_decision`

Append-only. One row = one subject × one party card at one `decided_at`. A later human decision is a **new** row (`review_status='human'`, `actor` = reviewer), never an overwrite.

Uma reads this table. Do not treat a UI-only store as the system of record. Open-card serving shortcut (no full scan): `us_criminal_bg.gold.match_queue` ([`docs/gold/NAMING.md`](../gold/NAMING.md)).

## Uma query / API contract

Uma owns UI. Silver delivers **flat** suggestion rows. A subject’s `candidates[]` is a query grouping, not a nested column.

### Subject (input + echoed on every row)

| Field | Type | Notes |
|-------|------|--------|
| `subject_ref` | STRING NOT NULL | Caller id (research or employer). Not a court person id. |
| `subject_name` | STRING | As submitted. Do not invent. |
| `subject_dob` | DATE | Null when absent (honest). |

### Each candidate card (one `match_decision` row)

| Field | Type | Notes |
|-------|------|--------|
| `party_key` | STRING | `source_system\|state_code\|source_record_id\|party_role\|party_ordinal` |
| `party_role` | STRING | Score `defendant` / `aka` only |
| `party_ordinal` | INT | |
| `raw_name` | STRING | Party display name |
| `name_last` / `name_first` / `name_middle` | STRING | Null when unparsed |
| `confidence_band` | STRING | `auto` \| `review` \| `no-link` |
| `score` | INT | Sketch integer; 0 when blocked |
| `reasons` | ARRAY\<STRING\> | e.g. `last_name_match`, `dob_absent` |
| `score_or_reason_codes` | ARRAY\<STRING\> | `[score_string, ...reasons]` (MATCH_REVIEW sketch column) |
| `source_system` | STRING | SF experiment: `sf_criminal_hf` |
| `state_code` | STRING | SF experiment: `CA` (dimension, no `ca_*` table) |
| `source_record_id` | STRING | `sf_case:{case_id}` |
| `ingest_run_id` | STRING | Copied from `court_party` |
| `payload_sha256` | STRING | Join-back to Bronze payload |
| `transform_run_id` | STRING | Copied from the **party** Silver row |
| `case_report_key` | STRING | `source_system\|state_code\|source_record_id` (existing case grain; SF has no `court_case` row in this research path) |
| `decision_id` | STRING | UUID per append |
| `decided_at` | TIMESTAMP | UTC |
| `actor` | STRING | Job: `system:suggestion`. Later human: reviewer email |
| `review_status` | STRING | `suggestion` (this job) vs `human` (later Uma append) |
| `experiment_tag` | STRING | Job: `sf_name_only_research` |
| `notes` | STRING | Research disclaimer; not adverse-action text |

Do **not** show hire / no-hire / adverse-action controls on this card.

### Suggested Uma query

Latest suggestion cards for a subject (SF experiment):

```sql
SELECT
  subject_ref, subject_name, subject_dob,
  party_key, party_role, party_ordinal, raw_name,
  name_last, name_first, name_middle,
  confidence_band, score, reasons,
  source_system, state_code, source_record_id,
  ingest_run_id, payload_sha256, transform_run_id,
  case_report_key, decision_id, decided_at, actor, review_status
FROM us_criminal_bg.silver.match_decision
WHERE subject_ref = :subject_ref
  AND experiment_tag = 'sf_name_only_research'
  AND review_status = 'suggestion'
  AND confidence_band IN ('review', 'auto')
QUALIFY row_number() OVER (
  PARTITION BY party_key
  ORDER BY decided_at DESC
) = 1
ORDER BY score DESC, decided_at DESC
```

Response shape for Uma: `{ subject_ref, subject_name, subject_dob, candidates: [ { party_key, …, confidence_band, score, reasons, decision_id, review_status, case_report_key } ] }`.

A later human append for the same `(subject_ref, party_key)` does not delete the suggestion. Uma should prefer the latest `decided_at` (any `review_status`) when resolving “current” state.

## How the coordinator proves live N subjects

Do **not** paste live full names, DOB, or street into git, PR comments, or this doc. Identifier-only + band counts.

1. Confirm parties exist (expect **~77,399** defendants):

```sql
SELECT count(*) AS sf_defendants
FROM us_criminal_bg.silver.court_party
WHERE source_system = 'sf_criminal_hf'
  AND state_code = 'CA'
  AND party_role = 'defendant'
```

2. Apply [`silver/schemas/match_decision.sql`](../../silver/schemas/match_decision.sql).

3. Load **N** subjects into `us_criminal_bg.silver._match_subject_sf_research` (`subject_ref`, `subject_name`, `subject_dob`). Names stay in the warehouse.

4. Run the SQL warehouse script **or** `python3 silver/transforms/match_decision_sf_research.py --apply` on a cluster (repo on `sys.path`). Optional `--persist-no-link` for last-name-equal negatives.

5. Report **without live names**:

```sql
SELECT confidence_band, count(*) AS n, count(DISTINCT subject_ref) AS subjects
FROM us_criminal_bg.silver.match_decision
WHERE experiment_tag = 'sf_name_only_research'
  AND actor = 'system:suggestion'
GROUP BY confidence_band
ORDER BY confidence_band
```

```sql
SELECT
  count(*) AS review_with_dob_absent
FROM us_criminal_bg.silver.match_decision
WHERE experiment_tag = 'sf_name_only_research'
  AND confidence_band = 'review'
  AND array_contains(reasons, 'dob_absent')
```

Expect: **`auto = 0`**. If `auto > 0` on this corpus, party DOB leaked or the band rule drifted — stop and do not treat rows as product signals.

Also log `count(DISTINCT subject_ref)`, N requested vs N with ≥1 `review` card, and a few `party_key` / `source_record_id` prefixes (no `raw_name`).

## Tests (local, synthetic)

```bash
python3 -m unittest discover -s silver/transforms/tests -v
python3 -m unittest discover -s sources/sf_criminal_hf/tests -v
python3 -m unittest discover -s sources/wcca/tests -v
```

Fixtures use names such as `JANE Q PUBLIC` / `JOHN MARSHALL FIXTURE` — **not** live defendants.
