"""Design-sketch scorer for docs/silver/MATCH_REVIEW.md.

Not a Databricks job. Not a hire/FCRA decision. Synthetic names only.
Uma can call the same helpers in UI unit tests; warehouse matching is out of
scope for Silver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping

from sources.wcca.parse import split_person_name

MATCHABLE_ROLES = frozenset({"defendant", "aka"})
AUTO_MIN = 90
REVIEW_MIN = 50


@dataclass(frozen=True)
class MatchSketch:
    band: str
    score: int
    reasons: tuple[str, ...]
    party_role: str
    party_ordinal: int
    raw_name: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "band": self.band,
            "score": self.score,
            "reasons": list(self.reasons),
            "party_role": self.party_role,
            "party_ordinal": self.party_ordinal,
            "raw_name": self.raw_name,
        }


def _collapse(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(str(value).split())
    return collapsed or None


def _norm_token(value: str | None) -> str | None:
    collapsed = _collapse(value)
    if collapsed is None:
        return None
    chars = [ch for ch in collapsed.upper() if ch.isalnum()]
    return "".join(chars) or None


def _parse_dob(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _collapse(str(value))
    if text is None:
        return None
    for fmt, slen in (("%Y-%m-%d", 10), ("%m-%d-%Y", 10), ("%m/%d/%Y", 10)):
        chunk = text[:slen] if slen <= len(text) else text
        try:
            return datetime.strptime(chunk, fmt).date()
        except ValueError:
            continue
    return None


def parse_subject_name(
    name: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Employer subject names: `Last, First M` or `First [Middle] Last`."""
    collapsed = _collapse(name)
    if collapsed is None:
        return None, None, None
    last, first, middle = split_person_name(collapsed)
    if last is not None:
        return last, first, middle
    tokens = collapsed.split()
    if len(tokens) == 1:
        return tokens[0], None, None
    if len(tokens) == 2:
        return tokens[1], tokens[0], None
    return tokens[-1], tokens[0], " ".join(tokens[1:-1])


def _band_for(score: int, *, blocked: bool) -> str:
    if blocked or score < REVIEW_MIN:
        return "no-link"
    if score >= AUTO_MIN:
        return "auto"
    return "review"


def score_subject_against_party(
    subject: Mapping[str, Any],
    party: Mapping[str, Any],
) -> MatchSketch:
    """Score one employer subject against one court_party row.

    Signals: normalized last/first (or first initial) and optional DOB.
    Non-signals: race (not on the table), sex, address. Plaintiff is never
    matchable. A DOB conflict is always no-link.
    """
    role = str(party.get("party_role") or "")
    ordinal = int(party.get("party_ordinal") or 0)
    raw_name = _collapse(party.get("raw_name")) or ""
    reasons: list[str] = []
    blocked = False
    score = 0

    if role not in MATCHABLE_ROLES:
        return MatchSketch(
            band="no-link",
            score=0,
            reasons=("party_role_not_matchable",),
            party_role=role or "other",
            party_ordinal=ordinal,
            raw_name=raw_name,
        )

    subj_last, subj_first, _subj_middle = parse_subject_name(subject.get("name"))
    party_last = party.get("name_last") or split_person_name(raw_name)[0]
    party_first = party.get("name_first") or split_person_name(raw_name)[1]
    n_subj_last = _norm_token(subj_last)
    n_party_last = _norm_token(party_last)
    n_subj_first = _norm_token(subj_first)
    n_party_first = _norm_token(party_first)

    if not n_subj_last or not n_party_last:
        reasons.append("last_name_unparsed")
        blocked = True
    elif n_subj_last != n_party_last:
        reasons.append("last_name_mismatch")
        blocked = True
    else:
        score += 40
        reasons.append("last_name_match")

    if n_subj_first and n_party_first:
        if n_subj_first == n_party_first:
            score += 30
            reasons.append("first_name_match")
        elif n_subj_first[0] == n_party_first[0]:
            score += 15
            reasons.append("first_initial_match")
        else:
            reasons.append("first_name_mismatch")
    elif n_subj_first or n_party_first:
        reasons.append("first_name_unparsed")

    subj_dob = _parse_dob(subject.get("dob"))
    party_dob = _parse_dob(party.get("dob"))
    if subj_dob and party_dob:
        if subj_dob == party_dob:
            score += 30
            reasons.append("dob_match")
        else:
            reasons.append("dob_conflict")
            blocked = True
    elif subj_dob or party_dob:
        reasons.append("dob_unilateral")
    else:
        reasons.append("dob_absent")

    if role == "aka":
        reasons.append("aka_alias_row")

    band = _band_for(score, blocked=blocked)
    return MatchSketch(
        band=band,
        score=0 if blocked else score,
        reasons=tuple(reasons),
        party_role=role,
        party_ordinal=ordinal,
        raw_name=raw_name,
    )


def required_provenance(party: Mapping[str, Any], sketch: MatchSketch) -> dict[str, Any]:
    """Fields every review card must carry (no hire decision payload)."""
    return {
        "source_system": party.get("source_system"),
        "state_code": party.get("state_code"),
        "source_record_id": party.get("source_record_id"),
        "ingest_run_id": party.get("ingest_run_id"),
        "payload_sha256": party.get("payload_sha256"),
        "party_role": sketch.party_role,
        "party_ordinal": sketch.party_ordinal,
        "score": sketch.score,
        "band": sketch.band,
        "reasons": list(sketch.reasons),
    }
