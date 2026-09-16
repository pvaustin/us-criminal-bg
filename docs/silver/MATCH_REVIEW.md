# Match / review design (employer subject vs `court_party`)

**Owner:** silva silver (facts) / Uma (review UI)  
**Silver table:** `us_criminal_bg.silver.court_party`  
**Sketch helper:** `silver/transforms/match_review_sketch.py` (pure Python, synthetic examples only — **not** a Databricks scoring job)

This is a design sketch so Uma can build a review queue against party facts Silver already stores. It does **not** implement matching in the warehouse, does **not** write Gold, and does **not** produce a hire decision.

## Grains

| Side | Grain | Inputs |
|------|-------|--------|
| Employer **subject** | One person the employer is asking about | `name` (required), `dob` (optional DATE) |
| Court **party** | One `court_party` row | `raw_name`, optional `name_last` / `name_first` / `name_middle`, optional `dob` |

Score **defendant** and **aka** rows only. **Plaintiff** (`State of Wisconsin` on WI criminal captions) is always **no-link**. `other` is not matchable in this sketch.

Race is not on `court_party` and **must not** be a matching signal if it is added later. `sex` and `address_raw` are reviewer display-only, not scored.

## Confidence bands

| Band | Meaning for the UI | Sketch rule (synthetic helper) |
|------|--------------------|--------------------------------|
| **auto** | High-confidence candidate: skip the queue only as a *suggestion*. Still not a hire decision. | Last + first match **and** both DOBs present and equal (score ≥ 90, no conflict). |
| **review** | Human must look. Typical when names agree but DOB is missing on one side, first names are initial-only, or the hit is an **aka** without DOB. | Last match plus first/first-initial, no DOB conflict (score 50–89). |
| **no-link** | Do not present as a match. | Last-name mismatch, DOB conflict, unparseable last names, or non-matchable `party_role`. |

DOB conflict is a hard block even when names match. Missing DOB never invents a date and never yields **auto**.

## Required provenance on every review card

The UI must persist and display these so an operator can join back to Bronze HTML without scraping:

| Field | Why |
|-------|-----|
| `source_system` | Which court adapter (`wcca`, …) |
| `state_code` | Dimension (`WI`, …) — no `wi_*` product prefix |
| `source_record_id` | Case grain (`51:2026CF000028` shape) |
| `ingest_run_id` | Bronze ingest that landed the payload |
| `payload_sha256` | Integrity / join-back to `bronze.court_case_raw.payload` |
| `party_role`, `party_ordinal` | `court_party` MERGE key |
| `score`, `band`, `reasons[]` | Why this card is auto / review / no-link |

Also show `raw_name` and labeled `dob` when present. Do not show a “hire” or “adverse action” control on this card.

`required_provenance()` in the sketch helper returns this dict for UI unit tests.

## Non-goals (explicit)

- No hire / no-hire decision
- No FCRA adverse-action copy, notices, or packages
- No automatic adverse action
- No bulk WCCA scrape, no weekly ingest, no Bronze writes
- No warehouse scoring job in this version (the Python helper documents examples only)
- No requirement that race, sex, or address participate in the score

## Synthetic examples

Names below are **fixtures**, not live defendants.

| Subject | Party | Band | Why |
|---------|-------|------|-----|
| Jane Q Fixture, DOB 2099-01-15 | defendant `FIXTURE, JANE Q`, DOB 2099-01-15 | **auto** | last + first + DOB |
| Jane Fixture (no DOB) | same defendant, DOB null | **review** | name match, `dob_absent` |
| Jane Fixture, DOB 2098-01-01 | same defendant, DOB 2099-01-15 | **no-link** | `dob_conflict` |
| Jane Fixture | plaintiff `State of Wisconsin` | **no-link** | `party_role_not_matchable` |
| Jane Aliasfixture | aka `ALIASFIXTURE, JANE` (no DOB) | **review** | alias row, no DOB |

Live Bronze grain `source_system=wcca`, `state_code=WI`, `source_record_id=51:2026CF000028` is expected to yield **plaintiff 1**, **defendant 1**, **aka N** (N = also-known-as lines on that snapshot). Do not copy live names, DOB, or address into git or into this doc.

## UI notes for Uma

1. Filter `court_party` to `party_role IN ('defendant','aka')` before scoring.
2. One subject can produce several cards (defendant + each aka). Keep provenance per card.
3. **auto** is a default sort / collapse hint, not an automated employment action.
4. Join `court_case` with the same natural key for caption, filing date, and charges; join Bronze with `ingest_run_id` + `payload_sha256` to show the source HTML in-workspace.
5. Warehouse apply of `court_party` DDL/transform is coordinator-side; this sketch does not depend on Databricks being updated first if the UI is developed against synthetic party dicts.
