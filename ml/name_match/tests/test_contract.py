"""Hard rules: no hire/risk, no invented court rows, no Uma wiring, no DOB."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PKG = ROOT / "ml" / "name_match"


class ContractTests(unittest.TestCase):
    def _py_sources(self) -> str:
        chunks: list[str] = []
        for path in sorted(PKG.glob("*.py")):
            chunks.append(path.read_text(encoding="utf-8"))
        return "\n".join(chunks)

    def test_no_hire_or_risk_score_api(self) -> None:
        blob = self._py_sources()
        self.assertNotIn("hire_score", blob)
        self.assertNotIn("hire_flag", blob)
        self.assertNotIn("no_hire", blob)
        self.assertNotIn("risk_score", blob)
        self.assertNotIn("adverse_action", blob)

    def test_does_not_write_match_decision_or_court_tables(self) -> None:
        blob = self._py_sources()
        self.assertNotIn("INSERT INTO", blob)
        self.assertNotIn("MERGE INTO", blob)
        self.assertNotIn("court_charge", blob)
        self.assertNotIn("CREATE TABLE", blob)
        train = (PKG / "train.py").read_text(encoding="utf-8")
        self.assertIn("Does **not** write", train)
        self.assertNotIn("match_queue", train)

    def test_does_not_import_wcca_transforms(self) -> None:
        blob = self._py_sources()
        self.assertNotIn("from sources.wcca", blob)
        self.assertNotIn("court_case.py", blob)
        self.assertNotIn("map_court_case", blob)

    def test_readme_calls_out_label_scarcity_and_no_court_invention(self) -> None:
        readme = (PKG / "README.md").read_text(encoding="utf-8")
        self.assertIn("0", readme)
        self.assertIn("suggestion", readme.lower())
        self.assertIn("not", readme.lower())
        self.assertIn("invent", readme.lower())
        self.assertIn("hire", readme.lower())
        self.assertIn("/Shared/us_criminal_bg_name_match", readme)
        self.assertIn("us_criminal_bg.ml.us_criminal_bg_name_match", readme)
        self.assertIn("sf_name_match_v1", readme)
        self.assertIn("alias", readme.lower())
        self.assertIn("absolute path", readme.lower())
