"""Rule baseline scores on synthetic SF-shaped names (no DOB → never auto)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.baseline import score_name_pair
from ml.name_match.constants import (
    RULE_EXACT_LAST_FIRST_SCORE,
    RULE_FIRST_INITIAL_SCORE,
)


SF_PUBLIC = {
    "raw_name": "JANE Q PUBLIC",
    "name_last": "PUBLIC",
    "name_first": "JANE",
    "name_middle": "Q",
    "party_role": "defendant",
}


class RuleBaselineTests(unittest.TestCase):
    def test_exact_last_first_is_review_70(self) -> None:
        result = score_name_pair("Jane Q Public", SF_PUBLIC)
        self.assertEqual(result.score, RULE_EXACT_LAST_FIRST_SCORE)
        self.assertEqual(result.band, "review")
        self.assertIn("dob_absent", result.reasons)
        self.assertIn("last_name_match", result.reasons)
        self.assertIn("first_name_match", result.reasons)
        self.assertNotEqual(result.band, "auto")

    def test_first_initial_is_review_55(self) -> None:
        result = score_name_pair("J Public", SF_PUBLIC)
        self.assertEqual(result.score, RULE_FIRST_INITIAL_SCORE)
        self.assertEqual(result.band, "review")
        self.assertIn("first_initial_match", result.reasons)
        self.assertNotEqual(result.band, "auto")

    def test_different_last_is_no_link(self) -> None:
        result = score_name_pair("Jane Otherperson", SF_PUBLIC)
        self.assertEqual(result.band, "no-link")
        self.assertIn("last_name_mismatch", result.reasons)
        self.assertEqual(result.score, 0)

    def test_forced_absent_dob_even_if_caller_passed_one(self) -> None:
        party = dict(SF_PUBLIC)
        party["dob"] = "2099-01-15"
        result = score_name_pair("Jane Q Public", party)
        self.assertEqual(result.band, "review")
        self.assertIn("dob_absent", result.reasons)
        self.assertNotIn("dob_match", result.reasons)
