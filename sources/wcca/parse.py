"""WCCA identifier / URL / HTML SSR / conservative JSON payload parser.

Never scrapes. Never invents case facts. Synthetic fixtures in tests are
labeled as such and must not be treated as real court records.

Identifier contract (see docs/silver/NAMING.md):
- source_record_id countyNo:caseNo (live Bronze sample) or WI|wcca|{county}|{case_number}
- URL query params countyNo / caseNo are preferred when they disagree with the id

HTML snapshots: live WCCA detail pages store server-rendered plain text (not an
empty SPA shell and not a __NEXT_DATA__ case blob). After scripts/styles/tags
are stripped, deterministic regex extracts caption, filing date, case status,
county name, charges, and parties (plaintiff / defendant / aka). Race is not a
Silver party column. See docs/silver/WCCA_HTML_SSR.md.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

SOURCE_SYSTEM = "wcca"
STATE_CODE = "WI"
SILVER_SCHEMA_VERSION = "silver.court_case.v2"
SILVER_CHARGE_SCHEMA_VERSION = "silver.court_charge.v1"
SILVER_PARTY_SCHEMA_VERSION = "silver.court_party.v1"

PARTY_ROLES = ("defendant", "plaintiff", "aka", "other")
ORG_PLAINTIFF_RE = re.compile(r"(?i)^state of wisconsin$")

# CCAP case numbers: year + 2-letter type + 6-digit sequence, e.g. 2026CF000028
CASE_NUMBER_RE = re.compile(r"^(\d{4})([A-Z]{2})(\d{6})$", re.IGNORECASE)
COLON_ID_RE = re.compile(r"^(\d+)\s*:\s*(.+)$")
COMPOSED_ID_RE = re.compile(
    r"^[A-Za-z]{2}\|[^|]+\|([^|]+)\|([^|]+)$"
)

SCRIPT_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
PRELOAD_RE = re.compile(
    r"(?:window\.)?(?:__PRELOADED_STATE__|__INITIAL_STATE__|__NEXT_DATA__)\s*=\s*(\{.*?\})\s*;",
    re.DOTALL,
)

FILED_DATE_KEYS = ("fileddate", "filingdate", "datefiled")
CAPTION_KEYS = ("caption", "casecaption")

_SCRIPT_STYLE_RE = re.compile(
    r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>"
)
_BLOCK_TO_NL_RE = re.compile(
    r"(?i)<br\s*/?>|</(?:p|div|tr|td|th|h[1-6]|li|table|thead|tbody|section|header|"
    r"article|blockquote|ul|ol)>|</title>"
)
# Letter-named tags only. A bare `<[^>]+>` can close on a `>` inside a charge
# description (e.g. `>10-50g` from `&gt;`) when an earlier `<` is unclosed.
_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*[^>]*>")
_COMMENT_RE = re.compile(r"(?is)<!--.*?-->")
_ENTITY_GT_RE = re.compile(r"(?i)&gt;|&#62;|&#x3e;")
_ENTITY_LT_RE = re.compile(r"(?i)&lt;|&#60;|&#x3c;")
_GT_SENTINEL = "\u27e9"
_LT_SENTINEL = "\u27e8"
_SPACES_RE = re.compile(r"[ \t\f\v]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")

HTML_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
TITLE_COUNTY_RE = re.compile(
    r"(\d{4}[A-Za-z]{2}\d{6})\s+Case Details in\s+(.+?)\s+County\b",
    re.IGNORECASE,
)
# Stop before the next SSR heading. "Case summary" is a following section on
# live WCCA snapshots; without it the caption swallows that heading.
CAPTION_RE = re.compile(
    r"(State of Wisconsin\s+vs\.?\s+.+?)(?="
    r"\s+Case summary\b|\s+Filing date\b|\s+Case type\b|\s+Case status\b|"
    r"\s+Defendant\b|\s+Charges\b|\s+Count no\.|\s+Branch\b|\s+DA case\b|\n|$)",
    re.IGNORECASE,
)
FILED_DATE_RE = re.compile(
    r"Filing date\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.IGNORECASE,
)
CASE_STATUS_RE = re.compile(
    r"Case status\s*:?\s*(.+?)(?="
    r"\s+Defendant\b|\s+Date of birth\b|\s+Address\b|\s+Sex\b|\s+Race\b|"
    r"\s+Charges\b|\s+Count no\.|\s+Filing date\b|\s+Case type\b|"
    r"\s+Branch\b|\s+Responsible\b|\s+Prosecuting\b|\s+Defense\b|\n|$)",
    re.IGNORECASE,
)
CHARGE_HEADER_RE = re.compile(
    r"Count\s+no\.?\s+Statute\s+Description\s+Severity(?:\s+Disposition)?",
    re.IGNORECASE,
)
CHARGE_SECTION_STOP_RE = re.compile(
    r"\b(?:Court records?|Warrants?|Judgments?|Civil judgments?|"
    r"Restitution|Receivables|This is not the official)\b",
    re.IGNORECASE,
)

# WI statute tokens as they appear in the charges grid, e.g. 946.41(1), 961.41(3g)(e)
STATUTE_RE = r"\d{3}\.\d{2,4}(?:\([^)]+\))*"
SEVERITY_RE = (
    r"(?:Felony|Misdemeanor|Misd\.?|Forfeiture|Ordinance)"
    r"(?:\s+[A-Z0-9]{1,3})?"
)
# Split on count+statute so descriptions may contain `>` / `<` / `&gt;`
# (a single `.+?` row regex missed count 1 on live SQL apply).
CHARGE_START_RE = re.compile(
    rf"(?:^|(?<=\s))(?P<count>\d+)\s+(?P<statute>{STATUTE_RE})(?=\s|>|<|$)",
    re.IGNORECASE,
)
CHARGE_ROW_RE = re.compile(
    rf"(?P<count>\d+)\s+(?P<statute>{STATUTE_RE})\s+"
    rf"(?P<description>.+?)\s+(?P<severity>{SEVERITY_RE})"
    rf"(?:\s+(?!Modifier:)(?!\d+\s+{STATUTE_RE})(?P<disposition>.+?))?"
    rf"(?=\s+Modifier:|\s+\d+\s+{STATUTE_RE}|\s*$)",
    re.IGNORECASE,
)
LINE_CHARGE_RE = re.compile(
    rf"^(?P<count>\d+)\s+(?P<statute>{STATUTE_RE})\s+"
    rf"(?P<description>.+?)\s+(?P<severity>{SEVERITY_RE})"
    rf"(?:\s+(?P<disposition>.*))?$",
    re.IGNORECASE,
)
MODIFIER_RE = re.compile(
    rf"Modifier:\s+(?P<mod_statute>{STATUTE_RE})\s+(?P<mod_text>.+?)"
    rf"(?=\s+Modifier:|\s+\d+\s+{STATUTE_RE}|\s*$)",
    re.IGNORECASE,
)
LINE_MODIFIER_RE = re.compile(
    rf"^Modifier:\s+(?P<mod_statute>{STATUTE_RE})\s+(?P<mod_text>.+)$",
    re.IGNORECASE,
)

# Party labels from the WCCA defendant block / caption. Never invent DOB/address.
DEFENDANT_NAME_RE = re.compile(
    r"Defendant\s+name\s*:?\s*(.+?)(?="
    r"\s+Date of birth\b|\s+Sex\b|\s+Race\b|\s+Address\b|"
    r"\s+Also known as\b|\s+Defendant name\b|\s+Charges\b|"
    r"\s+Count no\.|\s+Filing date\b|\s+Case type\b|\s+Case status\b|"
    r"\s+Branch\b|\s+DA case\b|\s+Prosecut|\s+Defense\b|$)",
    re.IGNORECASE,
)
DOB_LABEL_RE = re.compile(
    r"Date of birth\s*:?\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})",
    re.IGNORECASE,
)
SEX_LABEL_RE = re.compile(
    r"(?:^|\s)Sex\s*:?\s*(Male|Female|Unknown)(?="
    r"\s+Race\b|\s+Address\b|\s+Also known as\b|\s+Date of birth\b|"
    r"\s+Charges\b|\s+Count no\.|\s+Defendant\b|$|\s)",
    re.IGNORECASE,
)
# Headings that end defendant address / aka blocks on live WCCA SSR.
_PARTY_STOP_CORE = (
    r"Charges\b|Count no\.|Court records?\b|Court activit|"
    r"Warrants?\b|Judgments?\b|This is not the official\b|"
    r"Phone\b|Attorneys?\b|Prosecut|Defense\b|Responsible\b|"
    r"Branch(?:\s+ID)?\b|DA case\b|JUSTIS\b|Fingerprint\b|"
    r"Hearings?\b|Calendar\b"
)
ADDRESS_LABEL_RE = re.compile(
    rf"Address\s*:?\s*(.+?)(?="
    rf"\s+Also known as\b|\s+(?:{_PARTY_STOP_CORE})|"
    rf"\s+Race\b|\s+Sex\b|\s+Date of birth\b|$)",
    re.IGNORECASE,
)
AKA_SECTION_RE = re.compile(
    rf"Also known as\s*:?\s*(.+?)(?=\s+(?:{_PARTY_STOP_CORE})|$)",
    re.IGNORECASE,
)
# Last, First[ Middle] inside an aka section. Last is a single token so
# "Name Type Date of birth FIXTURE, JANE" does not swallow the header.
AKA_PERSON_FIND_RE = re.compile(
    r"\b([A-Za-z][A-Za-z.'\-]+),\s*([A-Za-z][A-Za-z.'-]*)"
    r"(?:\s+(?!Also\b|AKA\b|Alias\b|Maiden\b|Type\b)([A-Za-z][A-Za-z.'-]*))?"
)
_PARTY_STOP_SPLIT = re.compile(
    rf"(?i)\s+(?:Also known as|{_PARTY_STOP_CORE})"
)
AKA_TRAILING_TOKEN_RE = re.compile(
    r"(?i)(?:\s+|,)+(also known as|also|aka|alias|maiden|type)\s*$"
)
AKA_TYPE_TOKENS = frozenset(
    {"aka", "alias", "maiden", "type", "nickname", "also"}
)
AKA_SKIP_LAST = frozenset(
    {"name", "type", "date", "birth", "aka", "alias", "also", "known"}
)
CAPTION_SIDES_RE = re.compile(
    r"^(State of Wisconsin)\s+vs\.?\s+(.+)$",
    re.IGNORECASE,
)
PERSON_LAST_FIRST_RE = re.compile(
    r"^([A-Za-z][A-Za-z.'\- ]*?),\s*([A-Za-z][A-Za-z.'-]*)(?:\s+([A-Za-z][A-Za-z.'\- ]*))?$"
)
SWALLOWED_CHARGE_RE = re.compile(
    rf"\b(?:Felony|Misdemeanor|Misd\.?|Forfeiture|Count no)\b|{STATUTE_RE}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class IdentifierParts:
    county_code: str | None
    case_number: str | None
    origin: str


@dataclass(frozen=True)
class ChargeRow:
    charge_count: int
    statute: str
    description: str
    severity: str
    modifier_statute: str | None = None
    modifier_text: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "charge_count": self.charge_count,
            "statute": self.statute,
            "description": self.description,
            "severity": self.severity,
            "modifier_statute": self.modifier_statute,
            "modifier_text": self.modifier_text,
        }


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
    payload_parse_status: str = "html_ssr_v1"
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


@dataclass(frozen=True)
class WccaParseResult:
    county_code: str | None
    case_number: str | None
    case_type: str | None
    filed_date: date | None
    caption: str | None
    case_status: str | None
    county_name: str | None
    charges: tuple[ChargeRow, ...]
    payload_parse_status: str
    dq_flags: tuple[str, ...]
    silver_schema_version: str = SILVER_SCHEMA_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)
    parties: tuple[PartyRow, ...] = ()


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = unescape(str(value)).strip()
    return stripped or None


def _collapse_ws(value: str | None) -> str | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None
    collapsed = re.sub(r"\s+", " ", raw).strip()
    return collapsed or None


def _normalize_county(value: str | None) -> str | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None
    if raw.isdigit():
        return str(int(raw))
    return raw


def _normalize_case_number(value: str | None) -> str | None:
    raw = _blank_to_none(value)
    if raw is None:
        return None
    return raw.upper()


def _case_type_from_number(case_number: str | None) -> str | None:
    if not case_number:
        return None
    match = CASE_NUMBER_RE.match(case_number)
    if not match:
        return None
    return match.group(2).upper()


def parse_source_record_id(source_record_id: str | None) -> IdentifierParts:
    raw = _blank_to_none(source_record_id)
    if raw is None:
        return IdentifierParts(None, None, "source_record_id")
    colon = COLON_ID_RE.match(raw)
    if colon:
        return IdentifierParts(
            _normalize_county(colon.group(1)),
            _normalize_case_number(colon.group(2)),
            "source_record_id",
        )
    composed = COMPOSED_ID_RE.match(raw)
    if composed:
        return IdentifierParts(
            _normalize_county(composed.group(1)),
            _normalize_case_number(composed.group(2)),
            "source_record_id",
        )
    return IdentifierParts(None, None, "source_record_id")


def parse_source_url(source_url: str | None) -> IdentifierParts:
    raw = _blank_to_none(source_url)
    if raw is None:
        return IdentifierParts(None, None, "url")
    parsed = urlparse(raw)
    qs = parse_qs(parsed.query, keep_blank_values=False)
    county = (qs.get("countyNo") or qs.get("countyNo".lower()) or [None])[0]
    case_no = (qs.get("caseNo") or qs.get("caseNo".lower()) or [None])[0]
    # parse_qs is case-sensitive; WCCA uses countyNo / caseNo
    if county is None:
        for key, values in qs.items():
            if key.lower() == "countyno" and values:
                county = values[0]
                break
    if case_no is None:
        for key, values in qs.items():
            if key.lower() == "caseno" and values:
                case_no = values[0]
                break
    return IdentifierParts(
        _normalize_county(county),
        _normalize_case_number(case_no),
        "url",
    )


def _walk_dicts(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_dicts(item)


def _looks_like_case_object(obj: dict) -> bool:
    keys = {str(k).lower() for k in obj.keys()}
    has_id = "caseno" in keys or "case_number" in keys or "casenumber" in keys
    has_county = "countyno" in keys or "county_code" in keys or "countycode" in keys
    has_fact = any(k in keys for k in (*FILED_DATE_KEYS, *CAPTION_KEYS))
    return (has_id and has_county) or has_fact


def _get_ci(obj: dict, *names: str) -> Any:
    lower = {str(k).lower(): v for k, v in obj.items()}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _parse_filed_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _blank_to_none(str(value))
    if text is None:
        return None
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        if "T" in iso:
            return datetime.fromisoformat(iso).date()
    except ValueError:
        pass
    for fmt, slen in (
        ("%Y-%m-%d", 10),
        ("%m/%d/%Y", 10),
        ("%m-%d-%Y", 10),
        ("%m/%d/%Y", 8),
        ("%m-%d-%Y", 8),
    ):
        chunk = text[:slen] if slen <= len(text) else text
        try:
            return datetime.strptime(chunk, fmt).date()
        except ValueError:
            continue
    # Flexible M-D-YYYY / MM-DD-YYYY
    m = re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$", text)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def extract_structured_facts(payload_obj: Any) -> tuple[date | None, str | None, bool]:
    """Return (filed_date, caption, found_structured_case_object).

    Only explicit keys. Does not guess from free text.
    """
    filed: date | None = None
    caption: str | None = None
    found = False
    for obj in _walk_dicts(payload_obj):
        if not _looks_like_case_object(obj):
            continue
        found = True
        if filed is None:
            filed = _parse_filed_date(
                _get_ci(obj, *FILED_DATE_KEYS)
            )
        if caption is None:
            cap = _get_ci(obj, *CAPTION_KEYS)
            if cap is not None and not isinstance(cap, (dict, list)):
                caption = _blank_to_none(str(cap))
        if filed is not None and caption is not None:
            break
    return filed, caption, found


def html_to_text(html: str | None) -> str:
    """Strip scripts/styles/tags. Keep block boundaries as newlines.

    `&gt;` / `&lt;` are swapped for sentinels before tag strip so a charge
    description like `&gt;10-50g` cannot close a tag match on `>`.
    """
    raw = html if html else ""
    text = _SCRIPT_STYLE_RE.sub("\n", raw)
    text = _COMMENT_RE.sub(" ", text)
    text = _ENTITY_GT_RE.sub(_GT_SENTINEL, text)
    text = _ENTITY_LT_RE.sub(_LT_SENTINEL, text)
    text = _BLOCK_TO_NL_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = text.replace(_GT_SENTINEL, ">").replace(_LT_SENTINEL, "<")
    text = unescape(text)
    text = _SPACES_RE.sub(" ", text)
    text = _MULTI_NL_RE.sub("\n\n", text)
    lines = [_collapse_ws(ln) or "" for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _title_county_name(html: str, text: str) -> str | None:
    title_html = HTML_TITLE_RE.search(html or "")
    candidates = []
    if title_html:
        candidates.append(unescape(re.sub(r"\s+", " ", title_html.group(1)).strip()))
    candidates.append(text)
    for blob in candidates:
        match = TITLE_COUNTY_RE.search(blob or "")
        if match:
            return _collapse_ws(match.group(2))
    return None


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    return _collapse_ws(match.group(1))


def _charge_from_match(match: re.Match[str]) -> ChargeRow | None:
    try:
        count = int(match.group("count"))
    except (TypeError, ValueError):
        return None
    statute = _collapse_ws(match.group("statute"))
    description = _collapse_ws(match.group("description"))
    severity = _collapse_ws(match.group("severity"))
    if not statute or not description or not severity:
        return None
    return ChargeRow(
        charge_count=count,
        statute=statute,
        description=description,
        severity=severity,
    )


def _attach_modifier(charge: ChargeRow, mod: re.Match[str]) -> ChargeRow:
    return ChargeRow(
        charge_count=charge.charge_count,
        statute=charge.statute,
        description=charge.description,
        severity=charge.severity,
        modifier_statute=_collapse_ws(mod.group("mod_statute")),
        modifier_text=_collapse_ws(mod.group("mod_text")),
    )


def _charges_slice(text: str) -> str | None:
    header = CHARGE_HEADER_RE.search(text)
    if not header:
        return None
    rest = text[header.end() :]
    stop = CHARGE_SECTION_STOP_RE.search(rest)
    if stop:
        rest = rest[: stop.start()]
    return rest.strip()


def _parse_charges_lines(text: str) -> tuple[ChargeRow, ...]:
    rest = _charges_slice(text)
    if rest is None:
        return ()
    rows: list[ChargeRow] = []
    pending: ChargeRow | None = None
    for raw_line in rest.splitlines():
        line = _collapse_ws(raw_line)
        if not line:
            continue
        mod = LINE_MODIFIER_RE.match(line)
        if mod and pending is not None:
            if pending.modifier_statute is None:
                pending = _attach_modifier(pending, mod)
            continue
        row_match = LINE_CHARGE_RE.match(line)
        if row_match:
            parsed = _charge_from_match(row_match)
            if parsed is None:
                continue
            if pending is not None:
                rows.append(pending)
            pending = parsed
            leftover = _collapse_ws(row_match.groupdict().get("disposition"))
            if leftover:
                inline_mod = LINE_MODIFIER_RE.match(leftover) or re.match(
                    r"\s*" + MODIFIER_RE.pattern, leftover, re.IGNORECASE
                )
                if inline_mod:
                    pending = _attach_modifier(pending, inline_mod)
    if pending is not None:
        rows.append(pending)
    return tuple(rows)


def _parse_charges_collapsed(text: str) -> tuple[ChargeRow, ...]:
    rest = _charges_slice(text)
    if rest is None:
        return ()
    collapsed = _collapse_ws(rest) or ""
    rows: list[ChargeRow] = []
    pos = 0
    while pos < len(collapsed):
        row_match = CHARGE_ROW_RE.search(collapsed, pos)
        if not row_match:
            break
        parsed = _charge_from_match(row_match)
        pos = row_match.end()
        if parsed is None:
            continue
        mod = re.match(r"\s*" + MODIFIER_RE.pattern, collapsed[pos:], re.IGNORECASE)
        if mod:
            parsed = _attach_modifier(parsed, mod)
            pos += mod.end()
        rows.append(parsed)
    return tuple(rows)


def _parse_charges_by_starts(text: str) -> tuple[ChargeRow, ...]:
    """Split the charges grid on count+statute tokens (descriptions may contain `>`)."""
    rest = _charges_slice(text)
    if rest is None:
        return ()
    collapsed = _collapse_ws(rest) or ""
    starts = list(CHARGE_START_RE.finditer(collapsed))
    if not starts:
        return ()
    rows: list[ChargeRow] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(collapsed)
        chunk = collapsed[start.start() : end].strip()
        parsed = _charge_from_start_chunk(start, chunk)
        if parsed is not None:
            rows.append(parsed)
    return tuple(rows)


def _charge_from_start_chunk(start: re.Match[str], chunk: str) -> ChargeRow | None:
    try:
        count = int(start.group("count"))
    except (TypeError, ValueError):
        return None
    statute = _collapse_ws(start.group("statute"))
    if not statute:
        return None
    after = chunk[len(start.group(0)) :]
    mod_statute: str | None = None
    mod_text: str | None = None
    mod = re.search(
        rf"\s+Modifier:\s+({STATUTE_RE})\s+(.+?)\s*$",
        after,
        re.IGNORECASE,
    )
    body = after
    if mod:
        mod_statute = _collapse_ws(mod.group(1))
        mod_text = _collapse_ws(mod.group(2))
        body = after[: mod.start()]
    sev = re.search(rf"({SEVERITY_RE})\b", body, re.IGNORECASE)
    if not sev:
        return None
    description = _collapse_ws(body[: sev.start()])
    severity = _collapse_ws(sev.group(1))
    if not description or not severity:
        return None
    return ChargeRow(
        charge_count=count,
        statute=statute,
        description=description,
        severity=severity,
        modifier_statute=mod_statute,
        modifier_text=mod_text,
    )


def parse_charges_from_ssr_text(text: str) -> tuple[ChargeRow, ...]:
    """Parse charge rows from stripped SSR text. Empty if the grid is absent.

    Prefer count+statute splitting so descriptions may contain `>` / `<`.
    Fall back to the collapsed row regex, then per-line rows.
    """
    by_starts = _parse_charges_by_starts(text)
    if by_starts:
        return by_starts
    collapsed = _parse_charges_collapsed(text)
    if collapsed:
        return collapsed
    return _parse_charges_lines(text)


def is_org_party_name(raw_name: str | None) -> bool:
    """WI criminal caption plaintiff is typically the State, not a person."""
    collapsed = _collapse_ws(raw_name)
    if collapsed is None:
        return False
    return ORG_PLAINTIFF_RE.match(collapsed) is not None


def split_person_name(
    raw_name: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Split `Last, First[ Middle…]` when that form is reliable.

    Returns (None, None, None) when there is no comma, the tokens do not look
    like a person name, or the string is an organizational plaintiff. Never
    guesses `First Last` order.
    """
    collapsed = _collapse_ws(raw_name)
    if collapsed is None or is_org_party_name(collapsed):
        return None, None, None
    match = PERSON_LAST_FIRST_RE.match(collapsed)
    if not match:
        return None, None, None
    last = _collapse_ws(match.group(1))
    first = _collapse_ws(match.group(2))
    middle = _collapse_ws(match.group(3))
    if last is None or first is None:
        return None, None, None
    if len(last.split()) > 4:
        return None, None, None
    return last, first, middle


def caption_plaintiff_and_defendant(
    caption: str | None,
) -> tuple[str | None, str | None]:
    """Return (plaintiff, defendant) from `State of Wisconsin vs. {Name}`."""
    collapsed = _collapse_ws(caption)
    if collapsed is None:
        return None, None
    match = CAPTION_SIDES_RE.match(collapsed)
    if not match:
        return None, None
    return _collapse_ws(match.group(1)), _collapse_ws(match.group(2))


def _looks_like_swallowed_charges(value: str | None) -> bool:
    collapsed = _collapse_ws(value)
    if collapsed is None:
        return False
    return SWALLOWED_CHARGE_RE.search(collapsed) is not None


def _trim_party_stop(value: str | None) -> str | None:
    """Cut address/aka text at the next known heading (defense in depth)."""
    raw = _collapse_ws(value)
    if raw is None:
        return None
    trimmed = _PARTY_STOP_SPLIT.split(raw, maxsplit=1)[0].strip()
    return trimmed or None


def _strip_aka_trailing_tokens(raw_name: str | None) -> str | None:
    """Drop delimiter leftovers (`Also`, `AKA`, `Alias`) from aka names."""
    text = _collapse_ws(raw_name)
    if text is None:
        return None
    while True:
        stripped = AKA_TRAILING_TOKEN_RE.sub("", text).strip(" ,")
        if stripped == text:
            break
        text = stripped
    return text or None


def _canonical_aka_name(raw_name: str) -> str | None:
    cleaned = _strip_aka_trailing_tokens(raw_name)
    if cleaned is None:
        return None
    last, first, middle = split_person_name(cleaned)
    if last is None or first is None:
        return None
    if last.casefold() in AKA_SKIP_LAST:
        return None
    if middle:
        middle = _strip_aka_trailing_tokens(middle)
        if middle and middle.casefold() in AKA_TYPE_TOKENS:
            middle = None
    assembled = f"{last}, {first}" + (f" {middle}" if middle else "")
    assembled = _strip_aka_trailing_tokens(assembled) or assembled
    return assembled


def _is_aka_person_name(raw: str | None) -> bool:
    collapsed = _collapse_ws(raw)
    if collapsed is None:
        return False
    lowered = collapsed.casefold()
    if lowered.startswith("type ") or lowered.startswith("name type"):
        return False
    if "date of birth" in lowered or "branch id" in lowered:
        return False
    if _looks_like_swallowed_charges(collapsed):
        return False
    if len(collapsed) > 80 or len(collapsed.split()) > 6:
        return False
    return _canonical_aka_name(collapsed) is not None


def _aka_names(section: str | None) -> list[str]:
    """One clean Last, First[ M] per aka person. Never the table header or calendar."""
    if not section:
        return []
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str | None) -> None:
        canonical = _canonical_aka_name(raw or "")
        if canonical is None or not _is_aka_person_name(canonical):
            return
        key = canonical.casefold()
        if key in seen:
            return
        seen.add(key)
        names.append(canonical)

    for line in section.splitlines():
        add(_collapse_ws(line))
    collapsed = _collapse_ws(section) or ""
    for match in AKA_PERSON_FIND_RE.finditer(collapsed):
        last, first, middle = match.group(1), match.group(2), match.group(3)
        if middle and middle.casefold() in AKA_TYPE_TOKENS:
            middle = None
        assembled = f"{last}, {first}" + (f" {middle}" if middle else "")
        add(_strip_aka_trailing_tokens(assembled))
    return names


def _build_party(
    *,
    role: str,
    ordinal: int,
    raw_name: str,
    dob: date | None = None,
    sex: str | None = None,
    address_raw: str | None = None,
    status: str = "html_ssr_v1",
    extra_flags: tuple[str, ...] = (),
) -> PartyRow:
    last, first, middle = split_person_name(raw_name)
    if role == "aka":
        stripped = _strip_aka_trailing_tokens(raw_name)
        if stripped:
            raw_name = stripped
        last, first, middle = split_person_name(raw_name)
        if middle and middle.casefold() in AKA_TYPE_TOKENS:
            middle = None
            if last and first:
                raw_name = f"{last}, {first}"
    flags = [flag for flag in extra_flags if flag]
    if last is None and first is None and not is_org_party_name(raw_name):
        flags.append("ambiguous_name_parts")
    if role == "defendant" and dob is None:
        flags.append("missing_dob")
    if role not in PARTY_ROLES:
        flags.append("invalid_party_role")
    return PartyRow(
        party_role=role,
        party_ordinal=ordinal,
        raw_name=raw_name,
        name_last=last,
        name_first=first,
        name_middle=middle,
        dob=dob,
        sex=sex,
        address_raw=address_raw,
        payload_parse_status=status,
        dq_flags=tuple(sorted(set(flags))),
    )


def parse_parties_from_ssr_text(
    text: str | None,
    *,
    caption: str | None = None,
) -> tuple[PartyRow, ...]:
    """Extract plaintiff / defendant / aka rows. Empty if names are absent.

    DOB, sex, and address are filled only from explicit labels. Race is not a
    party column (agency-provided subjective; matching must not require it).
    """
    raw_text = text or ""
    collapsed = _collapse_ws(raw_text) or ""
    caption_text = caption or _first_group(CAPTION_RE, raw_text) or _first_group(
        CAPTION_RE, collapsed
    )
    plaintiff, caption_defendant = caption_plaintiff_and_defendant(caption_text)

    labeled_names: list[str] = []
    for blob in (raw_text, collapsed):
        if not blob:
            continue
        for match in DEFENDANT_NAME_RE.finditer(blob):
            name = _collapse_ws(match.group(1))
            if (
                name
                and not _looks_like_swallowed_charges(name)
                and name not in labeled_names
            ):
                labeled_names.append(name)
        if labeled_names:
            break

    dob_raw = _first_group(DOB_LABEL_RE, raw_text) or _first_group(
        DOB_LABEL_RE, collapsed
    )
    dob = _parse_filed_date(dob_raw)
    dob_unparsed = bool(dob_raw) and dob is None

    sex = None
    for blob in (raw_text, collapsed):
        sex_match = SEX_LABEL_RE.search(blob)
        if sex_match:
            sex = _collapse_ws(sex_match.group(1))
            if sex:
                sex = sex[:1].upper() + sex[1:].lower()
            break

    address_raw = None
    for blob in (raw_text, collapsed):
        addr = _trim_party_stop(_first_group(ADDRESS_LABEL_RE, blob))
        if addr and not _looks_like_swallowed_charges(addr):
            address_raw = addr
            break

    aka_section = None
    for blob in (raw_text, collapsed):
        aka_match = AKA_SECTION_RE.search(blob)
        if aka_match:
            aka_section = aka_match.group(1)
            break
    aka_list = _aka_names(aka_section)

    rows: list[PartyRow] = []
    if plaintiff:
        rows.append(
            _build_party(
                role="plaintiff",
                ordinal=1,
                raw_name=plaintiff,
            )
        )

    defendant_name = labeled_names[0] if labeled_names else caption_defendant
    extra: list[str] = []
    status = "html_ssr_v1"
    if defendant_name and not labeled_names:
        extra.append("defendant_from_caption")
        status = "html_ssr_partial"
    if dob_unparsed:
        extra.append("dob_unparsed")
    if defendant_name:
        rows.append(
            _build_party(
                role="defendant",
                ordinal=1,
                raw_name=defendant_name,
                dob=dob,
                sex=sex,
                address_raw=address_raw,
                status=status,
                extra_flags=tuple(extra),
            )
        )
        for index, extra_name in enumerate(labeled_names[1:], start=2):
            rows.append(
                _build_party(
                    role="defendant",
                    ordinal=index,
                    raw_name=extra_name,
                    status="html_ssr_v1",
                )
            )

    skip = {
        (defendant_name or "").casefold(),
        (plaintiff or "").casefold(),
    }
    aka_ordinal = 1
    for aka in aka_list:
        if aka.casefold() in skip:
            continue
        last, first, _middle = split_person_name(aka)
        if last is None or first is None:
            continue
        rows.append(
            _build_party(
                role="aka",
                ordinal=aka_ordinal,
                raw_name=aka,
            )
        )
        skip.add(aka.casefold())
        aka_ordinal += 1

    return tuple(rows)


def extract_ssr_facts(html: str | None) -> dict[str, Any]:
    """Deterministic SSR fields from visible HTML text. Never invents."""
    raw = html if html else ""
    text = html_to_text(raw)
    collapsed = _collapse_ws(text) or ""
    county_name = _title_county_name(raw, text) or _title_county_name(raw, collapsed)
    caption = _first_group(CAPTION_RE, text) or _first_group(CAPTION_RE, collapsed)
    filed_raw = _first_group(FILED_DATE_RE, text) or _first_group(
        FILED_DATE_RE, collapsed
    )
    filed_date = _parse_filed_date(filed_raw)
    case_status = _first_group(CASE_STATUS_RE, text) or _first_group(
        CASE_STATUS_RE, collapsed
    )
    charges = parse_charges_from_ssr_text(text)
    parties = parse_parties_from_ssr_text(text, caption=caption)
    found = bool(
        county_name
        or caption
        or filed_date
        or case_status
        or charges
        or parties
        or CHARGE_HEADER_RE.search(text)
        or TITLE_COUNTY_RE.search(text)
        or TITLE_COUNTY_RE.search(collapsed)
    )
    return {
        "filed_date": filed_date,
        "caption": caption,
        "case_status": case_status,
        "county_name": county_name,
        "charges": charges,
        "parties": parties,
        "found_ssr_text": found,
    }


def parse_html_snapshot(html: str | None) -> dict[str, Any]:
    """JSON embeds (if any) plus SSR text. JSON explicit keys win on overlap."""
    raw = html if html else ""
    blobs: list[Any] = []
    for match in SCRIPT_JSON_RE.finditer(raw):
        body = match.group(1).strip()
        if not body:
            continue
        try:
            blobs.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    for match in PRELOAD_RE.finditer(raw):
        try:
            blobs.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    filed: date | None = None
    caption: str | None = None
    found_json = False
    for blob in blobs:
        f, c, ok = extract_structured_facts(blob)
        found_json = found_json or ok
        filed = filed or f
        caption = caption or c
    ssr = extract_ssr_facts(raw)
    caption = caption or ssr["caption"]
    if caption != ssr["caption"]:
        parties = parse_parties_from_ssr_text(html_to_text(raw), caption=caption)
    else:
        parties = ssr["parties"]
    return {
        "filed_date": filed or ssr["filed_date"],
        "caption": caption,
        "case_status": ssr["case_status"],
        "county_name": ssr["county_name"],
        "charges": ssr["charges"],
        "parties": parties,
        "found_structured_json": found_json,
        "found_ssr_text": ssr["found_ssr_text"],
    }


def parse_json_payload(payload: str | None) -> tuple[date | None, str | None, bool]:
    raw = _blank_to_none(payload)
    if raw is None:
        return None, None, False
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None, None, False
    return extract_structured_facts(obj)


def merge_identifiers(
    from_id: IdentifierParts, from_url: IdentifierParts
) -> tuple[str | None, str | None, bool]:
    """Prefer URL params when both sides parse and disagree."""
    mismatch = False
    county = from_url.county_code or from_id.county_code
    case_no = from_url.case_number or from_id.case_number
    if (
        from_url.county_code
        and from_id.county_code
        and from_url.county_code != from_id.county_code
    ):
        mismatch = True
        county = from_url.county_code
    if (
        from_url.case_number
        and from_id.case_number
        and from_url.case_number != from_id.case_number
    ):
        mismatch = True
        case_no = from_url.case_number
    return county, case_no, mismatch


def _payload_parse_status(
    *,
    county: str | None,
    case_no: str | None,
    caption: str | None,
    filed_date: date | None,
    charges: tuple[ChargeRow, ...],
    found_json: bool,
    found_ssr: bool,
    case_status: str | None,
    county_name: str | None,
) -> str:
    if county is None or case_no is None:
        return "identifier_error"
    if caption is not None and filed_date is not None and len(charges) >= 1:
        return "html_ssr_v1"
    if found_ssr and (
        caption is not None
        or filed_date is not None
        or charges
        or case_status is not None
        or county_name is not None
    ):
        return "html_ssr_partial"
    if found_json and (caption is not None or filed_date is not None):
        return "structured_facts"
    return "identifiers_only"


def parse_wcca_bronze_row(
    *,
    source_system: str | None,
    source_record_id: str | None,
    source_url: str | None,
    payload_format: str | None,
    payload: str | None = None,
) -> WccaParseResult:
    flags: list[str] = []
    notes: list[str] = []

    if (source_system or "").strip() != SOURCE_SYSTEM:
        flags.append("unsupported_source_parser")
        if not _blank_to_none(source_url):
            flags.append("missing_source_url")
        flags.extend(["missing_caption", "missing_filed_date"])
        return WccaParseResult(
            county_code=None,
            case_number=None,
            case_type=None,
            filed_date=None,
            caption=None,
            case_status=None,
            county_name=None,
            charges=(),
            payload_parse_status="unsupported_source",
            dq_flags=tuple(sorted(set(flags))),
            notes=("no silver parser for this source_system",),
        )

    from_id = parse_source_record_id(source_record_id)
    from_url = parse_source_url(source_url)
    county, case_no, mismatch = merge_identifiers(from_id, from_url)
    case_type = _case_type_from_number(case_no)

    if mismatch:
        flags.append("identifier_url_mismatch")
        notes.append("url query params preferred over source_record_id")
    if not _blank_to_none(source_url):
        flags.append("missing_source_url")
    if county is None:
        flags.append("county_code_unparsed")
    elif not county.isdigit():
        flags.append("invalid_county_code")
    if case_no is None:
        flags.append("case_number_unparsed")
    elif case_type is None:
        flags.append("case_type_unparsed")

    filed_date: date | None = None
    caption: str | None = None
    case_status: str | None = None
    county_name: str | None = None
    charges: tuple[ChargeRow, ...] = ()
    parties: tuple[PartyRow, ...] = ()
    found_json = False
    found_ssr = False
    fmt = (payload_format or "").strip().lower()
    if fmt == "json":
        filed_date, caption, found_json = parse_json_payload(payload)
        parties = parse_parties_from_ssr_text("", caption=caption)
    elif fmt == "html_snapshot":
        parsed_html = parse_html_snapshot(payload)
        filed_date = parsed_html["filed_date"]
        caption = parsed_html["caption"]
        case_status = parsed_html["case_status"]
        county_name = parsed_html["county_name"]
        charges = parsed_html["charges"]
        parties = parsed_html["parties"]
        found_json = parsed_html["found_structured_json"]
        found_ssr = parsed_html["found_ssr_text"]
        if not found_json and not found_ssr:
            flags.append("unparsed_html_spa")
            notes.append("html snapshot: no SSR case text and no structured JSON embed")
        elif found_ssr:
            notes.append("html_ssr_v1 regex parser on stripped snapshot text")

    if caption is None:
        flags.append("missing_caption")
    if filed_date is None:
        flags.append("missing_filed_date")
    if fmt == "html_snapshot" and found_ssr and not charges:
        flags.append("missing_charges")

    status = _payload_parse_status(
        county=county,
        case_no=case_no,
        caption=caption,
        filed_date=filed_date,
        charges=charges,
        found_json=found_json,
        found_ssr=found_ssr,
        case_status=case_status,
        county_name=county_name,
    )

    return WccaParseResult(
        county_code=county,
        case_number=case_no,
        case_type=case_type,
        filed_date=filed_date,
        caption=caption,
        case_status=case_status,
        county_name=county_name,
        charges=charges,
        parties=parties,
        payload_parse_status=status,
        dq_flags=tuple(sorted(set(flags))),
        notes=tuple(notes),
    )
