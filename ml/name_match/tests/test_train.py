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

from ml.name_match.constants import (
    EXPERIMENT_PATH,
    LOGICAL_EXPERIMENT_NAME,
    resolve_experiment_path,
)
from ml.name_match.train import main, run_experiment


class ExperimentPathTests(unittest.TestCase):
    def test_alias_rewrites_to_shared_path(self) -> None:
        self.assertEqual(EXPERIMENT_PATH, "/Shared/us_criminal_bg_name_match")
        self.assertEqual(LOGICAL_EXPERIMENT_NAME, "us_criminal_bg_name_match")
        self.assertEqual(resolve_experiment_path(None), EXPERIMENT_PATH)
        self.assertEqual(resolve_experiment_path(""), EXPERIMENT_PATH)
        self.assertEqual(
            resolve_experiment_path("us_criminal_bg_name_match"),
            EXPERIMENT_PATH,
        )
        self.assertEqual(resolve_experiment_path(EXPERIMENT_PATH), EXPERIMENT_PATH)

    def test_other_bare_names_are_rejected(self) -> None:
        with self.assertRaises(ValueError) as raised:
            resolve_experiment_path("relative_experiment")
        self.assertIn("absolute", str(raised.exception).lower())

    def test_train_never_falls_back_to_bare_set_experiment(self) -> None:
        src = (ROOT / "ml" / "name_match" / "train.py").read_text(encoding="utf-8")
        self.assertIn("resolve_experiment_path", src)
        self.assertNotIn("WORKSPACE_EXPERIMENT_PATH,\n        EXPERIMENT_NAME", src)
        self.assertIn('mlflow.set_experiment(path)', src)


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
        self.assertEqual(result["experiment_name"], "/Shared/us_criminal_bg_name_match")
        self.assertEqual(result["experiment_alias"], "us_criminal_bg_name_match")
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
        self.assertIn("/Shared/us_criminal_bg_name_match", out)
        self.assertIn("us_criminal_bg_name_match", out)
        self.assertIn("hire", out.lower())
