# SF name-match ranking (`sf_name_match_v1`)

Research-only MLflow experiment that trains a **small name-match scorer / ranker** for subject → `us_criminal_bg.silver.court_party` (`source_system=sf_criminal_hf`, `state_code=CA`).

It compares that scorer to today’s **MATCH_REVIEW rule baseline** (exact last+first ≈ **70** `review`; first-initial ≈ **55** `review`). SF parties have **no DOB**, so `auto` is unreachable and **human review stays required**.

This package does **not**:

- emit hire / no-hire or “risk” scores
- auto-link parties or change Uma
- write `silver.match_decision` (no product wiring)
- invent court cases, charges, DOB, plaintiffs, or AKA rows
- use `system:suggestion` queue cards as link labels
- touch the WI WCCA path except a read-only import of the shared sketch scorer

National-first names: catalog `us_criminal_bg`, source `sf_criminal_hf`, state as dimension `CA`.

## Why labels are weak

Live warehouse (see `docs/silver/SF_MATCH_EXPERIMENT.md`):

| Item | Count | Use as ML label? |
|------|------:|------------------|
| SF name-only `court_party` defendants | ~77,399 | **Name strings only** (features / synthetic pairs) |
| Human `match_decision` (`review_status=human`) | **0** | Would be labels if they existed |
| `actor=system:suggestion` queue cards | ~40 | **No.** Those are review-queue candidates, not link/reject ground truth |

Until humans append link/reject rows, training is **weakly supervised + synthetic**:

- **positives** — exact same name string, or light format variants (case, comma vs space, dropped middle) built from real SF name *strings*
- **near-duplicate negatives** — same last name, different first
- **hard negatives** — different last names

Pair-level labels only. **Do not claim these are human ground truth.** Variants are not new court rows.

## Human eval (held-out `link` / `reject`)

Gold tables: [`docs/gold/NAME_MATCH_EVAL.md`](../../docs/gold/NAME_MATCH_EVAL.md).

| Item (2026-09-18) | N | In GT metrics? |
|-------------------|--:|----------------|
| Human `match_decision` | **0** | n/a |
| `gold.name_match_eval` | **0** (honest empty) | `link`/`reject` only |
| Suggestion / `match_queue` cards | **40** | **No** |
| `gold.name_match_label_pack` | ~40 open + hard negatives | unlabeled (`label` NULL) |

Label mapping from latest human `match_decision` band:

| Human band | Eval label | GT? |
|------------|------------|-----|
| `auto` | `link` | yes (explicit human confirm) |
| `no-link` | `reject` | yes |
| `review` | `leave_in_review` | **exclude** |

### How to generate more labels

1. Coordinator applies eval/pack DDL and refreshes `gold.match_queue`, then `gold.name_match_label_pack` (open SF cards + different-last-name `court_party` distractors; empty `label`).
2. Uma `/review`: append `silver.match_decision` with `review_status='human'` (`auto` = link, `no-link` = reject, `review` or skip = leave_in_review).
3. Refresh `gold.name_match_eval`.
4. `python3 ml/name_match/eval_human.py` (or `train.py --human-eval`).

### MLflow

```bash
python3 ml/name_match/train.py --human-eval
python3 ml/name_match/eval_human.py
```

Same experiment `/Shared/us_criminal_bg_name_match`. Tags: `human_eval=true`, `sf_name_match_v1_human=true`. Nested `rule_baseline` / `logistic` / `lightgbm` on **held-out human pairs only**. Does not mix synthetic GT.

**N=0 (today):** logs `n_human=0`, `n_gt=0`, `synthesized=0` and exits 0. No fake PR-AUC.

**N small:** if fewer than 4 train queries after a held-out split, score `rule_baseline` only. Do not claim logistic/LightGBM beats the baseline.

## MLflow

Workspace tracking requires an **absolute path**. Bare `us_criminal_bg_name_match` is rejected (`INVALID_PARAMETER_VALUE`).

| | |
|--|--|
| Physical experiment (`mlflow.set_experiment`) | `/Shared/us_criminal_bg_name_match` |
| Logical alias (Charlie; tag `experiment_alias` / `logical_experiment_name`) | `us_criminal_bg_name_match` — **not** a `set_experiment` name |
| Optional Unity Catalog override | `us_criminal_bg.ml.us_criminal_bg_name_match` (needs schema `us_criminal_bg.ml`; pass explicitly) |
| Run tag | `sf_name_match_v1` |

Coordinator may pre-create `/Shared/us_criminal_bg_name_match`. The job rewrites the logical alias to that path if someone passes the bare name on the CLI.

Parent run + nested runs in the **same** experiment:

1. `rule_baseline` — MATCH_REVIEW sketch integer as rank score (DOB forced absent)
2. `logistic` — sklearn `LogisticRegression` when present, else numpy logistic
3. `lightgbm` — `LGBMClassifier` used as a pairwise scorer when the package is installed

Tags on every run: `sf_name_match_v1=true`, `experiment_alias=us_criminal_bg_name_match`, `not_hire_signal=true`, `not_auto_link=true`, `dob_used=false`, `uma_wired=false`.

### Metrics logged (each scorer)

Prefix `baseline_`, `logistic_`, `lightgbm_`:

- `pr_auc`, `average_precision`, `map`
- `precision_at_{1,3,5,10}`, `recall_at_{1,3,5,10}`
- `n_pairs`, `n_positive`
- **Review-band slice** (`review_band_*`): same metrics on pairs the rule would put in `review` (score ≥ 50). This is ranking quality *inside* today’s queue policy, not a new auto-link band.

Dataset params / metrics on the parent: `n_source_names`, `n_pairs`, `n_human_labels` (expect 0), `n_suggestion_cards_ignored` (expect ~40 on live), `uses_dob=false`.

No live names, DOB, or street are logged as artifacts.

## How to run on Databricks

Spark is **optional**. Training is driver-local (`sklearn` / `lightgbm` / numpy). Prefer a **job cluster, serverless, or notebook**; the workspace SQL warehouse can pull names when no cluster is up.

From the repo root (repo on `sys.path`):

```bash
# Live SF name strings via Spark (job cluster / notebook)
python3 ml/name_match/train.py --from-silver

# Live SF name strings via SQL warehouse (no cluster)
python3 ml/name_match/train.py --from-silver --warehouse-id $DATABRICKS_WAREHOUSE_ID

# Fixture-only dry run (no warehouse, no PII)
python3 ml/name_match/train.py --synthetic --no-mlflow
```

Databricks job task: **Python** / Spark Python, file `ml/name_match/train.py`, parameters `--from-silver`. Cluster libraries if missing from the runtime: `scikit-learn`, `lightgbm` (`mlflow` is preinstalled).

If `mlflow.set_experiment` fails with parent-directory `NOT_FOUND`:

```bash
databricks workspace mkdirs /Shared
```

The coordinator may pre-create the experiment at `/Shared/us_criminal_bg_name_match`. Do **not** call `set_experiment("us_criminal_bg_name_match")` (no leading slash).

To use the UC experiment instead (explicit override only):

```bash
python3 ml/name_match/train.py --from-silver \
  --experiment-name us_criminal_bg.ml.us_criminal_bg_name_match
```

`--max-names` defaults to 5000 for a small first run; raise it to use more of the ~77k names. The job still must **not** cartesian-score 77k × 77k — pairs are built per source name (self / variants / a few negatives).

## Features (no DOB)

`exact_last`, `exact_first`, `first_initial_match`, `exact_raw_norm`, token Jaccard / overlap, Jaro–Winkler on raw / last / first, Soundex-style last / first match, token counts + abs diff, comma vs space flags, last/first character lengths, both-have-middle.

Rule baseline is the existing sketch (`silver/transforms/match_review_sketch.py`), with DOB forced null so SF name-only behavior is preserved.

## Tests (synthetic names only)

```bash
python3 -m unittest discover -s ml/name_match/tests -v
python3 ml/name_match/train.py --synthetic --no-mlflow --skip-lightgbm
python3 ml/name_match/train.py --human-eval --no-mlflow
```

Fixtures reuse documented names (`JANE Q PUBLIC`, `JOHN MARSHALL FIXTURE`, …). They are **not** live defendants.

## Out of scope

Uma UI, auto-link, FCRA / adverse action, hire scores, WI `sources/wcca` / `court_case` transforms, inventing SF `court_case` / `court_charge` rows, committing live PII.
