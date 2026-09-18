#!/usr/bin/env python3
"""Gold MVP serving snapshots over Silver (order_report, match_queue, metrics).

Reads already-landed `us_criminal_bg.silver.*`. Writes only `us_criminal_bg.gold.*`.
Does not scrape, mutate Bronze, or mutate Silver. Does not invent court_case /
court_charge rows (SF nulls stay null). No hire / no-hire / risk scores.
Does not use party_name_index.

`order_subject` and `search_audit` are DDL-only / not live: Python --apply
try-or-skips `order_subject` (empty scratch + match_decision subject fallback)
and never reads `search_audit`.

Warehouse SQL: `gold/transforms/*.sql` (Delta scratch, not TEMP VIEW).
Local unit tests cover open-queue / grain / metrics rules without Spark.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

GOLD_SCHEMA = "us_criminal_bg.gold"
SILVER_SCHEMA = "us_criminal_bg.silver"
ORDER_REPORT_VERSION = "gold.order_report.v1"
MATCH_QUEUE_VERSION = "gold.match_queue.v1"
METRICS_VERSION = "gold.source_coverage_metrics.v1"

OPEN_BANDS = frozenset({"review", "auto"})
REVIEW_STATUS_SUGGESTION = "suggestion"
REVIEW_STATUS_HUMAN = "human"
SUBJECT_SOURCE_ORDER = "order_subject"
SUBJECT_SOURCE_MATCH = "match_decision"

PILOT_SOURCES: tuple[tuple[str, str], ...] = (
    ("wcca", "WI"),
    ("sf_criminal_hf", "CA"),
)

ORDER_SUBJECT_TABLE = f"{SILVER_SCHEMA}.order_subject"
SEARCH_AUDIT_TABLE = f"{SILVER_SCHEMA}.search_audit"
MATCH_DECISION_TABLE = f"{SILVER_SCHEMA}.match_decision"
COURT_PARTY_TABLE = f"{SILVER_SCHEMA}.court_party"
COURT_CASE_TABLE = f"{SILVER_SCHEMA}.court_case"
COURT_CHARGE_TABLE = f"{SILVER_SCHEMA}.court_charge"

SCHEMA_SQL_FILES = (
    REPO_ROOT / "gold" / "schemas" / "order_report.sql",
    REPO_ROOT / "gold" / "schemas" / "match_queue.sql",
    REPO_ROOT / "gold" / "schemas" / "source_coverage_metrics.sql",
)
TRANSFORM_SQL_FILES = (
    REPO_ROOT / "gold" / "transforms" / "match_queue.sql",
    REPO_ROOT / "gold" / "transforms" / "source_coverage_metrics.sql",
    REPO_ROOT / "gold" / "transforms" / "order_report.sql",
)
ORDER_SUBJECT_SRC_SQL = (
    REPO_ROOT / "gold" / "transforms" / "order_subject_src_from_silver.sql"
)

HIRE_FORBIDDEN_TOKENS = (
    "hire_flag",
    "no_hire",
    "no-hire",
    "risk_score",
    "adverse_action",
)


def party_key(
    source_system: str,
    state_code: str,
    source_record_id: str,
    party_role: str,
    party_ordinal: int,
) -> str:
    return "|".join(
        [
            str(source_system),
            str(state_code),
            str(source_record_id),
            str(party_role),
            str(party_ordinal),
        ]
    )


def case_report_key(source_system: str, state_code: str, source_record_id: str) -> str:
    return "|".join([str(source_system), str(state_code), str(source_record_id)])


def party_key_from_row(row: Mapping[str, Any]) -> str:
    existing = row.get("party_key")
    if existing:
        return str(existing)
    return party_key(
        row["source_system"],
        row["state_code"],
        row["source_record_id"],
        row["party_role"],
        int(row["party_ordinal"]),
    )


def nonempty_name(raw_name: Any) -> bool:
    return bool(str(raw_name or "").strip())


def _as_utc(value: Any) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_sort_key(row: Mapping[str, Any]) -> tuple:
    """Higher is later. Human wins timestamp ties (prefer review_status=human)."""
    is_human = 1 if row.get("review_status") == REVIEW_STATUS_HUMAN else 0
    return (_as_utc(row.get("decided_at")), is_human, str(row.get("decision_id") or ""))


def latest_row_per_subject_party(
    decisions: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in decisions:
        key = (str(row["subject_ref"]), party_key_from_row(row))
        grouped[key].append(row)
    return {key: max(rows, key=_latest_sort_key) for key, rows in grouped.items()}


def latest_human_per_subject_party(
    decisions: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    humans = [
        row for row in decisions if row.get("review_status") == REVIEW_STATUS_HUMAN
    ]
    return latest_row_per_subject_party(humans)


def is_open_queue_card(latest_row: Mapping[str, Any]) -> bool:
    return (
        latest_row.get("review_status") == REVIEW_STATUS_SUGGESTION
        and latest_row.get("confidence_band") in OPEN_BANDS
    )


def is_closed_review(latest_row: Mapping[str, Any]) -> bool:
    return latest_row.get("review_status") == REVIEW_STATUS_HUMAN


def age_hours(decided_at: Any, now: datetime) -> float:
    return (now - _as_utc(decided_at)).total_seconds() / 3600.0


def _list_or_empty(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return list(value)


def aggregate_charges(
    charges: Sequence[Mapping[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in charges:
        key = (
            str(row["source_system"]),
            str(row["state_code"]),
            str(row["source_record_id"]),
        )
        grouped[key].append(row)
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, rows in grouped.items():
        ordered = sorted(rows, key=lambda r: int(r.get("charge_count") or 0))
        out[key] = {
            "charge_row_count": len(ordered),
            "charge_statutes": [r.get("statute") for r in ordered],
            "charge_severities": [r.get("severity") for r in ordered],
            "charge_descriptions": [r.get("description") for r in ordered],
        }
    return out


def build_match_queue(
    decisions: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Open review cards only. Synthetic-safe; no Spark."""
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    latest = latest_row_per_subject_party(decisions)
    cards: list[dict[str, Any]] = []
    for (subject_ref, pkey), row in latest.items():
        if not is_open_queue_card(row):
            continue
        src = str(row["source_system"])
        state = str(row["state_code"])
        record_id = str(row["source_record_id"])
        cards.append(
            {
                "subject_ref": subject_ref,
                "party_key": pkey,
                "subject_name": row.get("subject_name"),
                "subject_dob": row.get("subject_dob"),
                "source_system": src,
                "state_code": state,
                "source_record_id": record_id,
                "party_role": row.get("party_role"),
                "party_ordinal": row.get("party_ordinal"),
                "case_report_key": row.get("case_report_key")
                or case_report_key(src, state, record_id),
                "raw_name": row.get("raw_name"),
                "name_last": row.get("name_last"),
                "name_first": row.get("name_first"),
                "name_middle": row.get("name_middle"),
                "confidence_band": row.get("confidence_band"),
                "score": row.get("score"),
                "reasons": _list_or_empty(row.get("reasons")),
                "score_or_reason_codes": _list_or_empty(
                    row.get("score_or_reason_codes")
                ),
                "decision_id": row.get("decision_id"),
                "decided_at": row.get("decided_at"),
                "age_hours": age_hours(row.get("decided_at"), now_utc),
                "actor": row.get("actor"),
                "review_status": row.get("review_status"),
                "experiment_tag": row.get("experiment_tag"),
                "notes": row.get("notes"),
                "ingest_run_id": row.get("ingest_run_id"),
                "payload_sha256": row.get("payload_sha256"),
                "gold_schema_version": MATCH_QUEUE_VERSION,
                "refreshed_at": now_utc,
            }
        )
    cards.sort(
        key=lambda c: (
            str(c["source_system"]),
            str(c["state_code"]),
            -(int(c["score"] or 0)),
            str(c["party_key"]),
        )
    )
    return cards


def build_order_report(
    decisions: Sequence[Mapping[str, Any]],
    parties: Sequence[Mapping[str, Any]],
    cases: Sequence[Mapping[str, Any]],
    charges: Sequence[Mapping[str, Any]],
    order_subjects: Sequence[Mapping[str, Any]] | None,
    *,
    now: datetime,
    order_subject_table_present: bool,
) -> list[dict[str, Any]]:
    """Subject × party serving rows. SF case/charge joins may miss (honest)."""
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    latest = latest_row_per_subject_party(decisions)
    humans = latest_human_per_subject_party(decisions)
    parties_by_key = {party_key_from_row(p): p for p in parties}
    cases_by_nat = {
        (
            str(c["source_system"]),
            str(c["state_code"]),
            str(c["source_record_id"]),
        ): c
        for c in cases
    }
    charge_agg = aggregate_charges(charges)
    orders_by_ref = {
        str(o["subject_ref"]): o for o in (order_subjects or [])
    }

    rows: list[dict[str, Any]] = []
    for (subject_ref, pkey), md in latest.items():
        src = str(md["source_system"])
        state = str(md["state_code"])
        record_id = str(md["source_record_id"])
        nat = (src, state, record_id)
        party = parties_by_key.get(pkey)
        case_row = cases_by_nat.get(nat)
        chg = charge_agg.get(
            nat,
            {
                "charge_row_count": 0,
                "charge_statutes": [],
                "charge_severities": [],
                "charge_descriptions": [],
            },
        )
        order = orders_by_ref.get(subject_ref)
        human = humans.get((subject_ref, pkey))
        open_card = is_open_queue_card(md)
        subject_from_order = order is not None
        rows.append(
            {
                "subject_ref": subject_ref,
                "party_key": pkey,
                "order_id": None if order is None else order.get("order_id"),
                "order_status": None if order is None else order.get("status"),
                "order_created_by": None if order is None else order.get("created_by"),
                "order_updated_at": None if order is None else order.get("updated_at"),
                "order_subject_table_present": bool(order_subject_table_present),
                "subject_name": (
                    order.get("subject_name") if order else md.get("subject_name")
                ),
                "subject_dob": (
                    order.get("subject_dob") if order else md.get("subject_dob")
                ),
                "subject_source": (
                    SUBJECT_SOURCE_ORDER if subject_from_order else SUBJECT_SOURCE_MATCH
                ),
                "source_system": src,
                "state_code": state,
                "source_record_id": record_id,
                "party_role": md.get("party_role"),
                "party_ordinal": md.get("party_ordinal"),
                "raw_name": (party or {}).get("raw_name", md.get("raw_name")),
                "name_last": (party or {}).get("name_last", md.get("name_last")),
                "name_first": (party or {}).get("name_first", md.get("name_first")),
                "name_middle": (party or {}).get("name_middle", md.get("name_middle")),
                "party_dob": None if party is None else party.get("dob"),
                "party_row_present": party is not None,
                "party_payload_parse_status": None
                if party is None
                else party.get("payload_parse_status"),
                "party_dq_flags": _list_or_empty(
                    None if party is None else party.get("dq_flags")
                ),
                "case_report_key": md.get("case_report_key")
                or case_report_key(src, state, record_id),
                "has_court_case": case_row is not None,
                "county_code": None if case_row is None else case_row.get("county_code"),
                "case_number": None if case_row is None else case_row.get("case_number"),
                "case_type": None if case_row is None else case_row.get("case_type"),
                "filed_date": None if case_row is None else case_row.get("filed_date"),
                "caption": None if case_row is None else case_row.get("caption"),
                "case_status": None if case_row is None else case_row.get("case_status"),
                "county_name": None if case_row is None else case_row.get("county_name"),
                "case_payload_parse_status": None
                if case_row is None
                else case_row.get("payload_parse_status"),
                "case_dq_flags": _list_or_empty(
                    None if case_row is None else case_row.get("dq_flags")
                ),
                "has_court_charge": int(chg["charge_row_count"]) > 0,
                "charge_row_count": int(chg["charge_row_count"]),
                "charge_statutes": list(chg["charge_statutes"]),
                "charge_severities": list(chg["charge_severities"]),
                "charge_descriptions": list(chg["charge_descriptions"]),
                "latest_decision_id": md.get("decision_id"),
                "latest_review_status": md.get("review_status"),
                "latest_confidence_band": md.get("confidence_band"),
                "latest_score": md.get("score"),
                "latest_reasons": _list_or_empty(md.get("reasons")),
                "latest_score_or_reason_codes": _list_or_empty(
                    md.get("score_or_reason_codes")
                ),
                "latest_decided_at": md.get("decided_at"),
                "latest_actor": md.get("actor"),
                "latest_experiment_tag": md.get("experiment_tag"),
                "latest_notes": md.get("notes"),
                "current_confidence_band": md.get("confidence_band"),
                "current_review_status": md.get("review_status"),
                "is_open_review": open_card,
                "human_decision_id": None if human is None else human.get("decision_id"),
                "human_confidence_band": None
                if human is None
                else human.get("confidence_band"),
                "human_score": None if human is None else human.get("score"),
                "human_reasons": _list_or_empty(
                    None if human is None else human.get("reasons")
                ),
                "human_decided_at": None if human is None else human.get("decided_at"),
                "human_actor": None if human is None else human.get("actor"),
                "ingest_run_id": (party or {}).get(
                    "ingest_run_id", md.get("ingest_run_id")
                ),
                "payload_sha256": (party or {}).get(
                    "payload_sha256", md.get("payload_sha256")
                ),
                "party_transform_run_id": (party or {}).get(
                    "transform_run_id", md.get("transform_run_id")
                ),
                "party_ingested_at": None if party is None else party.get("ingested_at"),
                "party_transformed_at": None
                if party is None
                else party.get("transformed_at"),
                "case_transformed_at": None
                if case_row is None
                else case_row.get("transformed_at"),
                "gold_schema_version": ORDER_REPORT_VERSION,
                "refreshed_at": now_utc,
            }
        )
    rows.sort(key=lambda r: (str(r["source_system"]), str(r["party_key"]), str(r["subject_ref"])))
    return rows


def build_source_coverage_metrics(
    cases: Sequence[Mapping[str, Any]],
    parties: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    *,
    as_of_date: date,
    now: datetime,
    extra_sources: Iterable[tuple[str, str]] = (),
) -> list[dict[str, Any]]:
    """Counts by state_code + source_system. Pilot sources always present."""
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    universe: set[tuple[str, str]] = set(PILOT_SOURCES)
    universe.update(extra_sources)
    for row in cases:
        universe.add((str(row["source_system"]), str(row["state_code"])))
    for row in parties:
        universe.add((str(row["source_system"]), str(row["state_code"])))
    for row in decisions:
        universe.add((str(row["source_system"]), str(row["state_code"])))

    latest = latest_row_per_subject_party(decisions)
    metrics: list[dict[str, Any]] = []
    for source_system, state_code in sorted(universe):
        src_cases = [
            r
            for r in cases
            if r.get("source_system") == source_system
            and r.get("state_code") == state_code
        ]
        src_parties = [
            r
            for r in parties
            if r.get("source_system") == source_system
            and r.get("state_code") == state_code
        ]
        src_decisions = [
            r
            for r in decisions
            if r.get("source_system") == source_system
            and r.get("state_code") == state_code
        ]
        src_latest = [
            row
            for row in latest.values()
            if row.get("source_system") == source_system
            and row.get("state_code") == state_code
        ]
        metrics.append(
            {
                "as_of_date": as_of_date,
                "state_code": state_code,
                "source_system": source_system,
                "case_count": len(src_cases),
                "party_count": len(src_parties),
                "nonempty_name_count": sum(
                    1 for p in src_parties if nonempty_name(p.get("raw_name"))
                ),
                "suggestion_row_count": sum(
                    1
                    for d in src_decisions
                    if d.get("review_status") == REVIEW_STATUS_SUGGESTION
                ),
                "open_review_count": sum(1 for row in src_latest if is_open_queue_card(row)),
                "closed_review_count": sum(1 for row in src_latest if is_closed_review(row)),
                "gold_schema_version": METRICS_VERSION,
                "refreshed_at": now_utc,
            }
        )
    return metrics


def split_sql_statements(sql_text: str) -> list[str]:
    """Statement-at-a-time splitter. Drops full-line `--` comments."""
    kept: list[str] = []
    for raw_line in sql_text.splitlines():
        line = raw_line
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        if " -- " in line:
            line = line[: line.index(" -- ")]
        kept.append(line)
    joined = "\n".join(kept)
    return [part.strip() for part in joined.split(";") if part.strip()]


def table_exists(spark: Any, full_name: str) -> bool:
    try:
        spark.sql(f"DESCRIBE TABLE {full_name}").limit(1).collect()
        return True
    except Exception:
        return False


def run_sql_file(spark: Any, path: Path) -> None:
    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    for stmt in statements:
        spark.sql(stmt)


def _empty_order_subject_src_sql() -> str:
    return """
CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_order_subject_src
USING DELTA
AS
SELECT
  CAST(NULL AS STRING) AS order_id,
  CAST(NULL AS STRING) AS subject_ref,
  CAST(NULL AS STRING) AS subject_name,
  CAST(NULL AS DATE) AS subject_dob,
  CAST(NULL AS TIMESTAMP) AS created_at,
  CAST(NULL AS STRING) AS created_by,
  CAST(NULL AS TIMESTAMP) AS updated_at,
  CAST(NULL AS STRING) AS status
WHERE 1 = 0
"""


def apply_transform(spark: Any) -> dict[str, Any]:
    """Create Gold schema objects and refresh the three serving tables."""
    spark.sql("CREATE CATALOG IF NOT EXISTS us_criminal_bg")
    spark.sql("CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold")
    for path in SCHEMA_SQL_FILES:
        run_sql_file(spark, path)

    order_subject_present = table_exists(spark, ORDER_SUBJECT_TABLE)
    search_audit_present = table_exists(spark, SEARCH_AUDIT_TABLE)
    # search_audit is never a Gold MVP input — detect only for the apply log.
    if order_subject_present:
        run_sql_file(spark, ORDER_SUBJECT_SRC_SQL)
    else:
        spark.sql(_empty_order_subject_src_sql())

    for path in TRANSFORM_SQL_FILES:
        run_sql_file(spark, path)

    summary = {
        "order_subject_present": order_subject_present,
        "search_audit_present": search_audit_present,
        "search_audit_read": False,
        "order_report": f"{GOLD_SCHEMA}.order_report",
        "match_queue": f"{GOLD_SCHEMA}.match_queue",
        "source_coverage_metrics": f"{GOLD_SCHEMA}.source_coverage_metrics",
    }
    print("gold_mvp: refreshed", summary)
    if not order_subject_present:
        print("gold_mvp: silver.order_subject missing — subjects from match_decision")
    if search_audit_present:
        print("gold_mvp: silver.search_audit exists but was not read")
    return summary


def _spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh Gold serving tables from Silver "
            "(order_report, match_queue, source_coverage_metrics). "
            "Reads Silver only. Does not scrape, write Bronze, invent court "
            "rows, or emit hire/no-hire. order_subject is try-or-skip; "
            "search_audit is not read."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run DDL + transforms on the current Spark session (Databricks cluster)",
    )
    args = parser.parse_args(argv)
    if not args.apply:
        parser.print_help()
        print(
            "\nLocal tests: python3 -m unittest discover "
            "-s gold/transforms/tests -v"
        )
        print("SQL path: gold/transforms/*.sql (Delta scratch, not TEMP VIEW)")
        print("schema versions:", ORDER_REPORT_VERSION, MATCH_QUEUE_VERSION, METRICS_VERSION)
        print("pilot sources:", ", ".join(f"{s}/{st}" for s, st in PILOT_SOURCES))
        print("order_subject: try-or-skip; search_audit: not read")
        print("no party_name_index; no hire/no-hire")
        return 0
    spark = _spark()
    apply_transform(spark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
