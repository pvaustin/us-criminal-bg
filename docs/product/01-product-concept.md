# Product concept — US criminal background verification (WI-first MVP)

**Status:** Draft for Prasanth review · 2026-09-15 (CT)  
**Owner:** PM Pam · **Tech sequencing:** Charlie CTO

## Who it’s for

**Primary beachhead (locked 2026-09-15):** Wisconsin employers and their HR / hiring managers running pre-hire checks.

**Other personas (see `05-market-personas.md`):**
- Recruiters / staffing agencies — **Next** (volume packaging on the same WI data)
- Individuals (self-check) — **Later** (separate UX; same dockets, different product)

GTM copy and MVP flows are employer-shaped. Beachhead lock does not change AC1→AC3.

## Problem

Hiring teams need a fast, honest read on whether a candidate appears in **Wisconsin circuit court criminal dockets** before they advance a hire. Today that means manual WCCA hunting, unclear provenance, and no durable audit of what was searched.

## Value proposition

Give employers a **labeled, auditable WI docket lookup** — search a subject, see case/charge material with provenance, and (next) resolve party matches with human review — without pretending the product is certified criminal history or a finished FCRA CRA.

## What “verification” means here

| We mean | We do **not** mean |
| --- | --- |
| WCCA-sourced court **dockets** (cases, charges, parties when extractable) | Certified criminal history |
| Provenance back to source snapshots | Hire / no-hire recommendation |
| Match confidence + human review when identity is ambiguous | A consumer reporting agency product (yet) |
| Empty / no-link results stated plainly | Invented or demo-as-real records |

**Standing product line:** dockets ≠ certified criminal history. No hire/no-hire UI. No CRA / adverse-action claims until you and Charlie decide that path.

## Non-goals (MVP)

- Multi-state coverage
- Automated hire decisions
- Certified records or full FCRA CRA packaging
- Weekly free-site ingest (paused until you enable)
- Paid bulk / high-volume PII on personal Databricks/GitHub accounts
- Company account cutover (planned **before** paid employers / high-volume PII)

## MVP slice

**National product ambition; Wisconsin employer beachhead.** Pipeline: court sources → Databricks Bronze → Silver → employer-facing website. Near-term product center of gravity: **party match/review** (auto / review / no-link + provenance), not guaranteed DOB-backed identity resolution.

## Pilot data (2026-09-16)

Pilot includes **WI WCCA** and **SF HF named corpus** for match/review. Beachhead remains WI employers/HR — SF is in-pilot data, not a second GTM beachhead. VA VirginiaCourtData joins when free research access is approved (non-blocking). Always label provenance; never claim certified criminal history.

## Success for a non-paying pilot

An operator can place a subject, see honest WI docket material with provenance, resolve ambiguous party matches in a review queue, and leave an audit trail of who searched what and when — all with compliance labels that refuse overclaiming.
