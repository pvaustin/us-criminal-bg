# PRD sketch — WI MVP surfaces, objects, acceptance

**Status:** Draft for Prasanth review · aligned to Charlie AC tech-check  
**Owner:** PM Pam · **Builders (Charlie drives briefs):** Silva (Silver), Uma (web), Brian (Bronze, gated)

## Problem / outcome

Employer (default) can run a WI WCCA-sourced check on a hiring subject and get a labeled report path plus a match/review path when party identity is ambiguous.

## Surfaces (employer-facing + operator)

| Surface | MVP role | Notes |
| --- | --- | --- |
| **Order** | Create check; capture subject | Name required; DOB optional if present |
| **Consent** | Placeholder → productize later | After party match/review lands |
| **Report** | Case / charge / provenance | Live path + fixtures exist; source-key OK until matches exist |
| **Metrics** | Pilot health | Already present (`/metrics`) |
| **Match / review queue** | Resolve party ↔ subject | AC1 landed; Uma briefed for AC2 |
| **Status** | Thin stubs OK | Not a polish gate for this slice |
| **Dispute** | Deferred polish | After match/review |

## Data objects

| Object | Purpose |
| --- | --- |
| **Subject** | Person on the order (name; DOB optional) |
| **Case** | Court case from WCCA via Bronze→Silver |
| **Charge** | Charges on a case |
| **Party (`court_party`)** | Roles + names + lineage; 0–N per case |
| **Match decision** | Operator (or documented auto rule) link / reject / leave-in-review with confidence band |

## Match / review product rules

- Confidence bands: **auto / review / no-link** + provenance / reason codes.
- **Default MVP:** no silent auto-link unless Silva’s design doc documents a deterministic rule (e.g. exact-name + extra signal).
- UI must show ambiguity; never a binary hire control.
- Missing DOB is an honest signal, not a hard fail.

## Acceptance bar (locked with Charlie)

**Sequence:** AC1 → AC2 → AC3 · AC4 regression · AC5 standing gate.

### AC1 — Silva: `court_party` + match/review contract ✅
1. Silver exposes `court_party` (role, names, lineage/provenance to Bronze/WCCA).
2. Design doc: inputs (order subject name; DOB only if present), outputs (auto / review / no-link), stored evidence per band.
3. Missing DOB does not block review.
4. Contract names minimum review-queue fields: `party_id`/key, `party_role`, `raw_name` (+ normalized if present), `confidence_band`, `score_or_reason_codes`, `source_system`, `state_code`, `source_record_id`, lineage ids, link to case report route. Report-attach = existing case/charge keys only.
5. Live prove on `51:2026CF000028`; honest empty if HTML has no parseable party; don’t fail AC1 on other cases for empty parties.

### AC2 — Uma: review-queue UI (after AC1)
1. Show subject vs party candidates with band + provenance.
2. Persist link / reject / leave-in-review in **one named store** (`match_decision` in Databricks or web-side store — named in contract). Visible on reload. Single-operator OK; no full auth/RBAC for pilot.
3. No hire/no-hire; FCRA footer may be placeholder.
4. No silent auto-promote outside documented deterministic rules.

### AC3 — Subject on order + auditable search log
1. Order stores subject name (required) and DOB (optional).
2. Every search/match attempt logs who (operator id/email string), subject snapshot (name + optional DOB only), timestamp, query params, returned set (including empty / no-link). **No secrets in the log.**

### AC4 — Report view (regression)
Case/charge/provenance; explicit empty state; report-by-source-key remains valid until match decisions exist. Dispute / full consent productization out of this slice.

### AC5 — Brian gate
No new Brian work unless more Bronze samples are needed. Weekly/bulk stay paused.

## Out of scope (this PRD)

Multi-state, CRA claims, certified history, invented records, weekly enable, company cutover, paid high-volume on personal accounts.

## Product decision (locked)

**Primary beachhead:** Wisconsin employers / HR / hiring managers (locked 2026-09-15). Staffing = Next; individuals = Later.
