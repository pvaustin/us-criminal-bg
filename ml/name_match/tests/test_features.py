"""Feature contract: no DOB, JW / Soundex / comma-vs-space, synthetic names only."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.constants import FEATURE_NAMES
from ml.name_match.features import (
    jaro_winkler,
    pair_feature_dict,
    pair_feature_vector,
    soundex,
)


class FeatureTests(unittest.TestCase):
    def test_feature_names_exclude_dob_and_hire(self) -> None:
        joined = " ".join(FEATURE_NAMES).lower()
        self.assertNotIn("dob", joined)
        self.assertNotIn("hire", joined)
        self.assertNotIn("risk", joined)
        self.assertIn("exact_last", FEATURE_NAMES)
        self.assertIn("first_initial_match", FEATURE_NAMES)
        self.assertIn("jw_raw", FEATURE_NAMES)
        self.assertIn("soundex_last_match", FEATURE_NAMES)
        self.assertIn("comma_vs_space", FEATURE_NAMES)

    def test_exact_last_first_on_synthetic_public(self) -> None:
        feats = pair_feature_dict(
            "Jane Q Public",
            {
                "raw_name": "JANE Q PUBLIC",
                "name_last": "PUBLIC",
                "name_first": "JANE",
                "name_middle": "Q",
            },
        )
        self.assertEqual(feats["exact_last"], 1.0)
        self.assertEqual(feats["exact_first"], 1.0)
        self.assertEqual(feats["first_initial_match"], 1.0)
        self.assertEqual(feats["exact_raw_norm"], 1.0)
        self.assertGreater(feats["jw_raw"], 0.9)
        self.assertEqual(feats["soundex_last_match"], 1.0)
        self.assertEqual(len(pair_feature_vector("Jane Q Public", {"raw_name": "JANE Q PUBLIC"})), len(FEATURE_NAMES))

    def test_first_initial_not_exact_first(self) -> None:
        feats = pair_feature_dict(
            "J Public",
            {
                "raw_name": "JANE Q PUBLIC",
                "name_last": "PUBLIC",
                "name_first": "JANE",
            },
        )
        self.assertEqual(feats["exact_last"], 1.0)
        self.assertEqual(feats["exact_first"], 0.0)
        self.assertEqual(feats["first_initial_match"], 1.0)

    def test_comma_vs_space_flag(self) -> None:
        feats = pair_feature_dict(
            "Jane Q Public",
            {
                "raw_name": "PUBLIC, JANE Q",
                "name_last": "PUBLIC",
                "name_first": "JANE",
                "name_middle": "Q",
            },
        )
        self.assertEqual(feats["subject_has_comma"], 0.0)
        self.assertEqual(feats["party_has_comma"], 1.0)
        self.assertEqual(feats["comma_vs_space"], 1.0)
        self.assertEqual(feats["exact_last"], 1.0)
        self.assertEqual(feats["exact_first"], 1.0)

    def test_jaro_winkler_martha(self) -> None:
        # Classic JW example: MARTHA vs MARHTA ≈ 0.961
        score = jaro_winkler("MARTHA", "MARHTA")
        self.assertGreater(score, 0.94)
        self.assertLess(score, 0.98)

    def test_soundex_same_last(self) -> None:
        self.assertEqual(soundex("PUBLIC"), soundex("PUBLIC"))
        self.assertEqual(len(soundex("FIXTURE")), 4)
        self.assertEqual(soundex(""), "")
