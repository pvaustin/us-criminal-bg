"""Map a Bronze court_case_raw dict to Silver court_case / court_charge / court_party.

Pure Python: unit-testable without Spark. Databricks job uses the same function.
Never writes Bronze. Never scrapes.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from sources.wcca.parse import (
    SILVER_CHARGE_SCHEMA_VERSION,
    SILVER_PARTY_SCHEMA_VERSION,
    SILVER_SCHEMA_VERSION,
    parse_wcca_bronze_row,
)

BUSINESS_COLUMNS = (
    "source_system",
    "state_code",
    "source_record_id",
    "ingest_run_id",
    "ingested_at",
    "source_url",
    "payload_format",
    "payload_sha256",
    "extract_method",
    "bronze_schema_version",
    "county_code",
    "case_number",
    "case_type",
    "filed_date",
    "caption",
    "case_status",
    "county_name",
    "payload_parse_status",
    "dq_flags",
    "silver_schema_version",
)

CHARGE_BUSINESS_COLUMNS = (
    "source_system",
    "state_code",
    "source_record_id",
    "charge_count",
    "statute",
    "description",
    "severity",
    "modifier_statute",
    "modifier_text",
    "ingest_run_id",
    "payload_sha256",
    "bronze_schema_version",
    "silver_schema_version",
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


def map_bronze_to_court_case(
    bronze: Mapping[str, Any],
    *,
    transform_run_id: str,
    transformed_at: datetime | None = None,
) -> dict[str, Any]:
    """Build one Silver court_case row. `payload` is parsed then dropped."""
    parsed = parse_wcca_bronze_row(
        source_system=bronze.get("source_system"),
        source_record_id=bronze.get("source_record_id"),
        source_url=bronze.get("source_url"),
        payload_format=bronze.get("payload_format"),
        payload=bronze.get("payload"),
    )
    ts = transformed_at or datetime.now(timezone.utc)
    return {
        "source_system": bronze.get("source_system"),
        "state_code": bronze.get("state_code"),
        "source_record_id": bronze.get("source_record_id"),
        "ingest_run_id": bronze.get("ingest_run_id"),
        "ingested_at": _as_utc(bronze.get("ingested_at")),
        "source_url": bronze.get("source_url"),
        "payload_format": bronze.get("payload_format"),
        "payload_sha256": bronze.get("payload_sha256"),
        "extract_method": bronze.get("extract_method"),
        "bronze_schema_version": bronze.get("schema_version")
        or bronze.get("bronze_schema_version"),
        "county_code": parsed.county_code,
        "case_number": parsed.case_number,
        "case_type": parsed.case_type,
        "filed_date": parsed.filed_date,
        "caption": parsed.caption,
        "case_status": parsed.case_status,
        "county_name": parsed.county_name,
        "payload_parse_status": parsed.payload_parse_status,
        "dq_flags": list(parsed.dq_flags),
        "silver_schema_version": SILVER_SCHEMA_VERSION,
        "transformed_at": ts,
        "transform_run_id": transform_run_id,
    }


def map_bronze_to_court_charges(
    bronze: Mapping[str, Any],
    *,
    transform_run_id: str,
    transformed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build Silver court_charge rows for one Bronze case. Empty if none parsed."""
    parsed = parse_wcca_bronze_row(
        source_system=bronze.get("source_system"),
        source_record_id=bronze.get("source_record_id"),
        source_url=bronze.get("source_url"),
        payload_format=bronze.get("payload_format"),
        payload=bronze.get("payload"),
    )
    ts = transformed_at or datetime.now(timezone.utc)
    bronze_schema = bronze.get("schema_version") or bronze.get(
        "bronze_schema_version"
    )
    rows: list[dict[str, Any]] = []
    for charge in parsed.charges:
        rows.append(
            {
                "source_system": bronze.get("source_system"),
                "state_code": bronze.get("state_code"),
                "source_record_id": bronze.get("source_record_id"),
                "charge_count": charge.charge_count,
                "statute": charge.statute,
                "description": charge.description,
                "severity": charge.severity,
                "modifier_statute": charge.modifier_statute,
                "modifier_text": charge.modifier_text,
                "ingest_run_id": bronze.get("ingest_run_id"),
                "ingested_at": _as_utc(bronze.get("ingested_at")),
                "payload_sha256": bronze.get("payload_sha256"),
                "bronze_schema_version": bronze_schema,
                "silver_schema_version": SILVER_CHARGE_SCHEMA_VERSION,
                "transformed_at": ts,
                "transform_run_id": transform_run_id,
            }
        )
    return rows


def map_bronze_to_court_parties(
    bronze: Mapping[str, Any],
    *,
    transform_run_id: str,
    transformed_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Build Silver court_party rows for one Bronze case. Empty if none parsed."""
    parsed = parse_wcca_bronze_row(
        source_system=bronze.get("source_system"),
        source_record_id=bronze.get("source_record_id"),
        source_url=bronze.get("source_url"),
        payload_format=bronze.get("payload_format"),
        payload=bronze.get("payload"),
    )
    ts = transformed_at or datetime.now(timezone.utc)
    bronze_schema = bronze.get("schema_version") or bronze.get(
        "bronze_schema_version"
    )
    rows: list[dict[str, Any]] = []
    for party in parsed.parties:
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
    keys = (
        PARTY_BUSINESS_COLUMNS
        if "party_role" in row
        else CHARGE_BUSINESS_COLUMNS
        if "charge_count" in row
        else BUSINESS_COLUMNS
    )
    out: dict[str, Any] = {}
    for key in keys:
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
