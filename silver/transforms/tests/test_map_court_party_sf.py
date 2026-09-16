"""SF court_party mapping + transform-scope tests. Synthetic names only."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.sf_criminal_hf.map import payload_json  # noqa: E402
from silver.transforms.court_party_sf_criminal_hf import (  # noqa: E402
    SF_SOURCE_SYSTEM_SQL,
    SF_STATE_CODE_SQL,
)
from silver.transforms.map_court_party_sf import (  # noqa: E402
    business_fields,
    map_sf_bronze_to_court_parties,
)

SYN_NAME = "JANE Q PUBLIC"
LIVE_INGEST_RUN_ID = "26a31a80-a06f-4870-ab9e-cda5db38f47f"

SF_BRONZE = {
    "ingest_run_id": "sf-fixture-run",
    "ingested_at": datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc),
    "state_code": "CA",
    "source_system": "sf_criminal_hf",
    "source_record_id": "sf_case:99",
    "source_url": "https://huggingface.co/datasets/cfahlgren1/sf_criminal_court",
    "payload_format": "json",
    "payload": payload_json(
        {
            "case_number": "CRI00000000",
            "case_id": 99,
            "defendant_name": SYN_NAME,
            "filed_date": "2099-01-01",
            "scraped_at": "2099-01-02T00:00:00",
        }
    ),
    "payload_sha256": "abc123",
    "extract_method": "rest_bulk",
    "schema_version": "bronze.court_case_raw.v1",
}

WCCA_BRONZE = {
    "ingest_run_id": "wcca-fixture-run",
    "ingested_at": datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
    "state_code": "WI",
    "source_system": "wcca",
    "source_record_id": "51:2026CF000028",
    "payload_format": "html_snapshot",
    "payload": "<html>SYNTHETIC SHELL — NOT A REAL CASE</html>",
    "payload_sha256": "def456",
    "extract_method": "manual_upload",
    "schema_version": "bronze.court_case_raw.v1",
}

SQL_PATH = ROOT / "silver" / "transforms" / "court_party_sf_criminal_hf.sql"
PY_PATH = ROOT / "silver" / "transforms" / "court_party_sf_criminal_hf.py"


class MapSfCourtPartyTests(unittest.TestCase):
    def test_preserves_lineage_drops_payload(self) -> None:
        rows = map_sf_bronze_to_court_parties(SF_BRONZE, transform_run_id="run-1")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source_system"], "sf_criminal_hf")
        self.assertEqual(row["state_code"], "CA")
        self.assertEqual(row["source_record_id"], "sf_case:99")
        self.assertEqual(row["ingest_run_id"], "sf-fixture-run")
        self.assertEqual(row["payload_sha256"], "abc123")
        self.assertEqual(row["bronze_schema_version"], "bronze.court_case_raw.v1")
        self.assertEqual(row["silver_schema_version"], "silver.court_party.v1")
        self.assertEqual(row["payload_parse_status"], "json_cases_v1")
        self.assertEqual(row["party_role"], "defendant")
        self.assertEqual(row["party_ordinal"], 1)
        self.assertEqual(row["raw_name"], SYN_NAME)
        self.assertEqual(row["name_first"], "JANE")
        self.assertEqual(row["name_last"], "PUBLIC")
        self.assertIsNone(row["dob"])
        self.assertNotIn("payload", row)
        self.assertIn("missing_dob", row["dq_flags"])

    def test_idempotent_business_fields(self) -> None:
        a = map_sf_bronze_to_court_parties(SF_BRONZE, transform_run_id="run-a")
        b = map_sf_bronze_to_court_parties(SF_BRONZE, transform_run_id="run-b")
        self.assertEqual(business_fields(a[0]), business_fields(b[0]))
        self.assertNotEqual(a[0]["transform_run_id"], b[0]["transform_run_id"])

    def test_blank_name_emits_no_row(self) -> None:
        bronze = dict(SF_BRONZE)
        bronze["payload"] = payload_json(
            {
                "case_number": "CRI00000000",
                "case_id": 99,
                "defendant_name": "  ",
                "filed_date": "2099-01-01",
                "scraped_at": "2099-01-02T00:00:00",
            }
        )
        self.assertEqual(map_sf_bronze_to_court_parties(bronze, transform_run_id="run-1"), [])

    def test_wcca_bronze_is_not_mapped(self) -> None:
        self.assertEqual(
            map_sf_bronze_to_court_parties(WCCA_BRONZE, transform_run_id="run-1"),
            [],
        )

    def test_live_ingest_run_id_is_identifier_only(self) -> None:
        # Documented live Bronze run id (not PII). Mapper must copy whatever
        # ingest_run_id the Bronze row carries.
        bronze = dict(SF_BRONZE)
        bronze["ingest_run_id"] = LIVE_INGEST_RUN_ID
        row = map_sf_bronze_to_court_parties(bronze, transform_run_id="run-1")[0]
        self.assertEqual(row["ingest_run_id"], LIVE_INGEST_RUN_ID)


class TransformScopeTests(unittest.TestCase):
    def test_sql_delete_is_scoped_to_sf_ca(self) -> None:
        sql = SQL_PATH.read_text(encoding="utf-8")
        self.assertIn("WHERE t.source_system = 'sf_criminal_hf'", sql)
        self.assertIn("AND t.state_code = 'CA'", sql)
        self.assertIn("WHEN MATCHED AND t.source_system = 'sf_criminal_hf'", sql)
        self.assertIn("WHEN NOT MATCHED AND s.source_system = 'sf_criminal_hf'", sql)
        self.assertIn("r.source_system = 'sf_criminal_hf'", sql)
        self.assertIn("r.state_code = 'CA'", sql)
        self.assertIn("json_cases_v1", sql)
        self.assertNotIn("parse_parties_from_ssr_text", sql)
        self.assertNotIn("html_ssr_v1", sql)
        self.assertNotIn("MERGE INTO us_criminal_bg.silver.court_case", sql)
        self.assertNotIn("MERGE INTO us_criminal_bg.silver.court_charge", sql)
        delete_block = sql.split("DELETE FROM us_criminal_bg.silver.court_party")[1]
        self.assertIn("t.source_system = 'sf_criminal_hf'", delete_block)
        self.assertIn("t.state_code = 'CA'", delete_block)
        # Must not delete by case key alone (that would wipe wcca on collision).
        self.assertNotIn("DELETE FROM us_criminal_bg.silver.court_party t\nWHERE EXISTS", sql)

    def test_python_job_constants_are_sf_only(self) -> None:
        self.assertEqual(SF_SOURCE_SYSTEM_SQL, "sf_criminal_hf")
        self.assertEqual(SF_STATE_CODE_SQL, "CA")
        py = PY_PATH.read_text(encoding="utf-8")
        self.assertIn("r.source_system = '{SF_SOURCE_SYSTEM_SQL}'", py)
        self.assertIn("r.state_code = '{SF_STATE_CODE_SQL}'", py)
        self.assertIn("t.source_system = '{SF_SOURCE_SYSTEM_SQL}'", py)
        self.assertIn("t.state_code = '{SF_STATE_CODE_SQL}'", py)
        self.assertNotIn("from sources.wcca", py)

    def test_help_does_not_need_spark(self) -> None:
        out = subprocess.check_output(
            [sys.executable, str(PY_PATH), "--help"],
            text=True,
        )
        self.assertIn("sf_criminal_hf", out)
        self.assertIn("wcca", out.lower())  # mentions it will not delete wcca

    def test_sql_file_mentions_wcca_only_as_exclusion(self) -> None:
        sql = SQL_PATH.read_text(encoding="utf-8")
        self.assertIn("wcca", sql.lower())
        self.assertIn("does not delete wcca", sql.lower())


class PayloadShapeTests(unittest.TestCase):
    def test_payload_round_trip_from_bronze_mapper(self) -> None:
        payload = json.loads(SF_BRONZE["payload"])
        self.assertEqual(payload["defendant_name"], SYN_NAME)
        self.assertEqual(payload["county"], "San Francisco")
        self.assertEqual(payload["locality"], "SF")
        self.assertIn("case_id", payload)


if __name__ == "__main__":
    unittest.main()
