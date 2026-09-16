"""SF name-only match_decision experiment. Synthetic names only — not live PII."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from silver.transforms.match_decision_sf_research import (  # noqa: E402
    EXPERIMENT_TAG,
    SF_SOURCE_SYSTEM,
    SF_STATE_CODE,
    filter_sf_research_parties,
    score_sf_research_subjects,
)
from silver.transforms.match_review_sketch import (  # noqa: E402
    UMA_CONTRACT_FIELDS,
    score_subject_against_party,
)

SQL_PATH = ROOT / "silver" / "transforms" / "match_decision_sf_research.sql"
PY_PATH = ROOT / "silver" / "transforms" / "match_decision_sf_research.py"
DDL_PATH = ROOT / "silver" / "schemas" / "match_decision.sql"

SF_PUBLIC = {
    "source_system": "sf_criminal_hf",
    "state_code": "CA",
    "source_record_id": "sf_case:99",
    "ingest_run_id": "synthetic-sf-ingest",
    "payload_sha256": "sfabc123",
    "transform_run_id": "synthetic-sf-transform",
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "JANE Q PUBLIC",
    "name_last": "PUBLIC",
    "name_first": "JANE",
    "name_middle": "Q",
    "dob": None,
}

SF_MARSHALL = {
    **SF_PUBLIC,
    "source_record_id": "sf_case:100",
    "raw_name": "JOHN MARSHALL FIXTURE",
    "name_last": "FIXTURE",
    "name_first": "JOHN",
    "name_middle": "MARSHALL",
}

SF_FOURTOKEN = {
    **SF_PUBLIC,
    "source_record_id": "sf_case:101",
    "raw_name": "A B C D FOURTOKEN",
    "name_last": "FOURTOKEN",
    "name_first": "A",
    "name_middle": "B C D",
}

WCCA_PARTY = {
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


class SfNameOnlyBandTests(unittest.TestCase):
    def test_exact_name_without_party_dob_is_review_never_auto(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Q Public"},
            SF_PUBLIC,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("dob_absent", sketch.reasons)
        self.assertIn("last_name_match", sketch.reasons)
        self.assertIn("first_name_match", sketch.reasons)
        self.assertNotIn("dob_match", sketch.reasons)
        self.assertNotEqual(sketch.band, "auto")

    def test_subject_dob_still_review_when_party_dob_absent(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Q Public", "dob": "2099-01-15"},
            SF_PUBLIC,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("dob_absent", sketch.reasons)
        self.assertNotIn("dob_conflict", sketch.reasons)
        self.assertNotEqual(sketch.band, "auto")

    def test_last_name_mismatch_is_no_link(self) -> None:
        sketch = score_subject_against_party(
            {"name": "Jane Otherperson"},
            SF_PUBLIC,
        )
        self.assertEqual(sketch.band, "no-link")
        self.assertIn("last_name_mismatch", sketch.reasons)

    def test_space_separated_first_last_subject(self) -> None:
        sketch = score_subject_against_party(
            {"name": "John Marshall Fixture"},
            SF_MARSHALL,
        )
        self.assertEqual(sketch.band, "review")
        self.assertIn("last_name_match", sketch.reasons)
        self.assertIn("first_name_match", sketch.reasons)


class SfResearchJobTests(unittest.TestCase):
    def test_filters_out_wcca_parties(self) -> None:
        scoped = filter_sf_research_parties([SF_PUBLIC, WCCA_PARTY])
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["source_system"], "sf_criminal_hf")

    def test_last_name_retrieve_does_not_score_unrelated_parties(self) -> None:
        rows = score_sf_research_subjects(
            [
                {
                    "subject_ref": "synthetic-subject-1",
                    "name": "Jane Q Public",
                }
            ],
            [SF_PUBLIC, SF_MARSHALL, SF_FOURTOKEN, WCCA_PARTY],
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_record_id"], "sf_case:99")
        self.assertEqual(rows[0]["confidence_band"], "review")
        self.assertEqual(rows[0]["actor"], "system:suggestion")
        self.assertEqual(rows[0]["review_status"], "suggestion")
        self.assertEqual(rows[0]["experiment_tag"], EXPERIMENT_TAG)
        self.assertEqual(rows[0]["source_system"], SF_SOURCE_SYSTEM)
        self.assertEqual(rows[0]["state_code"], SF_STATE_CODE)
        self.assertIn("dob_absent", rows[0]["reasons"])
        self.assertNotEqual(rows[0]["confidence_band"], "auto")
        for field in UMA_CONTRACT_FIELDS:
            self.assertIn(field, rows[0])

    def test_wcca_auto_path_is_not_emitted_by_sf_job(self) -> None:
        rows = score_sf_research_subjects(
            [
                {
                    "subject_ref": "synthetic-subject-wi",
                    "name": "Jane Q Fixture",
                    "dob": "2099-01-15",
                }
            ],
            [WCCA_PARTY, SF_PUBLIC],
        )
        self.assertEqual(rows, [])

    def test_persist_no_link_keeps_last_name_equal_negatives(self) -> None:
        rows = score_sf_research_subjects(
            [{"subject_ref": "synthetic-subject-2", "name": "Zelda Public"}],
            [SF_PUBLIC],
            persist_no_link=True,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["confidence_band"], "no-link")
        self.assertIn("first_name_mismatch", rows[0]["reasons"])
        self.assertIn("last_name_match", rows[0]["reasons"])

    def test_default_omits_no_link(self) -> None:
        rows = score_sf_research_subjects(
            [{"subject_ref": "synthetic-subject-2", "name": "Zelda Public"}],
            [SF_PUBLIC],
        )
        self.assertEqual(rows, [])


class SqlAndDdlContractTests(unittest.TestCase):
    def test_ddl_is_append_only_array_string(self) -> None:
        ddl = DDL_PATH.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS us_criminal_bg.silver.match_decision", ddl)
        self.assertIn("reasons ARRAY<STRING> NOT NULL", ddl)
        self.assertIn("score_or_reason_codes ARRAY<STRING> NOT NULL", ddl)
        self.assertNotIn("reasons ARRAY NOT NULL", ddl)
        self.assertIn("ALWAYS APPEND", ddl)
        self.assertIn("review_status", ddl)
        self.assertIn("case_report_key", ddl)
        self.assertNotIn("MERGE INTO", ddl)
        self.assertNotRegex(ddl, r"(?i)^\s*hire\s", msg="must not add a hire column")
        self.assertNotIn("hire_flag", ddl.lower())
        self.assertNotIn("no-hire", ddl.lower())

    def test_sql_is_sf_scoped_last_name_join_insert(self) -> None:
        sql = SQL_PATH.read_text(encoding="utf-8")
        self.assertIn("p.source_system = 'sf_criminal_hf'", sql)
        self.assertIn("p.state_code = 'CA'", sql)
        self.assertIn("INNER JOIN parties p", sql)
        self.assertIn("ON s.last_key = p.last_key", sql)
        self.assertIn("INSERT INTO us_criminal_bg.silver.match_decision", sql)
        self.assertIn("'system:suggestion'", sql)
        self.assertIn("dob_absent", sql)
        self.assertIn(">= 50", sql)
        self.assertIn("sf_name_only_research", sql)
        self.assertIn("CREATE OR REPLACE TABLE us_criminal_bg.silver._match_decision_sf_staged", sql)
        self.assertNotIn("CREATE OR REPLACE TEMP VIEW", sql)
        self.assertNotIn("MERGE INTO", sql)
        self.assertNotIn("UPDATE us_criminal_bg", sql)
        self.assertNotIn("DELETE FROM us_criminal_bg.silver.court_party", sql)
        self.assertNotIn("DELETE FROM us_criminal_bg.silver.match_decision", sql)
        self.assertNotIn("MERGE INTO us_criminal_bg.silver.court_case", sql)
        self.assertNotIn("source_system = 'wcca'", sql)
        self.assertIn("not a 77k cartesian", sql.lower())
        self.assertIn("DROP TABLE IF EXISTS us_criminal_bg.silver._match_decision_sf_staged", sql)
        self.assertNotIn("DROP TABLE IF EXISTS us_criminal_bg.silver._match_subject_sf_research", sql)

    def test_python_job_does_not_import_wcca_transform(self) -> None:
        py = PY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("from sources.wcca", py)
        self.assertNotIn("court_case.py", py)
        self.assertNotIn("map_court_case", py)
        self.assertIn("JOIN", py.upper())
        self.assertIn("sf_criminal_hf", py)
        self.assertIn("INSERT INTO", py)

    def test_help_does_not_need_spark(self) -> None:
        out = subprocess.check_output(
            [sys.executable, str(PY_PATH), "--help"],
            text=True,
        )
        self.assertIn("sf_criminal_hf", out)
        self.assertIn("match_decision", out)
        self.assertIn("wcca", out.lower())


if __name__ == "__main__":
    unittest.main()
