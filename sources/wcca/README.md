# Source: `wcca` (Wisconsin)

Adapter for Wisconsin Circuit Court Access → Bronze, plus Silver identifier / HTML SSR parsing.

- `source_system` = `wcca`
- `state_code` = `WI`
- Public UI: https://wcca.wicourts.gov/

See `docs/bronze/ACCESS.md` for CAPTCHA / paid REST rules. This package must never include bypass or scrape logic. See `docs/silver/NAMING.md` and `docs/silver/WCCA_HTML_SSR.md` for Silver identifier / SSR / DQ contract.

## Layout

- `extract_stub.py` — skeleton Bronze entrypoint (no live scrape past walls)
- `parse.py` — pure-Python parser for `source_record_id`, WCCA URLs, HTML SSR text, and conservative JSON embeds
- `tests/` — synthetic fixtures only (never claimed as real court records)

## Identifier shapes

- Live Bronze grain: `source_record_id` = `{countyNo}:{caseNo}` (example shape `51:2026CF000028`)
- URL: `caseDetail.html?caseNo=...&countyNo=...` query params are preferred if they disagree with the id
- Bronze composed fallback from `docs/bronze/NAMING.md`: `WI|wcca|{county}|{case_number}`

HTML snapshots of WCCA case detail are treated as **server-rendered text** (title, caption, filing date, status, charges grid, defendant / aka labels) after scripts/styles/tags are stripped. Empty SPA shells stay identifier-only. The parser does **not** invent fields that are not in those patterns. See `docs/silver/WCCA_HTML_SSR.md`.

```bash
python3 -m unittest discover -s sources/wcca/tests -v
```
