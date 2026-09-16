# Strategy notes — pilot → scale, compliance posture

**Status:** Draft for Prasanth review · 2026-09-15 (CT)  
**Owner:** PM Pam · **Infra / accounts:** Charlie CTO

## Ambition vs slice

**Ambition:** US national criminal background verification for hiring.  
**Slice:** Wisconsin WCCA only until you expand. Ship depth in one state before breadth.

## Two supply paths

| Path | Role |
| --- | --- |
| **Free WCCA** | Proof path — learn extraction, Silver shape, UI honesty, match/review. Weekly ingest **paused**; bulk free-site **deferred**. |
| **Paid WCCA API** | Scale path for more WI volume when pilot proves the product loop. |

Do not conflate “we can scrape” with “we should run weekly.” Enable is your call.

## Accounts and PII

- **Now:** personal GitHub + personal Databricks OK for a **non-paying, labeled pilot**.
- **Before paid employers or high-volume PII:** cut over to company accounts (Charlie-owned plan).
- Personal stack constraints Charlie already flagged: Free Edition quirks, one-off CLI/SQL ETLs (not Jobs yet), web live path needs server token/OAuth — acceptable for pilot, not for paid volume.

## Compliance posture (product)

Non-negotiables in every surface and doc:

1. **Dockets ≠ certified criminal history** — say it in UI and sales language.
2. **No hire / no-hire** — we surface material; humans decide employment.
3. **No CRA / adverse-action claims** until you explicitly take that path with Charlie.
4. **No invented records** — empty and no-link are valid outcomes.
5. Match UI shows **ambiguity**; confidence + human review for anything that looks like a consumer-report-style match.

Final FCRA wording: **you + Charlie + Pam**. Uma ships placeholders until then. No hard tech blocker for a labeled pilot; hard **product** blocker is overclaiming.

## Buyer / beachhead strategy (locked)

Persona pack: `05-market-personas.md`.

**Locked primary beachhead (2026-09-15):** Employers — WI HR / hiring managers (**A**).

| Persona | Horizon |
| --- | --- |
| Employers (HR / hiring managers) | **Now** — locked beachhead |
| Recruiters / staffing | **Next** after employer loop works |
| Individuals (self-check) | **Later** — don’t bend MVP |

Messaging and MVP flows are employer-shaped. Does **not** change AC1→AC3 or Uma AC2.

## How we work

- Pam: problem framing, roadmap, MVP scope, prioritization, acceptance criteria, GTM readiness language.
- Charlie: tech plan, secrets/least-privilege, builder sequencing.
- Pam does **not** fan out tasks to Brian / Silva / Uma unless Charlie agrees or you say drive it directly.

## Asks for you (strategy only)

1. Lock **buyer** (A / B / C or write-in).  
2. Any preference on **when** to prioritize paid WCCA API vs staying on free proof path longer?  
3. Any hard “never claim X” language you want frozen before pilot demos?
