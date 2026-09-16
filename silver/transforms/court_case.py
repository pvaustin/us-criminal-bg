#!/usr/bin/env python3
"""Bronze court_case_raw → silver.court_case + silver.court_charge type-1 MERGE.

Reads Bronze only. Idempotent upsert:
  court_case  on (source_system, state_code, source_record_id)
  court_charge on (source_system, state_code, source_record_id, charge_count)
Always appends silver.transform_run. transform_run_id is materialized once into
us_criminal_bg.silver._this_transform_run (same scratch pattern as the SQL job).

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

from sources.wcca.parse import (  # noqa: E402
    SILVER_CHARGE_SCHEMA_VERSION,
    SILVER_SCHEMA_VERSION,
    parse_wcca_bronze_row,
)

BRONZE_TABLE = "us_criminal_bg.bronze.court_case_raw"
INGEST_RUN_TABLE = "us_criminal_bg.bronze.ingest_run"
SILVER_CASE_TABLE = "us_criminal_bg.silver.court_case"
SILVER_CHARGE_TABLE = "us_criminal_bg.silver.court_charge"
SILVER_RUN_TABLE = "us_criminal_bg.silver.transform_run"
THIS_RUN_TABLE = "us_criminal_bg.silver._this_transform_run"


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

    charge_schema = StructType(
        [
            StructField("charge_count", IntegerType()),
            StructField("statute", StringType()),
            StructField("description", StringType()),
            StructField("severity", StringType()),
            StructField("modifier_statute", StringType()),
            StructField("modifier_text", StringType()),
        ]
    )
    schema = StructType(
        [
            StructField("county_code", StringType()),
            StructField("case_number", StringType()),
            StructField("case_type", StringType()),
            StructField("filed_date", DateType()),
            StructField("caption", StringType()),
            StructField("case_status", StringType()),
            StructField("county_name", StringType()),
            StructField("payload_parse_status", StringType()),
            StructField("dq_flags", ArrayType(StringType())),
            StructField("charges", ArrayType(charge_schema)),
        ]
    )

    @udf(schema)
    def parse_udf(source_system, source_record_id, source_url, payload_format, payload):
        parsed = parse_wcca_bronze_row(
            source_system=source_system,
            source_record_id=source_record_id,
            source_url=source_url,
            payload_format=payload_format,
            payload=payload,
        )
        charges = [
            (
                c.charge_count,
                c.statute,
                c.description,
                c.severity,
                c.modifier_statute,
                c.modifier_text,
            )
            for c in parsed.charges
        ]
        return (
            parsed.county_code,
            parsed.case_number,
            parsed.case_type,
            parsed.filed_date,
            parsed.caption,
            parsed.case_status,
            parsed.county_name,
            parsed.payload_parse_status,
            list(parsed.dq_flags),
            charges,
        )

    return parse_udf


def apply_transform(spark, *, notes: str = "python html_ssr_v1 MERGE") -> str:
    """Run type-1 MERGE for court_case and court_charge. Returns transform_run_id."""
    run_id = str(uuid4())
    started = datetime.now(timezone.utc)
    label = started.strftime("all_all_%Y%m%d_%H%M%S") + "Z"
    started_sql = started.strftime("%Y-%m-%d %H:%M:%S")
    safe_notes = notes.replace("'", "''")

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
  CAST(NULL AS STRING),
  CAST(NULL AS STRING),
  started_at,
  CAST(NULL AS TIMESTAMP),
  'running',
  '{BRONZE_TABLE}',
  CAST(NULL AS BIGINT),
  '{SILVER_SCHEMA_VERSION}',
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
WHERE (i.status IS NULL OR i.status = 'succeeded')
QUALIFY row_number() OVER (
  PARTITION BY r.source_system, r.state_code, r.source_record_id
  ORDER BY r.ingested_at DESC, r.ingest_run_id DESC
) = 1
"""
    )

    from pyspark.sql import functions as F

    parsed = bronze.withColumn(
        "p",
        parse_udf(
            F.col("source_system"),
            F.col("source_record_id"),
            F.col("source_url"),
            F.col("payload_format"),
            F.col("payload"),
        ),
    )

    cases = parsed.select(
        F.col("source_system"),
        F.col("state_code"),
        F.col("source_record_id"),
        F.col("ingest_run_id"),
        F.col("ingested_at"),
        F.col("source_url"),
        F.col("payload_format"),
        F.col("payload_sha256"),
        F.col("extract_method"),
        F.col("schema_version").alias("bronze_schema_version"),
        F.col("p.county_code").alias("county_code"),
        F.col("p.case_number").alias("case_number"),
        F.col("p.case_type").alias("case_type"),
        F.col("p.filed_date").alias("filed_date"),
        F.col("p.caption").alias("caption"),
        F.col("p.case_status").alias("case_status"),
        F.col("p.county_name").alias("county_name"),
        F.col("p.payload_parse_status").alias("payload_parse_status"),
        F.col("p.dq_flags").alias("dq_flags"),
        F.lit(SILVER_SCHEMA_VERSION).alias("silver_schema_version"),
        F.current_timestamp().alias("transformed_at"),
        F.lit(run_id).alias("transform_run_id"),
    )
    cases.createOrReplaceTempView("silver_court_case_staged")

    charges = (
        parsed.select(
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
            F.col("ingest_run_id"),
            F.col("ingested_at"),
            F.col("payload_sha256"),
            F.col("schema_version").alias("bronze_schema_version"),
            F.explode(F.col("p.charges")).alias("ch"),
        )
        .select(
            F.col("source_system"),
            F.col("state_code"),
            F.col("source_record_id"),
            F.col("ch.charge_count").alias("charge_count"),
            F.col("ch.statute").alias("statute"),
            F.col("ch.description").alias("description"),
            F.col("ch.severity").alias("severity"),
            F.col("ch.modifier_statute").alias("modifier_statute"),
            F.col("ch.modifier_text").alias("modifier_text"),
            F.col("ingest_run_id"),
            F.col("ingested_at"),
            F.col("payload_sha256"),
            F.col("bronze_schema_version"),
            F.lit(SILVER_CHARGE_SCHEMA_VERSION).alias("silver_schema_version"),
            F.current_timestamp().alias("transformed_at"),
            F.lit(run_id).alias("transform_run_id"),
        )
    )
    charges.createOrReplaceTempView("silver_court_charge_staged")

    spark.sql(
        f"""
MERGE INTO {SILVER_CASE_TABLE} AS t
USING silver_court_case_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
WHEN MATCHED THEN UPDATE SET
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.source_url = s.source_url,
  t.payload_format = s.payload_format,
  t.payload_sha256 = s.payload_sha256,
  t.extract_method = s.extract_method,
  t.bronze_schema_version = s.bronze_schema_version,
  t.county_code = s.county_code,
  t.case_number = s.case_number,
  t.case_type = s.case_type,
  t.filed_date = s.filed_date,
  t.caption = s.caption,
  t.case_status = s.case_status,
  t.county_name = s.county_name,
  t.payload_parse_status = s.payload_parse_status,
  t.dq_flags = s.dq_flags,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id
WHEN NOT MATCHED THEN INSERT (
  source_system, state_code, source_record_id, ingest_run_id, ingested_at,
  source_url, payload_format, payload_sha256, extract_method,
  bronze_schema_version, county_code, case_number, case_type, filed_date,
  caption, case_status, county_name, payload_parse_status, dq_flags,
  silver_schema_version, transformed_at, transform_run_id
) VALUES (
  s.source_system, s.state_code, s.source_record_id, s.ingest_run_id, s.ingested_at,
  s.source_url, s.payload_format, s.payload_sha256, s.extract_method,
  s.bronze_schema_version, s.county_code, s.case_number, s.case_type, s.filed_date,
  s.caption, s.case_status, s.county_name, s.payload_parse_status, s.dq_flags,
  s.silver_schema_version, s.transformed_at, s.transform_run_id
)
"""
    )

    spark.sql(
        f"""
MERGE INTO {SILVER_CHARGE_TABLE} AS t
USING silver_court_charge_staged AS s
ON t.source_system = s.source_system
 AND t.state_code = s.state_code
 AND t.source_record_id = s.source_record_id
 AND t.charge_count = s.charge_count
WHEN MATCHED THEN UPDATE SET
  t.statute = s.statute,
  t.description = s.description,
  t.severity = s.severity,
  t.modifier_statute = s.modifier_statute,
  t.modifier_text = s.modifier_text,
  t.ingest_run_id = s.ingest_run_id,
  t.ingested_at = s.ingested_at,
  t.payload_sha256 = s.payload_sha256,
  t.bronze_schema_version = s.bronze_schema_version,
  t.silver_schema_version = s.silver_schema_version,
  t.transformed_at = s.transformed_at,
  t.transform_run_id = s.transform_run_id
WHEN NOT MATCHED THEN INSERT (
  source_system, state_code, source_record_id, charge_count,
  statute, description, severity, modifier_statute, modifier_text,
  ingest_run_id, ingested_at, payload_sha256, bronze_schema_version,
  silver_schema_version, transformed_at, transform_run_id
) VALUES (
  s.source_system, s.state_code, s.source_record_id, s.charge_count,
  s.statute, s.description, s.severity, s.modifier_statute, s.modifier_text,
  s.ingest_run_id, s.ingested_at, s.payload_sha256, s.bronze_schema_version,
  s.silver_schema_version, s.transformed_at, s.transform_run_id
)
"""
    )

    spark.sql(
        f"""
DELETE FROM {SILVER_CHARGE_TABLE} t
WHERE EXISTS (
  SELECT 1 FROM silver_court_case_staged s
  WHERE t.source_system = s.source_system
    AND t.state_code = s.state_code
    AND t.source_record_id = s.source_record_id
)
AND NOT EXISTS (
  SELECT 1 FROM silver_court_charge_staged c
  WHERE t.source_system = c.source_system
    AND t.state_code = c.state_code
    AND t.source_record_id = c.source_record_id
    AND t.charge_count = c.charge_count
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
    FROM {SILVER_CASE_TABLE} c
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
            "MERGE Bronze court_case_raw into Silver court_case and court_charge. "
            "Databricks/Spark only for --apply. Does not scrape or write Bronze."
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
            "\nLocal parser tests: python3 -m unittest discover -s sources/wcca/tests -v"
        )
        print(
            "SQL path: silver/transforms/court_case.sql "
            "(SSR regex on warehouse; modifiers best from this Python job)"
        )
        return 0
    spark = _spark()
    run_id = apply_transform(spark)
    print("transform_run_id=", run_id)
    print("silver_schema_version=", SILVER_SCHEMA_VERSION)
    print("silver_charge_schema_version=", SILVER_CHARGE_SCHEMA_VERSION)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
