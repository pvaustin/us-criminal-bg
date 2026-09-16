#!/usr/bin/env python3
"""Load published SF HF cases.parquet into Bronze. Does not scrape.

Research-only named corpus (source_system=sf_criminal_hf, state_code=CA).
Not employer product. Not commercial CRA. Isolated from the WI WCCA path.

Downloads Hugging Face cases.parquet only. Lands under
dbfs:/Volumes/.../state_code=CA/source_system=sf_criminal_hf/...
then INSERT ingest_run + MERGE court_case_raw with JSON payload that
preserves defendant_name.

Auth is the Databricks CLI profile — never commit .databrickscfg, tokens,
or parquet files.

PROFILE / warehouse defaults (env-overridable, not secrets):
  DATABRICKS_CONFIG_PROFILE  (default WCCA_BRONZE)
  DATABRICKS_WAREHOUSE_ID    (default e40cabf0355df274)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sources.sf_criminal_hf.map import (  # noqa: E402
    CASES_PARQUET_FILENAME,
    CASES_PARQUET_URL,
    EXTRACT_METHOD,
    SOURCE_SYSTEM,
    STATE_CODE,
    assert_allowed_cases_parquet_url,
    court_case_raw_merge_sql,
    dbfs_volume_paths,
    ingest_run_finalize_sql,
    ingest_run_insert_sql,
    new_ingest_run_id,
)

PROFILE = os.environ.get("DATABRICKS_CONFIG_PROFILE", "WCCA_BRONZE")
WH = os.environ.get("DATABRICKS_WAREHOUSE_ID", "e40cabf0355df274")
USER_AGENT = "us-criminal-bg-sf-hf-research-loader/1.0"


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
        "w", suffix=".json", prefix="sf_hf_sql_", delete=False
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
    payload = json.loads(out)
    state = payload.get("status", {}).get("state")
    statement_id = payload.get("statement_id")
    while state in {"PENDING", "RUNNING"}:
        if not statement_id:
            break
        time.sleep(2)
        payload = json.loads(
            sh(
                "databricks",
                "api",
                "get",
                f"/api/2.0/sql/statements/{statement_id}",
                "-p",
                PROFILE,
            )
        )
        state = payload.get("status", {}).get("state")
    if state != "SUCCEEDED":
        raise RuntimeError(json.dumps(payload.get("status"), indent=2)[:4000])
    return payload


def download_cases_parquet(url: str, dest: Path) -> None:
    assert_allowed_cases_parquet_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    if dest.stat().st_size < 100:
        raise SystemExit(f"download too small: {dest} ({dest.stat().st_size} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Download published HF cases.parquet into the Bronze UC volume and "
            "MERGE court_case_raw. rest_bulk only — does not scrape courts. "
            "Research CA/sf_criminal_hf; does not touch WI/wcca."
        )
    )
    ap.add_argument(
        "--url",
        default=CASES_PARQUET_URL,
        help="Published Hugging Face cases.parquet URL",
    )
    ap.add_argument(
        "--local-parquet",
        type=Path,
        help="Skip download; use an already-fetched cases.parquet (not committed)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional SQL LIMIT for a small proof load",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print volume path + SQL; do not download or call Databricks",
    )
    args = ap.parse_args()

    assert_allowed_cases_parquet_url(args.url)
    if args.local_parquet and args.local_parquet.suffix.lower() != ".parquet":
        raise SystemExit("local file must be .parquet")

    run_id = new_ingest_run_id()
    now = datetime.now(timezone.utc)
    ingest_date = now.strftime("%Y-%m-%d")
    volume_uc, volume_dbfs, dest_dbfs = dbfs_volume_paths(ingest_date, run_id)
    parquet_uc = f"{volume_uc}/{CASES_PARQUET_FILENAME}"
    running_sql = ingest_run_insert_sql(
        run_id=run_id,
        now=now,
        status="running",
        row_count=None,
        notes="sf_criminal_hf published cases.parquet rest_bulk (research-only)",
    )
    merge_sql = court_case_raw_merge_sql(
        run_id=run_id,
        now=now,
        parquet_uc_path=parquet_uc,
        limit=args.limit,
    )
    done_sql = ingest_run_finalize_sql(run_id=run_id, now=now, status="succeeded")

    plan = {
        "source_system": SOURCE_SYSTEM,
        "state_code": STATE_CODE,
        "extract_method": EXTRACT_METHOD,
        "ingest_run_id": run_id,
        "volume_path": parquet_uc,
        "volume_dbfs": dest_dbfs,
        "url": args.url,
        "limit": args.limit,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        print("-- ingest_run INSERT --")
        print(running_sql)
        print("-- court_case_raw MERGE --")
        print(merge_sql)
        print("-- ingest_run UPDATE --")
        print(done_sql)
        return

    tmp_dir = tempfile.TemporaryDirectory(prefix="sf_criminal_hf_")
    try:
        local = (
            args.local_parquet.resolve()
            if args.local_parquet
            else Path(tmp_dir.name) / CASES_PARQUET_FILENAME
        )
        if args.local_parquet:
            if not local.is_file():
                raise SystemExit(f"not a file: {local}")
        else:
            download_cases_parquet(args.url, local)

        sh("databricks", "fs", "mkdir", volume_dbfs, "-p", PROFILE)
        sh(
            "databricks",
            "fs",
            "cp",
            str(local),
            dest_dbfs,
            "--overwrite",
            "-p",
            PROFILE,
        )
        sql(running_sql)
        try:
            sql(merge_sql)
            sql(done_sql)
        except Exception:
            sql(ingest_run_finalize_sql(run_id=run_id, now=now, status="failed"))
            raise
    finally:
        tmp_dir.cleanup()

    c1 = sql(
        "SELECT COUNT(*) AS c FROM us_criminal_bg.bronze.ingest_run "
        f"WHERE ingest_run_id = '{run_id}'"
    )
    c2 = sql(
        "SELECT COUNT(*) AS c FROM us_criminal_bg.bronze.court_case_raw "
        f"WHERE ingest_run_id = '{run_id}'"
    )
    plan["ingest_run_count"] = c1["result"]["data_array"][0][0]
    plan["court_case_raw_count"] = c2["result"]["data_array"][0][0]
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
