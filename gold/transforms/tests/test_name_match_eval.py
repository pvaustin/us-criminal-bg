"""sf_name_match_v1 eval + label pack. Synthetic names only — not live PII."""

from __future__ import annotations

import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gold.transforms.gold_mvp import (  # noqa: E402
    build_match_queue,
    party_key,
    split_sql_statements,
)
from gold.transforms.name_match_eval import (  # noqa: E402
    EVAL_NAME,
    EVAL_VERSION,
    LABEL_LEAVE,
    LABEL_LINK,
    LABEL_REJECT,
    PACK_VERSION,
    PAIR_HARD_NEGATIVE,
    PAIR_OPEN_QUEUE,
    build_name_match_eval,
    build_name_match_label_pack,
    count_eval_labels,
    map_human_band_to_label,
)

GOLD_DIR = ROOT / "gold"
SCHEMA_DIR = GOLD_DIR / "schemas"
TRANSFORM_DIR = GOLD_DIR / "transforms"
PY_PATH = TRANSFORM_DIR / "name_match_eval.py"
EVAL_DDL = SCHEMA_DIR / "name_match_eval.sql"
PACK_DDL = SCHEMA_DIR / "name_match_label_pack.sql"
EVAL_SQL = TRANSFORM_DIR / "name_match_eval.sql"
PACK_SQL = TRANSFORM_DIR / "name_match_label_pack.sql"

NOW = datetime(2099, 6, 1, 12, 0, tzinfo=timezone.utc)
T_SUGGEST = datetime(2099, 6, 1, 10, 0, tzinfo=timezone.utc)
T_HUMAN = datetime(2099, 6, 1, 11, 0, tzinfo=timezone.utc)

SF_PUBLIC = {
    "source_system": "sf_criminal_hf",
    "state_code": "CA",
    "source_record_id": "sf_case:fixture-1",
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "JANE Q PUBLIC",
    "name_last": "PUBLIC",
    "name_first": "JANE",
    "name_middle": "Q",
    "ingest_run_id": "synthetic-sf-ingest",
    "payload_sha256": "sfabc123",
}

SF_MARSHALL = {
    **SF_PUBLIC,
    "source_record_id": "sf_case:fixture-2",
    "raw_name": "JOHN MARSHALL FIXTURE",
    "name_last": "FIXTURE",
    "name_first": "JOHN",
    "name_middle": "MARSHALL",
    "payload_sha256": "sfabc456",
}

WI_PARTY = {
    "source_system": "wcca",
    "state_code": "WI",
    "source_record_id": "01:2099CF000099",
    "party_role": "defendant",
    "party_ordinal": 1,
    "raw_name": "FIXTURE, JANE Q",
    "name_last": "FIXTURE",
    "name_first": "JANE",
    "name_middle": "Q",
    "ingest_run_id": "synthetic-wi-ingest",
    "payload_sha256": "wiabc123",
}

HIRE_TOKENS = ("hire_flag", "no_hire", "risk_score", "adverse_action")


def _decision(
    *,
    decision_id: str,
    subject_ref: str,
    party: dict,
    review_status: str,
    confidence_band: str,
    decided_at: datetime,
    actor: str,
    subject_name: str = "Jane Q Public",
    experiment_tag: str | None = "sf_name_only_research",
    score: int = 70,
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
        "case_report_key": f"{src}|{state}|{record_id}",
        "review_status": review_status,
        "experiment_tag": experiment_tag,
        "notes": "synthetic fixture — not a live defendant",
        "decided_at": decided_at,
        "actor": actor,
    }


class LabelMappingTests(unittest.TestCase):
    def test_band_mapping(self) -> None:
        self.assertEqual(map_human_band_to_label("auto"), LABEL_LINK)
        self.assertEqual(map_human_band_to_label("no-link"), LABEL_REJECT)
        self.assertEqual(map_human_band_to_label("review"), LABEL_LEAVE)
        self.assertEqual(map_human_band_to_label("unexpected"), LABEL_LEAVE)

    def test_suggestions_never_become_eval_rows(self) -> None:
        suggestion = _decision(
            decision_id="s1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            actor="system:suggestion",
        )
        rows = build_name_match_eval([suggestion], now=NOW)
        self.assertEqual(rows, [])
        self.assertEqual(count_eval_labels(rows)["n_human"], 0)

    def test_human_auto_is_link_and_no_link_is_reject(self) -> None:
        link = _decision(
            decision_id="h1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="human",
            confidence_band="auto",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
        )
        reject = _decision(
            decision_id="h2",
            subject_ref="sub-sf",
            party=SF_MARSHALL,
            review_status="human",
            confidence_band="no-link",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
            subject_name="Jane Q Public",
        )
        leave = _decision(
            decision_id="h3",
            subject_ref="sub-other",
            party={**SF_PUBLIC, "source_record_id": "sf_case:fixture-3"},
            review_status="human",
            confidence_band="review",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
        )
        rows = build_name_match_eval([link, reject, leave], now=NOW)
        by_label = {r["label"]: r for r in rows}
        self.assertEqual(set(by_label), {LABEL_LINK, LABEL_REJECT, LABEL_LEAVE})
        self.assertEqual(by_label[LABEL_LINK]["eval_name"], EVAL_NAME)
        self.assertEqual(by_label[LABEL_LINK]["gold_schema_version"], EVAL_VERSION)
        counts = count_eval_labels(rows)
        self.assertEqual(counts["n_human"], 3)
        self.assertEqual(counts["n_gt"], 2)
        self.assertEqual(counts["n_leave_in_review"], 1)

    def test_later_human_wins_and_wi_is_excluded(self) -> None:
        early = _decision(
            decision_id="h0",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="human",
            confidence_band="review",
            decided_at=T_SUGGEST,
            actor="reviewer@example.com",
        )
        later = _decision(
            decision_id="h1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="human",
            confidence_band="auto",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
        )
        wi = _decision(
            decision_id="h-wi",
            subject_ref="sub-wi",
            party=WI_PARTY,
            review_status="human",
            confidence_band="auto",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
            subject_name="Jane Q Fixture",
        )
        rows = build_name_match_eval([early, later, wi], now=NOW)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], LABEL_LINK)
        self.assertEqual(rows[0]["decision_id"], "h1")
        self.assertEqual(rows[0]["source_system"], "sf_criminal_hf")


class LabelPackTests(unittest.TestCase):
    def test_open_queue_plus_hard_negative_empty_label(self) -> None:
        suggestion = _decision(
            decision_id="s1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            actor="system:suggestion",
        )
        queue = build_match_queue([suggestion], now=NOW)
        pack = build_name_match_label_pack(
            queue,
            [SF_PUBLIC, SF_MARSHALL, WI_PARTY],
            now=NOW,
            distractors_per_subject=1,
        )
        kinds = {row["pair_kind"] for row in pack}
        self.assertEqual(kinds, {PAIR_OPEN_QUEUE, PAIR_HARD_NEGATIVE})
        self.assertTrue(all(row["label"] is None for row in pack))
        self.assertTrue(all(row["experiment_tag"] == EVAL_NAME for row in pack))
        self.assertTrue(all(row["gold_schema_version"] == PACK_VERSION for row in pack))
        open_rows = [r for r in pack if r["pair_kind"] == PAIR_OPEN_QUEUE]
        negs = [r for r in pack if r["pair_kind"] == PAIR_HARD_NEGATIVE]
        self.assertEqual(len(open_rows), 1)
        self.assertEqual(len(negs), 1)
        self.assertEqual(negs[0]["name_last"], "FIXTURE")
        self.assertNotEqual(negs[0]["name_last"], open_rows[0]["name_last"])
        self.assertEqual(negs[0]["source_system"], "sf_criminal_hf")
        self.assertFalse(any(r["source_system"] == "wcca" for r in pack))

    def test_closed_human_card_is_not_packed(self) -> None:
        suggestion = _decision(
            decision_id="s1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            actor="system:suggestion",
        )
        human = _decision(
            decision_id="h1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="human",
            confidence_band="auto",
            decided_at=T_HUMAN,
            actor="reviewer@example.com",
        )
        queue = build_match_queue([suggestion, human], now=NOW)
        self.assertEqual(queue, [])
        pack = build_name_match_label_pack(queue, [SF_PUBLIC, SF_MARSHALL], now=NOW)
        self.assertEqual(pack, [])

    def test_does_not_invent_parties(self) -> None:
        suggestion = _decision(
            decision_id="s1",
            subject_ref="sub-sf",
            party=SF_PUBLIC,
            review_status="suggestion",
            confidence_band="review",
            decided_at=T_SUGGEST,
            actor="system:suggestion",
        )
        queue = build_match_queue([suggestion], now=NOW)
        pack = build_name_match_label_pack(queue, [SF_PUBLIC], now=NOW)
        self.assertEqual(len(pack), 1)
        self.assertEqual(pack[0]["pair_kind"], PAIR_OPEN_QUEUE)


class SqlContractTests(unittest.TestCase):
    def test_eval_sql_is_human_only_and_maps_labels(self) -> None:
        sql = EVAL_SQL.read_text(encoding="utf-8")
        self.assertIn("review_status = 'human'", sql)
        self.assertIn("sf_criminal_hf", sql)
        self.assertIn("THEN 'link'", sql)
        self.assertIn("THEN 'reject'", sql)
        self.assertIn("'leave_in_review'", sql)
        self.assertIn("sf_name_match_v1", sql)
        self.assertNotIn("CREATE OR REPLACE TEMP VIEW", sql)
        self.assertNotIn("CREATE TEMP VIEW", sql)
        self.assertNotIn("us_criminal_bg.bronze", sql)
        lowered = sql.lower()
        self.assertNotIn("insert into us_criminal_bg.silver", lowered)
        self.assertNotIn("merge into us_criminal_bg.silver", lowered)
        for token in HIRE_TOKENS:
            self.assertNotIn(token, lowered)

    def test_pack_sql_unlabeled_and_hard_negative(self) -> None:
        sql = PACK_SQL.read_text(encoding="utf-8")
        self.assertIn("us_criminal_bg.gold.match_queue", sql)
        self.assertIn("hard_negative", sql)
        self.assertIn("open_queue", sql)
        self.assertIn("CAST(NULL AS STRING) AS label", sql)
        self.assertIn("party_last_key <> s.subj_last_key", sql)
        self.assertIn("LEFT ANTI JOIN", sql)
        self.assertIn("xxhash64", sql)
        self.assertNotIn("CREATE OR REPLACE TEMP VIEW", sql)
        self.assertNotIn("CREATE TEMP VIEW", sql)
        self.assertNotIn("us_criminal_bg.bronze", sql)
        lowered = sql.lower()
        self.assertNotIn("insert into us_criminal_bg.silver", lowered)
        for token in HIRE_TOKENS:
            self.assertNotIn(token, lowered)

    def test_ddl_min_columns(self) -> None:
        ddl = EVAL_DDL.read_text(encoding="utf-8")
        for col in (
            "subject_ref",
            "party_key",
            "label",
            "source_system",
            "state_code",
            "labeled_at",
            "actor",
            "decision_id",
            "confidence_band",
            "experiment_tag",
        ):
            self.assertIn(col, ddl)
        pack = PACK_DDL.read_text(encoding="utf-8")
        self.assertIn("pair_kind", pack)
        self.assertIn("label STRING", pack)

    def test_sql_splits_without_temp_view(self) -> None:
        statements = split_sql_statements(EVAL_SQL.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(statements), 3)
        joined = "\n".join(statements)
        self.assertIn("CREATE OR REPLACE TABLE us_criminal_bg.gold.name_match_eval", joined)
        self.assertNotIn("TEMP VIEW", joined)

    def test_help_does_not_need_spark(self) -> None:
        out = subprocess.check_output(
            [sys.executable, str(PY_PATH), "--help"],
            text=True,
        )
        self.assertIn("name_match_eval", out)
        self.assertIn("label_pack", out)
        self.assertIn("hire", out.lower())


class DocsContractTests(unittest.TestCase):
    def test_mapping_doc_exists(self) -> None:
        doc = (ROOT / "docs" / "gold" / "NAME_MATCH_EVAL.md").read_text(encoding="utf-8")
        self.assertIn("leave_in_review", doc)
        self.assertIn("Suggestions are not ground truth", doc)
        self.assertIn("sf_name_match_v1", doc)
        self.assertIn("/review", doc)
        self.assertIn("0", doc)


if __name__ == "__main__":
    unittest.main()
