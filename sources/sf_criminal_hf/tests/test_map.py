"""Unit tests for SF HF Bronze mapping. Synthetic rows only — not real cases."""

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

from sources.sf_criminal_hf.map import (  # noqa: E402
    CASES_PARQUET_URL,
    EXTRACT_METHOD,
    SOURCE_SYSTEM,
    STATE_CODE,
    assert_allowed_cases_parquet_url,
    court_case_raw_merge_sql,
    dbfs_volume_paths,
    ingest_run_insert_sql,
    payload_dict,
    payload_json,
    source_record_id,
    volume_uc_prefix,
)

SYNTHETIC = {
    "case_number": "CRI00000000",
    "case_id": 1,
    "defendant_name": "FIXTURE, SYNTHETIC DEFENDANT",
    "filed_date": "2099-01-01",
    "scraped_at": "2099-01-02T00:00:00",
}


class SourceRecordIdTests(unittest.TestCase):
    def test_prefers_case_id(self) -> None:
        self.assertEqual(source_record_id(SYNTHETIC), "1")

    def test_falls_back_to_case_number(self) -> None:
        row = dict(SYNTHETIC)
        row["case_id"] = None
        self.assertEqual(source_record_id(row), "CRI00000000")

    def test_string_case_id(self) -> None:
        row = dict(SYNTHETIC)
        row["case_id"] = "  42 "
        self.assertEqual(source_record_id(row), "42")

    def test_blank_raises(self) -> None:
        with self.assertRaises(ValueError):
            source_record_id({"case_id": None, "case_number": "  "})


class PayloadTests(unittest.TestCase):
    def test_preserves_defendant_name(self) -> None:
        payload = payload_dict(SYNTHETIC)
        self.assertEqual(payload["defendant_name"], "FIXTURE, SYNTHETIC DEFENDANT")
        self.assertEqual(payload["case_number"], "CRI00000000")
        self.assertEqual(payload["case_id"], 1)
        self.assertIn("defendant_name", json.loads(payload_json(SYNTHETIC)))

    def test_keeps_defendant_name_key_when_missing(self) -> None:
        row = {"case_number": "CRI00000000", "case_id": 2}
        payload = payload_dict(row)
        self.assertIn("defendant_name", payload)
        self.assertIsNone(payload["defendant_name"])


class VolumePathTests(unittest.TestCase):
    def test_ca_source_and_dbfs_prefix(self) -> None:
        uc, dbfs_dir, dbfs_file = dbfs_volume_paths("2026-09-16", "run-1")
        self.assertIn("state_code=CA", uc)
        self.assertIn("source_system=sf_criminal_hf", uc)
        self.assertTrue(uc.startswith("/Volumes/us_criminal_bg/bronze/court_source/"))
        self.assertEqual(volume_uc_prefix("2026-09-16", "run-1"), uc)
        self.assertTrue(dbfs_dir.startswith("dbfs:/Volumes/"))
        self.assertTrue(dbfs_file.endswith("/cases.parquet"))
        self.assertNotIn("state_code=WI", uc)
        self.assertNotIn("wcca", uc)


class UrlAllowlistTests(unittest.TestCase):
    def test_default_url_ok(self) -> None:
        assert_allowed_cases_parquet_url(CASES_PARQUET_URL)

    def test_rejects_virginia(self) -> None:
        with self.assertRaises(ValueError):
            assert_allowed_cases_parquet_url(
                "https://virginiacourtdata.org/downloads/circuit-criminal.csv"
            )

    def test_rejects_cook(self) -> None:
        with self.assertRaises(ValueError):
            assert_allowed_cases_parquet_url(
                "https://huggingface.co/datasets/example/cook-county/resolve/main/cases.parquet"
            )

    def test_rejects_other_hf_file(self) -> None:
        with self.assertRaises(ValueError):
            assert_allowed_cases_parquet_url(
                "https://huggingface.co/datasets/cfahlgren1/sf_criminal_court/resolve/main/attorneys.parquet"
            )


class SqlBuilderTests(unittest.TestCase):
    def test_merge_preserves_research_lineage(self) -> None:
        now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        sql = court_case_raw_merge_sql(
            run_id="run-1",
            now=now,
            parquet_uc_path="/Volumes/us_criminal_bg/bronze/court_source/"
            "state_code=CA/source_system=sf_criminal_hf/ingest_date=2026-09-16/"
            "ingest_run_id=run-1/cases.parquet",
        )
        self.assertIn("MERGE INTO us_criminal_bg.bronze.court_case_raw", sql)
        self.assertIn("'CA' AS state_code", sql)
        self.assertIn("'sf_criminal_hf' AS source_system", sql)
        self.assertIn("'rest_bulk' AS extract_method", sql)
        self.assertIn("defendant_name", sql)
        self.assertIn("CAST(case_id AS STRING)", sql)
        self.assertIn("FROM parquet.`", sql)
        self.assertNotIn("dbfs:", sql)
        self.assertNotIn("wcca", sql)
        self.assertNotIn("'WI'", sql)

    def test_strips_dbfs_prefix_for_sql(self) -> None:
        now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        sql = court_case_raw_merge_sql(
            run_id="run-1",
            now=now,
            parquet_uc_path="dbfs:/Volumes/us_criminal_bg/bronze/court_source/cases.parquet",
        )
        self.assertIn("FROM parquet.`/Volumes/us_criminal_bg/bronze/court_source/cases.parquet`", sql)
        self.assertNotIn("parquet.`dbfs:", sql)

    def test_limit(self) -> None:
        now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        sql = court_case_raw_merge_sql(
            run_id="run-1",
            now=now,
            parquet_uc_path="/Volumes/x/cases.parquet",
            limit=10,
        )
        self.assertIn("LIMIT 10", sql)

    def test_ingest_run_rest_bulk(self) -> None:
        now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
        sql = ingest_run_insert_sql(
            run_id="run-1",
            now=now,
            status="running",
            row_count=None,
            notes="test",
        )
        self.assertEqual(SOURCE_SYSTEM, "sf_criminal_hf")
        self.assertEqual(STATE_CODE, "CA")
        self.assertEqual(EXTRACT_METHOD, "rest_bulk")
        self.assertIn("'CA'", sql)
        self.assertIn("'sf_criminal_hf'", sql)
        self.assertIn("'rest_bulk'", sql)


class DryRunCliTests(unittest.TestCase):
    def test_dry_run_prints_plan_without_databricks(self) -> None:
        script = ROOT / "bronze" / "jobs" / "load_sf_criminal_hf.py"
        out = subprocess.check_output(
            [sys.executable, str(script), "--dry-run", "--limit", "5"],
            text=True,
        )
        self.assertIn("sf_criminal_hf", out)
        self.assertIn('"state_code": "CA"', out)
        self.assertIn("defendant_name", out)
        self.assertIn("dbfs:/Volumes/", out)
        self.assertIn("MERGE INTO us_criminal_bg.bronze.court_case_raw", out)
        self.assertIn("LIMIT 5", out)
        self.assertNotIn("source_system=wcca", out)
        self.assertNotIn("'WI'", out)


if __name__ == "__main__":
    unittest.main()
