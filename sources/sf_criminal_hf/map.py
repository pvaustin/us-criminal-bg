"""San Francisco Hugging Face cases.parquet → Bronze mapping.

Research-only. Published parquet download, not a court scrape.
Synthetic unit tests must never be claimed as real court records.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlparse
from uuid import uuid4

SOURCE_SYSTEM = "sf_criminal_hf"
STATE_CODE = "CA"
EXTRACT_METHOD = "rest_bulk"
SCHEMA_VERSION = "bronze.court_case_raw.v1"
PAYLOAD_FORMAT = "json"
HF_DATASET_URL = "https://huggingface.co/datasets/cfahlgren1/sf_criminal_court"
CASES_PARQUET_FILENAME = "cases.parquet"
CASES_PARQUET_URL = (
    "https://huggingface.co/datasets/cfahlgren1/sf_criminal_court/resolve/main/cases.parquet"
)
PAYLOAD_COLUMNS = (
    "case_number",
    "case_id",
    "defendant_name",
    "filed_date",
    "scraped_at",
)

_ALLOWED_NETLOCS = frozenset({"huggingface.co", "www.huggingface.co"})
_FORBIDDEN_URL_MARKERS = (
    "virginiacourtdata",
    "cookcounty",
    "cook-county",
    "cook_county",
    "wcca.wicourts",
)


def assert_allowed_cases_parquet_url(url: str) -> None:
    """Refuse anything that is not the published HF cases.parquet."""
    lowered = url.strip().lower()
    for marker in _FORBIDDEN_URL_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"refusing URL ({marker}): SF loader only downloads published "
                "Hugging Face cases.parquet (no VA, no Cook, no court scrape)"
            )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("cases.parquet URL must be http(s)")
    if parsed.netloc.lower() not in _ALLOWED_NETLOCS:
        raise ValueError("cases.parquet URL must be huggingface.co")
    path = parsed.path.lower()
    if "/datasets/cfahlgren1/sf_criminal_court/" not in path:
        raise ValueError("cases.parquet URL must be the cfahlgren1/sf_criminal_court dataset")
    if not path.endswith("/cases.parquet"):
        raise ValueError("SF loader downloads cases.parquet only")


def source_record_id(row: Mapping[str, Any]) -> str:
    """Prefer case_id; fall back to case_number."""
    case_id = row.get("case_id")
    if case_id is not None and str(case_id).strip() != "":
        if isinstance(case_id, bool):
            raise ValueError("case_id must not be a boolean")
        if isinstance(case_id, float):
            if not case_id.is_integer():
                raise ValueError("case_id must be an integer id")
            return str(int(case_id))
        if isinstance(case_id, int):
            return str(case_id)
        text = str(case_id).strip()
        if text.endswith(".0") and text.replace(".", "", 1).isdigit():
            return str(int(float(text)))
        return text
    case_number = row.get("case_number")
    if case_number is not None and str(case_number).strip():
        return str(case_number).strip()
    raise ValueError("row has neither case_id nor case_number")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return value


def payload_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    out = {col: _jsonable(row.get(col)) for col in PAYLOAD_COLUMNS}
    if "defendant_name" not in out:
        out["defendant_name"] = None
    return out


def payload_json(row: Mapping[str, Any]) -> str:
    """Canonical JSON payload. Always includes defendant_name (may be null)."""
    return json.dumps(payload_dict(row), ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def payload_sha256(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(payload_json(row).encode("utf-8")).hexdigest()


def volume_uc_prefix(ingest_date: str, ingest_run_id: str) -> str:
    return (
        "/Volumes/us_criminal_bg/bronze/court_source/"
        f"state_code={STATE_CODE}/source_system={SOURCE_SYSTEM}/"
        f"ingest_date={ingest_date}/ingest_run_id={ingest_run_id}"
    )


def dbfs_volume_paths(ingest_date: str, ingest_run_id: str) -> tuple[str, str, str]:
    """UC prefix, dbfs dir, dbfs file. CLI mkdir/cp must use dbfs:/Volumes/..."""
    volume_uc = volume_uc_prefix(ingest_date, ingest_run_id)
    dest_uc = f"{volume_uc}/{CASES_PARQUET_FILENAME}"
    return volume_uc, f"dbfs:{volume_uc}", f"dbfs:{dest_uc}"


def new_ingest_run_id() -> str:
    return str(uuid4())


def ingest_run_label(now: datetime) -> str:
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return f"{SOURCE_SYSTEM}_{STATE_CODE}_{utc.strftime('%Y%m%d_%H%M%S')}Z"


def sql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")


def ingest_run_insert_sql(
    *,
    run_id: str,
    now: datetime,
    status: str,
    row_count: int | None,
    notes: str,
) -> str:
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    ts = utc.strftime("%Y-%m-%d %H:%M:%S")
    count_sql = "NULL" if row_count is None else str(int(row_count))
    return f"""
INSERT INTO us_criminal_bg.bronze.ingest_run
(ingest_run_id, ingest_run_label, state_code, source_system, extract_method,
 started_at, finished_at, status, row_count, notes)
VALUES (
  '{sql_literal(run_id)}',
  '{sql_literal(ingest_run_label(utc))}',
  '{STATE_CODE}', '{SOURCE_SYSTEM}', '{EXTRACT_METHOD}',
  TIMESTAMP '{ts}', TIMESTAMP '{ts}',
  '{sql_literal(status)}', {count_sql},
  '{sql_literal(notes)}'
)
""".strip()


def ingest_run_finalize_sql(*, run_id: str, now: datetime, status: str) -> str:
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    ts = utc.strftime("%Y-%m-%d %H:%M:%S")
    return f"""
UPDATE us_criminal_bg.bronze.ingest_run
SET finished_at = TIMESTAMP '{ts}',
    status = '{sql_literal(status)}',
    row_count = (
      SELECT COUNT(*) FROM us_criminal_bg.bronze.court_case_raw
      WHERE ingest_run_id = '{sql_literal(run_id)}'
    )
WHERE ingest_run_id = '{sql_literal(run_id)}'
""".strip()


def court_case_raw_merge_sql(
    *,
    run_id: str,
    now: datetime,
    parquet_uc_path: str,
    limit: int | None = None,
) -> str:
    """MERGE from published parquet on the UC volume. SQL uses /Volumes (not dbfs:)."""
    if parquet_uc_path.startswith("dbfs:"):
        parquet_uc_path = parquet_uc_path.removeprefix("dbfs:")
    utc = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    ts = utc.strftime("%Y-%m-%d %H:%M:%S")
    limit_sql = f" LIMIT {int(limit)}" if limit is not None else ""
    parquet_lit = sql_literal(parquet_uc_path)
    payload_expr = """to_json(
      named_struct(
        'case_id', case_id,
        'case_number', case_number,
        'defendant_name', defendant_name,
        'filed_date', filed_date,
        'scraped_at', scraped_at
      ),
      map('ignoreNullFields', 'false')
    )"""
    source_id_expr = """CASE
        WHEN case_id IS NOT NULL THEN CAST(case_id AS STRING)
        ELSE NULLIF(TRIM(CAST(case_number AS STRING)), '')
      END"""
    return f"""
MERGE INTO us_criminal_bg.bronze.court_case_raw AS t
USING (
  SELECT
    '{sql_literal(run_id)}' AS ingest_run_id,
    TIMESTAMP '{ts}' AS ingested_at,
    '{STATE_CODE}' AS state_code,
    '{SOURCE_SYSTEM}' AS source_system,
    {source_id_expr} AS source_record_id,
    '{sql_literal(HF_DATASET_URL)}' AS source_url,
    '{PAYLOAD_FORMAT}' AS payload_format,
    {payload_expr} AS payload,
    sha2({payload_expr}, 256) AS payload_sha256,
    '{EXTRACT_METHOD}' AS extract_method,
    '{SCHEMA_VERSION}' AS schema_version
  FROM parquet.`{parquet_lit}`
  {limit_sql}
)
AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
WHEN MATCHED AND s.source_record_id IS NOT NULL THEN UPDATE SET
  ingest_run_id = s.ingest_run_id,
  ingested_at = s.ingested_at,
  source_url = s.source_url,
  payload_format = s.payload_format,
  payload = s.payload,
  payload_sha256 = s.payload_sha256,
  extract_method = s.extract_method,
  schema_version = s.schema_version
WHEN NOT MATCHED AND s.source_record_id IS NOT NULL THEN INSERT (
  ingest_run_id, ingested_at, state_code, source_system, source_record_id, source_url,
  payload_format, payload, payload_sha256, extract_method, schema_version
) VALUES (
  s.ingest_run_id, s.ingested_at, s.state_code, s.source_system, s.source_record_id, s.source_url,
  s.payload_format, s.payload, s.payload_sha256, s.extract_method, s.schema_version
)
""".strip()
