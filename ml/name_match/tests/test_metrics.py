"""Ranking metrics on tiny synthetic lists."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.metrics import (
    evaluate_ranker,
    precision_at_k,
    pr_auc,
    recall_at_k,
)


class MetricsTests(unittest.TestCase):
    def test_perfect_ranking(self) -> None:
        y_true = [1, 0, 1, 0]
        y_score = [0.9, 0.1, 0.8, 0.2]
        q = ["a", "a", "b", "b"]
        self.assertEqual(precision_at_k(y_true, y_score, q, 1), 1.0)
        self.assertEqual(recall_at_k(y_true, y_score, q, 1), 1.0)
        self.assertGreater(pr_auc(y_true, y_score), 0.9)

    def test_inverted_ranking_is_worse(self) -> None:
        y_true = [1, 0, 1, 0]
        good = [0.9, 0.1, 0.8, 0.2]
        bad = [0.1, 0.9, 0.2, 0.8]
        self.assertGreater(pr_auc(y_true, good), pr_auc(y_true, bad))

    def test_review_band_slice(self) -> None:
        pairs = [
            {"query_id": "q1", "label": 1},
            {"query_id": "q1", "label": 0},
            {"query_id": "q1", "label": 0},
        ]
        scores = [0.9, 0.4, 0.2]
        mask = [True, True, False]
        metrics = evaluate_ranker(pairs, scores, review_mask=mask, prefix="m_")
        self.assertIn("m_pr_auc", metrics)
        self.assertIn("m_review_band_pr_auc", metrics)
        self.assertEqual(metrics["m_review_band_n_pairs"], 2.0)
        self.assertIn("m_precision_at_1", metrics)
        self.assertIn("m_recall_at_5", metrics)
