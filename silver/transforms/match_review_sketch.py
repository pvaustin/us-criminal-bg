"""Design-sketch scorer for docs/silver/MATCH_REVIEW.md.

Not silent auto-link. Not a hire/FCRA decision. Synthetic names only.
Uma can call the same helpers in UI unit tests. SF research jobs wrap these
bands; they must not invent a parallel auto/review/no-link system.

The Databricks scoring job for SF name-only experiments lives in
`match_decision_sf_research.py` / `.sql` and only INSERTs suggestion rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4

from sources.wcca.parse import split_person_name

MATCHABLE_ROLES = frozenset({"defendant", "aka"})
REVIEW_MIN = 50
ACTOR_SUGGESTION = "system:suggestion"
REVIEW_STATUS_SUGGESTION = "suggestion"
REVIEW_STATUS_HUMAN = "human"
PERSIST_BANDS_DEFAULT = frozenset({"auto", "review"})

# Stable Uma query/API contract (flat match_decision row = one candidate card).
# Nested `candidates[]` is a query grouping by subject_ref, not a table column.
UMA_CONTRACT_FIELDS = (
    "subject_ref",
    "subject_name",
    "subject_dob",
    "party_key",
    "party_role",
    "party_ordinal",
    "raw_name",
    "name_last",
    "name_first",
    "name_middle",
    "confidence_band",
    "score",
    "reasons",
    "source_system",
    "state_code",
    "source_record_id",
    "ingest_run_id",
    "payload_sha256",
    "transform_run_id",
    "case_report_key",
    "decision_id",
    "decided_at",
    "actor",
    "review_status",
)


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
    """Employer / search subject names: `Last, First M` or `First [Middle] Last`.

    First-Last (space-separated) is required for SF HF research subjects; the
    comma form is the WI WCCA caption style. Unparseable last → no-link.
    """
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


def norm_name_token(value: str | None) -> str | None:
    """Alphanumeric upper token used for last-name retrieval and scoring."""
    return _norm_token(value)


def normalized_last_name_from_subject(subject: Mapping[str, Any]) -> str | None:
    name = subject.get("name")
    if name is None:
        name = subject.get("subject_name")
    last, _first, _middle = parse_subject_name(name)
    return _norm_token(last)


def normalized_last_name_from_party(party: Mapping[str, Any]) -> str | None:
    """Prefer Silver `name_last`; fall back to comma split then First-Last raw."""
    last = _norm_token(party.get("name_last"))
    if last:
        return last
    raw = _collapse(party.get("raw_name"))
    comma_last = _norm_token(split_person_name(raw)[0])
    if comma_last:
        return comma_last
    space_last, _first, _middle = parse_subject_name(raw)
    return _norm_token(space_last)


def retrieve_candidates_by_last_name(
    subject: Mapping[str, Any],
    parties: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Last-name equality (normalized) only — never a full cartesian product."""
    key = normalized_last_name_from_subject(subject)
    if not key:
        return []
    return [p for p in parties if normalized_last_name_from_party(p) == key]


def party_key(party: Mapping[str, Any], *, role: str = "", ordinal: int = 0) -> str:
    """`source_system|state_code|source_record_id|party_role|party_ordinal`."""
    return "|".join(
        [
            str(party.get("source_system") or ""),
            str(party.get("state_code") or ""),
            str(party.get("source_record_id") or ""),
            str(party.get("party_role") or role or ""),
            str(party.get("party_ordinal") if party.get("party_ordinal") is not None else ordinal),
        ]
    )


def case_report_key(party: Mapping[str, Any]) -> str:
    """Existing court_case natural key — no new report grain."""
    return "|".join(
        [
            str(party.get("source_system") or ""),
            str(party.get("state_code") or ""),
            str(party.get("source_record_id") or ""),
        ]
    )


def _exact_name_match(
    *,
    n_subj_last: str | None,
    n_party_last: str | None,
    n_subj_first: str | None,
    n_party_first: str | None,
    n_subj_raw: str | None,
    n_party_raw: str | None,
) -> bool:
    last_first = bool(
        n_subj_last
        and n_party_last
        and n_subj_last == n_party_last
        and n_subj_first
        and n_party_first
        and n_subj_first == n_party_first
    )
    raw = bool(n_subj_raw and n_party_raw and n_subj_raw == n_party_raw)
    return last_first or raw


def score_subject_against_party(
    subject: Mapping[str, Any],
    party: Mapping[str, Any],
) -> MatchSketch:
    """Score one employer subject against one court_party row.

    MVP: no silent auto-link. `auto` only when exact last+first (or exact
    raw_name) and both DOBs present and equal — suggestion only.
    Missing DOB → `dob_absent` → review; never invent a date.
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
    n_subj_raw = _norm_token(_collapse(subject.get("name")))
    n_party_raw = _norm_token(raw_name)

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

    if n_subj_raw and n_party_raw and n_subj_raw == n_party_raw:
        reasons.append("raw_name_match")

    subj_dob = _parse_dob(subject.get("dob"))
    party_dob = _parse_dob(party.get("dob"))
    if subj_dob and party_dob:
        if subj_dob == party_dob:
            score += 30
            reasons.append("dob_match")
        else:
            reasons.append("dob_conflict")
            blocked = True
    else:
        reasons.append("dob_absent")

    if role == "aka":
        reasons.append("aka_alias_row")

    exact_name = _exact_name_match(
        n_subj_last=n_subj_last,
        n_party_last=n_party_last,
        n_subj_first=n_subj_first,
        n_party_first=n_party_first,
        n_subj_raw=n_subj_raw,
        n_party_raw=n_party_raw,
    )
    if blocked:
        band = "no-link"
    elif exact_name and "dob_match" in reasons:
        band = "auto"
    elif score >= REVIEW_MIN:
        band = "review"
    else:
        band = "no-link"

    return MatchSketch(
        band=band,
        score=0 if blocked else score,
        reasons=tuple(reasons),
        party_role=role,
        party_ordinal=ordinal,
        raw_name=raw_name,
    )


def required_provenance(party: Mapping[str, Any], sketch: MatchSketch) -> dict[str, Any]:
    """Minimum review-queue field contract (no hire decision payload)."""
    role = sketch.party_role
    ordinal = sketch.party_ordinal
    return {
        "party_key": party_key(party, role=role, ordinal=ordinal),
        "party_role": role,
        "party_ordinal": ordinal,
        "raw_name": sketch.raw_name,
        "name_last": party.get("name_last"),
        "name_first": party.get("name_first"),
        "name_middle": party.get("name_middle"),
        "confidence_band": sketch.band,
        "score_or_reason_codes": [str(sketch.score), *sketch.reasons],
        "source_system": party.get("source_system"),
        "state_code": party.get("state_code"),
        "source_record_id": party.get("source_record_id"),
        "ingest_run_id": party.get("ingest_run_id"),
        "payload_sha256": party.get("payload_sha256"),
        "transform_run_id": party.get("transform_run_id"),
        "case_report_key": case_report_key(party),
        "score": sketch.score,
        "band": sketch.band,
        "reasons": list(sketch.reasons),
    }


def _subject_name(subject: Mapping[str, Any]) -> str | None:
    name = subject.get("name")
    if name is None:
        name = subject.get("subject_name")
    return _collapse(name)


def _subject_dob(subject: Mapping[str, Any]) -> date | None:
    if "dob" in subject:
        return _parse_dob(subject.get("dob"))
    return _parse_dob(subject.get("subject_dob"))


def match_decision_row(
    subject: Mapping[str, Any],
    party: Mapping[str, Any],
    sketch: MatchSketch,
    *,
    decision_id: str | None = None,
    decided_at: datetime | None = None,
    actor: str = ACTOR_SUGGESTION,
    review_status: str = REVIEW_STATUS_SUGGESTION,
    experiment_tag: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Flat append row for `us_criminal_bg.silver.match_decision`.

    Suggestion-only when `actor=system:suggestion`. Never a hire / FCRA payload.
    """
    prov = required_provenance(party, sketch)
    ts = decided_at or datetime.now(timezone.utc)
    return {
        "decision_id": decision_id or str(uuid4()),
        "subject_ref": str(subject.get("subject_ref") or ""),
        "subject_name": _subject_name(subject),
        "subject_dob": _subject_dob(subject),
        "party_key": prov["party_key"],
        "source_system": prov["source_system"],
        "state_code": prov["state_code"],
        "source_record_id": prov["source_record_id"],
        "party_role": prov["party_role"],
        "party_ordinal": prov["party_ordinal"],
        "raw_name": prov["raw_name"],
        "name_last": prov["name_last"],
        "name_first": prov["name_first"],
        "name_middle": prov["name_middle"],
        "confidence_band": sketch.band,
        "score": sketch.score,
        "reasons": list(sketch.reasons),
        "score_or_reason_codes": list(prov["score_or_reason_codes"]),
        "ingest_run_id": prov["ingest_run_id"],
        "payload_sha256": prov["payload_sha256"],
        "transform_run_id": prov["transform_run_id"],
        "case_report_key": prov["case_report_key"],
        "review_status": review_status,
        "experiment_tag": experiment_tag,
        "notes": notes,
        "decided_at": ts,
        "actor": actor,
    }


def suggestion_rows_for_subject(
    subject: Mapping[str, Any],
    parties: Sequence[Mapping[str, Any]],
    *,
    persist_bands: Iterable[str] = PERSIST_BANDS_DEFAULT,
    persist_no_link: bool = False,
    actor: str = ACTOR_SUGGESTION,
    review_status: str = REVIEW_STATUS_SUGGESTION,
    experiment_tag: str | None = None,
    notes: str | None = None,
    decided_at: datetime | None = None,
) -> list[dict[str, Any]]:
    """Retrieve by last name, score with MATCH_REVIEW bands, build append rows.

    Default persists `review` and `auto` only. Last-name mismatches are not
    retrieved (no cartesian). Optional `persist_no_link` keeps last-name-equal
    negatives (e.g. first-name mismatch) for warehouse prove.
    """
    allowed = frozenset(persist_bands)
    ts = decided_at or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for party in retrieve_candidates_by_last_name(subject, parties):
        sketch = score_subject_against_party(subject, party)
        if sketch.band == "no-link":
            if not persist_no_link:
                continue
        elif sketch.band not in allowed:
            continue
        rows.append(
            match_decision_row(
                subject,
                party,
                sketch,
                decided_at=ts,
                actor=actor,
                review_status=review_status,
                experiment_tag=experiment_tag,
                notes=notes,
            )
        )
    return rows
