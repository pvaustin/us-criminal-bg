"""SF name-match ranking (research). Pair scores only — not hire / risk / auto-link.

Wraps the MATCH_REVIEW rule baseline and trains a small scorer on weakly
supervised + synthetic pair labels built from SF `court_party` name strings.
Does not write `match_decision`, does not invent court cases, and does not
wire Uma.
"""

from ml.name_match.constants import (
    EXPERIMENT_NAME,
    FEATURE_NAMES,
    RUN_TAG,
    WORKSPACE_EXPERIMENT_PATH,
)

__all__ = [
    "EXPERIMENT_NAME",
    "FEATURE_NAMES",
    "RUN_TAG",
    "WORKSPACE_EXPERIMENT_PATH",
]
