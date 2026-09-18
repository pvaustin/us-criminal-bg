"""Stable names for the SF name-match ranking experiment.

Not a hire / no-hire signal. Not an auto-link product change.
"""

from __future__ import annotations

# MLflow experiment *name*. On Databricks, create it as a workspace experiment
# under /Shared (parent already exists) unless a Unity Catalog experiment is used.
EXPERIMENT_NAME = "us_criminal_bg_name_match"
WORKSPACE_EXPERIMENT_PATH = "/Shared/us_criminal_bg_name_match"
# Optional UC experiment if schema `us_criminal_bg.ml` exists:
#   us_criminal_bg.ml.us_criminal_bg_name_match
UC_EXPERIMENT_NAME = "us_criminal_bg.ml.us_criminal_bg_name_match"
UC_ML_SCHEMA = "us_criminal_bg.ml"

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
