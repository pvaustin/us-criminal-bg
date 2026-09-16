# Source: `wcca` (Wisconsin)

Adapter for Wisconsin Circuit Court Access → Bronze, plus Silver identifier parsing.

- `source_system` = `wcca`
- `state_code` = `WI`
- Public UI: https://wcca.wicourts.gov/

See `docs/bronze/ACCESS.md` for CAPTCHA / paid REST rules. This package must never include bypass or scrape logic. See `docs/silver/NAMING.md` for Silver identifier / DQ contract.

## Layout

- `extract_stub.py` — skeleton Bronze entrypoint (no live scrape past walls)
- `parse.py` — pure-Python parser for `source_record_id`, WCCA URLs, and conservative HTML/JSON embeds
- `tests/` — synthetic fixtures only (never claimed as real court records)
- `schema_notes.md` — fields observed from legitimate samples (fill when real fixtures land)

## Identifier shapes

- Live Bronze grain: `source_record_id` = `{countyNo}:{caseNo}` (example shape `51:2026CF000028`)
- URL: `caseDetail.html?caseNo=...&countyNo=...` query params are preferred if they disagree with the id
- Bronze composed fallback from `docs/bronze/NAMING.md`: `WI|wcca|{county}|{case_number}`

HTML snapshots are React SPA shells. The parser does **not** invent caption / filed_date from page chrome.

```bash
python3 -m unittest discover -s sources/wcca/tests -v
```
