#!/usr/bin/env python3
"""Train / evaluate SF name-match scorers and log to MLflow.

Databricks job / notebook entry (Spark optional):

    python3 ml/name_match/train.py --from-silver
    python3 ml/name_match/train.py --from-silver --warehouse-id <id>
    python3 ml/name_match/train.py --synthetic --no-mlflow

Pulls SF `court_party` **name strings** (no DOB). Builds pair-level synthetic
labels (exact / near-positive / same-last different-first / different last).
Does **not** invent court cases or charges. Does **not** treat
`system:suggestion` queue cards as link labels. Does **not** write
`match_decision` or wire Uma. Human review stays required.

MLflow experiment: `us_criminal_bg_name_match`
  workspace path: `/Shared/us_criminal_bg_name_match`
  optional UC:    `us_criminal_bg.ml.us_criminal_bg_name_match`
Run tag: `sf_name_match_v1`

Logs rule-baseline metrics and model metrics in the **same** experiment
(parent run + nested `rule_baseline` / `logistic` / `lightgbm`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.name_match.baseline import rule_rank_scores, rule_review_mask  # noqa: E402
from ml.name_match.constants import (  # noqa: E402
    EXPERIMENT_NAME,
    FEATURE_NAMES,
    RUN_TAG,
    SOURCE_SYSTEM,
    STATE_CODE,
    UC_EXPERIMENT_NAME,
    WORKSPACE_EXPERIMENT_PATH,
)
from ml.name_match.dataset import (  # noqa: E402
    LabelInventory,
    NamePair,
    build_synthetic_pairs,
    filter_pairs,
    load_human_pairs,
    load_label_inventory,
    load_sf_party_names,
    pair_dicts,
    split_query_ids,
    summarize_pairs,
    synthetic_fixture_records,
)
from ml.name_match.features import matrix_from_pairs  # noqa: E402
from ml.name_match.metrics import evaluate_ranker, mlflow_metric_items  # noqa: E402
from ml.name_match.model import (  # noqa: E402
    FittedScorer,
    lightgbm_available,
    train_lightgbm,
    train_logistic,
)


def _try_spark() -> Any | None:
    try:
        from pyspark.sql import SparkSession
    except ImportError:
        return None
    try:
        return SparkSession.getActiveSession() or SparkSession.builder.getOrCreate()
    except Exception:  # noqa: BLE001
        return None


def _start_mlflow(
    *,
    experiment_name: str,
    enabled: bool,
) -> Any | None:
    if not enabled:
        return None
    try:
        import mlflow
    except ImportError:
        print("name_match: mlflow not installed; metrics will print only")
        return None
    tried = []
    for name in (
        experiment_name,
        WORKSPACE_EXPERIMENT_PATH,
        EXPERIMENT_NAME,
        UC_EXPERIMENT_NAME,
    ):
        if not name or name in tried:
            continue
        tried.append(name)
        try:
            mlflow.set_experiment(name)
            print("name_match: mlflow experiment =", name)
            return mlflow
        except Exception as exc:  # noqa: BLE001
            print("name_match: set_experiment failed for", name, ":", exc)
    print("name_match: could not set MLflow experiment; logging disabled")
    return None


def _log_params(mlflow: Any, params: dict[str, Any]) -> None:
    payload = {k: str(v) for k, v in params.items() if v is not None}
    if mlflow is not None:
        mlflow.log_params(payload)


def _log_metrics(mlflow: Any, metrics: dict[str, float]) -> None:
    clean = mlflow_metric_items(metrics)
    if mlflow is not None and clean:
        mlflow.log_metrics(clean)


def _log_tags(mlflow: Any, tags: dict[str, str]) -> None:
    if mlflow is not None:
        mlflow.set_tags(tags)


COMMON_TAGS = {
    "sf_name_match_v1": "true",
    "run_tag": RUN_TAG,
    "source_system": SOURCE_SYSTEM,
    "state_code": STATE_CODE,
    "not_hire_signal": "true",
    "not_auto_link": "true",
    "dob_used": "false",
    "uma_wired": "false",
    "label_strategy": "synthetic_weak_pairs",
}


def _evaluate(
    name: str,
    pairs: Sequence[dict[str, Any]],
    scores: Sequence[float],
    review_mask: Sequence[bool],
) -> dict[str, float]:
    metrics = evaluate_ranker(pairs, scores, review_mask=review_mask, prefix=f"{name}_")
    return metrics


def run_experiment(
    *,
    from_silver: bool,
    synthetic: bool,
    warehouse_id: str | None,
    max_names: int,
    seed: int,
    experiment_name: str,
    use_mlflow: bool,
    skip_lightgbm: bool,
    skip_model: bool,
    spark: Any | None = None,
) -> dict[str, Any]:
    inventory = LabelInventory()
    human_pairs: list[NamePair] = []
    names_mode = "synthetic_fixtures"
    if from_silver and not synthetic:
        spark = spark if spark is not None else _try_spark()
        wid = warehouse_id or os.environ.get("DATABRICKS_WAREHOUSE_ID")
        names = load_sf_party_names(spark=spark, warehouse_id=wid, limit=max_names)
        names_mode = "silver_court_party_name_strings"
        inventory = load_label_inventory(spark=spark, warehouse_id=wid)
        human_pairs = load_human_pairs(spark=spark, warehouse_id=wid)
        if inventory.n_human == 0:
            print(
                "name_match: 0 human match_decision rows; "
                f"{inventory.n_suggestion} suggestion cards are NOT labels"
            )
    else:
        names = synthetic_fixture_records()
        if max_names:
            names = names[:max_names]
    pairs = build_synthetic_pairs(names, seed=seed)
    if human_pairs:
        print("name_match: mixing", len(human_pairs), "human pair labels")
        pairs.extend(human_pairs)
    if not pairs:
        raise RuntimeError("no training pairs built")
    train_ids, test_ids = split_query_ids(pairs, seed=seed)
    train_pairs = filter_pairs(pairs, train_ids)
    test_pairs = filter_pairs(pairs, test_ids)
    train_docs = pair_dicts(train_pairs)
    test_docs = pair_dicts(test_pairs)
    X_train = np.asarray(matrix_from_pairs(train_docs), dtype=float)
    y_train = np.asarray([p.label for p in train_pairs], dtype=int)
    X_test = np.asarray(matrix_from_pairs(test_docs), dtype=float)
    review_mask = rule_review_mask(test_docs)
    summary = {
        "names_mode": names_mode,
        "n_source_names": len(names),
        **{f"all_{k}": v for k, v in summarize_pairs(pairs).items()},
        **{f"train_{k}": v for k, v in summarize_pairs(train_pairs).items()},
        **{f"test_{k}": v for k, v in summarize_pairs(test_pairs).items()},
        "n_human_labels_inventory": inventory.n_human,
        "n_suggestion_cards_ignored": inventory.n_suggestion,
        "n_match_decision_total": inventory.n_total,
        "feature_count": len(FEATURE_NAMES),
        "uses_dob": False,
    }
    params = {
        "run_tag": RUN_TAG,
        "experiment_name": EXPERIMENT_NAME,
        "names_mode": names_mode,
        "max_names": max_names,
        "seed": seed,
        "n_features": len(FEATURE_NAMES),
        "label_strategy": "synthetic_exact_near_pos_plus_hard_and_near_dup_neg",
        "suggestions_are_labels": "false",
        "uses_dob": "false",
        "writes_match_decision": "false",
        "wires_uma": "false",
        "source_system": SOURCE_SYSTEM,
        "state_code": STATE_CODE,
    }
    mlflow = _start_mlflow(experiment_name=experiment_name, enabled=use_mlflow)
    results: dict[str, Any] = {"summary": summary, "metrics": {}}

    def _run_nested(run_name: str, fn) -> None:
        if mlflow is None:
            fn(None)
            return
        with mlflow.start_run(run_name=run_name, nested=True):
            _log_tags(mlflow, COMMON_TAGS)
            _log_tags(mlflow, {"model_family": run_name})
            fn(mlflow)

    parent_ctx = (
        mlflow.start_run(run_name=f"{RUN_TAG}_{names_mode}") if mlflow is not None else None
    )
    try:
        if mlflow is not None:
            _log_tags(mlflow, COMMON_TAGS)
            _log_params(mlflow, params)
            _log_metrics(
                mlflow,
                {
                    "n_source_names": float(summary["n_source_names"]),
                    "n_pairs": float(summary["all_n_pairs"]),
                    "n_positive": float(summary["all_n_positive"]),
                    "n_negative": float(summary["all_n_negative"]),
                    "n_human_labels": float(inventory.n_human),
                    "n_suggestion_cards_ignored": float(inventory.n_suggestion),
                },
            )

        def _baseline(_ml) -> None:
            scores = rule_rank_scores(test_docs)
            metrics = _evaluate("baseline", test_docs, scores, review_mask)
            results["metrics"].update(metrics)
            if _ml is not None:
                _log_params(_ml, {"scorer": "match_review_sketch", "uses_dob": "false"})
                _log_metrics(_ml, metrics)
            print("name_match: rule baseline", json.dumps(mlflow_metric_items(metrics)))

        _run_nested("rule_baseline", _baseline)

        if not skip_model:
            def _logistic(_ml) -> None:
                model = train_logistic(X_train, y_train, seed=seed)
                scores = model.predict_scores(X_test)
                metrics = _evaluate("logistic", test_docs, scores, review_mask)
                results["metrics"].update(metrics)
                results["logistic_backend"] = model.name
                if _ml is not None:
                    _log_params(_ml, {"scorer": model.name, "uses_dob": "false"})
                    _log_metrics(_ml, metrics)
                print("name_match: logistic", json.dumps(mlflow_metric_items(metrics)))

            _run_nested("logistic", _logistic)

            if not skip_lightgbm:
                def _lgbm(_ml) -> None:
                    if not lightgbm_available():
                        print("name_match: lightgbm not installed; skipped")
                        return
                    model: FittedScorer = train_lightgbm(X_train, y_train, seed=seed)
                    scores = model.predict_scores(X_test)
                    metrics = _evaluate("lightgbm", test_docs, scores, review_mask)
                    results["metrics"].update(metrics)
                    if _ml is not None:
                        _log_params(_ml, {"scorer": model.name, "uses_dob": "false"})
                        _log_metrics(_ml, metrics)
                    print("name_match: lightgbm", json.dumps(mlflow_metric_items(metrics)))

                _run_nested("lightgbm", _lgbm)
    finally:
        if parent_ctx is not None:
            parent_ctx.__exit__(None, None, None)

    results["feature_names"] = list(FEATURE_NAMES)
    results["experiment_name"] = EXPERIMENT_NAME
    results["run_tag"] = RUN_TAG
    print("name_match: summary", json.dumps(summary, default=str))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SF name-match ranking experiment (research). "
            "Logs rule baseline + model metrics to MLflow experiment "
            f"{EXPERIMENT_NAME}. Not a hire signal; does not auto-link."
        )
    )
    parser.add_argument(
        "--from-silver",
        action="store_true",
        help="Pull SF court_party name strings via Spark or SQL warehouse",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use documented synthetic fixture names only (unit tests / dry run)",
    )
    parser.add_argument(
        "--warehouse-id",
        default=os.environ.get("DATABRICKS_WAREHOUSE_ID"),
        help="SQL warehouse id when no Spark session is available",
    )
    parser.add_argument("--max-names", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--experiment-name",
        default=os.environ.get("MLFLOW_EXPERIMENT_NAME", WORKSPACE_EXPERIMENT_PATH),
        help=(
            "MLflow experiment. Default /Shared/us_criminal_bg_name_match. "
            f"Bare name {EXPERIMENT_NAME}; UC {UC_EXPERIMENT_NAME}."
        ),
    )
    parser.add_argument("--no-mlflow", action="store_true")
    parser.add_argument("--skip-lightgbm", action="store_true")
    parser.add_argument("--skip-model", action="store_true", help="Log rule baseline only")
    args = parser.parse_args(argv)
    if not args.from_silver and not args.synthetic:
        # Databricks default: silver names. Local default: synthetic fixtures.
        args.synthetic = _try_spark() is None and not args.warehouse_id
        args.from_silver = not args.synthetic
    run_experiment(
        from_silver=bool(args.from_silver),
        synthetic=bool(args.synthetic),
        warehouse_id=args.warehouse_id,
        max_names=int(args.max_names),
        seed=int(args.seed),
        experiment_name=str(args.experiment_name),
        use_mlflow=not args.no_mlflow,
        skip_lightgbm=bool(args.skip_lightgbm),
        skip_model=bool(args.skip_model),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
