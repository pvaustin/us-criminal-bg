# Pilot contract — `order_subject` + `search_audit` (AC3)

**Owner:** silva silver (schema) / Uma (web writes)  
**Catalog:** `us_criminal_bg.silver`  
**DDL:** [`silver/schemas/order_subject.sql`](../../silver/schemas/order_subject.sql) · [`silver/schemas/search_audit.sql`](../../silver/schemas/search_audit.sql)  
**Related:** [`MATCH_REVIEW.md`](MATCH_REVIEW.md) (`match_decision`, review queue) · [`SF_MATCH_EXPERIMENT.md`](SF_MATCH_EXPERIMENT.md) · [`COURT_PARTY.md`](COURT_PARTY.md)

Pilot tables so Uma can persist the **employer order subject** and an **auditable search log**. This is not a court-fact transform. It does **not** scrape, does **not** invent court records, does **not** add a scoring job, and does **not** produce hire / no-hire or FCRA packages.

The web app may `CREATE TABLE IF NOT EXISTS` (same pattern as `match_decision`). Warehouse apply of this DDL is **operator-side**; the cloud agent that opened this PR does **not** apply it. `match_decision` DDL lives in [`silver/schemas/match_decision.sql`](../../silver/schemas/match_decision.sql).

## Purpose

| Table | Grain | SCD |
|-------|--------|-----|
| `us_criminal_bg.silver.order_subject` | One **current** subject snapshot per employer `order_id` | Type-1 overwrite |
| `us_criminal_bg.silver.search_audit` | One row per search/match **attempt** | Always **append** |

`subject_ref` is the stable id used by `/review/[subjectRef]`. Prefer uniqueness so review routing has one subject per ref. `order_id` is the natural key of `order_subject`.

Readable via `/audit` UI and SQL. Join later `match_decision` rows on `subject_ref`. Join returned parties on `party_key` → `court_party`.

## Non-goals (explicit)

| Out of scope | Why |
|--------------|-----|
| Hire / no-hire columns or UI | Pilot audit of search, not an employment decision |
| FCRA package / adverse-action copy | Out of this slice |
| Secrets, tokens, cookies, PATs | Never in logs or git |
| Full court payloads / Bronze HTML | Stay in Bronze; log summaries + `party_key`s only |
| Invented DOB or court records | Name as entered; DOB null when absent |
| Scoring / match jobs | Review bands stay in `MATCH_REVIEW.md`; this table logs attempts |
| Scrape / HTTP to WCCA | No live court fetch from these tables |
| Bronze writes | No INSERT/UPDATE/DELETE on `us_criminal_bg.bronze.*` |

## `us_criminal_bg.silver.order_subject`

One current subject snapshot per order (employer order id). Re-save the same `order_id` **overwrites** the current row (`updated_at` moves). Do **not** append a history of subjects here — search snapshots belong in `search_audit`.

**Natural key:** `order_id`. **`subject_ref` unique preferred** for `/review/[subjectRef]`.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `order_id` | `STRING` | NOT NULL | App-generated UUID. Natural key. |
| `subject_ref` | `STRING` | NOT NULL | Stable ref for `/review/[subjectRef]`. Unique preferred. |
| `subject_name` | `STRING` | NOT NULL | Required; **as entered**. Do not invent or normalize into a court caption. |
| `subject_dob` | `DATE` | null | Optional. **Null when absent** (honest). Never infer. |
| `created_at` | `TIMESTAMP` | NOT NULL | UTC |
| `created_by` | `STRING` | NOT NULL | Pilot operator id or email string |
| `updated_at` | `TIMESTAMP` | NOT NULL | UTC |
| `status` | `STRING` | NOT NULL | Pilot: `draft` \| `submitted` \| `in_review` |

No hire flag, no FCRA package key, no court `source_record_id` on this table.

## `us_criminal_bg.silver.search_audit`

Append-only log of **every** search/match attempt (including empty, error, and no-matchable-parties). **Never** store secrets, tokens, or full court payloads.

**Identity:** `audit_id` (UUID per append). Always **append**. Never UPDATE/DELETE a prior attempt. Never type-1 overwrite.

| Column | Type | Null | Notes |
|--------|------|------|-------|
| `audit_id` | `STRING` | NOT NULL | UUID per append |
| `order_id` | `STRING` | null | Null if the search started **outside** an order |
| `subject_ref` | `STRING` | NOT NULL | Same ref as review routing |
| `initiated_by` | `STRING` | NOT NULL | Pilot operator id or email |
| `initiated_at` | `TIMESTAMP` | NOT NULL | UTC |
| `subject_name` | `STRING` | NOT NULL | Snapshot **at search time** (as entered) |
| `subject_dob` | `DATE` | null | Snapshot; null if absent |
| `query_source_system` | `STRING` | null | e.g. `wcca` |
| `query_state_code` | `STRING` | null | e.g. `WI` (dimension, not a `wi_*` table) |
| `query_source_record_id` | `STRING` | null | Case grain searched, when known |
| `query_params_json` | `STRING` | null | Small JSON of **non-secret** query params |
| `result_status` | `STRING` | NOT NULL | `ok` \| `empty` \| `error` \| `no_matchable_parties` |
| `result_summary_json` | `STRING` | null | Counts by band, `party_key`s, error code. No secrets. Do not dump full PII beyond the subject snapshot + party keys / roles / bands. |
| `party_keys_returned` | `ARRAY<STRING>` | null | May be empty. Writers should persist `array()` rather than SQL NULL when the search ran and returned no parties. Databricks SQL requires `ARRAY<STRING>` (not bare `ARRAY`). |
| `error_message` | `STRING` | null | Honest short error; **never tokens** |

`result_status`:

| Value | When |
|-------|------|
| `ok` | Completed with one or more returned `party_key`s |
| `empty` | Completed with zero returned parties |
| `error` | Failed; fill `error_message` (no tokens) |
| `no_matchable_parties` | Completed but nothing matchable (e.g. plaintiff-only / `party_role_not_matchable`) |

Log empty and no-link outcomes. Do not omit attempts.

## What not to persist

- Secrets, session tokens, cookies, PATs, CAPTCHA tokens
- Full Bronze `payload` / HTML / court JSON
- Race, extra PII beyond the subject snapshot and returned `party_key` / role / band
- Hire / no-hire, FCRA notices, adverse-action text

## Create / apply

1. **Web app:** `CREATE TABLE IF NOT EXISTS` on first write is allowed (same pattern as `match_decision`).
2. **Warehouse:** operator may run the DDL files in `silver/schemas/`. This PR documents them only.
3. Confirm tables exist; do **not** treat a UI-only store as the system of record once Unity Catalog tables are live.

No transform job, no scoring job, no Bronze mutation.
