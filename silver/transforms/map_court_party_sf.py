"""Map a Bronze sf_criminal_hf court_case_raw dict to silver.court_party rows.

Pure Python: unit-testable without Spark. Databricks job uses the same function.
Never writes Bronze. Never scrapes. Never invents parties.
WI / WCCA rows are skipped (empty list) so this mapper cannot overwrite them.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from sources.sf_criminal_hf.parse_party import (
    SILVER_PARTY_SCHEMA_VERSION,
    parse_sf_criminal_hf_bronze_row,
)

PARTY_BUSINESS_COLUMNS = (
    "source_system",
    "state_code",
    "source_record_id",
    "party_role",
    "party_ordinal",
    "raw_name",
    "name_last",
    "name_first",
    "name_middle",
    "dob",
    "sex",
    "address_raw",
    "ingest_run_id",
    "payload_sha256",
    "bronze_schema_version",
    "silver_schema_version",
    "payload_parse_status",
    "dq_flags",
)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return value


def map_sf_bronze_to_court_parties(
    bronze: Mapping[str, Any],
    *,
    transform_run_id: str,
    transformed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build Silver court_party rows for one SF Bronze case. Empty if none parsed."""
    parties = parse_sf_criminal_hf_bronze_row(
        source_system=bronze.get("source_system"),
        payload=bronze.get("payload"),
    )
    ts = transformed_at or datetime.now(timezone.utc)
    bronze_schema = bronze.get("schema_version") or bronze.get("bronze_schema_version")
    rows: list[dict[str, Any]] = []
    for party in parties:
        rows.append(
            {
                "source_system": bronze.get("source_system"),
                "state_code": bronze.get("state_code"),
                "source_record_id": bronze.get("source_record_id"),
                "party_role": party.party_role,
                "party_ordinal": party.party_ordinal,
                "raw_name": party.raw_name,
                "name_last": party.name_last,
                "name_first": party.name_first,
                "name_middle": party.name_middle,
                "dob": party.dob,
                "sex": party.sex,
                "address_raw": party.address_raw,
                "ingest_run_id": bronze.get("ingest_run_id"),
                "ingested_at": _as_utc(bronze.get("ingested_at")),
                "payload_sha256": bronze.get("payload_sha256"),
                "bronze_schema_version": bronze_schema,
                "silver_schema_version": SILVER_PARTY_SCHEMA_VERSION,
                "transformed_at": ts,
                "transform_run_id": transform_run_id,
                "payload_parse_status": party.payload_parse_status,
                "dq_flags": list(party.dq_flags),
            }
        )
    return rows


def business_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Comparable projection for idempotency checks (excludes run timestamps/ids)."""
    out: dict[str, Any] = {}
    for key in PARTY_BUSINESS_COLUMNS:
        value = row.get(key)
        if isinstance(value, date) and not isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, datetime):
            out[key] = value.astimezone(timezone.utc).isoformat()
        elif isinstance(value, list):
            out[key] = list(value)
        else:
            out[key] = value
    return out
