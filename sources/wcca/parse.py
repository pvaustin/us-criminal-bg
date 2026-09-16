"""WCCA identifier / URL / HTML SSR / conservative JSON payload parser.

Never scrapes. Never invents case facts. Synthetic fixtures in tests are
labeled as such and must not be treated as real court records.

Identifier contract (see docs/silver/NAMING.md):
- source_record_id countyNo:caseNo (live Bronze sample) or WI|wcca|{county}|{case_number}
- URL query params countyNo / caseNo are preferred when they disagree with the id

HTML snapshots: live WCCA detail pages store server-rendered plain text (not an
empty SPA shell and not a __NEXT_DATA__ case blob). After scripts/styles/tags
are stripped, deterministic regex extracts caption, filing date, case status,
county name, and charges. See docs/silver/WCCA_HTML_SSR.md.
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

# WI statute tokens: 946.41(1), 961.41(3g)(e), 961.41(1m)(hm)3 (trailing digit)
STATUTE_RE = r"\d{3}\.\d{2,4}(?:\([^)]+\))*\d*"
# Exact SSR severity tokens. Do not expand Misd. → Misdemeanor or eat "M" from Misd.
# Class letter is a single A–I / U token with a word boundary.
SEVERITY_RE = (
    r"(?:Misd\.\s+[A-IU]\b|Felony\s+[A-IU]\b|Misdemeanor\s+[A-IU]\b|"
    r"Misd\.|Felony|Misdemeanor|Forfeiture|Ordinance)"
)
SEVERITY_TOKEN_RE = re.compile(SEVERITY_RE, re.IGNORECASE)
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


def _last_severity_token(body: str) -> re.Match[str] | None:
    """Last whitespace-delimited severity token (not `Jumping-Felony` in the name)."""
    matches = list(SEVERITY_TOKEN_RE.finditer(body))
    if not matches:
        return None
    spaced = [
        match
        for match in matches
        if match.start() == 0 or body[match.start() - 1].isspace()
    ]
    return spaced[-1] if spaced else matches[-1]


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
    sev = _last_severity_token(body)
    if not sev:
        return None
    description = _collapse_ws(body[: sev.start()])
    severity = _collapse_ws(sev.group(0))
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
    found = bool(
        county_name
        or caption
        or filed_date
        or case_status
        or charges
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
    return {
        "filed_date": filed or ssr["filed_date"],
        "caption": caption or ssr["caption"],
        "case_status": ssr["case_status"],
        "county_name": ssr["county_name"],
        "charges": ssr["charges"],
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
    found_json = False
    found_ssr = False
    fmt = (payload_format or "").strip().lower()
    if fmt == "json":
        filed_date, caption, found_json = parse_json_payload(payload)
    elif fmt == "html_snapshot":
        parsed_html = parse_html_snapshot(payload)
        filed_date = parsed_html["filed_date"]
        caption = parsed_html["caption"]
        case_status = parsed_html["case_status"]
        county_name = parsed_html["county_name"]
        charges = parsed_html["charges"]
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
        payload_parse_status=status,
        dq_flags=tuple(sorted(set(flags))),
        notes=tuple(notes),
    )
