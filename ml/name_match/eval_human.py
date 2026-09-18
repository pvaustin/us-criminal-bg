#!/usr/bin/env python3
"""Alias for `python3 ml/name_match/train.py --human-eval`."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ml.name_match.train import main

if __name__ == "__main__":
    extra = [arg for arg in sys.argv[1:] if arg != "--human-eval"]
    raise SystemExit(main(["--human-eval", *extra]))
