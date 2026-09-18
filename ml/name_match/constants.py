"""Stable names for the SF name-match ranking experiment.

Not a hire / no-hire signal. Not an auto-link product change.
"""

from __future__ import annotations

# Physical workspace experiment. Databricks workspace MLflow rejects bare
# names; `set_experiment` must use this absolute path. Coordinator may
# pre-create `/Shared/us_criminal_bg_name_match`.
EXPERIMENT_PATH = "/Shared/us_criminal_bg_name_match"
WORKSPACE_EXPERIMENT_PATH = EXPERIMENT_PATH
# Charlie's logical name — alias / tag only. Never pass this bare string to
# mlflow.set_experiment (workspace tracking returns INVALID_PARAMETER_VALUE).
LOGICAL_EXPERIMENT_NAME = "us_criminal_bg_name_match"
EXPERIMENT_ALIAS = LOGICAL_EXPERIMENT_NAME
# Back-compat: EXPERIMENT_NAME is the physical path used with set_experiment.
EXPERIMENT_NAME = EXPERIMENT_PATH
# Optional UC experiment if schema `us_criminal_bg.ml` exists (explicit override only):
#   us_criminal_bg.ml.us_criminal_bg_name_match
UC_EXPERIMENT_NAME = "us_criminal_bg.ml.us_criminal_bg_name_match"
UC_ML_SCHEMA = "us_criminal_bg.ml"


def resolve_experiment_path(name: str | None) -> str:
    """Map CLI / env names to a workspace-legal experiment path.

    Bare `us_criminal_bg_name_match` is Charlie's alias and is rewritten to
    `/Shared/us_criminal_bg_name_match`. Other relative names are rejected.
    """
    text = (name or "").strip()
    if not text or text in {
        LOGICAL_EXPERIMENT_NAME,
        EXPERIMENT_ALIAS,
        EXPERIMENT_PATH,
        WORKSPACE_EXPERIMENT_PATH,
    }:
        return EXPERIMENT_PATH
    if text.startswith("/"):
        return text
    # Unity Catalog experiment: catalog.schema.name
    if text.count(".") >= 2:
        return text
    raise ValueError(
        "Workspace MLflow requires an absolute experiment path; "
        f"got {text!r}. Use {EXPERIMENT_PATH} "
        f"(logical alias {LOGICAL_EXPERIMENT_NAME})."
    )

RUN_TAG = "sf_name_match_v1"
SOURCE_SYSTEM = "sf_criminal_hf"
STATE_CODE = "CA"
PARTY_TABLE = "us_criminal_bg.silver.court_party"
DECISION_TABLE = "us_criminal_bg.silver.match_decision"
SUGGESTION_EXPERIMENT_TAG = "sf_name_only_research"

ACTOR_SUGGESTION = "system:suggestion"
REVIEW_STATUS_SUGGESTION = "suggestion"
REVIEW_STATUS_HUMAN = "human"

# MATCH_REVIEW sketch integers on name-only SF parties (dob always absent).
RULE_EXACT_LAST_FIRST_SCORE = 70  # last 40 + first 30 → review
RULE_FIRST_INITIAL_SCORE = 55  # last 40 + initial 15 → review
RULE_REVIEW_MIN = 50

# Pair-level synthetic label kinds. Suggestions are never labels.
LABEL_SYNTHETIC_EXACT_POSITIVE = "synthetic_exact_positive"
LABEL_SYNTHETIC_NEAR_POSITIVE = "synthetic_near_positive"
LABEL_SYNTHETIC_NEAR_DUP_NEGATIVE = "synthetic_near_duplicate_negative"
LABEL_SYNTHETIC_HARD_NEGATIVE = "synthetic_hard_negative"
LABEL_HUMAN_LINK = "human_link"
LABEL_HUMAN_REJECT = "human_reject"

LABEL_SOURCE_SYNTHETIC = "synthetic_pair"
LABEL_SOURCE_HUMAN = "human_match_decision"

FEATURE_NAMES: tuple[str, ...] = (
    "exact_last",
    "exact_first",
    "first_initial_match",
    "exact_raw_norm",
    "token_jaccard",
    "token_overlap",
    "jw_raw",
    "jw_last",
    "jw_first",
    "soundex_last_match",
    "soundex_first_match",
    "subject_token_count",
    "party_token_count",
    "token_count_abs_diff",
    "subject_has_comma",
    "party_has_comma",
    "comma_vs_space",
    "last_char_len",
    "first_char_len",
    "both_have_middle",
)
