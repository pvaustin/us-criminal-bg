"""Synthetic pair labels — not court rows, not suggestion-card labels."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.constants import (
    LABEL_HUMAN_LINK,
    LABEL_SOURCE_SYNTHETIC,
    LABEL_SYNTHETIC_EXACT_POSITIVE,
    LABEL_SYNTHETIC_HARD_NEGATIVE,
    LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE,
    LABEL_SYNTHETIC_NEAR_POSITIVE,
)
from ml.name_match.dataset import (
    build_synthetic_pairs,
    inventory_from_counts,
    pairs_from_human_decisions,
    split_query_ids,
    summarize_pairs,
    synthetic_fixture_records,
)


class DatasetBuilderTests(unittest.TestCase):
    def test_fixtures_are_documented_synthetic_names(self) -> None:
        names = [r.raw_name for r in synthetic_fixture_records()]
        self.assertIn("JANE Q PUBLIC", names)
        self.assertIn("JOHN MARSHALL FIXTURE", names)
        blob = json.dumps(names)
        self.assertNotIn("sf_case:", blob)

    def test_synthetic_pairs_have_pos_and_neg_kinds(self) -> None:
        pairs = build_synthetic_pairs(synthetic_fixture_records(), seed=1)
        kinds = {p.label_kind for p in pairs}
        self.assertIn(LABEL_SYNTHETIC_EXACT_POSITIVE, kinds)
        self.assertIn(LABEL_SYNTHETIC_NEAR_POSITIVE, kinds)
        self.assertIn(LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE, kinds)
        self.assertIn(LABEL_SYNTHETIC_HARD_NEGATIVE, kinds)
        self.assertTrue(all(p.label_source == LABEL_SOURCE_SYNTHETIC for p in pairs))
        self.assertTrue(all(p.source_party_key is None for p in pairs))
        dumped = json.dumps([p.as_dict() for p in pairs])
        self.assertNotIn("source_record_id", dumped)
        self.assertNotIn("charge", dumped.lower())
        summary = summarize_pairs(pairs)
        self.assertGreater(summary["n_positive"], 0)
        self.assertGreater(summary["n_negative"], 0)

    def test_same_last_different_first_is_negative(self) -> None:
        pairs = build_synthetic_pairs(synthetic_fixture_records(), seed=1)
        near = [
            p
            for p in pairs
            if p.label_kind == LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE
            and "PUBLIC" in p.subject_name
        ]
        self.assertTrue(near)
        self.assertTrue(all(p.label == 0 for p in near))
        self.assertTrue(any("ZELDA" in p.party_raw_name or "JANE" in p.party_raw_name for p in near))

    def test_comma_variant_is_positive(self) -> None:
        pairs = build_synthetic_pairs(synthetic_fixture_records(), seed=1)
        jane = [
            p
            for p in pairs
            if p.subject_name == "JANE Q PUBLIC" and p.label_kind == LABEL_SYNTHETIC_NEAR_POSITIVE
        ]
        self.assertTrue(any("," in p.party_raw_name for p in jane))
        self.assertTrue(all(p.label == 1 for p in jane))

    def test_suggestions_are_not_labels(self) -> None:
        rows = [
            {
                "review_status": "suggestion",
                "actor": "system:suggestion",
                "subject_name": "JANE Q PUBLIC",
                "party_raw_name": "JANE Q PUBLIC",
                "confidence_band": "review",
                "subject_ref": "synthetic-queue-1",
            },
            {
                "review_status": "human",
                "actor": "reviewer@example.com",
                "subject_name": "JANE Q PUBLIC",
                "party_raw_name": "JANE Q PUBLIC",
                "confidence_band": "auto",
                "subject_ref": "synthetic-human-1",
            },
        ]
        pairs = pairs_from_human_decisions(rows)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].label_kind, LABEL_HUMAN_LINK)
        self.assertEqual(pairs[0].label, 1)

    def test_human_review_band_is_leave_in_review_not_gt(self) -> None:
        rows = [
            {
                "review_status": "human",
                "actor": "reviewer@example.com",
                "subject_name": "JANE Q PUBLIC",
                "party_raw_name": "JANE Q PUBLIC",
                "confidence_band": "review",
                "label": "leave_in_review",
                "subject_ref": "synthetic-leave-1",
            },
            {
                "review_status": "human",
                "actor": "reviewer@example.com",
                "subject_name": "JANE Q PUBLIC",
                "party_raw_name": "JOHN MARSHALL FIXTURE",
                "confidence_band": "no-link",
                "label": "reject",
                "subject_ref": "synthetic-rej-1",
            },
        ]
        pairs = pairs_from_human_decisions(rows)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].label, 0)
        self.assertEqual(pairs[0].label_kind, "human_reject")

    def test_inventory_counts_suggestions_separately(self) -> None:
        inv = inventory_from_counts(
            [
                {"review_status": "suggestion", "actor": "system:suggestion", "n": 40},
                {"review_status": "human", "actor": "reviewer@example.com", "n": 0},
            ]
        )
        self.assertEqual(inv.n_suggestion, 40)
        self.assertEqual(inv.n_human, 0)

    def test_query_split_keeps_at_least_one_each_side(self) -> None:
        pairs = build_synthetic_pairs(synthetic_fixture_records(), seed=1)
        train_ids, test_ids = split_query_ids(pairs, seed=1)
        self.assertTrue(train_ids)
        self.assertTrue(test_ids)
        self.assertTrue(set(train_ids).isdisjoint(test_ids))
