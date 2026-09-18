"""Held-out human eval. Synthetic labels only — not live PII."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.constants import EXPERIMENT_PATH, EVAL_TABLE
from ml.name_match.train import HUMAN_EVAL_TAGS, main, run_human_eval

TRAIN_PY = ROOT / "ml" / "name_match" / "train.py"
EVAL_PY = ROOT / "ml" / "name_match" / "eval_human.py"


def _eval_row(
    *,
    subject_ref: str,
    label: str,
    band: str,
    subject_name: str,
    raw_name: str,
    name_last: str,
    name_first: str,
    decision_id: str,
) -> dict:
    return {
        "subject_ref": subject_ref,
        "party_key": f"sf_criminal_hf|CA|{subject_ref}|defendant|1",
        "label": label,
        "source_system": "sf_criminal_hf",
        "state_code": "CA",
        "actor": "reviewer@example.com",
        "decision_id": decision_id,
        "confidence_band": band,
        "subject_name": subject_name,
        "party_raw_name": raw_name,
        "raw_name": raw_name,
        "name_last": name_last,
        "name_first": name_first,
        "review_status": "human",
    }


class HumanEvalPathTests(unittest.TestCase):
    def test_n_zero_does_not_synthesize(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_human_eval(
                warehouse_id=None,
                seed=7,
                experiment_name=EXPERIMENT_PATH,
                use_mlflow=False,
                skip_lightgbm=True,
                skip_model=False,
                eval_rows=[],
            )
        self.assertEqual(result["summary"]["status"], "no_human_gt")
        self.assertEqual(result["summary"]["n_gt"], 0)
        self.assertFalse(result["synthesized"])
        self.assertEqual(result["metrics"], {})
        self.assertEqual(HUMAN_EVAL_TAGS["human_eval"], "true")
        self.assertEqual(HUMAN_EVAL_TAGS["sf_name_match_v1_human"], "true")
        text = buf.getvalue()
        self.assertIn("n_gt=0", text)
        self.assertIn("not synthesizing", text)

    def test_leave_in_review_excluded_and_suggestions_ignored(self) -> None:
        rows = [
            _eval_row(
                subject_ref="sub-leave",
                label="leave_in_review",
                band="review",
                subject_name="Jane Q Public",
                raw_name="JANE Q PUBLIC",
                name_last="PUBLIC",
                name_first="JANE",
                decision_id="h-leave",
            ),
            {
                "review_status": "suggestion",
                "actor": "system:suggestion",
                "label": "link",
                "subject_name": "Jane Q Public",
                "party_raw_name": "JANE Q PUBLIC",
                "confidence_band": "review",
                "subject_ref": "sub-sugg",
            },
            _eval_row(
                subject_ref="sub-link",
                label="link",
                band="auto",
                subject_name="Jane Q Public",
                raw_name="JANE Q PUBLIC",
                name_last="PUBLIC",
                name_first="JANE",
                decision_id="h-link",
            ),
            _eval_row(
                subject_ref="sub-rej",
                label="reject",
                band="no-link",
                subject_name="Jane Q Public",
                raw_name="JOHN MARSHALL FIXTURE",
                name_last="FIXTURE",
                name_first="JOHN",
                decision_id="h-rej",
            ),
        ]
        result = run_human_eval(
            warehouse_id=None,
            seed=7,
            experiment_name=EXPERIMENT_PATH,
            use_mlflow=False,
            skip_lightgbm=True,
            skip_model=False,
            eval_rows=rows,
        )
        self.assertEqual(result["summary"]["n_gt"], 2)
        self.assertEqual(result["summary"]["n_leave_in_review"], 1)
        self.assertEqual(result["summary"]["n_link"], 1)
        self.assertEqual(result["summary"]["n_reject"], 1)
        self.assertEqual(result["summary"]["status"], "n_too_small_rule_only")
        self.assertIn("baseline_pr_auc", result["metrics"])
        self.assertNotIn("logistic_pr_auc", result["metrics"])
        self.assertFalse(result["synthesized"])

    def test_cli_human_eval_no_spark_exit_zero(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(TRAIN_PY),
                "--human-eval",
                "--no-mlflow",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("n_gt=0", completed.stdout)
        self.assertIn("human_eval", completed.stdout)
        self.assertIn(EVAL_TABLE, completed.stdout)

    def test_eval_human_alias(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(EVAL_PY), "--no-mlflow"],
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0)
        self.assertIn("n_gt=0", completed.stdout)

    def test_help_mentions_human_eval(self) -> None:
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(buf):
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("--human-eval", out)
        self.assertIn("/Shared/us_criminal_bg_name_match", out)


if __name__ == "__main__":
    unittest.main()
