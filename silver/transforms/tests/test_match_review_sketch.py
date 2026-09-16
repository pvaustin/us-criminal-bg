"""Synthetic-only examples for the MATCH_REVIEW.md scoring sketch."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from silver.transforms.match_review_sketch import (  # noqa: E402
    UMA_CONTRACT_FIELDS,
    match_decision_row,
    retrieve_candidates_by_last_name,
    required_provenance,
    score_subject_against_party,
    suggestion_rows_for_subject,
)

SYNTHETIC_PARTY = {
    "source_system": "wcca",
    "state_code": "WI",
    "source_record_id": "01:2099CF000010",
    "ingest_run_id": "synthetic-ingest",
    "payload_sha256": "abc123",
    "transform_run_id": "synthetic-transform",
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "FIXTURE, JANE Q",
    "name_last": "FIXTURE",
    "name_first": "JANE",
    "name_middle": "Q",
    "dob": date(2099, 1, 15),
}


class MatchReviewSketchTests(unittest.TestCase):
    def test_auto_name_and_dob(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Q Fixture", "dob": "2099-01-15"},
            SYNTHETIC_PARTY,
        )
        self.assertEqual(sketch.band, "auto")
        self.assertIn("last_name_match", sketch.reasons)
        self.assertIn("first_name_match", sketch.reasons)
        self.assertIn("dob_match", sketch.reasons)
        prov = required_provenance(SYNTHETIC_PARTY, sketch)
        self.assertEqual(prov["source_system"], "wcca")
        self.assertEqual(prov["state_code"], "WI")
        self.assertEqual(prov["source_record_id"], "01:2099CF000010")
        self.assertEqual(prov["ingest_run_id"], "synthetic-ingest")
        self.assertEqual(prov["payload_sha256"], "abc123")
        self.assertEqual(prov["transform_run_id"], "synthetic-transform")
        self.assertEqual(prov["party_role"], "defendant")
        self.assertEqual(prov["party_ordinal"], 1)
        self.assertEqual(prov["band"], "auto")
        self.assertEqual(prov["confidence_band"], "auto")
        self.assertEqual(prov["party_key"], "wcca|WI|01:2099CF000010|defendant|1")
        self.assertEqual(prov["case_report_key"], "wcca|WI|01:2099CF000010")
        self.assertIn("dob_match", prov["score_or_reason_codes"])

    def test_review_when_dob_missing(self) -> None:
        party = dict(SYNTHETIC_PARTY)
        party["dob"] = None
        sketch = score_subject_against_party(
            {"name": "Jane Fixture"},
            party,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("dob_absent", sketch.reasons)

    def test_no_link_on_dob_conflict(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Fixture", "dob": date(2098, 1, 1)},
            SYNTHETIC_PARTY,
        )
        self.assertEqual(sketch.band, "no-link")
        self.assertIn("dob_conflict", sketch.reasons)
        self.assertEqual(sketch.score, 0)

    def test_plaintiff_never_matchable(self) -> None:
        party = dict(SYNTHETIC_PARTY)
        party["party_role"] = "plaintiff"
        party["raw_name"] = "State of Wisconsin"
        party["name_last"] = None
        party["name_first"] = None
        sketch = score_subject_against_party(
            {"name": "Jane Fixture", "dob": date(2099, 1, 15)},
            party,
        )
        self.assertEqual(sketch.band, "no-link")
        self.assertEqual(sketch.reasons, ("party_role_not_matchable",))

    def test_aka_without_dob_is_review(self) -> None:
        party = {
            **SYNTHETIC_PARTY,
            "party_role": "aka",
            "party_ordinal": 2,
            "raw_name": "ALIASFIXTURE, JANE",
            "name_last": "ALIASFIXTURE",
            "name_first": "JANE",
            "name_middle": None,
            "dob": None,
        }
        sketch = score_subject_against_party(
            {"name": "Jane Aliasfixture"},
            party,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("aka_alias_row", sketch.reasons)
        self.assertIn("last_name_match", sketch.reasons)

    def test_last_name_mismatch_is_no_link(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Otherperson", "dob": date(2099, 1, 15)},
            SYNTHETIC_PARTY,
        )
        self.assertEqual(sketch.band, "no-link")
        self.assertIn("last_name_mismatch", sketch.reasons)

    def test_missing_dob_on_one_side_is_review_not_fail(self) -> None:
        party = dict(SYNTHETIC_PARTY)
        party["dob"] = None
        sketch = score_subject_against_party(
            {"name": "Jane Fixture", "dob": date(2099, 1, 15)},
            party,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("dob_absent", sketch.reasons)
        self.assertNotIn("dob_conflict", sketch.reasons)

    def test_first_initial_with_dob_is_review_not_auto(self) -> None:
        sketch = score_subject_against_party(
            {"name": "J Fixture", "dob": date(2099, 1, 15)},
            SYNTHETIC_PARTY,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("first_initial_match", sketch.reasons)
        self.assertIn("dob_match", sketch.reasons)

    def test_first_last_subject_parses_against_comma_party(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Q Fixture", "dob": "2099-01-15"},
            SYNTHETIC_PARTY,
        )
        self.assertEqual(sketch.band, "auto")
        self.assertIn("last_name_match", sketch.reasons)
        self.assertIn("first_name_match", sketch.reasons)

    def test_last_name_retrieval_is_not_cartesian(self) -> None:
        other = {
            **SYNTHETIC_PARTY,
            "source_record_id": "01:2099CF000011",
            "raw_name": "OTHERPERSON, JANE",
            "name_last": "OTHERPERSON",
            "name_first": "JANE",
        }
        hits = retrieve_candidates_by_last_name(
            {"name": "Jane Fixture"},
            [SYNTHETIC_PARTY, other],
        )
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["name_last"], "FIXTURE")

    def test_suggestion_row_carries_uma_contract_fields(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Q Fixture", "dob": "2099-01-15"},
            SYNTHETIC_PARTY,
        )
        row = match_decision_row(
            {"subject_ref": "synthetic-subject-1", "name": "Jane Q Fixture", "dob": "2099-01-15"},
            SYNTHETIC_PARTY,
            sketch,
        )
        for field in UMA_CONTRACT_FIELDS:
            self.assertIn(field, row)
        self.assertEqual(row["actor"], "system:suggestion")
        self.assertEqual(row["review_status"], "suggestion")
        self.assertEqual(row["confidence_band"], "auto")
        self.assertEqual(row["score_or_reason_codes"][0], str(row["score"]))

    def test_suggestion_rows_skip_no_link_by_default(self) -> None:
        rows = suggestion_rows_for_subject(
            {"subject_ref": "synthetic-subject-1", "name": "Jane Otherperson"},
            [SYNTHETIC_PARTY],
        )
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
