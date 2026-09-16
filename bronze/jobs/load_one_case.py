#!/usr/bin/env python3
"""Load one manual_upload WCCA HTML into Bronze. Does not scrape.

CAPTCHA / ToS walls stay in place. Pass a file a human already exported.
Auth is the Databricks CLI profile — never commit .databrickscfg, tokens, or
case HTML.

PROFILE / warehouse defaults (env-overridable, not secrets):
  DATABRICKS_CONFIG_PROFILE  (default WCCA_BRONZE)
  DATABRICKS_WAREHOUSE_ID    (default e40cabf0355df274)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "WCCA_BRONZE")
WH = os.environ.get("DATABRICKS_WAREHOUSE_ID", "e40cabf0355df274")
SCHEMA_VERSION = "bronze.court_case_raw.v1"


def sh(*args: str) -> str:
    return subprocess.check_output(list(args), text=True)


def sql(statement: str) -> dict:
    body = {
        "warehouse_id": WH,
        "catalog": "us_criminal_bg",
        "schema": "bronze",
        "statement": statement,
        "wait_timeout": "50s",
    }
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", prefix="wcca_sql_", delete=False
    ) as handle:
        json.dump(body, handle)
        tmp = handle.name
    try:
        out = sh(
            "databricks",
            "api",
            "post",
            "/api/2.0/sql/statements",
            "-p",
            PROFILE,
            "--json",
            f"@{tmp}",
        )
    finally:
        os.unlink(tmp)
    d = json.loads(out)
    state = d.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(json.dumps(d.get("status"), indent=2)[:2000])
    return d


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "''")


def dbfs_volume_paths(ingest_date: str, run_id: str, filename: str) -> tuple[str, str]:
    """UC volume layout plus the dbfs: URIs required by `databricks fs`.

    Bare /Volumes/... is a local path to the CLI (that was a live bug).
    mkdir/cp must use dbfs:/Volumes/...
    """
    volume_uc = (
        "/Volumes/us_criminal_bg/bronze/court_source/"
        f"state_code=WI/source_system=wcca/ingest_date={ingest_date}/"
        f"ingest_run_id={run_id}"
    )
    dest_uc = f"{volume_uc}/{filename}"
    return f"dbfs:{volume_uc}", f"dbfs:{dest_uc}"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Copy one HTML export into the Bronze UC volume and INSERT "
            "ingest_run + court_case_raw. manual_upload only — does not scrape."
        )
    )
    ap.add_argument("path", type=Path, help="Local HTML file already exported by a human")
    ap.add_argument("--source-url", required=True, help="WCCA URL or UI deep link")
    ap.add_argument(
        "--source-record-id",
        required=True,
        help="Native WCCA id, or WI|wcca|{county}|{case_number}",
    )
    ap.add_argument("--payload-format", default="html_snapshot")
    args = ap.parse_args()

    if not args.path.is_file():
        raise SystemExit(f"not a file: {args.path}")

    data = args.path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    digest = hashlib.sha256(data).hexdigest()
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    ingest_date = now.strftime("%Y-%m-%d")
    volume_dbfs, dest_dbfs = dbfs_volume_paths(ingest_date, run_id, args.path.name)
    dest_uc = dest_dbfs.removeprefix("dbfs:")

    sh("databricks", "fs", "mkdir", volume_dbfs, "-p", PROFILE)
    sh(
        "databricks",
        "fs",
        "cp",
        str(args.path.resolve()),
        dest_dbfs,
        "--overwrite",
        "-p",
        PROFILE,
    )

    sql(
        f"""
INSERT INTO us_criminal_bg.bronze.ingest_run
(ingest_run_id, ingest_run_label, state_code, source_system, extract_method,
 started_at, finished_at, status, row_count, notes)
VALUES (
  '{run_id}',
  'wcca_WI_{now.strftime('%Y%m%d_%H%M%S')}Z',
  'WI', 'wcca', 'manual_upload',
  TIMESTAMP '{ts}', TIMESTAMP '{ts}',
  'succeeded', 1,
  'manual_upload proof load'
)
"""
    )

    sql(
        f"""
INSERT INTO us_criminal_bg.bronze.court_case_raw
(ingest_run_id, ingested_at, state_code, source_system, source_record_id, source_url,
 payload_format, payload, payload_sha256, extract_method, schema_version)
VALUES (
  '{run_id}',
  TIMESTAMP '{ts}',
  'WI', 'wcca',
  '{esc(args.source_record_id)}',
  '{esc(args.source_url)}',
  '{esc(args.payload_format)}',
  '{esc(text)}',
  '{digest}',
  'manual_upload',
  '{SCHEMA_VERSION}'
)
"""
    )

    c1 = sql("SELECT COUNT(*) AS c FROM us_criminal_bg.bronze.ingest_run")
    c2 = sql("SELECT COUNT(*) AS c FROM us_criminal_bg.bronze.court_case_raw")
    print(
        json.dumps(
            {
                "ingest_run_id": run_id,
                "volume_path": dest_uc,
                "volume_dbfs": dest_dbfs,
                "payload_sha256": digest,
                "ingest_run_count": c1["result"]["data_array"][0][0],
                "court_case_raw_count": c2["result"]["data_array"][0][0],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
