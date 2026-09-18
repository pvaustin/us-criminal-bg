# Gold naming and serving layout (national-first)

**Owner:** silva silver (this MVP slice) / Uma (report, `/review`, `/metrics` reads)  
**Upstream:** silva silver (`docs/silver/NAMING.md`) — Gold **reads** Silver; it never writes Silver or Bronze  
**Repo:** https://github.com/pvaustin/us-criminal-bg  
**Databricks workspace (non-secret):** `dbc-a0dcbe75-2647.cloud.databricks.com` (workspace ID `7474648418210162`)

This doc is the durable contract for Gold identifiers and serving transforms. **Gold is the serving layer. Silver is the truth / clean layer.** Do not treat Gold as a second court-fact store, a hire engine, or a place to invent records.

Warehouse apply is **coordinator-side**. This repo does not run Databricks.

Live Silver reality this MVP is built against (workspace proof 2026-09-17; **counts and keys only**, no live names / DOB / street):

| Silver object | WI `wcca` | SF `sf_criminal_hf` / `CA` |
|---------------|-----------|----------------------------|
| `court_case` | **1** | **0** |
| `court_charge` | **8** | **0** |
| `court_party` | **6** (plaintiff 1 + defendant 1 + aka 4) | **77,399** defendant parties |
| `match_decision` | **0** | **40** `review` / `suggestion` (`experiment_tag=sf_name_only_research`); **auto = 0** |
| `order_subject` | DDL in repo, **not live** | same |
| `search_audit` | DDL in repo, **not live** | same |

Gold must **tolerate missing** `order_subject` / `search_audit` (empty scratch + match_decision subject fallback). SF case/charge **nulls are honest** — do not invent `court_case` / `court_charge` rows to fill the report.

## Principles

1. **National-first.** Catalogs, schemas, top-level repo folders, and job names describe the US court-source product. Do not make `wi` (or any state) the only top-level product prefix. No `wi_*` / `ca_*` / `sf_*` product tables, catalogs, or schemas.
2. **State and source as dimensions.** Persist `state_code` (ISO-3166-2 subdivision without country, e.g. `WI`, `CA`) and `source_system` (`wcca`, `sf_criminal_hf`). Both WI and SF are **in the pilot**; keep provenance columns on every serving row. UI filter WI vs SF = those two columns, not separate tables.
3. **Serving, not truth.** Silver cleanses and types court facts plus append-only decisions. Gold **projects** those facts into UI-shaped snapshots (`order_report`, `match_queue`, `source_coverage_metrics`). Re-running Gold must not change Silver. If Gold and Silver disagree, **Silver wins** — refresh Gold.
4. **Do not invent court facts.** Join `court_case` / `court_charge` when the Silver row exists. If it does not (SF research path today), leave case/charge fields null / zero / empty arrays and set honest flags (`has_court_case=false`, `has_court_charge=false`). Never copy a WI case onto an SF party. Never fabricate a subject to fill WI report rows.
5. **No hire / no-hire / risk scores.** Gold must not add employment decisions, FCRA packages, adverse-action copy, or numeric “risk” scores. Match **confidence bands** (`auto` / `review` / `no-link`) are review-queue labels copied from Silver, not hiring signals. `auto` is still not silent auto-link.
6. **Idempotent refresh.** Re-running the same Silver keys must converge on one current Gold row per serving grain. `order_report` and `match_queue` are type-1 snapshots (`CREATE OR REPLACE`). `source_coverage_metrics` MERGEs the calendar `as_of_date` so same-day reruns overwrite and other days remain.
7. **Never scrape. Never mutate Bronze or Silver.** Transforms consume already-landed Silver only.
8. **No live PII in git.** Tests use synthetic fixture names (`JANE Q PUBLIC`, `FIXTURE, JANE Q`). Coordinator prove reports **counts + keys**, not full names / DOB / street.
9. **Defer `party_name_index`.** The serving tables join `court_party` on the existing natural key / `party_key`. Do not add a name index for this MVP.
10. **Warehouse SQL is statement-at-a-time.** Use durable Delta scratch tables (`CREATE OR REPLACE TABLE … USING DELTA`). Do **not** use `TEMP VIEW` (the warehouse `/api/2.0/sql/statements` apply drops them between statements).

## Unity Catalog / object names

| Layer | Name | Notes |
|-------|------|--------|
| Catalog | `us_criminal_bg` | Same product catalog as Bronze / Silver |
| Schema | `gold` | All Gold serving tables |
| Volume | *(none for MVP)* | Payloads stay in Bronze |

Do **not** create `wi_*` catalogs/schemas.

### Tables (serving MVP)

| Table | Purpose | Grain |
|-------|---------|-------|
| `us_criminal_bg.gold.order_report` | One read for the employer **report UI**: subject/order identity + linked party + case/charge summary + latest match band + latest human decision + provenance + as-of timestamps | `(subject_ref, party_key)` |
| `us_criminal_bg.gold.match_queue` | **Open** review cards only for `/review` (no full `match_decision` scan) | `(subject_ref, party_key)` among **open** cards |
| `us_criminal_bg.gold.source_coverage_metrics` | Refreshable counts for `/metrics` | `(as_of_date, state_code, source_system)` |

`search_audit` is **not** a Gold input for this MVP (table not live; not required for these grains).

### Tables (name-match eval — research, not UI serving)

Human-labeled eval for `sf_name_match_v1`. **Suggestions are not GT.** Contract: [`NAME_MATCH_EVAL.md`](NAME_MATCH_EVAL.md) · operator: [`ml/name_match/README.md`](../../ml/name_match/README.md).

| Table | Purpose | Grain |
|-------|---------|-------|
| `us_criminal_bg.gold.name_match_eval` | Latest **human** SF `match_decision` mapped to `link` \| `reject` \| `leave_in_review`. Empty when N_human=0 (honest). | `(subject_ref, party_key)` among humans |
| `us_criminal_bg.gold.name_match_label_pack` | Unlabeled worksheet: open SF `match_queue` cards + hard-negative distractors (existing `court_party`, different last name). `label` NULL. | `(subject_ref, party_key)` in one pack refresh |

Live 2026-09-18: **0** human rows, **40** suggestion/`match_queue` cards. Eval starts empty; pack is built from those 40 + distractors. Not a hire engine.

## Layering

```
Bronze  raw / near-raw payloads + lineage     (brian bronze)
   ↑ never write
Silver  current court facts + append decisions (silva silver)  ← truth / clean
   ↑ never write
Gold    UI-shaped snapshots                    (this slice)     ← serving
```

| Question | Answer from |
|----------|-------------|
| What did the court source say? | Silver `court_*` (join back to Bronze payload by key / sha256) |
| What did a reviewer / suggester decide? | Silver `match_decision` (append-only) |
| What should the report / review / metrics UI read? | Gold |

Uma should prefer Gold for list/detail serving. Drill-in to Silver when a card needs a fact Gold did not project. Do not treat Gold as a court archive.

## Grains (chosen)

### `order_report` — `(subject_ref, party_key)`

**Why this grain, not `(order_id, subject_ref, party_key)`.**  
`silver.order_subject` is DDL-only and **not live**. `order_id` cannot be a required grain key. `subject_ref` is the stable review id (`ORDER_AUDIT.md`). `party_key` is the review-card id (`MATCH_REVIEW.md`). Together they are the smallest serving row the report UI can fetch in one read: this subject, this party card, plus joined case/charge **when Silver has them**.

**Driver of rows.** Distinct `(subject_ref, party_key)` that already exist on `silver.match_decision` (latest row per pair after the rank rule below). Gold does **not** invent a subject for WI’s 1 case / 6 parties when no `match_decision` (and no live `order_subject`) exists. Expected live prove: **SF fat** (~40 report rows from the 40 suggestion cards, minus any duplicate keys); **WI thin** (**0** `order_report` rows until a subject is decided or `order_subject` is live and a later slice adds unmatched-order rows).

**`order_id` is an attribute, not the grain.** When `silver.order_subject` exists, LEFT JOIN on `subject_ref` fills `order_id` / order status / subject snapshot. When the table is missing, those columns stay null and `subject_name` / `subject_dob` fall back to the latest `match_decision` row (`subject_source='match_decision'`).

**SF case/charge gap.** `case_report_key` is still `source_system|state_code|source_record_id` (existing case grain — not a new identity). `has_court_case=false`, case attribute columns null, `has_court_charge=false`, `charge_row_count=0`, charge arrays empty. Party + match still serve.

**Current band vs human overlay.** Rank `match_decision` per `(subject_ref, party_key)` by `decided_at DESC`, then **prefer `review_status='human'` on timestamp ties**, then `decision_id DESC`. That latest row is `latest_*` / `current_*`. Separately, the latest `review_status='human'` row (if any) is `human_*`. A later human append **closes** the queue card even though the suggestion row remains in Silver (append-only).

**`is_open_review`.** Copied from the `match_queue` open rule so the report UI does not reimplement it.

No hire flag. No new person-id / FCRA package key. Attach remains existing case/charge keys only.

### `match_queue` — open cards only

**Open definition (normative):**

> Take the latest `match_decision` row per `(subject_ref, party_key)` using the rank rule above. The card is **open** iff that latest row has `review_status='suggestion'` **and** `confidence_band IN ('review','auto')`. A later **human** append (`review_status='human'`) closes it. Latest `no-link` (any `review_status`) is not queued.

This is the `/review` serving set. It is **not** a scan of every historical suggestion. `auto` still appears as a card (sort hint only — not silent auto-link, not a hire).

**Age.** `age_hours` = fractional hours from `decided_at` to Gold `refreshed_at` (double, not truncated).

**WI vs SF filter.** `WHERE source_system = 'wcca' AND state_code = 'WI'` vs `WHERE source_system = 'sf_criminal_hf' AND state_code = 'CA'`. Expected live prove: SF ~40 open cards (until humans append); WI **0**.

### `source_coverage_metrics` — `(as_of_date, state_code, source_system)`

Refreshable counts. **Include both pilot sources even when one has zero cases** (SF today: `case_count=0`, `party_count≈77399`). Universe = explicit pilot pair union distinct keys from `court_case`, `court_party`, and `match_decision`:

| `source_system` | `state_code` | Pilot label (UI only) |
|-----------------|--------------|------------------------|
| `wcca` | `WI` | WI |
| `sf_criminal_hf` | `CA` | SF |

Do not create a `pilot_label` column that could be mistaken for a verdict; the UI maps provenance → WI | SF.

| Metric | Definition |
|--------|------------|
| `case_count` | `count(*)` on `silver.court_case` for that source |
| `party_count` | `count(*)` on `silver.court_party` |
| `nonempty_name_count` | parties whose `trim(raw_name) <> ''` |
| `suggestion_row_count` | **volume**: all `match_decision` rows with `review_status='suggestion'` (not distinct cards) |
| `open_review_count` | distinct open cards (same rule as `match_queue`) |
| `closed_review_count` | distinct `(subject_ref, party_key)` whose **latest** row is `review_status='human'` |

Same-day re-run MERGEs on `(as_of_date, state_code, source_system)`. `refreshed_at` moves.

## Natural keys and SCD

| Table | Natural key | SCD |
|-------|-------------|-----|
| `order_report` | `(subject_ref, party_key)` | Type-1 snapshot replace |
| `match_queue` | `(subject_ref, party_key)` | Type-1 snapshot replace (open subset only) |
| `source_coverage_metrics` | `(as_of_date, state_code, source_system)` | Daily MERGE (type-1 within a date) |
| `name_match_eval` | `(subject_ref, party_key)` among latest SF humans | Type-1 snapshot replace (empty when N_human=0) |
| `name_match_label_pack` | `(subject_ref, party_key)` in a pack refresh | Type-1 snapshot replace (unlabeled) |

`party_key` format (unchanged from Silver): `source_system|state_code|source_record_id|party_role|party_ordinal`  
`case_report_key` format: `source_system|state_code|source_record_id`

## Missing Silver tables

| Table | Live? | Gold behavior |
|-------|-------|----------------|
| `court_case` / `court_charge` / `court_party` / `match_decision` | yes (thin WI / fat SF as above) | Required inputs |
| `order_subject` | **not live** | `CREATE TABLE IF NOT EXISTS` empty Delta scratch `_gold_order_subject_src`; LEFT JOIN. Optional [`gold/transforms/order_subject_src_from_silver.sql`](../../gold/transforms/order_subject_src_from_silver.sql) when Uma creates the table. Python `--apply` try-or-skip. |
| `search_audit` | **not live** | **Not read.** Documented skip. |
| `party_name_index` | n/a | **Not used.** |

## Lineage (Silver → Gold)

Gold copies identifiers and serving attributes. Raw **payload stays in Bronze**. Join back with `(source_system, state_code, source_record_id)` and/or `ingest_run_id` + `payload_sha256`.

Silver-owned columns Gold may project (not modify):

- Provenance: `source_system`, `state_code`, `source_record_id`, `ingest_run_id`, `payload_sha256`, `transform_run_id`
- Party display: `raw_name`, name parts, `party_role`, `party_ordinal`, `dob` (null on SF)
- Case display: `county_code`, `case_number`, `case_type`, `filed_date`, `caption`, `case_status`, `county_name`
- Charge summary: `charge_count`, `statute`, `description`, `severity` aggregated **in charge_count order**
- Decision: `confidence_band`, `score`, `reasons`, `score_or_reason_codes`, `review_status`, `experiment_tag`, `actor`, `decided_at`, `notes`

Gold-owned columns:

| Column | Meaning |
|--------|---------|
| `gold_schema_version` | e.g. `gold.order_report.v1` |
| `refreshed_at` | Gold write time (UTC) |
| `as_of_date` | Calendar date of a metrics snapshot (`current_date()` at refresh) |
| `has_court_case` / `has_court_charge` / `party_row_present` / `order_subject_table_present` | Honest presence flags |
| `charge_row_count` + charge arrays | Aggregated; `0` / `array()` when none |
| `age_hours` | Queue freshness |
| `subject_source` | `order_subject` \| `match_decision` |
| `is_open_review` | Matches `match_queue` open rule |
| `current_confidence_band` / `current_review_status` | From the latest ranked `match_decision` row |

## DQ / honesty rules

1. Natural-key columns on each Gold table are NOT NULL.
2. Missing Silver facts → null column or empty array / zero count + a boolean flag. **Do not default** case numbers, charges, names, or DOB.
3. `dq_flags` copied from Silver stay as-is (never SQL NULL on those arrays when the Silver row exists; Gold uses `CAST(array() AS ARRAY<STRING>)` when the join missed).
4. Transforms must not INSERT/UPDATE/DELETE `us_criminal_bg.bronze.*` or `us_criminal_bg.silver.*`.
5. Do not persist hire / no-hire / risk / adverse-action columns.

## Repo layout (national-first)

```
docs/
  gold/NAMING.md          ← this file (contract)
  gold/ACCESS.md          ← serving access + coordinator prove
  gold/NAME_MATCH_EVAL.md ← sf_name_match_v1 human labels (not UI serving)
  silver/NAMING.md        ← truth / clean contract (Gold reads this)
gold/
  schemas/                ← Unity Catalog DDL (serving + name-match eval)
  transforms/             ← Spark SQL + Python refresh from Silver
  transforms/tests/       ← synthetic fixtures only
  jobs/README.md          ← how to apply (operator)
ml/name_match/            ← human-eval MLflow entry (held-out human only)
```

## Out of scope (do not put in Gold)

- Invented or hallucinated court records (including SF `court_case` / `court_charge`)
- Hire / no-hire, risk scores, FCRA adverse-action packages
- `party_name_index` (deferred)
- Silent auto-link or employment action on `auto` bands
- Scraping WCCA / SF court sites; mutating Bronze or Silver
- Secrets, PATs, cookies, CAPTCHA tokens, live PII in git
- Databricks apply of DDL/transform by the cloud agent that opened this PR (operator applies in-workspace)
- A fourth **serving** Gold table for report / `/review` / `/metrics` (name-match eval tables are research, not UI serving)
- Person-id graph, or new report identity grain

## Versioning

Bump `gold_schema_version` when Gold columns or open-queue / metrics vocabularies change. Append a short changelog below.

### Changelog

- `2026-09-18` — `name_match_eval.v1` + `name_match_label_pack.v1` for `sf_name_match_v1`. Human-only labels (`link`/`reject`/`leave_in_review`). Suggestions are not GT. Live N_human=0 → empty eval + unlabeled pack from 40 open SF cards.
- `2026-09-18` — Initial Gold MVP: `order_report.v1`, `match_queue.v1`, `source_coverage_metrics.v1`. Serving snapshots over live Silver (thin WI, fat SF parties, 40 SF review suggestions). `order_subject` / `search_audit` tolerated as missing.
