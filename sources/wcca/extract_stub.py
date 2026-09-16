"""WCCA → Bronze extract stub.

MVP: document inputs and write path only. Do not bypass CAPTCHA, auth, or ToS.
Paid REST bulk is a future extract_method=rest_bulk path after subscription.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

SOURCE_SYSTEM = "wcca"
STATE_CODE = "WI"
SCHEMA_VERSION = "bronze.court_case_raw.v1"

ExtractMethod = Literal["interactive_export", "manual_upload", "rest_bulk"]


@dataclass(frozen=True)
class IngestRun:
    ingest_run_id: str
    ingested_at: datetime
    state_code: str
    source_system: str
    extract_method: ExtractMethod


def new_ingest_run(extract_method: ExtractMethod = "manual_upload") -> IngestRun:
    now = datetime.now(timezone.utc)
    return IngestRun(
        ingest_run_id=str(uuid4()),
        ingested_at=now,
        state_code=STATE_CODE,
        source_system=SOURCE_SYSTEM,
        extract_method=extract_method,
    )


def volume_prefix(run: IngestRun) -> str:
    """Unity Catalog volume path fragment (see docs/bronze/NAMING.md)."""
    ingest_date = run.ingested_at.strftime("%Y-%m-%d")
    return (
        "/Volumes/us_criminal_bg/bronze/court_source/"
        f"state_code={run.state_code}/"
        f"source_system={run.source_system}/"
        f"ingest_date={ingest_date}/"
        f"ingest_run_id={run.ingest_run_id}/"
    )


def main() -> None:
    run = new_ingest_run("manual_upload")
    print("ingest_run_id=", run.ingest_run_id)
    print("volume_prefix=", volume_prefix(run))
    print("schema_version=", SCHEMA_VERSION)
    print(
        "Next: drop legitimate export files under volume_prefix, "
        "then register rows in us_criminal_bg.bronze.court_case_raw"
    )


if __name__ == "__main__":
    main()
