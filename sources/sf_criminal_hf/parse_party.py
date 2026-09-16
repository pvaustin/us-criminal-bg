"""Parse SF HF Bronze JSON payloads into silver.court_party defendant rows.

Research-only. Consumes already-landed Bronze `payload_format=json` rows.
Never scrapes. Never invents names, DOB, sex, address, plaintiffs, or AKAs.

Synthetic fixtures in tests are labeled as such and must not be treated as
real court records. See docs/silver/SF_RESEARCH.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping

from sources.sf_criminal_hf.map import SOURCE_SYSTEM, STATE_CODE

SILVER_PARTY_SCHEMA_VERSION = "silver.court_party.v1"
PAYLOAD_PARSE_STATUS = "json_cases_v1"
PARTY_ROLE_DEFENDANT = "defendant"

# Last, First[ Middle…] when a comma is present. Same idea as WCCA comma form;
# this module does not import the WCCA parser (WI path stays untouched).
_PERSON_LAST_FIRST_RE = re.compile(
    r"^([A-Za-z][A-Za-z.'\- ]*?),\s*([A-Za-z][A-Za-z.'-]*)(?:\s+([A-Za-z][A-Za-z.'\- ]*))?$"
)
_SPACES_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PartyRow:
    party_role: str
    party_ordinal: int
    raw_name: str
    name_last: str | None = None
    name_first: str | None = None
    name_middle: str | None = None
    dob: date | None = None
    sex: str | None = None
    address_raw: str | None = None
    payload_parse_status: str = PAYLOAD_PARSE_STATUS
    dq_flags: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "party_role": self.party_role,
            "party_ordinal": self.party_ordinal,
            "raw_name": self.raw_name,
            "name_last": self.name_last,
            "name_first": self.name_first,
            "name_middle": self.name_middle,
            "dob": self.dob,
            "sex": self.sex,
            "address_raw": self.address_raw,
            "payload_parse_status": self.payload_parse_status,
            "dq_flags": list(self.dq_flags),
        }


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _collapse_ws(value: Any) -> str | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None
    collapsed = _SPACES_RE.sub(" ", raw).strip()
    return collapsed or None


def _payload_obj(payload: Any) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, (bytes, bytearray)):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if not isinstance(payload, str):
        return None
    text = payload.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _defendant_name_from_obj(obj: Mapping[str, Any]) -> str | None:
    value = obj.get("defendant_name")
    if value is None:
        lower = {str(k).lower(): v for k, v in obj.items()}
        value = lower.get("defendant_name")
    if not isinstance(value, str):
        return None
    return _collapse_ws(value)


def split_sf_person_name(
    raw_name: str | None,
) -> tuple[str | None, str | None, str | None, bool]:
    """Split a defendant raw_name into (last, first, middle, ambiguous).

    Rules (research corpus; flag First-Last heuristics liberally):
    - Comma present → `Last, First[ Middle…]` only. Unreliable comma → null
      parts + ambiguous. Do not fall back to space tokens (would invent order).
    - No comma, 2+ space tokens → first=first token, last=last token,
      middle=joined inner tokens (or null). 4+ tokens → still fill, ambiguous.
    - Single token → null parts + ambiguous. Do not invent a comma form.
    """
    collapsed = _collapse_ws(raw_name)
    if collapsed is None:
        return None, None, None, False
    if "," in collapsed:
        match = _PERSON_LAST_FIRST_RE.match(collapsed)
        if not match:
            return None, None, None, True
        last = _collapse_ws(match.group(1))
        first = _collapse_ws(match.group(2))
        middle = _collapse_ws(match.group(3))
        if last is None or first is None:
            return None, None, None, True
        if len(last.split()) > 4:
            return None, None, None, True
        return last, first, middle, False

    tokens = collapsed.split(" ")
    if len(tokens) == 1:
        return None, None, None, True
    first = tokens[0]
    last = tokens[-1]
    middle_tokens = tokens[1:-1]
    middle = " ".join(middle_tokens) if middle_tokens else None
    ambiguous = len(tokens) >= 4
    return last, first, middle, ambiguous


def _build_defendant(raw_name: str) -> PartyRow:
    last, first, middle, ambiguous = split_sf_person_name(raw_name)
    flags = ["missing_dob"]
    if ambiguous:
        flags.append("ambiguous_name_parts")
    if last is None and first is None:
        flags.append("name_unparsed")
        if "ambiguous_name_parts" not in flags:
            flags.append("ambiguous_name_parts")
    return PartyRow(
        party_role=PARTY_ROLE_DEFENDANT,
        party_ordinal=1,
        raw_name=raw_name,
        name_last=last,
        name_first=first,
        name_middle=middle,
        dob=None,
        sex=None,
        address_raw=None,
        payload_parse_status=PAYLOAD_PARSE_STATUS,
        dq_flags=tuple(sorted(set(flags))),
    )


def parse_parties_from_payload(payload: Any) -> tuple[PartyRow, ...]:
    """One defendant row when `defendant_name` is nonempty after trim; else empty.

    Does not invent a party for blank / missing / non-string names.
    DOB, sex, address, plaintiff, aka, and charges are never filled from this
    corpus (those fields are not in cases.parquet).
    """
    obj = _payload_obj(payload)
    if obj is None:
        return ()
    raw_name = _defendant_name_from_obj(obj)
    if raw_name is None:
        return ()
    return (_build_defendant(raw_name),)


def parse_sf_criminal_hf_bronze_row(
    *,
    source_system: str | None,
    payload: Any = None,
) -> tuple[PartyRow, ...]:
    """Parse parties for one Bronze row. Empty when source is not sf_criminal_hf."""
    if (source_system or "").strip() != SOURCE_SYSTEM:
        return ()
    return parse_parties_from_payload(payload)


__all__ = (
    "PAYLOAD_PARSE_STATUS",
    "PARTY_ROLE_DEFENDANT",
    "PartyRow",
    "SILVER_PARTY_SCHEMA_VERSION",
    "SOURCE_SYSTEM",
    "STATE_CODE",
    "parse_parties_from_payload",
    "parse_sf_criminal_hf_bronze_row",
    "split_sf_person_name",
)
