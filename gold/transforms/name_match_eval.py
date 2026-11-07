#!/usr/bin/env python3
"""Gold name-match eval + unlabeled label pack (sf_name_match_v1).

Reads already-landed Silver `match_decision` / `court_party` and Gold
`match_queue`. Writes only `us_criminal_bg.gold.name_match_eval` and
`us_criminal_bg.gold.name_match_label_pack`.

Human-only eval: `review_status='human'`. Scorer suggestions are not GT.
Empty eval is honest when N_human=0. Do not invent humans or court rows.

Label pack: open SF queue cards + hard-negative distractors (existing
court_party rows with a different last name). `label` stays empty.

No hire / no-hire / risk. WI WCCA transforms are not imported or run.
Warehouse SQL: Delta scratch, not TEMP VIEW.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gold.transforms.gold_mvp import (  # noqa: E402
    HIRE_FORBIDDEN_TOKENS,
    REVIEW_STATUS_HUMAN,
    is_open_queue_card,
    latest_row_per_subject_party,
    party_key_from_row,
    run_sql_file,
    table_exists,
)
from silver.transforms.match_review_sketch import (  # noqa: E402
    MATCHABLE_ROLES,
    normalized_last_name_from_party,
    normalized_last_name_from_subject,
)

GOLD_SCHEMA = "us_criminal_bg.gold"
SILVER_SCHEMA = "us_criminal_bg.silver"
EVAL_TABLE = f"{GOLD_SCHEMA}.name_match_eval"
PACK_TABLE = f"{GOLD_SCHEMA}.name_match_label_pack"
MATCH_QUEUE_TABLE = f"{GOLD_SCHEMA}.match_queue"
MATCH_DECISION_TABLE = f"{SILVER_SCHEMA}.match_decision"
COURT_PARTY_TABLE = f"{SILVER_SCHEMA}.court_party"

EVAL_NAME = "sf_name_match_v1"
EVAL_VERSION = "gold.name_match_eval.v1"
PACK_VERSION = "gold.name_match_label_pack.v1"

SF_SOURCE_SYSTEM = "sf_criminal_hf"
SF_STATE_CODE = "CA"

LABEL_LINK = "link"
LABEL_REJECT = "reject"
LABEL_LEAVE = "leave_in_review"
GT_LABELS = frozenset({LABEL_LINK, LABEL_REJECT})
ALL_LABELS = frozenset({LABEL_LINK, LABEL_REJECT, LABEL_LEAVE})

PAIR_OPEN_QUEUE = "open_queue"
PAIR_HARD_NEGATIVE = "hard_negative"

SCHEMA_SQL_FILES = (
    REPO_ROOT / "gold" / "schemas" / "name_match_eval.sql",
    REPO_ROOT / "gold" / "schemas" / "name_match_label_pack.sql",
)
EVAL_TRANSFORM_SQL = REPO_ROOT / "gold" / "transforms" / "name_match_eval.sql"
PACK_TRANSFORM_SQL = REPO_ROOT / "gold" / "transforms" / "name_match_label_pack.sql"


def is_sf_research_row(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("source_system") or "") == SF_SOURCE_SYSTEM
        and str(row.get("state_code") or "") == SF_STATE_CODE
    )


def map_human_band_to_label(confidence_band: Any) -> str:
    """Map a *human* MATCH_REVIEW band onto eval labels.

    Suggestions must never call this for GT. `auto` on a human append is an
    explicit confirm (SF scorer cannot emit auto without party DOB). `review`
    stays leave_in_review and is excluded from metrics.
    """
    band = str(confidence_band or "").strip().lower()
    if band == "auto":
        return LABEL_LINK
    if band == "no-link":
        return LABEL_REJECT
    return LABEL_LEAVE


def is_gt_label(label: Any) -> bool:
    return str(label or "") in GT_LABELS


def build_name_match_eval(
    decisions: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    """Latest human SF row per (subject_ref, party_key). Suggestions dropped."""
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    humans = [
        row
        for row in decisions
        if row.get("review_status") == REVIEW_STATUS_HUMAN and is_sf_research_row(row)
    ]
    latest = latest_row_per_subject_party(humans)
    rows: list[dict[str, Any]] = []
    for (subject_ref, pkey), row in latest.items():
        reasons = row.get("reasons")
        if reasons is None:
            reasons_list: list[Any] = []
        elif isinstance(reasons, list):
            reasons_list = list(reasons)
        else:
            reasons_list = list(reasons)
        rows.append(
            {
                "subject_ref": subject_ref,
                "party_key": pkey,
                "label": map_human_band_to_label(row.get("confidence_band")),
                "source_system": str(row.get("source_system")),
                "state_code": str(row.get("state_code")),
                "labeled_at": row.get("decided_at"),
                "actor": row.get("actor"),
                "decision_id": row.get("decision_id"),
                "confidence_band": row.get("confidence_band"),
                "experiment_tag": row.get("experiment_tag"),
                "subject_name": row.get("subject_name"),
                "subject_dob": row.get("subject_dob"),
                "party_role": row.get("party_role"),
                "party_ordinal": row.get("party_ordinal"),
                "raw_name": row.get("raw_name"),
                "name_last": row.get("name_last"),
                "name_first": row.get("name_first"),
                "name_middle": row.get("name_middle"),
                "score": row.get("score"),
                "reasons": reasons_list,
                "review_status": REVIEW_STATUS_HUMAN,
                "eval_name": EVAL_NAME,
                "gold_schema_version": EVAL_VERSION,
                "refreshed_at": now_utc,
            }
        )
    rows.sort(key=lambda r: (str(r["subject_ref"]), str(r["party_key"])))
    return rows


def _stable_hex(subject_ref: str, party_key: str) -> str:
    payload = f"{subject_ref}|{party_key}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _subject_last_key_from_queue_card(card: Mapping[str, Any]) -> str | None:
    """Open SF cards were last-name retrieval; party last name is the subject proxy."""
    party_last = normalized_last_name_from_party(card)
    if party_last:
        return party_last
    return normalized_last_name_from_subject(
        {"subject_name": card.get("subject_name"), "name": card.get("subject_name")}
    )


def build_name_match_label_pack(
    queue_cards: Sequence[Mapping[str, Any]],
    parties: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    distractors_per_subject: int = 1,
) -> list[dict[str, Any]]:
    """Unlabeled pack: open SF queue cards + different-last-name parties.

    `label` is always None. Does not invent court_party rows. Does not treat
    suggestion bands as GT.
    """
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    open_sf = [
        card
        for card in queue_cards
        if is_sf_research_row(card) and is_open_queue_card(card)
    ]
    pack: list[dict[str, Any]] = []
    queued_keys: set[tuple[str, str]] = set()

    for card in open_sf:
        subject_ref = str(card["subject_ref"])
        pkey = party_key_from_row(card)
        queued_keys.add((subject_ref, pkey))
        pack.append(
            {
                "pack_row_id": str(uuid4()),
                "subject_ref": subject_ref,
                "party_key": pkey,
                "subject_name": card.get("subject_name"),
                "subject_dob": card.get("subject_dob"),
                "source_system": str(card.get("source_system")),
                "state_code": str(card.get("state_code")),
                "source_record_id": str(card.get("source_record_id")),
                "party_role": card.get("party_role"),
                "party_ordinal": card.get("party_ordinal"),
                "raw_name": card.get("raw_name"),
                "name_last": card.get("name_last"),
                "name_first": card.get("name_first"),
                "name_middle": card.get("name_middle"),
                "pair_kind": PAIR_OPEN_QUEUE,
                "suggestion_decision_id": card.get("decision_id"),
                "suggestion_confidence_band": card.get("confidence_band"),
                "suggestion_score": card.get("score"),
                "suggestion_actor": card.get("actor"),
                "label": None,
                "labeled_at": None,
                "actor": None,
                "experiment_tag": EVAL_NAME,
                "notes": (
                    "unlabeled pack row — not GT; label via Uma /review "
                    "append to match_decision"
                ),
                "ingest_run_id": card.get("ingest_run_id"),
                "payload_sha256": card.get("payload_sha256"),
                "gold_schema_version": PACK_VERSION,
                "refreshed_at": now_utc,
            }
        )

    subjects: dict[str, Mapping[str, Any]] = {}
    subject_last: dict[str, str] = {}
    for card in open_sf:
        ref = str(card["subject_ref"])
        subjects.setdefault(ref, card)
        last = _subject_last_key_from_queue_card(card)
        if last and ref not in subject_last:
            subject_last[ref] = last

    sf_parties = [
        p
        for p in parties
        if is_sf_research_row(p)
        and str(p.get("party_role") or "") in MATCHABLE_ROLES
    ]

    k = max(0, int(distractors_per_subject))
    for subject_ref, card in subjects.items():
        subj_last = subject_last.get(subject_ref)
        if not subj_last or k == 0:
            continue
        ranked: list[tuple[str, Mapping[str, Any], str]] = []
        for party in sf_parties:
            party_last = normalized_last_name_from_party(party)
            if not party_last or party_last == subj_last:
                continue
            pkey = party_key_from_row(party)
            if (subject_ref, pkey) in queued_keys:
                continue
            ranked.append((_stable_hex(subject_ref, pkey), party, pkey))
        ranked.sort(key=lambda item: item[0])
        for _hex, party, pkey in ranked[:k]:
            queued_keys.add((subject_ref, pkey))
            pack.append(
                {
                    "pack_row_id": str(uuid4()),
                    "subject_ref": subject_ref,
                    "party_key": pkey,
                    "subject_name": card.get("subject_name"),
                    "subject_dob": card.get("subject_dob"),
                    "source_system": str(party.get("source_system")),
                    "state_code": str(party.get("state_code")),
                    "source_record_id": str(party.get("source_record_id")),
                    "party_role": party.get("party_role"),
                    "party_ordinal": party.get("party_ordinal"),
                    "raw_name": party.get("raw_name"),
                    "name_last": party.get("name_last"),
                    "name_first": party.get("name_first"),
                    "name_middle": party.get("name_middle"),
                    "pair_kind": PAIR_HARD_NEGATIVE,
                    "suggestion_decision_id": None,
                    "suggestion_confidence_band": None,
                    "suggestion_score": None,
                    "suggestion_actor": None,
                    "label": None,
                    "labeled_at": None,
                    "actor": None,
                    "experiment_tag": EVAL_NAME,
                    "notes": (
                        "unlabeled hard-negative distractor — different last "
                        "name; not GT"
                    ),
                    "ingest_run_id": party.get("ingest_run_id"),
                    "payload_sha256": party.get("payload_sha256"),
                    "gold_schema_version": PACK_VERSION,
                    "refreshed_at": now_utc,
                }
            )

    pack.sort(key=lambda r: (str(r["pair_kind"]), str(r["subject_ref"]), str(r["party_key"])))
    return pack


def count_eval_labels(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {
        "n_human": len(rows),
        "n_link": 0,
        "n_reject": 0,
        "n_leave_in_review": 0,
        "n_gt": 0,
    }
    for row in rows:
        label = str(row.get("label") or "")
        if label == LABEL_LINK:
            counts["n_link"] += 1
        elif label == LABEL_REJECT:
            counts["n_reject"] += 1
        else:
            counts["n_leave_in_review"] += 1
    counts["n_gt"] = counts["n_link"] + counts["n_reject"]
    return counts


def apply_transform(spark: Any) -> dict[str, Any]:
    """Create eval/pack schema objects and refresh from live Silver/Gold."""
    spark.sql("CREATE CATALOG IF NOT EXISTS us_criminal_bg")
    spark.sql("CREATE SCHEMA IF NOT EXISTS us_criminal_bg.gold")
    for path in SCHEMA_SQL_FILES:
        run_sql_file(spark, path)

    run_sql_file(spark, EVAL_TRANSFORM_SQL)

    queue_present = table_exists(spark, MATCH_QUEUE_TABLE)
    pack_refreshed = False
    if queue_present:
        run_sql_file(spark, PACK_TRANSFORM_SQL)
        pack_refreshed = True
    else:
        print(
            "name_match_eval: gold.match_queue missing — "
            "run gold/transforms/match_queue.sql before the label pack"
        )

    summary = {
        "eval_table": EVAL_TABLE,
        "pack_table": PACK_TABLE,
        "match_queue_present": queue_present,
        "pack_refreshed": pack_refreshed,
        "eval_name": EVAL_NAME,
    }
    print("name_match_eval: refreshed", summary)
    print(
        "name_match_eval: suggestions are not GT; empty eval is honest when "
        "n_human=0"
    )
    return summary


def _spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Refresh gold.name_match_eval (human-only) and "
            "gold.name_match_label_pack (unlabeled SF queue + hard negatives). "
            "Does not scrape, write Bronze/Silver, invent court rows, or emit "
            "hire/no-hire. Suggestions are not ground truth."
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
        print("SQL: gold/transforms/name_match_eval.sql + name_match_label_pack.sql")
        print("eval_name=", EVAL_NAME)
        print("labels:", ", ".join(sorted(ALL_LABELS)))
        print("GT metrics use link|reject only; leave_in_review is excluded")
        print("forbidden:", ", ".join(HIRE_FORBIDDEN_TOKENS))
        return 0
    spark = _spark()
    apply_transform(spark)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
