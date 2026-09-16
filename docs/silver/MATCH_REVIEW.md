# Match / review design (employer subject vs `court_party`)

**Owner:** silva silver (facts) / Uma (review UI)  
**Silver facts:** `us_criminal_bg.silver.court_party`  
**Decisions (named store):** `us_criminal_bg.silver.match_decision` (append-only; DDL [`silver/schemas/match_decision.sql`](../../silver/schemas/match_decision.sql))  
**Sketch helper:** `silver/transforms/match_review_sketch.py` (pure Python, synthetic examples — **not** silent auto-link)  
**SF research job:** [`docs/silver/SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md) — name-only scoring of sample subjects against `sf_criminal_hf` / `CA` defendants; still not a hire engine

This is a design sketch so Uma can build a review queue against party facts Silver already stores. It does **not** scrape, does **not** write Bronze, does **not** write Gold, and does **not** produce a hire / FCRA adverse-action output.

AKA rows are **one person-name each** (`Last, First[ M]`); `address_raw` stops at ZIP / before Branch ID. See `docs/silver/WCCA_HTML_SSR.md`.

SF HF research defendants (`source_system=sf_criminal_hf`, `state_code=CA`) may appear on the same `court_party` table for **name-match experiments**. They always lack DOB (`dob_absent` → **review**, **never `auto`**). That corpus is **not** the WI employer product path — see [`SF_RESEARCH.md`](SF_RESEARCH.md) and [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md). Do not treat an SF experiment hit as a hire signal.

## Subject inputs

| Field | Required | Rule |
|-------|----------|------|
| `name` | **yes** | Employer-provided subject name (`First Last` or `Last, First`). Unparseable last name → **no-link** (`last_name_unparsed`). |
| `dob` | **no** | Optional DATE. Missing DOB (subject, party, or both) is an honest signal **`dob_absent` → review**. It is **never** a hard fail and **never** invents a date. |

Both DOBs present and unequal → **no-link** (`dob_conflict`). Race is not a signal. `sex` / `address_raw` are display-only.

## Grains

| Side | Grain | Inputs |
|------|-------|--------|
| Employer **subject** | One person the employer is asking about | `name` (required), `dob` (optional) |
| Court **party** | One `court_party` row | `raw_name`, optional name parts, optional `dob` |

Score **defendant** and **aka** only. **Plaintiff** (`State of Wisconsin` on WI criminal captions) is always **no-link**. `other` is not matchable.

## Default MVP band policy — no silent auto-link

**MVP default is `review` (or `no-link`).** The UI must not attach a party to a case report, skip the queue, or take any employment action without a human.

The only **written** `auto` rule (suggestion-only, still not a hire decision, still not silent auto-link):

> Exact last+first **or** exact `raw_name` (normalized) **and** matching DOB when **both** subject and party DOBs are present.

Anything else that is not `no-link` is **`review`**: missing DOB, first-initial-only, aka without DOB, extra-signal not in the rule above.

| Band | Queue behavior | Sketch rule |
|------|----------------|-------------|
| **auto** | Suggestion / sort hint **only**. Card still has full provenance. Must **not** silent auto-link or fire employment action. | Exact last+first (or exact `raw_name`) **and** `dob_match`. |
| **review** | Human must look. **MVP default** for name-compatible hits. | Name compatible, no DOB conflict; includes **`dob_absent`**. |
| **no-link** | Do not present as a match. | Last-name mismatch, DOB conflict, unparseable last names, non-matchable `party_role`. |

## Review-queue field contract (minimum)

Every card, for every band, must carry at least:

| Field | Source |
|-------|--------|
| `party_key` | `source_system\|state_code\|source_record_id\|party_role\|party_ordinal` |
| `party_role` | `court_party.party_role` |
| `party_ordinal` | `court_party.party_ordinal` |
| `raw_name` | `court_party.raw_name` |
| `name_last` / `name_first` / `name_middle` | Normalized parts when present; else null |
| `confidence_band` | `auto` \| `review` \| `no-link` |
| `score_or_reason_codes` | Integer sketch score **and** `reasons[]` (e.g. `dob_absent`, `dob_match`) |
| `source_system` | Party / case key |
| `state_code` | Party / case key (no `wi_*` prefix) |
| `source_record_id` | Party / case key |
| `ingest_run_id` | Bronze lineage |
| `payload_sha256` | Join-back to `bronze.court_case_raw.payload` |
| `transform_run_id` | Silver lineage |
| `case_report_key` | Same natural **case** key: `source_system\|state_code\|source_record_id` → existing `court_case` / charges UI |

Do not show a hire or adverse-action control on this card. `required_provenance()` in the sketch helper returns this dict (synthetic tests).

## Report-attach

Attach using **existing** case/charge keys only:

- Case: `(source_system, state_code, source_record_id)` → `court_case`
- Charges (optional drill-in): that key plus `charge_count` → `court_charge`

**No new report identity grain.** Do not invent a match-report id, person-id, or FCRA package key.

## MVP store: `us_criminal_bg.silver.match_decision`

Prefer a Databricks append-only table over a web-app-only store. **DDL is in this PR** ([`silver/schemas/match_decision.sql`](../../silver/schemas/match_decision.sql)); warehouse apply is coordinator-side. Extra Uma contract columns (`raw_name`, name parts, `score`, `reasons`, `case_report_key`, `review_status`, `experiment_tag`) are documented in [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md).

```text
us_criminal_bg.silver.match_decision
  decision_id            STRING NOT NULL   -- uuid per append
  subject_ref            STRING NOT NULL   -- employer / research subject id (not a court person id)
  subject_name           STRING            -- as submitted; do not invent
  subject_dob            DATE              -- null when absent (honest)
  party_key              STRING NOT NULL   -- source_system|state_code|source_record_id|party_role|party_ordinal
  source_system          STRING NOT NULL
  state_code             STRING NOT NULL
  source_record_id       STRING NOT NULL
  party_role             STRING NOT NULL
  party_ordinal          INT NOT NULL
  confidence_band        STRING NOT NULL   -- auto | review | no-link
  score_or_reason_codes  ARRAY<STRING> NOT NULL
  ingest_run_id          STRING
  payload_sha256         STRING
  transform_run_id       STRING
  decided_at             TIMESTAMP NOT NULL
  actor                  STRING NOT NULL   -- e.g. reviewer email, or system:suggestion
```

Always **append**. Never type-1 overwrite a human decision. `auto` rows are `actor = system:suggestion` and are not employment actions. SF research suggestions also set `review_status='suggestion'` and `experiment_tag='sf_name_only_research'`.

### Evidence persisted per band

| Band | What to persist | What not to persist |
|------|-----------------|---------------------|
| **auto** | Full queue contract + suggestion reasons (`last_name_match`, `first_name_match` or `raw_name_match`, `dob_match`) + lineage ids + `party_key`. | Silent attach, hire flag, FCRA copy. Suggestion is not a decision until a human appends a later row. |
| **review** | Full queue contract + `dob_absent` / initial-match / `aka_alias_row` reasons + lineage + link to `case_report_key`. | Invented DOB, race, adverse-action text. |
| **no-link** | `party_key`, `confidence_band=no-link`, reason codes (`last_name_mismatch`, `dob_conflict`, `party_role_not_matchable`, …), lineage ids, `decided_at`, `actor`. | Do not attach to the case report as a match. Short negative row is enough to avoid re-surfacing. |

## Non-goals (explicit)

- No silent auto-link
- No hire / no-hire decision
- No FCRA adverse-action copy, notices, or packages
- No automatic adverse action
- No bulk WCCA scrape, no weekly ingest, no Bronze writes
- No WI employer scoring job (SF **research** last-name job is isolated: [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md); not CRA / adverse action)
- No new report identity grain
- Matching must not require race (column omitted from `court_party`)

## Synthetic examples

Names below are **fixtures**, not live defendants.

| Subject | Party | Band | Why |
|---------|-------|------|-----|
| Jane Q Fixture, DOB 2099-01-15 | defendant `FIXTURE, JANE Q`, DOB 2099-01-15 | **auto** (suggestion only) | exact last+first **and** `dob_match` |
| Jane Fixture (no DOB) | same defendant, DOB null | **review** | name match, `dob_absent` — not a hard fail |
| Jane Fixture, DOB 2098-01-01 | same defendant, DOB 2099-01-15 | **no-link** | `dob_conflict` |
| Jane Fixture | plaintiff `State of Wisconsin` | **no-link** | `party_role_not_matchable` |
| Jane Aliasfixture | aka `ALIASFIXTURE, JANE` (no DOB) | **review** | alias row, `dob_absent` |
| J Fixture, DOB 2099-01-15 | defendant `FIXTURE, JANE Q`, DOB 2099-01-15 | **review** | first-initial only — not the auto rule |
| Jane Q Public (no DOB) | SF defendant `JANE Q PUBLIC`, DOB null | **review** | name match, `dob_absent` — SF **never `auto`** |

Live Bronze grain `source_system=wcca`, `state_code=WI`, `source_record_id=51:2026CF000028` is expected to yield **plaintiff 1**, **defendant 1**, **aka N≥1** (clean person names). Do not copy live names, DOB, or address into git or into this doc.

## UI notes for Uma

1. Filter `court_party` to `party_role IN ('defendant','aka')` before scoring.
2. One subject can produce several cards (defendant + each aka). Keep `party_key` per card.
3. **MVP: show the queue.** `auto` may collapse/sort; it must not skip human confirmation or attach the report.
4. Case report route uses **`case_report_key`** only (existing `court_case` / `court_charge` keys).
5. Persist later decisions to `us_criminal_bg.silver.match_decision` (append), not a UI-only store. Uma contract (subject, candidates[], score, band, `decision_id`, `review_status`): [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md).
6. Warehouse apply of `court_party` and `match_decision` DDL is coordinator-side. SF name-only experiment job is research-only and must not mix into WI employer product claims.
