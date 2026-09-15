"""Unit tests for WCCA identifier / URL / conservative HTML parsing.

Fixtures are synthetic and are never claimed as real court records.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.wcca.parse import (  # noqa: E402
    parse_source_record_id,
    parse_source_url,
    parse_wcca_bronze_row,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Live Bronze sample identifiers (workspace proof). Used only as id/url shape.
# Do not treat these strings as a fixture of case caption, parties, or filing date.
LIVE_SOURCE_RECORD_ID = "51:2026CF000028"
LIVE_SOURCE_URL = (
    "https://wcca.wicourts.gov/caseDetail.html"
    "?caseNo=2026CF000028&countyNo=51&index=0&mode=details"
)


class ParseSourceRecordIdTests(unittest.TestCase):
    def test_colon_county_case(self) -> None:
        parts = parse_source_record_id(LIVE_SOURCE_RECORD_ID)
        self.assertEqual(parts.county_code, "51")
        self.assertEqual(parts.case_number, "2026CF000028")

    def test_composed_bronze_form(self) -> None:
        parts = parse_source_record_id("WI|wcca|51|2026CF000028")
        self.assertEqual(parts.county_code, "51")
        self.assertEqual(parts.case_number, "2026CF000028")

    def test_strips_leading_zeros_on_numeric_county(self) -> None:
        parts = parse_source_record_id("051:2026CF000028")
        self.assertEqual(parts.county_code, "51")

    def test_blank(self) -> None:
        parts = parse_source_record_id("  ")
        self.assertIsNone(parts.county_code)
        self.assertIsNone(parts.case_number)


class ParseSourceUrlTests(unittest.TestCase):
    def test_wcca_query_params(self) -> None:
        parts = parse_source_url(LIVE_SOURCE_URL)
        self.assertEqual(parts.county_code, "51")
        self.assertEqual(parts.case_number, "2026CF000028")

    def test_missing_url(self) -> None:
        parts = parse_source_url(None)
        self.assertIsNone(parts.county_code)
        self.assertIsNone(parts.case_number)


class ParseBronzeRowTests(unittest.TestCase):
    def test_live_sample_identifiers_do_not_invent_facts(self) -> None:
        spa = (FIXTURES / "synthetic_spa_shell.html").read_text(encoding="utf-8")
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id=LIVE_SOURCE_RECORD_ID,
            source_url=LIVE_SOURCE_URL,
            payload_format="html_snapshot",
            payload=spa,
        )
        self.assertEqual(result.county_code, "51")
        self.assertEqual(result.case_number, "2026CF000028")
        self.assertEqual(result.case_type, "CF")
        self.assertIsNone(result.filed_date)
        self.assertIsNone(result.caption)
        self.assertEqual(result.payload_parse_status, "identifiers_only")
        self.assertIn("missing_caption", result.dq_flags)
        self.assertIn("missing_filed_date", result.dq_flags)
        self.assertIn("unparsed_html_spa", result.dq_flags)
        self.assertNotIn("identifier_url_mismatch", result.dq_flags)

    def test_url_wins_on_mismatch(self) -> None:
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="40:2026CF000028",
            source_url=LIVE_SOURCE_URL,
            payload_format="html_snapshot",
            payload="",
        )
        self.assertEqual(result.county_code, "51")
        self.assertIn("identifier_url_mismatch", result.dq_flags)

    def test_spa_shell_does_not_scrape_title_as_caption(self) -> None:
        spa = (FIXTURES / "synthetic_spa_shell.html").read_text(encoding="utf-8")
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="01:2099CF000001",
            source_url=(
                "https://example.test/caseDetail.html?caseNo=2099CF000001&countyNo=1"
            ),
            payload_format="html_snapshot",
            payload=spa,
        )
        self.assertIsNone(result.caption)
        self.assertIsNone(result.filed_date)
        self.assertEqual(result.payload_parse_status, "identifiers_only")

    def test_synthetic_embedded_json_reads_only_explicit_keys(self) -> None:
        html = (FIXTURES / "synthetic_embedded_json.html").read_text(encoding="utf-8")
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="01:2099CF000001",
            source_url=(
                "https://example.test/caseDetail.html?caseNo=2099CF000001&countyNo=1"
            ),
            payload_format="html_snapshot",
            payload=html,
        )
        self.assertEqual(result.caption, "SYNTHETIC v. FIXTURE")
        self.assertEqual(result.filed_date, date(2099, 1, 1))
        self.assertEqual(result.payload_parse_status, "structured_facts")
        self.assertNotIn("missing_caption", result.dq_flags)
        self.assertNotIn("unparsed_html_spa", result.dq_flags)

    def test_synthetic_embedded_null_facts_stay_null(self) -> None:
        html = (FIXTURES / "synthetic_embedded_null_facts.html").read_text(
            encoding="utf-8"
        )
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="01:2099CF000001",
            source_url=(
                "https://example.test/caseDetail.html?caseNo=2099CF000001&countyNo=1"
            ),
            payload_format="html_snapshot",
            payload=html,
        )
        self.assertIsNone(result.caption)
        self.assertIsNone(result.filed_date)
        self.assertEqual(result.payload_parse_status, "identifiers_only")
        self.assertIn("missing_caption", result.dq_flags)

    def test_json_payload_explicit_caption_only(self) -> None:
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="01:2099CM000001",
            source_url=(
                "https://example.test/caseDetail.html?caseNo=2099CM000001&countyNo=1"
            ),
            payload_format="json",
            payload=(
                '{"synthetic": true, "notice": "NOT A REAL COURT CASE",'
                ' "countyNo": "01", "caseNo": "2099CM000001",'
                ' "caption": "SYNTHETIC v. FIXTURE"}'
            ),
        )
        self.assertEqual(result.case_type, "CM")
        self.assertEqual(result.caption, "SYNTHETIC v. FIXTURE")
        self.assertIsNone(result.filed_date)
        self.assertEqual(result.payload_parse_status, "structured_facts")
        self.assertNotIn("unparsed_html_spa", result.dq_flags)
        self.assertIn("missing_filed_date", result.dq_flags)

    def test_unsupported_source(self) -> None:
        result = parse_wcca_bronze_row(
            source_system="other_court",
            source_record_id="abc",
            source_url=None,
            payload_format="json",
            payload="{}",
        )
        self.assertEqual(result.payload_parse_status, "unsupported_source")
        self.assertIn("unsupported_source_parser", result.dq_flags)
        self.assertIsNone(result.county_code)

    def test_identifier_error(self) -> None:
        result = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id="not-an-id",
            source_url=None,
            payload_format="html_snapshot",
            payload="",
        )
        self.assertEqual(result.payload_parse_status, "identifier_error")
        self.assertIn("county_code_unparsed", result.dq_flags)
        self.assertIn("case_number_unparsed", result.dq_flags)

    def test_flags_are_sorted_and_deterministic(self) -> None:
        a = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id=LIVE_SOURCE_RECORD_ID,
            source_url=LIVE_SOURCE_URL,
            payload_format="html_snapshot",
            payload="<html></html>",
        )
        b = parse_wcca_bronze_row(
            source_system="wcca",
            source_record_id=LIVE_SOURCE_RECORD_ID,
            source_url=LIVE_SOURCE_URL,
            payload_format="html_snapshot",
            payload="<html></html>",
        )
        self.assertEqual(a.dq_flags, b.dq_flags)
        self.assertEqual(a.dq_flags, tuple(sorted(a.dq_flags)))


if __name__ == "__main__":
    unittest.main()
