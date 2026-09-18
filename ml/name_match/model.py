"""Small name-match scorers: numpy logistic, sklearn logistic, LightGBM.

Outputs a pair probability used only as a ranking score. Not a hire / risk
score and not an auto-link decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ml.name_match.constants import FEATURE_NAMES


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -30.0, 30.0)
    return 1.0 / (1.0 + np.exp(-z))


@dataclass
class NumpyLogistic:
    """Driver-local logistic regression (no sklearn required)."""

    lr: float = 0.25
    n_iter: int = 400
    l2: float = 1e-2
    seed: int = 7
    coef_: np.ndarray | None = None
    intercept_: float = 0.0

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NumpyLogistic":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float)
        n, d = X.shape
        rng = np.random.default_rng(self.seed)
        w = rng.normal(0.0, 0.01, size=d)
        b = 0.0
        n_pos = max(float(y.sum()), 1.0)
        n_neg = max(float((1.0 - y).sum()), 1.0)
        sw = np.where(y >= 0.5, n / (2.0 * n_pos), n / (2.0 * n_neg))
        for _ in range(self.n_iter):
            p = _sigmoid(X @ w + b)
            err = (p - y) * sw
            w -= self.lr * ((X.T @ err) / n + self.l2 * w)
            b -= self.lr * float(err.mean())
        self.coef_ = w
        self.intercept_ = float(b)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if self.coef_ is None:
            raise RuntimeError("NumpyLogistic is not fitted")
        p1 = _sigmoid(X @ self.coef_ + self.intercept_)
        return np.column_stack([1.0 - p1, p1])


class FittedScorer:
    """Thin wrapper so train.py can score without caring which backend ran."""

    def __init__(self, name: str, backend: Any, feature_names: Sequence[str] = FEATURE_NAMES):
        self.name = name
        self.backend = backend
        self.feature_names = tuple(feature_names)

    def predict_scores(self, X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if hasattr(self.backend, "predict_proba"):
            proba = np.asarray(self.backend.predict_proba(X), dtype=float)
            if proba.ndim == 2 and proba.shape[1] >= 2:
                return proba[:, 1]
            return proba.reshape(-1)
        if hasattr(self.backend, "predict"):
            return np.asarray(self.backend.predict(X), dtype=float).reshape(-1)
        raise TypeError(f"backend {type(self.backend)!r} has no predict_proba/predict")


def sklearn_available() -> bool:
    try:
        import sklearn  # noqa: F401
    except ImportError:
        return False
    return True


def lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
    except ImportError:
        return False
    return True


def train_logistic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    seed: int = 7,
    prefer_sklearn: bool = True,
) -> FittedScorer:
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=int)
    if prefer_sklearn and sklearn_available():
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(
            max_iter=400,
            class_weight="balanced",
            solver="liblinear",
            random_state=seed,
        )
        clf.fit(X, y)
        return FittedScorer("logistic_sklearn", clf)
    model = NumpyLogistic(seed=seed).fit(X, y)
    return FittedScorer("logistic_numpy", model)


def train_lightgbm(
    X: np.ndarray,
    y: np.ndarray,
    *,
    seed: int = 7,
) -> FittedScorer:
    if not lightgbm_available():
        raise RuntimeError("lightgbm is not installed")
    import lightgbm as lgb

    clf = lgb.LGBMClassifier(
        n_estimators=80,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.9,
        colsample_bytree=0.8,
        min_child_samples=4,
        objective="binary",
        class_weight="balanced",
        random_state=seed,
        verbosity=-1,
    )
    clf.fit(X, np.asarray(y, dtype=int))
    return FittedScorer("lightgbm", clf)
