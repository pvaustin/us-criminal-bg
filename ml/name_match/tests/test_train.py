"""End-to-end synthetic train entry (no MLflow, no Spark, no live PII)."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ml.name_match.train import main, run_experiment


class TrainEntryTests(unittest.TestCase):
    def test_synthetic_no_mlflow_logs_baseline_and_logistic(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_experiment(
                from_silver=False,
                synthetic=True,
                warehouse_id=None,
                max_names=20,
                seed=7,
                experiment_name="us_criminal_bg_name_match",
                use_mlflow=False,
                skip_lightgbm=True,
                skip_model=False,
            )
        metrics = result["metrics"]
        self.assertIn("baseline_pr_auc", metrics)
        self.assertIn("baseline_precision_at_1", metrics)
        self.assertIn("baseline_review_band_pr_auc", metrics)
        self.assertIn("logistic_pr_auc", metrics)
        self.assertIn("logistic_recall_at_5", metrics)
        self.assertEqual(result["run_tag"], "sf_name_match_v1")
        self.assertEqual(result["experiment_name"], "us_criminal_bg_name_match")
        self.assertFalse(result["summary"]["uses_dob"])
        self.assertEqual(result["summary"]["n_human_labels_inventory"], 0)
        self.assertNotIn("lightgbm_pr_auc", metrics)
        text = buf.getvalue()
        self.assertIn("rule baseline", text)
        self.assertIn("logistic", text)
        self.assertNotIn("hire", text.lower())

    def test_cli_synthetic_exit_zero(self) -> None:
        code = main(["--synthetic", "--no-mlflow", "--skip-lightgbm"])
        self.assertEqual(code, 0)

    def test_help_mentions_experiment_and_not_cra(self) -> None:
        buf = io.StringIO()
        with self.assertRaises(SystemExit) as raised:
            with redirect_stdout(buf):
                main(["--help"])
        self.assertEqual(raised.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("us_criminal_bg_name_match", out)
        self.assertIn("hire", out.lower())
