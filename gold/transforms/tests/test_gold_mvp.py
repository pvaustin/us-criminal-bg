"""Gold MVP serving rules. Synthetic names only — not live PII."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gold.transforms.gold_mvp import (  # noqa: E402
    MATCH_QUEUE_VERSION,
    METRICS_VERSION,
    ORDER_REPORT_VERSION,
    PILOT_SOURCES,
    aggregate_charges,
    age_hours,
    build_match_queue,
    build_order_report,
    build_source_coverage_metrics,
    case_report_key,
    is_closed_review,
    is_open_queue_card,
    latest_row_per_subject_party,
    nonempty_name,
    party_key,
    split_sql_statements,
)

GOLD_DIR = ROOT / "gold"
SCHEMA_DIR = GOLD_DIR / "schemas"
TRANSFORM_DIR = GOLD_DIR / "transforms"
PY_PATH = TRANSFORM_DIR / "gold_mvp.py"
SQL_FILES = (
    TRANSFORM_DIR / "match_queue.sql",
    TRANSFORM_DIR / "source_coverage_metrics.sql",
    TRANSFORM_DIR / "order_report.sql",
    TRANSFORM_DIR / "order_subject_src_from_silver.sql",
)
DDL_FILES = (
    SCHEMA_DIR / "order_report.sql",
    SCHEMA_DIR / "match_queue.sql",
    SCHEMA_DIR / "source_coverage_metrics.sql",
)

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)
T_SUGGEST = datetime(2099, 6, 1, 10, 0, tzinfo=timezone.utc)
T_HUMAN = datetime(2099, 6, 1, 11, 0, tzinfo=timezone.utc)

WI_CASE_ID = "01:2099CF000099"
SF_CASE_ID = "sf_case:fixture-1"

WI_PARTY = {
    "source_system": "wcca",
    "state_code": "WI",
    "source_record_id": WI_CASE_ID,
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "FIXTURE, JANE Q",
    "name_last": "FIXTURE",
    "name_first": "JANE",
    "name_middle": "Q",
    "dob": date(2099, 1, 15),
    "payload_parse_status": "html_ssr_v1",
    "dq_flags": [],
    "ingest_run_id": "synthetic-wi-ingest",
    "payload_sha256": "wiabc123",
    "transform_run_id": "synthetic-wi-transform",
    "ingested_at": T_SUGGEST,
    "transformed_at": T_SUGGEST,
}

WI_PLAINTIFF = {
    **WI_PARTY,
    "party_role": "plaintiff",
    "raw_name": "State of Wisconsin",
    "name_last": None,
    "name_first": None,
    "name_middle": None,
    "dob": None,
}

WI_BLANK_NAME = {
    **WI_PARTY,
    "party_role": "aka",
    "party_ordinal": 1,
    "raw_name": "   ",
    "name_last": None,
    "name_first": None,
    "dob": None,
}

SF_PARTY = {
    "source_system": "sf_criminal_hf",
    "state_code": "CA",
    "source_record_id": SF_CASE_ID,
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "JANE Q PUBLIC",
    "name_last": "PUBLIC",
    "name_first": "JANE",
    "name_middle": "Q",
    "dob": None,
    "payload_parse_status": "json_cases_v1",
    "dq_flags": ["missing_dob"],
    "ingest_run_id": "synthetic-sf-ingest",
    "payload_sha256": "sfabc123",
    "transform_run_id": "synthetic-sf-transform",
    "ingested_at": T_SUGGEST,
    "transformed_at": T_SUGGEST,
}

WI_CASE = {
    "source_system": "wcca",
    "state_code": "WI",
    "source_record_id": WI_CASE_ID,
    "county_code": "01",
    "case_number": "2099CF000099",
    "case_type": "CF",
    "filed_date": date(2099, 2, 1),
    "caption": "State of Wisconsin vs. Fixture",
    "case_status": "Open",
    "county_name": "Synthetic",
    "payload_parse_status": "html_ssr_v1",
    "dq_flags": [],
    "transformed_at": T_SUGGEST,
}

WI_CHARGES = [
    {
        "source_system": "wcca",
        "state_code": "WI",
        "source_record_id": WI_CASE_ID,
        "charge_count": 2,
        "statute": "999.02",
        "severity": "Misdemeanor",
        "description": "Synthetic count two",
    },
    {
        "source_system": "wcca",
        "state_code": "WI",
        "source_record_id": WI_CASE_ID,
        "charge_count": 1,
        "statute": "999.01",
        "severity": "Felony",
        "description": "Synthetic count one",
    },
]


def _decision(
    *,
    decision_id: str,
    subject_ref: str,
    party: dict,
    review_status: str,
    confidence_band: str,
    decided_at: datetime,
    actor: str = "system:suggestion",
    score: int = 70,
    subject_name: str = "Jane Q Fixture",
    experiment_tag: str | None = None,
) -> dict:
    src = party["source_system"]
    state = party["state_code"]
    record_id = party["source_record_id"]
    return {
        "decision_id": decision_id,
        "subject_ref": subject_ref,
        "subject_name": subject_name,
        "subject_dob": None,
        "party_key": party_key(
            src, state, record_id, party["party_role"], party["party_ordinal"]
        ),
        "source_system": src,
        "state_code": state,
        "source_record_id": record_id,
        "party_role": party["party_role"],
        "party_ordinal": party["party_ordinal"],
        "raw_name": party["raw_name"],
        "name_last": party["name_last"],
        "name_first": party["name_first"],
        "name_middle": party.get("name_middle"),
        "confidence_band": confidence_band,
        "score": score,
        "reasons": ["last_name_match", "dob_absent"],
        "score_or_reason_codes": ["70", "last_name_match", "dob_absent"],
        "ingest_run_id": party.get("ingest_run_id"),
        "payload_sha256": party.get("payload_sha256"),
        "transform_run_id": party.get("transform_run_id"),
        "case_report_key": case_report_key(src, state, record_id),
        "review_status": review_status,
        "experiment_tag": experiment_tag,
        "notes": "synthetic fixture — not a live defendant",
        "decided_at": decided_at,
        "actor": actor,
    }


class OpenQueueRuleTests(unittest.TestCase):
    def test_latest_suggestion_review_is_open(self) -> None:
        row = _decision(
            decision_id="d1",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            experiment_tag="sf_name_only_research",
        )
        self.assertTrue(is_open_queue_card(row))
        queue = build_match_queue([row], now=NOW)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["subject_ref"], "sub-sf")
        self.assertEqual(queue[0]["confidence_band"], "review")
        self.assertEqual(queue[0]["age_hours"], 2.0)
        self.assertEqual(queue[0]["gold_schema_version"], MATCH_QUEUE_VERSION)
        self.assertEqual(queue[0]["source_system"], "sf_criminal_hf")
        self.assertEqual(queue[0]["state_code"], "CA")

    def test_later_human_closes_card(self) -> None:
        suggestion = _decision(
            decision_id="d1",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        human = _decision(
            decision_id="d2",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="human",
            confidence_band="no-link",
            decided_at=T_HUMAN,
            actor="reviewer@example.test",
        )
        latest = latest_row_per_subject_party([suggestion, human])
        only = next(iter(latest.values()))
        self.assertEqual(only["decision_id"], "d2")
        self.assertTrue(is_closed_review(only))
        self.assertFalse(is_open_queue_card(only))
        self.assertEqual(build_match_queue([suggestion, human], now=NOW), [])

    def test_human_wins_timestamp_tie(self) -> None:
        suggestion = _decision(
            decision_id="z-later-id",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_HUMAN,
        )
        human = _decision(
            decision_id="a-earlier-id",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="human",
            confidence_band="review",
            decided_at=T_HUMAN,
            actor="reviewer@example.test",
        )
        latest = next(iter(latest_row_per_subject_party([suggestion, human]).values()))
        self.assertEqual(latest["review_status"], "human")
        self.assertEqual(latest["decision_id"], "a-earlier-id")
        self.assertEqual(build_match_queue([suggestion, human], now=NOW), [])

    def test_auto_suggestion_stays_open(self) -> None:
        row = _decision(
            decision_id="d-auto",
            subject_ref="sub-wi",
            party=WI_PARTY,
            review_status="suggestion",
            confidence_band="auto",
            decided_at=T_SUGGEST,
            score=100,
        )
        self.assertTrue(is_open_queue_card(row))
        queue = build_match_queue([row], now=NOW)
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["confidence_band"], "auto")

    def test_no_link_latest_not_queued(self) -> None:
        row = _decision(
            decision_id="d-nl",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="no-link",
            decided_at=T_SUGGEST,
            score=0,
        )
        self.assertFalse(is_open_queue_card(row))
        self.assertEqual(build_match_queue([row], now=NOW), [])

    def test_older_suggestion_does_not_reopen_after_human(self) -> None:
        human = _decision(
            decision_id="d-h",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="human",
            confidence_band="review",
            decided_at=T_HUMAN,
            actor="reviewer@example.test",
        )
        older = _decision(
            decision_id="d-old",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        self.assertEqual(build_match_queue([human, older], now=NOW), [])


class OrderReportGrainTests(unittest.TestCase):
    def test_sf_case_and_charges_are_honest_nulls(self) -> None:
        md = _decision(
            decision_id="d-sf",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            experiment_tag="sf_name_only_research",
            subject_name="Jane Q Public",
        )
        reports = build_order_report(
            [md],
            [SF_PARTY],
            [],
            [],
            None,
            now=NOW,
            order_subject_table_present=False,
        )
        self.assertEqual(len(reports), 1)
        row = reports[0]
        self.assertEqual(row["subject_ref"], "sub-sf")
        self.assertEqual(
            row["party_key"],
            party_key("sf_criminal_hf", "CA", SF_CASE_ID, "defendant", 1),
        )
        self.assertIsNone(row["order_id"])
        self.assertEqual(row["subject_source"], "match_decision")
        self.assertFalse(row["order_subject_table_present"])
        self.assertTrue(row["party_row_present"])
        self.assertFalse(row["has_court_case"])
        self.assertFalse(row["has_court_charge"])
        self.assertEqual(row["charge_row_count"], 0)
        self.assertEqual(row["charge_statutes"], [])
        self.assertIsNone(row["case_number"])
        self.assertIsNone(row["caption"])
        self.assertIsNone(row["party_dob"])
        self.assertTrue(row["is_open_review"])
        self.assertEqual(row["gold_schema_version"], ORDER_REPORT_VERSION)
        self.assertNotIn("hire", row)
        self.assertNotIn("risk_score", row)

    def test_wi_joins_case_and_charges_in_count_order(self) -> None:
        md = _decision(
            decision_id="d-wi",
            subject_ref="sub-wi",
            party=WI_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        reports = build_order_report(
            [md],
            [WI_PARTY],
            [WI_CASE],
            WI_CHARGES,
            None,
            now=NOW,
            order_subject_table_present=False,
        )
        row = reports[0]
        self.assertTrue(row["has_court_case"])
        self.assertTrue(row["has_court_charge"])
        self.assertEqual(row["case_number"], "2099CF000099")
        self.assertEqual(row["charge_row_count"], 2)
        self.assertEqual(row["charge_statutes"], ["999.01", "999.02"])
        self.assertEqual(row["charge_severities"], ["Felony", "Misdemeanor"])
        self.assertEqual(row["party_dob"], date(2099, 1, 15))

    def test_order_subject_enriches_when_present(self) -> None:
        md = _decision(
            decision_id="d-wi",
            subject_ref="sub-wi",
            party=WI_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        order = {
            "order_id": "ord-1",
            "subject_ref": "sub-wi",
            "subject_name": "Jane Order Subject",
            "subject_dob": date(2099, 1, 15),
            "created_by": "operator@example.test",
            "updated_at": T_HUMAN,
            "status": "in_review",
        }
        row = build_order_report(
            [md],
            [WI_PARTY],
            [WI_CASE],
            WI_CHARGES,
            [order],
            now=NOW,
            order_subject_table_present=True,
        )[0]
        self.assertEqual(row["order_id"], "ord-1")
        self.assertEqual(row["subject_name"], "Jane Order Subject")
        self.assertEqual(row["subject_source"], "order_subject")
        self.assertTrue(row["order_subject_table_present"])

    def test_no_order_report_row_without_match_decision(self) -> None:
        reports = build_order_report(
            [],
            [WI_PARTY],
            [WI_CASE],
            WI_CHARGES,
            None,
            now=NOW,
            order_subject_table_present=False,
        )
        self.assertEqual(reports, [])

    def test_human_overlay_on_closed_report(self) -> None:
        suggestion = _decision(
            decision_id="d1",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        human = _decision(
            decision_id="d2",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="human",
            confidence_band="no-link",
            decided_at=T_HUMAN,
            actor="reviewer@example.test",
            score=0,
        )
        row = build_order_report(
            [suggestion, human],
            [SF_PARTY],
            [],
            [],
            None,
            now=NOW,
            order_subject_table_present=False,
        )[0]
        self.assertFalse(row["is_open_review"])
        self.assertEqual(row["current_review_status"], "human")
        self.assertEqual(row["human_actor"], "reviewer@example.test")
        self.assertEqual(row["human_confidence_band"], "no-link")
        self.assertEqual(row["latest_decision_id"], "d2")


class MetricsTests(unittest.TestCase):
    def test_includes_both_pilot_sources_when_sf_has_zero_cases(self) -> None:
        metrics = build_source_coverage_metrics(
            [WI_CASE],
            [WI_PARTY, WI_PLAINTIFF, WI_BLANK_NAME, SF_PARTY],
            [
                _decision(
                    decision_id="d-sf",
                    subject_ref="sub-sf",
                    party=SF_PARTY,
                    review_status="suggestion",
                    confidence_band="review",
                    decided_at=T_SUGGEST,
                    experiment_tag="sf_name_only_research",
                )
            ],
            as_of_date=date(2099, 6, 1),
            now=NOW,
        )
        by_src = {(m["source_system"], m["state_code"]): m for m in metrics}
        self.assertIn(("wcca", "WI"), by_src)
        self.assertIn(("sf_criminal_hf", "CA"), by_src)
        wi = by_src[("wcca", "WI")]
        sf = by_src[("sf_criminal_hf", "CA")]
        self.assertEqual(wi["case_count"], 1)
        self.assertEqual(wi["party_count"], 3)
        self.assertEqual(wi["nonempty_name_count"], 2)
        self.assertEqual(wi["suggestion_row_count"], 0)
        self.assertEqual(wi["open_review_count"], 0)
        self.assertEqual(wi["closed_review_count"], 0)
        self.assertEqual(sf["case_count"], 0)
        self.assertEqual(sf["party_count"], 1)
        self.assertEqual(sf["nonempty_name_count"], 1)
        self.assertEqual(sf["suggestion_row_count"], 1)
        self.assertEqual(sf["open_review_count"], 1)
        self.assertEqual(sf["closed_review_count"], 0)
        self.assertEqual(sf["gold_schema_version"], METRICS_VERSION)

    def test_closed_review_count_uses_latest_human(self) -> None:
        suggestion = _decision(
            decision_id="d1",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
        )
        human = _decision(
            decision_id="d2",
            subject_ref="sub-sf",
            party=SF_PARTY,
            review_status="human",
            confidence_band="review",
            decided_at=T_HUMAN,
            actor="reviewer@example.test",
        )
        metrics = build_source_coverage_metrics(
            [],
            [SF_PARTY],
            [suggestion, human],
            as_of_date=date(2099, 6, 1),
            now=NOW,
        )
        sf = next(m for m in metrics if m["source_system"] == "sf_criminal_hf")
        self.assertEqual(sf["suggestion_row_count"], 1)
        self.assertEqual(sf["open_review_count"], 0)
        self.assertEqual(sf["closed_review_count"], 1)

    def test_pilot_sources_constant(self) -> None:
        self.assertEqual(PILOT_SOURCES, (("wcca", "WI"), ("sf_criminal_hf", "CA")))


class HelperTests(unittest.TestCase):
    def test_keys_and_age(self) -> None:
        self.assertEqual(
            party_key("wcca", "WI", WI_CASE_ID, "defendant", 1),
            f"wcca|WI|{WI_CASE_ID}|defendant|1",
        )
        self.assertEqual(
            case_report_key("sf_criminal_hf", "CA", SF_CASE_ID),
            f"sf_criminal_hf|CA|{SF_CASE_ID}",
        )
        self.assertEqual(age_hours(T_SUGGEST, NOW), 2.0)
        self.assertTrue(nonempty_name("JANE Q PUBLIC"))
        self.assertFalse(nonempty_name("  "))
        self.assertFalse(nonempty_name(None))

    def test_charge_aggregate_sorts_by_count(self) -> None:
        agg = aggregate_charges(WI_CHARGES)
        bundled = agg[("wcca", "WI", WI_CASE_ID)]
        self.assertEqual(bundled["charge_statutes"], ["999.01", "999.02"])


class SqlAndDdlContractTests(unittest.TestCase):
    def _ddl_and_transform_sql(self) -> str:
        return "\n".join(p.read_text(encoding="utf-8") for p in DDL_FILES + SQL_FILES)

    def test_ddl_grains_and_array_string(self) -> None:
        order_ddl = (SCHEMA_DIR / "order_report.sql").read_text(encoding="utf-8")
        queue_ddl = (SCHEMA_DIR / "match_queue.sql").read_text(encoding="utf-8")
        metrics_ddl = (SCHEMA_DIR / "source_coverage_metrics.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("us_criminal_bg.gold.order_report", order_ddl)
        self.assertIn("subject_ref STRING NOT NULL", order_ddl)
        self.assertIn("party_key STRING NOT NULL", order_ddl)
        self.assertIn("has_court_case BOOLEAN NOT NULL", order_ddl)
        self.assertIn("charge_statutes ARRAY<STRING> NOT NULL", order_ddl)
        self.assertNotIn("ARRAY NOT NULL", order_ddl)
        self.assertIn("No hire", order_ddl)
        self.assertIn("age_hours DOUBLE NOT NULL", queue_ddl)
        self.assertIn("confidence_band STRING NOT NULL", queue_ddl)
        self.assertIn("as_of_date DATE NOT NULL", metrics_ddl)
        self.assertIn("open_review_count BIGINT NOT NULL", metrics_ddl)
        self.assertIn("closed_review_count BIGINT NOT NULL", metrics_ddl)

    def test_no_hire_risk_or_state_prefixed_tables(self) -> None:
        blob = self._ddl_and_transform_sql().lower()
        for token in ("hire_flag", "no_hire", "risk_score", "adverse_action"):
            self.assertNotIn(token, blob)
        self.assertNotIn("wi_gold", blob)
        self.assertNotIn("gold.wi_", blob)
        self.assertNotIn("create schema if not exists us_criminal_bg.wi", blob)
        self.assertNotIn("us_criminal_bg.gold.party_name_index", blob)

    def test_sql_uses_delta_scratch_not_temp_view(self) -> None:
        for path in SQL_FILES:
            sql = path.read_text(encoding="utf-8")
            self.assertNotIn("CREATE OR REPLACE TEMP VIEW", sql)
            self.assertNotIn("CREATE TEMP VIEW", sql)
            self.assertNotIn("TEMPORARY VIEW", sql)
            self.assertNotIn("us_criminal_bg.bronze", sql)
            lowered = sql.lower()
            self.assertNotIn("insert into us_criminal_bg.silver", lowered)
            self.assertNotIn("merge into us_criminal_bg.silver", lowered)
            self.assertNotIn("delete from us_criminal_bg.silver", lowered)
            self.assertNotIn("update us_criminal_bg.silver", lowered)

    def test_open_rule_and_pilot_universe_in_sql(self) -> None:
        queue_sql = (TRANSFORM_DIR / "match_queue.sql").read_text(encoding="utf-8")
        self.assertIn("review_status = 'suggestion'", queue_sql)
        self.assertIn("confidence_band IN ('review', 'auto')", queue_sql)
        self.assertIn("CREATE OR REPLACE TABLE us_criminal_bg.gold._gold_match_latest", queue_sql)
        self.assertIn("USING DELTA", queue_sql)
        self.assertIn("prefer human", queue_sql.lower())

        metrics_sql = (TRANSFORM_DIR / "source_coverage_metrics.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("('wcca', 'WI')", metrics_sql)
        self.assertIn("('sf_criminal_hf', 'CA')", metrics_sql)
        self.assertIn("MERGE INTO us_criminal_bg.gold.source_coverage_metrics", metrics_sql)
        self.assertIn("nonempty_name_count", metrics_sql)

        report_sql = (TRANSFORM_DIR / "order_report.sql").read_text(encoding="utf-8")
        self.assertIn("information_schema.tables", report_sql)
        self.assertIn("_gold_order_subject_src", report_sql)
        self.assertIn("LEFT JOIN us_criminal_bg.silver.court_case", report_sql)
        self.assertIn("LEFT JOIN us_criminal_bg.silver.court_party", report_sql)
        self.assertIn("WHEN os.subject_ref IS NOT NULL THEN os.subject_dob", report_sql)
        self.assertNotIn("us_criminal_bg.silver.search_audit", report_sql)
        self.assertNotIn("us_criminal_bg.silver.order_subject", report_sql)

        optional = (TRANSFORM_DIR / "order_subject_src_from_silver.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("us_criminal_bg.silver.order_subject", optional)
        self.assertIn("OPTIONAL", optional)

    def test_python_does_not_import_wcca_or_read_search_audit(self) -> None:
        py = PY_PATH.read_text(encoding="utf-8")
        self.assertNotIn("from sources.wcca", py)
        self.assertNotIn("map_court_case", py)
        self.assertIn("Does not use party_name_index", py)
        self.assertIn("try-or-skip", py)
        self.assertIn("SEARCH_AUDIT_TABLE", py)
        self.assertIn("search_audit_read", py)
        self.assertIn("never reads `search_audit`", py)
        self.assertNotIn("spark.table(SEARCH_AUDIT_TABLE)", py)
        self.assertNotIn("FROM us_criminal_bg.silver.search_audit", py)

    def test_split_sql_skips_comments(self) -> None:
        statements = split_sql_statements(
            (TRANSFORM_DIR / "match_queue.sql").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(statements), 3)
        joined = "\n".join(statements)
        self.assertIn("CREATE OR REPLACE TABLE us_criminal_bg.gold.match_queue", joined)
        self.assertNotIn("TEMP VIEW", joined)

    def test_help_does_not_need_spark(self) -> None:
        out = subprocess.check_output(
            [sys.executable, str(PY_PATH), "--help"],
            text=True,
        )
        self.assertIn("order_report", out)
        self.assertIn("match_queue", out)
        self.assertIn("order_subject", out)
        self.assertIn("search_audit", out.lower())
        self.assertIn("hire", out.lower())


class DocsContractTests(unittest.TestCase):
    def test_naming_and_access_exist(self) -> None:
        naming = (ROOT / "docs" / "gold" / "NAMING.md").read_text(encoding="utf-8")
        access = (ROOT / "docs" / "gold" / "ACCESS.md").read_text(encoding="utf-8")
        self.assertIn("(subject_ref, party_key)", naming)
        self.assertIn("Gold is the serving layer", naming)
        self.assertIn("Silver is the truth / clean layer", naming)
        self.assertIn("Do not invent", naming)
        self.assertIn("order_subject", naming)
        self.assertIn("TEMP VIEW", naming)
        self.assertIn("has_court_case=false", naming)
        self.assertIn("/review", access)
        self.assertIn("/metrics", access)
        self.assertIn("77399", access)


if __name__ == "__main__":
    unittest.main()
