"""Numpy logistic (and sklearn/LightGBM if installed) on synthetic pairs."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.dataset import build_synthetic_pairs, pair_dicts, synthetic_fixture_records
from ml.name_match.features import matrix_from_pairs
from ml.name_match.model import (
    lightgbm_available,
    sklearn_available,
    train_lightgbm,
    train_logistic,
)


class ModelTests(unittest.TestCase):
    def _xy(self):
        pairs = pair_dicts(build_synthetic_pairs(synthetic_fixture_records(), seed=3))
        X = np.asarray(matrix_from_pairs(pairs), dtype=float)
        y = np.asarray([p["label"] for p in pairs], dtype=int)
        return X, y

    def test_numpy_logistic_ranks_positives_higher(self) -> None:
        X, y = self._xy()
        model = train_logistic(X, y, seed=3, prefer_sklearn=False)
        self.assertEqual(model.name, "logistic_numpy")
        scores = model.predict_scores(X)
        pos = float(scores[y == 1].mean())
        neg = float(scores[y == 0].mean())
        self.assertGreater(pos, neg)

    def test_sklearn_logistic_optional(self) -> None:
        if not sklearn_available():
            self.skipTest("sklearn not installed")
        X, y = self._xy()
        model = train_logistic(X, y, seed=3, prefer_sklearn=True)
        self.assertEqual(model.name, "logistic_sklearn")
        scores = model.predict_scores(X)
        self.assertEqual(len(scores), len(y))
        self.assertGreater(float(scores[y == 1].mean()), float(scores[y == 0].mean()))

    def test_lightgbm_optional(self) -> None:
        if not lightgbm_available():
            self.skipTest("lightgbm not installed")
        X, y = self._xy()
        model = train_lightgbm(X, y, seed=3)
        scores = model.predict_scores(X)
        self.assertGreater(float(scores[y == 1].mean()), float(scores[y == 0].mean()))
