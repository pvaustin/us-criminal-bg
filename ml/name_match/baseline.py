"""Rule baseline wrapping MATCH_REVIEW sketch scores (name-only, no DOB).

SF defendants never have DOB, so exact last+first lands at score 70 / `review`
and first-initial at 55 / `review`. `auto` is unreachable. This module does
not invent a second band system and does not emit hire / risk scores.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ml.name_match.constants import RULE_REVIEW_MIN
from silver.transforms.match_review_sketch import score_subject_against_party


@dataclass(frozen=True)
class RuleBaselineResult:
    score: int
    band: str
    reasons: tuple[str, ...]

    @property
    def rank_score(self) -> float:
        """Higher is better for ranking. Integer sketch score, not a probability."""
        return float(self.score)

    @property
    def in_review_band(self) -> bool:
        return self.band == "review"


def party_for_name_only_score(party: Mapping[str, Any]) -> dict[str, Any]:
    """Copy scoring fields and force DOB absent (SF name-only contract)."""
    return {
        "party_role": party.get("party_role") or "defendant",
        "party_ordinal": int(party.get("party_ordinal") or 1),
        "raw_name": party.get("raw_name") or party.get("party_raw_name") or "",
        "name_last": party.get("name_last") or party.get("party_name_last"),
        "name_first": party.get("name_first") or party.get("party_name_first"),
        "name_middle": party.get("name_middle") or party.get("party_name_middle"),
        "dob": None,
    }


def score_name_pair(
    subject_name: str,
    party: Mapping[str, Any],
) -> RuleBaselineResult:
    """Score one pair with the production sketch, ignoring DOB on both sides."""
    sketch = score_subject_against_party(
        {"name": subject_name},
        party_for_name_only_score(party),
    )
    return RuleBaselineResult(
        score=int(sketch.score),
        band=str(sketch.band),
        reasons=tuple(sketch.reasons),
    )


def rule_rank_scores(pairs: Sequence[Mapping[str, Any]]) -> list[float]:
    out: list[float] = []
    for pair in pairs:
        party = {
            "raw_name": pair.get("party_raw_name"),
            "name_last": pair.get("party_name_last"),
            "name_first": pair.get("party_name_first"),
            "name_middle": pair.get("party_name_middle"),
            "party_role": pair.get("party_role") or "defendant",
        }
        out.append(score_name_pair(str(pair.get("subject_name") or ""), party).rank_score)
    return out


def rule_review_mask(pairs: Sequence[Mapping[str, Any]]) -> list[bool]:
    mask: list[bool] = []
    for pair in pairs:
        party = {
            "raw_name": pair.get("party_raw_name"),
            "name_last": pair.get("party_name_last"),
            "name_first": pair.get("party_name_first"),
            "name_middle": pair.get("party_name_middle"),
            "party_role": pair.get("party_role") or "defendant",
        }
        result = score_name_pair(str(pair.get("subject_name") or ""), party)
        mask.append(result.score >= RULE_REVIEW_MIN or result.band == "review")
    return mask
