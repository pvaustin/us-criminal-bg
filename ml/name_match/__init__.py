"""SF name-match ranking (research). Pair scores only — not hire / risk / auto-link.

Wraps the MATCH_REVIEW rule baseline and trains a small scorer on weakly
supervised + synthetic pair labels built from SF `court_party` name strings.
Does not write `match_decision`, does not invent court cases, and does not
wire Uma. Human GT is `gold.name_match_eval` (`train.py --human-eval`).
"""

from ml.name_match.constants import (
    EXPERIMENT_ALIAS,
    EXPERIMENT_NAME,
    EXPERIMENT_PATH,
    FEATURE_NAMES,
    LOGICAL_EXPERIMENT_NAME,
    RUN_TAG,
    WORKSPACE_EXPERIMENT_PATH,
    resolve_experiment_path,
)

__all__ = [
    "EXPERIMENT_ALIAS",
    "EXPERIMENT_NAME",
    "EXPERIMENT_PATH",
    "FEATURE_NAMES",
    "LOGICAL_EXPERIMENT_NAME",
    "RUN_TAG",
    "WORKSPACE_EXPERIMENT_PATH",
    "resolve_experiment_path",
]
