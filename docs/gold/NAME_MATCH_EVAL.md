# Name-match human eval (`sf_name_match_v1`)

**Owner:** silva silver (store + transform) / Uma (`/review` human appends)  
**Eval name:** `sf_name_match_v1`  
**Tables:** `us_criminal_bg.gold.name_match_eval` · `us_criminal_bg.gold.name_match_label_pack`  
**MLflow:** `/Shared/us_criminal_bg_name_match` (tags `human_eval=true`, `sf_name_match_v1_human=true`)  
**Code:** [`gold/transforms/name_match_eval.py`](../../gold/transforms/name_match_eval.py) · [`ml/name_match/`](../../ml/name_match/)

Research-only. **Not** a hire / no-hire / risk model. **Not** Uma model wiring. WI WCCA transforms are untouched. Warehouse apply is coordinator-side.

Live warehouse 2026-09-18 (counts + keys only; no live names / DOB / street):

| Item | N |
|------|---|
| `silver.match_decision` `review_status='human'` | **0** |
| `system:suggestion` / open `gold.match_queue` SF cards | **40** |
| Human GT (`link` + `reject`) | **0** |

**Suggestions are not ground truth.** An empty `name_match_eval` is the honest 2026-09-18 state. Do not invent human actors or court rows to fill it.

Operator how-to (DDL, pack, MLflow): [`ml/name_match/README.md`](../../ml/name_match/README.md).

## Label mapping (normative)

Latest **human** `silver.match_decision` row per `(subject_ref, party_key)` (`review_status='human'`). Rank: `decided_at DESC`, `decision_id DESC`. Scoped to `source_system='sf_criminal_hf'` and `state_code='CA'`.

| Human `confidence_band` | Eval `label` | In GT metrics? |
|-------------------------|--------------|----------------|
| `auto` | `link` | **yes** — human confirmed match. SF scorer cannot emit `auto` (party DOB absent); `auto` on a human append is an explicit confirm, not a silent auto-link. |
| `no-link` | `reject` | **yes** — human said this pair is not a match. |
| `review` (or any other / missing band) | `leave_in_review` | **no** — unlabeled / still in review; **exclude** from precision/recall. |

`review_status='suggestion'` rows (including the 40 live SF cards) are **dropped**. They never become `link` / `reject`.

Uma `/review` writes by **appending** a new `match_decision` row (`actor` = reviewer, `review_status='human'`). Do not UPDATE prior suggestion rows.

## Tables

### `name_match_eval`

Grain: `(subject_ref, party_key)` among latest SF humans. Type-1 snapshot (`CREATE OR REPLACE`). Empty when N_human=0.

Minimum columns: `subject_ref`, `party_key`, `label`, `source_system`, `state_code`, `labeled_at`, `actor`, `decision_id`, `confidence_band`, `experiment_tag`. Extra name/score columns are copied from the human decision so models can score without joining live PII into git.

### `name_match_label_pack`

Unlabeled worksheet. Grain: `(subject_ref, party_key)` in one refresh.

| `pair_kind` | Source |
|-------------|--------|
| `open_queue` | Open SF cards on `gold.match_queue` (same open rule as `/review`) |
| `hard_negative` | Same `subject_ref`, one existing `silver.court_party` row whose normalized last name **differs**. Not invented. |

`label`, `labeled_at`, and `actor` are **NULL**. Do not pre-fill from the scorer. Humans do not need to write this table: they append `match_decision` via `/review`, then refresh `name_match_eval`.

Refresh `gold.match_queue` before the pack.

## Non-goals

- Treating `system:suggestion` as GT
- Invented court rows or fake human actors
- Live PII in git
- Hire / risk / FCRA packages
- Uma model serving
- WI product scoring
