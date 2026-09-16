#!/usr/bin/env python3
"""Score sample subjects against SF HF `court_party` defendants (research-only).

Reads already-landed `us_criminal_bg.silver.court_party` rows where
`source_system='sf_criminal_hf'` and `state_code='CA'`. Joins on normalized
last name, scores with `match_review_sketch` bands, and APPENDS suggestion
rows to `us_criminal_bg.silver.match_decision`.

SF parties have no DOB: exact name hits are `review` (`dob_absent`), never
`auto`. `auto` requires both DOBs present and equal. This is a name-only
review queue, not a hire / CRA / adverse-action signal.

Does not scrape. Does not mutate Bronze. Does not MERGE/DELETE court_party.
Does not import or run the WI WCCA `court_case` transform.
Always INSERT (append). Never type-1 overwrite.

Local unit tests cover retrieval + scoring without Spark. `--apply` needs a
Databricks Spark session. Warehouse stand-in:
`silver/transforms/match_decision_sf_research.sql`.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from silver.transforms.match_review_sketch import (  # noqa: E402
    ACTOR_SUGGESTION,
    MATCHABLE_ROLES,
    PERSIST_BANDS_DEFAULT,
    REVIEW_STATUS_SUGGESTION,
    normalized_last_name_from_party,
    normalized_last_name_from_subject,
    score_subject_against_party,
    suggestion_rows_for_subject,
)

SF_SOURCE_SYSTEM = "sf_criminal_hf"
SF_STATE_CODE = "CA"
EXPERIMENT_TAG = "sf_name_only_research"
DEFAULT_NOTES = (
    "research-only SF name-match; not CRA/adverse action; "
    "party DOB always null so auto is unreachable"
)
SUBJECT_TABLE = "us_criminal_bg.silver._match_subject_sf_research"
PARTY_TABLE = "us_criminal_bg.silver.court_party"
DECISION_TABLE = "us_criminal_bg.silver.match_decision"
RESEARCH_DEFENDANT_COUNT = 77399


def is_sf_research_party(party: Mapping[str, Any]) -> bool:
    return (
        str(party.get("source_system") or "") == SF_SOURCE_SYSTEM
        and str(party.get("state_code") or "") == SF_STATE_CODE
        and str(party.get("party_role") or "") in MATCHABLE_ROLES
    )


def filter_sf_research_parties(
    parties: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Drop WI / other sources before last-name retrieval."""
    return [p for p in parties if is_sf_research_party(p)]


def score_sf_research_subjects(
    subjects: Sequence[Mapping[str, Any]],
    parties: Sequence[Mapping[str, Any]],
    *,
    persist_no_link: bool = False,
    decided_at: datetime | None = None,
    notes: str | None = None,
) -> list[dict[str, Any]]:
    """Last-name retrieve + MATCH_REVIEW score; SF/CA defendants (and aka) only.

    Does not cartesian `parties`. WI `wcca` rows are filtered out first.
    """
    scoped = filter_sf_research_parties(parties)
    ts = decided_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for subject in subjects:
        rows.extend(
            suggestion_rows_for_subject(
                subject,
                scoped,
                persist_bands=PERSIST_BANDS_DEFAULT,
                persist_no_link=persist_no_link,
                actor=ACTOR_SUGGESTION,
                review_status=REVIEW_STATUS_SUGGESTION,
                experiment_tag=EXPERIMENT_TAG,
                notes=notes or DEFAULT_NOTES,
                decided_at=ts,
            )
        )
    return rows


def _spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def _register_udfs(spark):
    from pyspark.sql.functions import udf
    from pyspark.sql.types import (
        ArrayType,
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    sketch_schema = StructType(
        [
            StructField("band", StringType()),
            StructField("score", IntegerType()),
            StructField("reasons", ArrayType(StringType())),
        ]
    )

    @udf(StringType())
    def subject_last_key(name):
        return normalized_last_name_from_subject({"name": name})

    @udf(StringType())
    def party_last_key(name_last, raw_name):
        return normalized_last_name_from_party(
            {"name_last": name_last, "raw_name": raw_name}
        )

    @udf(sketch_schema)
    def score_udf(
        subject_name,
        subject_dob,
        party_role,
        party_ordinal,
        raw_name,
        name_last,
        name_first,
        name_middle,
        dob,
    ):
        sketch = score_subject_against_party(
            {"name": subject_name, "dob": subject_dob},
            {
                "party_role": party_role,
                "party_ordinal": party_ordinal,
                "raw_name": raw_name,
                "name_last": name_last,
                "name_first": name_first,
                "name_middle": name_middle,
                "dob": dob,
            },
        )
        return sketch.band, sketch.score, list(sketch.reasons)

    return subject_last_key, party_last_key, score_udf


def apply_transform(
    spark,
    *,
    subjects_table: str = SUBJECT_TABLE,
    persist_no_link: bool = False,
    notes: str | None = None,
) -> str:
    """Join SF parties on last-name key, score, APPEND. No driver cartesian.

    Returns a batch id (not a court transform_run_id).
    """
    from pyspark.sql import functions as F

    batch_id = str(uuid4())
    persist_flag = "true" if persist_no_link else "false"
    job_notes = notes or DEFAULT_NOTES
    subject_last_key, party_last_key, score_udf = _register_udfs(spark)

    subjects = (
        spark.table(subjects_table)
        .select("subject_ref", "subject_name", "subject_dob")
        .withColumn("last_key", subject_last_key(F.col("subject_name")))
        .where(F.col("last_key").isNotNull() & (F.col("last_key") != ""))
    )
    parties = (
        spark.table(PARTY_TABLE)
        .where(
            (F.col("source_system") == SF_SOURCE_SYSTEM)
            & (F.col("state_code") == SF_STATE_CODE)
            & F.col("party_role").isin("defendant", "aka")
        )
        .select(
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
            "ingest_run_id",
            "payload_sha256",
            "transform_run_id",
        )
        .withColumn(
            "last_key",
            party_last_key(F.col("name_last"), F.col("raw_name")),
        )
        .where(F.col("last_key").isNotNull() & (F.col("last_key") != ""))
    )
    joined = subjects.join(parties, "last_key", "inner")
    scored = joined.withColumn(
        "sk",
        score_udf(
            F.col("subject_name"),
            F.col("subject_dob"),
            F.col("party_role"),
            F.col("party_ordinal"),
            F.col("raw_name"),
            F.col("name_last"),
            F.col("name_first"),
            F.col("name_middle"),
            F.col("dob"),
        ),
    )
    bands = ["review", "auto"]
    if persist_no_link:
        bands.append("no-link")
    staged = scored.where(F.col("sk.band").isin(*bands)).select(
        F.expr("uuid()").alias("decision_id"),
        F.col("subject_ref"),
        F.col("subject_name"),
        F.col("subject_dob"),
        F.concat_ws(
            "|",
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
            F.col("party_role"),
            F.col("party_ordinal"),
        ).alias("party_key"),
        F.col("source_system"),
        F.col("state_code"),
        F.col("source_record_id"),
        F.col("party_role"),
        F.col("party_ordinal"),
        F.col("raw_name"),
        F.col("name_last"),
        F.col("name_first"),
        F.col("name_middle"),
        F.col("sk.band").alias("confidence_band"),
        F.col("sk.score").alias("score"),
        F.col("sk.reasons").alias("reasons"),
        F.concat(
            F.array(F.col("sk.score").cast("string")),
            F.col("sk.reasons"),
        ).alias("score_or_reason_codes"),
        F.col("ingest_run_id"),
        F.col("payload_sha256"),
        F.col("transform_run_id"),
        F.concat_ws(
            "|",
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
        ).alias("case_report_key"),
        F.lit(REVIEW_STATUS_SUGGESTION).alias("review_status"),
        F.lit(EXPERIMENT_TAG).alias("experiment_tag"),
        F.lit(job_notes).alias("notes"),
        F.current_timestamp().alias("decided_at"),
        F.lit(ACTOR_SUGGESTION).alias("actor"),
    )
    staged.createOrReplaceTempView("_match_decision_sf_batch")
    spark.sql(
        f"""
INSERT INTO {DECISION_TABLE} (
  decision_id, subject_ref, subject_name, subject_dob,
  party_key, source_system, state_code, source_record_id,
  party_role, party_ordinal, raw_name, name_last, name_first, name_middle,
  confidence_band, score, reasons, score_or_reason_codes,
  ingest_run_id, payload_sha256, transform_run_id, case_report_key,
  review_status, experiment_tag, notes, decided_at, actor
)
SELECT
  decision_id, subject_ref, subject_name, subject_dob,
  party_key, source_system, state_code, source_record_id,
  party_role, party_ordinal, raw_name, name_last, name_first, name_middle,
  confidence_band, score, reasons, score_or_reason_codes,
  ingest_run_id, payload_sha256, transform_run_id, case_report_key,
  review_status, experiment_tag, notes, decided_at, actor
FROM _match_decision_sf_batch
"""
    )
    appended = staged.count()
    print("match_decision_sf_research: appended", appended, "rows")
    print("batch_id=", batch_id)
    print("experiment_tag=", EXPERIMENT_TAG)
    print("actor=", ACTOR_SUGGESTION)
    print("persist_no_link=", persist_flag)
    return batch_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "APPEND SF name-only match suggestions into silver.match_decision. "
            "Scoped to source_system=sf_criminal_hf / state_code=CA. "
            "Uses MATCH_REVIEW bands; never silent auto-link; not CRA. "
            "Does not scrape, write Bronze, or touch wcca court_case."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run INSERT on the current Spark session (Databricks cluster)",
    )
    parser.add_argument(
        "--subjects-table",
        default=SUBJECT_TABLE,
        help="Small subject table (subject_ref, subject_name, subject_dob)",
    )
    parser.add_argument(
        "--persist-no-link",
        action="store_true",
        help="Also append last-name-equal no-link negatives (warehouse prove)",
    )
    args = parser.parse_args(argv)
    if not args.apply:
        parser.print_help()
        print(
            "\nLocal tests: python3 -m unittest discover "
            "-s silver/transforms/tests -v"
        )
        print("SQL path: silver/transforms/match_decision_sf_research.sql")
        print("experiment_tag=", EXPERIMENT_TAG)
        print("expected_sf_defendants~=", RESEARCH_DEFENDANT_COUNT)
        print("auto requires both DOBs; SF parties have none → review only")
        return 0
    spark = _spark()
    apply_transform(
        spark,
        subjects_table=args.subjects_table,
        persist_no_link=args.persist_no_link,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
