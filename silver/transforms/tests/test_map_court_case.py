"""Silver row mapping tests. Fixtures are synthetic, not real court records."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from silver.transforms.map_court_case import (  # noqa: E402
    business_fields,
    map_bronze_to_court_case,
)

LIVE_BRONZE = {
    "ingest_run_id": "686ebfa4-810c-485a-9a56-94d329cd14b1",
    "ingested_at": datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
    "state_code": "WI",
    "source_system": "wcca",
    "source_record_id": "51:2026CF000028",
    "source_url": (
        "https://wcca.wicourts.gov/caseDetail.html"
        "?caseNo=2026CF000028&countyNo=51&index=0&mode=details"
    ),
    "payload_format": "html_snapshot",
    "payload": "<html><title>SYNTHETIC SHELL — NOT A REAL CASE</title></html>",
    "payload_sha256": "abc123",
    "extract_method": "manual_upload",
    "schema_version": "bronze.court_case_raw.v1",
}


class MapCourtCaseTests(unittest.TestCase):
    def test_preserves_lineage_drops_payload(self) -> None:
        row = map_bronze_to_court_case(LIVE_BRONZE, transform_run_id="run-1")
        self.assertEqual(row["ingest_run_id"], LIVE_BRONZE["ingest_run_id"])
        self.assertEqual(row["payload_sha256"], "abc123")
        self.assertEqual(row["bronze_schema_version"], "bronze.court_case_raw.v1")
        self.assertNotIn("payload", row)
        self.assertEqual(row["county_code"], "51")
        self.assertEqual(row["case_number"], "2026CF000028")
        self.assertEqual(row["case_type"], "CF")
        self.assertIsNone(row["caption"])
        self.assertIsNone(row["filed_date"])
        self.assertEqual(row["payload_parse_status"], "identifiers_only")
        self.assertEqual(row["silver_schema_version"], "silver.court_case.v1")

    def test_idempotent_business_fields_on_rerun(self) -> None:
        a = map_bronze_to_court_case(LIVE_BRONZE, transform_run_id="run-a")
        b = map_bronze_to_court_case(LIVE_BRONZE, transform_run_id="run-b")
        self.assertEqual(business_fields(a), business_fields(b))
        self.assertNotEqual(a["transform_run_id"], b["transform_run_id"])

    def test_does_not_copy_title_into_caption(self) -> None:
        row = map_bronze_to_court_case(LIVE_BRONZE, transform_run_id="run-1")
        self.assertIsNone(row["caption"])
        self.assertIn("unparsed_html_spa", row["dq_flags"])


if __name__ == "__main__":
    unittest.main()
