"""Name-pair features for SF name-only ranking.

No DOB. No hire / risk score. Token, Jaro-Winkler, and Soundex-style signals
plus the exact last / first / first-initial bits used by the rule baseline.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ml.name_match.constants import FEATURE_NAMES
from silver.transforms.match_review_sketch import (
    norm_name_token,
    parse_subject_name,
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

_SOUNDEX_MAP = {}
for _letters, _digit in (
    ("BFPV", "1"),
    ("CGJKQSXZ", "2"),
    ("DT", "3"),
    ("L", "4"),
    ("MN", "5"),
    ("R", "6"),
):
    for _ch in _letters:
        _SOUNDEX_MAP[_ch] = _digit


def collapse_ws(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def name_tokens(value: str | None) -> tuple[str, ...]:
    collapsed = collapse_ws(value)
    if not collapsed:
        return ()
    return tuple(tok.upper() for tok in _TOKEN_RE.findall(collapsed))


def has_comma(value: str | None) -> bool:
    return "," in (value or "")


def jaro_similarity(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    return (
        matches / len1
        + matches / len2
        + (matches - transpositions / 2.0) / matches
    ) / 3.0


def jaro_winkler(s1: str, s2: str, *, p: float = 0.1, max_l: int = 4) -> float:
    a = collapse_ws(s1).upper()
    b = collapse_ws(s2).upper()
    j = jaro_similarity(a, b)
    prefix = 0
    for ca, cb in zip(a, b):
        if ca != cb or prefix >= max_l:
            break
        prefix += 1
    return j + prefix * p * (1.0 - j)


def soundex(value: str | None) -> str:
    """US-census-style Soundex. Empty input → empty code (not a person id)."""
    letters = [c for c in collapse_ws(value).upper() if c.isalpha()]
    if not letters:
        return ""
    first = letters[0]
    out = [first]
    prev = _SOUNDEX_MAP.get(first, "0")
    for ch in letters[1:]:
        code = _SOUNDEX_MAP.get(ch, "0")
        if code != "0" and code != prev:
            out.append(code)
            if len(out) == 4:
                break
        if ch in "AEIOUY":
            prev = "0"
        elif code != "0":
            prev = code
        # H/W keep prev so adjacent same-coded consonants collapse.
    return "".join(out).ljust(4, "0")[:4]


def token_jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def token_overlap(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def parse_party_parts(party: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    last = party.get("name_last")
    first = party.get("name_first")
    middle = party.get("name_middle")
    if last or first:
        return (
            collapse_ws(last) or None,
            collapse_ws(first) or None,
            collapse_ws(middle) or None,
        )
    return parse_subject_name(party.get("raw_name"))


def pair_feature_dict(
    subject_name: str,
    party: Mapping[str, Any],
) -> dict[str, float]:
    """Dense features for one subject-name × party-name pair. Never uses DOB."""
    subj_last, subj_first, subj_middle = parse_subject_name(subject_name)
    party_last, party_first, party_middle = parse_party_parts(party)
    raw_party = collapse_ws(party.get("raw_name"))
    n_subj_last = norm_name_token(subj_last)
    n_party_last = norm_name_token(party_last)
    n_subj_first = norm_name_token(subj_first)
    n_party_first = norm_name_token(party_first)
    n_subj_raw = norm_name_token(subject_name)
    n_party_raw = norm_name_token(raw_party)
    subj_tokens = name_tokens(subject_name)
    party_tokens = name_tokens(raw_party)
    exact_last = float(bool(n_subj_last and n_party_last and n_subj_last == n_party_last))
    exact_first = float(
        bool(n_subj_first and n_party_first and n_subj_first == n_party_first)
    )
    first_initial = 0.0
    if n_subj_first and n_party_first:
        first_initial = float(n_subj_first[0] == n_party_first[0])
    subj_comma = float(has_comma(subject_name))
    party_comma = float(has_comma(raw_party))
    sx_last_s = soundex(n_subj_last)
    sx_last_p = soundex(n_party_last)
    sx_first_s = soundex(n_subj_first)
    sx_first_p = soundex(n_party_first)
    return {
        "exact_last": exact_last,
        "exact_first": exact_first,
        "first_initial_match": first_initial,
        "exact_raw_norm": float(
            bool(n_subj_raw and n_party_raw and n_subj_raw == n_party_raw)
        ),
        "token_jaccard": token_jaccard(subj_tokens, party_tokens),
        "token_overlap": token_overlap(subj_tokens, party_tokens),
        "jw_raw": jaro_winkler(subject_name, raw_party),
        "jw_last": jaro_winkler(n_subj_last or "", n_party_last or ""),
        "jw_first": jaro_winkler(n_subj_first or "", n_party_first or ""),
        "soundex_last_match": float(bool(sx_last_s and sx_last_p and sx_last_s == sx_last_p)),
        "soundex_first_match": float(
            bool(sx_first_s and sx_first_p and sx_first_s == sx_first_p)
        ),
        "subject_token_count": float(len(subj_tokens)),
        "party_token_count": float(len(party_tokens)),
        "token_count_abs_diff": float(abs(len(subj_tokens) - len(party_tokens))),
        "subject_has_comma": subj_comma,
        "party_has_comma": party_comma,
        "comma_vs_space": float(subj_comma != party_comma),
        "last_char_len": float(len(n_subj_last or "")),
        "first_char_len": float(len(n_subj_first or "")),
        "both_have_middle": float(bool(subj_middle and party_middle)),
    }


def pair_feature_vector(
    subject_name: str,
    party: Mapping[str, Any],
) -> list[float]:
    feats = pair_feature_dict(subject_name, party)
    return [float(feats[name]) for name in FEATURE_NAMES]


def matrix_from_pairs(pairs: Sequence[Mapping[str, Any]]) -> list[list[float]]:
    rows: list[list[float]] = []
    for pair in pairs:
        party = {
            "raw_name": pair.get("party_raw_name"),
            "name_last": pair.get("party_name_last"),
            "name_first": pair.get("party_name_first"),
            "name_middle": pair.get("party_name_middle"),
        }
        rows.append(pair_feature_vector(str(pair.get("subject_name") or ""), party))
    return rows
