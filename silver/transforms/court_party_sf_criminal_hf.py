#!/usr/bin/env python3
"""Bronze sf_criminal_hf JSON → silver.court_party type-1 MERGE (parallel path).

Reads Bronze only. Filters `source_system='sf_criminal_hf'` and `state_code='CA'`.
Idempotent upsert on (source_system, state_code, source_record_id, party_role,
party_ordinal). Stale-key DELETE is scoped to those SF/CA keys so WI `wcca`
party rows are never matched.

Does not write court_case / court_charge. Does not scrape. Does not mutate Bronze.
Does not import or call sources/wcca.

Run on a Databricks cluster (Spark session). Local unit tests cover the parser
and mapper without Spark. This module does not apply DDL/transform live by default.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sources.sf_criminal_hf.parse_party import (  # noqa: E402
    PAYLOAD_PARSE_STATUS,
    SILVER_PARTY_SCHEMA_VERSION,
    SOURCE_SYSTEM,
    STATE_CODE,
    parse_sf_criminal_hf_bronze_row,
)

BRONZE_TABLE = "us_criminal_bg.bronze.court_case_raw"
INGEST_RUN_TABLE = "us_criminal_bg.bronze.ingest_run"
SILVER_PARTY_TABLE = "us_criminal_bg.silver.court_party"
SILVER_RUN_TABLE = "us_criminal_bg.silver.transform_run"
THIS_RUN_TABLE = "us_criminal_bg.silver._this_transform_run"

# Hard scope: MERGE/DELETE must never touch other source_system values.
SF_SOURCE_SYSTEM_SQL = "sf_criminal_hf"
SF_STATE_CODE_SQL = "CA"


def _spark():
    from pyspark.sql import SparkSession

    return SparkSession.builder.getOrCreate()


def _register_parse_udf(spark):
    from pyspark.sql.functions import udf
    from pyspark.sql.types import (
        ArrayType,
        DateType,
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    party_schema = StructType(
        [
            StructField("party_role", StringType()),
            StructField("party_ordinal", IntegerType()),
            StructField("raw_name", StringType()),
            StructField("name_last", StringType()),
            StructField("name_first", StringType()),
            StructField("name_middle", StringType()),
            StructField("dob", DateType()),
            StructField("sex", StringType()),
            StructField("address_raw", StringType()),
            StructField("payload_parse_status", StringType()),
            StructField("dq_flags", ArrayType(StringType())),
        ]
    )

    @udf(ArrayType(party_schema))
    def parse_udf(source_system, payload):
        parties = parse_sf_criminal_hf_bronze_row(
            source_system=source_system,
            payload=payload,
        )
        return [
            (
                p.party_role,
                p.party_ordinal,
                p.raw_name,
                p.name_last,
                p.name_first,
                p.name_middle,
                p.dob,
                p.sex,
                p.address_raw,
                p.payload_parse_status,
                list(p.dq_flags),
            )
            for p in parties
        ]

    return parse_udf


def apply_transform(spark, *, notes: str | None = None) -> str:
    """Run type-1 MERGE for sf_criminal_hf court_party only. Returns transform_run_id."""
    run_id = str(uuid4())
    started = datetime.now(timezone.utc)
    label = started.strftime(f"{SOURCE_SYSTEM}_{STATE_CODE}_%Y%m%d_%H%M%S") + "Z"
    started_sql = started.strftime("%Y-%m-%d %H:%M:%S")
    default_notes = (
        "python json_cases_v1 court_party MERGE; "
        "source_system=sf_criminal_hf state_code=CA only; "
        "does not delete wcca parties"
    )
    safe_notes = (notes or default_notes).replace("'", "''")

    spark.sql(
        f"""
CREATE OR REPLACE TABLE {THIS_RUN_TABLE}
USING DELTA
AS
SELECT
  '{run_id}' AS transform_run_id,
  '{label}' AS transform_run_label,
  TIMESTAMP '{started_sql}' AS started_at
"""
    )

    spark.sql(
        f"""
INSERT INTO {SILVER_RUN_TABLE} (
  transform_run_id, transform_run_label, state_code, source_system,
  started_at, finished_at, status, bronze_source_table, row_count,
  silver_schema_version, notes
)
SELECT
  transform_run_id,
  transform_run_label,
  '{SF_STATE_CODE_SQL}',
  '{SF_SOURCE_SYSTEM_SQL}',
  started_at,
  CAST(NULL AS TIMESTAMP),
  'running',
  '{BRONZE_TABLE}',
  CAST(NULL AS BIGINT),
  '{SILVER_PARTY_SCHEMA_VERSION}',
  '{safe_notes}'
FROM {THIS_RUN_TABLE}
"""
    )

    parse_udf = _register_parse_udf(spark)
    bronze = spark.sql(
        f"""
SELECT r.*
FROM {BRONZE_TABLE} r
LEFT JOIN {INGEST_RUN_TABLE} i
  ON r.ingest_run_id = i.ingest_run_id
WHERE r.source_system = '{SF_SOURCE_SYSTEM_SQL}'
  AND r.state_code = '{SF_STATE_CODE_SQL}'
  AND lower(r.payload_format) = 'json'
  AND (i.status IS NULL OR i.status = 'succeeded')
QUALIFY row_number() OVER (
  PARTITION BY r.source_system, r.state_code, r.source_record_id
  ORDER BY r.ingested_at DESC, r.ingest_run_id DESC
) = 1
"""
    )

    from pyspark.sql import functions as F

    parsed = bronze.withColumn("parties", parse_udf(F.col("source_system"), F.col("payload")))
    parsed.createOrReplaceTempView("silver_court_party_sf_cases")

    parties = (
        parsed.select(
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
            F.col("ingest_run_id"),
            F.col("ingested_at"),
            F.col("payload_sha256"),
            F.col("schema_version").alias("bronze_schema_version"),
            F.explode(F.col("parties")).alias("pt"),
        )
        .select(
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
            F.col("pt.party_role").alias("party_role"),
            F.col("pt.party_ordinal").alias("party_ordinal"),
            F.col("pt.raw_name").alias("raw_name"),
            F.col("pt.name_last").alias("name_last"),
            F.col("pt.name_first").alias("name_first"),
            F.col("pt.name_middle").alias("name_middle"),
            F.col("pt.dob").alias("dob"),
            F.col("pt.sex").alias("sex"),
            F.col("pt.address_raw").alias("address_raw"),
            F.col("ingest_run_id"),
            F.col("ingested_at"),
            F.col("payload_sha256"),
            F.col("bronze_schema_version"),
            F.lit(SILVER_PARTY_SCHEMA_VERSION).alias("silver_schema_version"),
            F.current_timestamp().alias("transformed_at"),
            F.lit(run_id).alias("transform_run_id"),
            F.col("pt.payload_parse_status").alias("payload_parse_status"),
            F.col("pt.dq_flags").alias("dq_flags"),
        )
    )
    parties.createOrReplaceTempView("silver_court_party_sf_staged")

    spark.sql(
        f"""
MERGE INTO {SILVER_PARTY_TABLE} AS t
USING silver_court_party_sf_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
 AND t.party_role = s.party_role
 AND t.party_ordinal = s.party_ordinal
WHEN MATCHED AND t.source_system = '{SF_SOURCE_SYSTEM_SQL}' THEN UPDATE SET
  t.raw_name = s.raw_name,
  t.name_last = s.name_last,
  t.name_first = s.name_first,
  t.name_middle = s.name_middle,
  t.dob = s.dob,
  t.sex = s.sex,
  t.address_raw = s.address_raw,
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.payload_sha256 = s.payload_sha256,
  t.bronze_schema_version = s.bronze_schema_version,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id,
  t.payload_parse_status = s.payload_parse_status,
  t.dq_flags = s.dq_flags
WHEN NOT MATCHED AND s.source_system = '{SF_SOURCE_SYSTEM_SQL}' THEN INSERT (
  source_system, state_code, source_record_id, party_role, party_ordinal,
  raw_name, name_last, name_first, name_middle, dob, sex, address_raw,
  ingest_run_id, ingested_at, payload_sha256, bronze_schema_version,
  silver_schema_version, transformed_at, transform_run_id,
  payload_parse_status, dq_flags
) VALUES (
  s.source_system, s.state_code, s.source_record_id, s.party_role, s.party_ordinal,
  s.raw_name, s.name_last, s.name_first, s.name_middle, s.dob, s.sex, s.address_raw,
  s.ingest_run_id, s.ingested_at, s.payload_sha256, s.bronze_schema_version,
  s.silver_schema_version, s.transformed_at, s.transform_run_id,
  s.payload_parse_status, s.dq_flags
)
"""
    )

    # Type-1: drop role+ordinal rows that disappeared for SF/CA cases in this run.
    # Extra AND on t.source_system / t.state_code is defense in depth so wcca/WI
    # keys cannot match even if a case-key collision were ever staged.
    spark.sql(
        f"""
DELETE FROM {SILVER_PARTY_TABLE} t
WHERE t.source_system = '{SF_SOURCE_SYSTEM_SQL}'
  AND t.state_code = '{SF_STATE_CODE_SQL}'
  AND EXISTS (
    SELECT 1 FROM silver_court_party_sf_cases s
    WHERE t.source_system = s.source_system
      AND t.state_code = s.state_code
      AND t.source_record_id = s.source_record_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM silver_court_party_sf_staged p
    WHERE t.source_system = p.source_system
      AND t.state_code = p.state_code
      AND t.source_record_id = p.source_record_id
      AND t.party_role = p.party_role
      AND t.party_ordinal = p.party_ordinal
  )
"""
    )

    spark.sql(
        f"""
UPDATE {SILVER_RUN_TABLE} t
SET
  finished_at = current_timestamp(),
  status = 'succeeded',
  row_count = (
    SELECT count(*)
    FROM {SILVER_PARTY_TABLE} c
    WHERE c.transform_run_id = t.transform_run_id
  )
WHERE t.status = 'running'
  AND t.transform_run_id IN (
    SELECT transform_run_id FROM {THIS_RUN_TABLE}
  )
"""
    )
    spark.sql(f"DROP TABLE IF EXISTS {THIS_RUN_TABLE}")
    return run_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "MERGE Bronze sf_criminal_hf JSON into Silver court_party only. "
            "Scoped to source_system=sf_criminal_hf / state_code=CA. "
            "Does not scrape, write Bronze, or delete wcca parties."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run MERGE on the current Spark session (Databricks cluster)",
    )
    args = parser.parse_args(argv)
    if not args.apply:
        parser.print_help()
        print(
            "\nLocal parser tests: python3 -m unittest discover "
            "-s sources/sf_criminal_hf/tests -v"
        )
        print("SQL path: silver/transforms/court_party_sf_criminal_hf.sql")
        print(f"payload_parse_status={PAYLOAD_PARSE_STATUS}")
        return 0
    spark = _spark()
    run_id = apply_transform(spark)
    print("transform_run_id=", run_id)
    print("silver_party_schema_version=", SILVER_PARTY_SCHEMA_VERSION)
    print("source_system=", SOURCE_SYSTEM)
    print("state_code=", STATE_CODE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
