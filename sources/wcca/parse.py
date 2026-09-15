"""WCCA identifier / URL / conservative payload parser.

Never scrapes. Never invents case facts. Synthetic fixtures in tests are
labeled as such and must not be treated as real court records.

Identifier contract (see docs/silver/NAMING.md):
- source_record_id countyNo:caseNo (live Bronze sample) or WI|wcca|{county}|{case_number}
- URL query params countyNo / caseNo are preferred when they disagree with the id
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
SILVER_SCHEMA_VERSION = "silver.court_case.v1"

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


@dataclass(frozen=True)
class IdentifierParts:
    county_code: str | None
    case_number: str | None
    origin: str


@dataclass(frozen=True)
class WccaParseResult:
    county_code: str | None
    case_number: str | None
    case_type: str | None
    filed_date: date | None
    caption: str | None
    payload_parse_status: str
    dq_flags: tuple[str, ...]
    silver_schema_version: str = SILVER_SCHEMA_VERSION
    notes: tuple[str, ...] = field(default_factory=tuple)


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = unescape(str(value)).strip()
    return stripped or None


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
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
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


def parse_html_snapshot(html: str | None) -> tuple[date | None, str | None, bool]:
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
    found = False
    for blob in blobs:
        f, c, ok = extract_structured_facts(blob)
        found = found or ok
        filed = filed or f
        caption = caption or c
    return filed, caption, found


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
    found_structured = False
    fmt = (payload_format or "").strip().lower()
    if fmt == "json":
        filed_date, caption, found_structured = parse_json_payload(payload)
    elif fmt == "html_snapshot":
        filed_date, caption, found_structured = parse_html_snapshot(payload)
        if not found_structured:
            flags.append("unparsed_html_spa")
            notes.append("react spa snapshot: no structured case embed")

    if caption is None:
        flags.append("missing_caption")
    if filed_date is None:
        flags.append("missing_filed_date")

    if county is None or case_no is None:
        status = "identifier_error"
    elif found_structured and (caption is not None or filed_date is not None):
        status = "structured_facts"
    else:
        status = "identifiers_only"

    return WccaParseResult(
        county_code=county,
        case_number=case_no,
        case_type=case_type,
        filed_date=filed_date,
        caption=caption,
        payload_parse_status=status,
        dq_flags=tuple(sorted(set(flags))),
        notes=tuple(notes),
    )
