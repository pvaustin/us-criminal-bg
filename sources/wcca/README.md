# Source: `wcca` (Wisconsin)

Adapter for Wisconsin Circuit Court Access → Bronze.

- `source_system` = `wcca`
- `state_code` = `WI`
- Public UI: https://wcca.wicourts.gov/

See `docs/bronze/ACCESS.md` for CAPTCHA / paid REST rules. This package must never include bypass logic.

## Layout

- `extract_stub.py` — skeleton entrypoint (no live scrape past walls)
- `schema_notes.md` — fields observed from legitimate samples (fill when real fixtures land)
