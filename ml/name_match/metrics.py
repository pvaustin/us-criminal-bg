"""Ranking metrics: precision@k, recall@k, PR-AUC, plus review-band slices.

Scores are name-match ranks only — never hire / risk. Labels are pair-level
(synthetic or later human `match_decision`); suggestion queue cards are not
ground truth.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


def _as_np(y_true: Sequence[Any], y_score: Sequence[Any]) -> tuple[np.ndarray, np.ndarray]:
    yt = np.asarray(y_true, dtype=float)
    ys = np.asarray(y_score, dtype=float)
    if yt.shape[0] != ys.shape[0]:
        raise ValueError("y_true and y_score length mismatch")
    return yt, ys


def average_precision(y_true: Sequence[Any], y_score: Sequence[Any]) -> float:
    """Step-function average precision (sklearn-style, no sklearn dependency)."""
    yt, ys = _as_np(y_true, y_score)
    n_pos = float(yt.sum())
    if n_pos <= 0:
        return float("nan")
    order = np.argsort(-ys, kind="mergesort")
    yt_sorted = yt[order]
    tp = np.cumsum(yt_sorted)
    fp = np.cumsum(1.0 - yt_sorted)
    recall = tp / n_pos
    precision = tp / np.maximum(tp + fp, 1e-12)
    # Sum precision at each positive, weighted by recall delta.
    prev_r = 0.0
    ap = 0.0
    for p, r, lab in zip(precision, recall, yt_sorted):
        if lab <= 0:
            continue
        ap += float(p) * (float(r) - prev_r)
        prev_r = float(r)
    return float(ap)


def pr_auc(y_true: Sequence[Any], y_score: Sequence[Any]) -> float:
    """Trapezoidal PR-AUC. Alias used in MLflow logs (`*_pr_auc`)."""
    yt, ys = _as_np(y_true, y_score)
    n_pos = float(yt.sum())
    if n_pos <= 0 or yt.size == 0:
        return float("nan")
    order = np.argsort(-ys, kind="mergesort")
    yt_sorted = yt[order]
    tp = np.cumsum(yt_sorted)
    fp = np.cumsum(1.0 - yt_sorted)
    recall = np.concatenate([[0.0], tp / n_pos])
    precision = np.concatenate([[1.0], tp / np.maximum(tp + fp, 1e-12)])
    trapz = getattr(np, "trapezoid", None) or np.trapz
    return float(trapz(precision, recall))


def _groups(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
) -> Iterable[tuple[np.ndarray, np.ndarray]]:
    buckets: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    for lab, score, qid in zip(y_true, y_score, query_ids):
        buckets[qid].append((float(lab), float(score)))
    for rows in buckets.values():
        yt = np.asarray([r[0] for r in rows], dtype=float)
        ys = np.asarray([r[1] for r in rows], dtype=float)
        yield yt, ys


def precision_at_k(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
    k: int,
) -> float:
    """Macro precision@k over queries that have at least one pair."""
    if k < 1:
        raise ValueError("k must be >= 1")
    vals: list[float] = []
    for yt, ys in _groups(y_true, y_score, query_ids):
        if yt.size == 0:
            continue
        order = np.argsort(-ys, kind="mergesort")[:k]
        vals.append(float(yt[order].mean()))
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def recall_at_k(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
    k: int,
) -> float:
    """Macro recall@k over queries that have ≥1 positive."""
    if k < 1:
        raise ValueError("k must be >= 1")
    vals: list[float] = []
    for yt, ys in _groups(y_true, y_score, query_ids):
        n_pos = float(yt.sum())
        if n_pos <= 0:
            continue
        order = np.argsort(-ys, kind="mergesort")[:k]
        vals.append(float(yt[order].sum() / n_pos))
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def mean_average_precision(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
) -> float:
    vals: list[float] = []
    for yt, ys in _groups(y_true, y_score, query_ids):
        if yt.sum() <= 0:
            continue
        vals.append(average_precision(yt, ys))
    if not vals:
        return float("nan")
    return float(np.mean(vals))


def _finite(value: float) -> float | None:
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return float(value)


def ranking_metrics(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
    *,
    ks: Sequence[int] = (1, 3, 5, 10),
    prefix: str = "",
) -> dict[str, float]:
    metrics: dict[str, float] = {
        f"{prefix}pr_auc": pr_auc(y_true, y_score),
        f"{prefix}average_precision": average_precision(y_true, y_score),
        f"{prefix}map": mean_average_precision(y_true, y_score, query_ids),
        f"{prefix}n_pairs": float(len(y_true)),
        f"{prefix}n_positive": float(np.asarray(y_true, dtype=float).sum()),
    }
    for k in ks:
        metrics[f"{prefix}precision_at_{k}"] = precision_at_k(
            y_true, y_score, query_ids, k
        )
        metrics[f"{prefix}recall_at_{k}"] = recall_at_k(y_true, y_score, query_ids, k)
    return metrics


def slice_arrays(
    y_true: Sequence[Any],
    y_score: Sequence[Any],
    query_ids: Sequence[Any],
    mask: Sequence[bool],
) -> tuple[list[float], list[float], list[Any]]:
    yt: list[float] = []
    ys: list[float] = []
    q: list[Any] = []
    for lab, score, qid, keep in zip(y_true, y_score, query_ids, mask):
        if keep:
            yt.append(float(lab))
            ys.append(float(score))
            q.append(qid)
    return yt, ys, q


def evaluate_ranker(
    pairs: Sequence[Mapping[str, Any]],
    scores: Sequence[Any],
    *,
    review_mask: Sequence[bool] | None = None,
    prefix: str = "",
) -> dict[str, float]:
    """Full-set metrics plus optional `review_band_` slice (rule score ≥ 50)."""
    y_true = [int(p.get("label") or 0) for p in pairs]
    query_ids = [p.get("query_id") for p in pairs]
    out = ranking_metrics(y_true, scores, query_ids, prefix=prefix)
    if review_mask is not None:
        yt, ys, q = slice_arrays(y_true, scores, query_ids, review_mask)
        sliced = ranking_metrics(yt, ys, q, prefix=f"{prefix}review_band_")
        out.update(sliced)
    return out


def mlflow_metric_items(metrics: Mapping[str, float]) -> dict[str, float]:
    """Drop NaN/inf so MLflow log_metrics does not fail."""
    clean: dict[str, float] = {}
    for key, value in metrics.items():
        ok = _finite(float(value) if value is not None else float("nan"))
        if ok is not None:
            clean[str(key)] = ok
    return clean
