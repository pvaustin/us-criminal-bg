# WCCA HTML snapshot parseability (Silver)

**Owner:** silva silver  
**Parser:** `sources/wcca/parse.py`  
**Contract:** `docs/silver/NAMING.md`

This note is the durable list of what Silver **will** and **will not** read from Bronze `payload_format=html_snapshot` rows for `source_system=wcca`. It does not scrape. It does not invent court facts. Unit fixtures under `sources/wcca/tests/fixtures/` are **synthetic** and are not real court records.

## What the stored HTML is

Live WCCA case-detail snapshots already in Bronze are **server-rendered HTML**, not an empty React SPA shell and not a `__NEXT_DATA__` / `application/json` case blob.

After `<script>`, `<style>`, and tags are stripped, visible text includes labeled case facts. The parser is deterministic plain-text / regex on that stripped text (Python job) or the same labels via Spark `regexp_*` (SQL warehouse job).

JSON `application/json` script tags and well-known preload assignments are still honored when present. Explicit JSON keys win on overlap with SSR text. Live snapshots examined for this layer did **not** include those blobs.

## Parseable from SSR text

| Silver field | SSR signal | Notes |
|--------------|------------|--------|
| `county_name` | Title / heading `{caseNo} Case Details in {County} County` | County token only (not `county_code`, not a lookup table). Multi-word names such as `Green Lake` are kept. |
| `caption` | `State of Wisconsin vs. {Name}` | Full caption string. Stops before `Case summary` / `Filing date` (not an unrelated `<title>`). |
| `filed_date` | `Filing date MM-DD-YYYY` (optional colon) | Stored as ISO date. Example live label shape `01-09-2026` → `2026-01-09`. `/` separators accepted. |
| `case_status` | `Case status {text}` | Terminated at the next known label (Defendant, Charges, Count no., …). |
| `court_charge` rows | Header `Count no. Statute Description Severity Disposition` then `{n} {statute} {description} {severity}` | `charge_count` is the source count number. Statutes may have a trailing digit immediately after nested parens (`(hm)3`); digits inside the decimal are not a trail (`961.573(1)`). Descriptions may contain `>` (e.g. `&gt;10-50g`). Severity is the exact grid token (`Misd. A`, `Felony D`), not expanded. Optional following `Modifier: {statute} {text}` → `modifier_statute` / `modifier_text` (Python path). |
| `case_type` | **Not** the SSR `Case type Criminal` label | Still the CCAP two-letter code derived from `case_number` (e.g. `CF`). |

`payload_parse_status = html_ssr_v1` only when **caption**, **filed_date**, and **≥1 charge** all parse. Anything less from SSR is `html_ssr_partial`. Empty shells stay `identifiers_only`.

## Not parseable (leave null; do not invent)

- `__NEXT_DATA__` / preload JSON case objects (absent on the live snapshots)
- Empty SPA shells (`<div id="root">` + bundle only) — flag `unparsed_html_spa`
- Defendant DOB, sex, race, address, phone (PII; not Silver case/charge columns)
- Hearings, court officials, warrants, judgments, restitution, receivables
- Charge **disposition** text (header exists; not a `court_charge` column in this version)
- Additional `Modifier:` lines after the first (schema has one modifier pair per count)
- `Case type Criminal` as `court_case.case_type`
- County name from a `countyNo` lookup table
- Parties other than the caption string
- Any field not clearly present in identifiers, URL params, JSON keys, or the SSR patterns above

## DQ flags related to HTML

| Flag | When |
|------|------|
| `unparsed_html_spa` | `html_snapshot` and neither SSR case text nor a structured JSON embed was found |
| `missing_caption` / `missing_filed_date` | That column is null (omitted when the field parsed) |
| `missing_charges` | SSR case text was found but zero charge rows parsed |

Flags are omitted when they do not apply.

## Jobs

- **Python** (`silver/transforms/court_case.py --apply`): complete SSR parser, including charge modifiers.
- **Spark SQL** (`silver/transforms/court_case.sql`): same case-level labels and charge cores; `modifier_*` left null. Prefer Python when modifiers matter.
