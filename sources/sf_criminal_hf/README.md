# Source: `sf_criminal_hf` (San Francisco, research)

Hugging Face published `cases.parquet` → Bronze. **Not** the WI employer MVP.

- `source_system` = `sf_criminal_hf`
- `state_code` = `CA`
- Identifier grain: `source_record_id` = `sf_case:{case_id}`
- Access notes: [`docs/bronze/ACCESS_SF_CRIMINAL_HF.md`](../../docs/bronze/ACCESS_SF_CRIMINAL_HF.md)

This package must never scrape court sites, download Virginia anonymized CSVs, or load Cook County.

## Layout

- `map.py` — identifiers, payload JSON, volume paths, SQL builders
- `parse_party.py` — Silver `court_party` defendant parse from Bronze JSON (research; no scrape)
- `tests/` — synthetic rows / names only (never claimed as real court records)

```bash
python3 -m unittest discover -s sources/sf_criminal_hf/tests -v
```

Silver transform (scoped MERGE; does not delete WI parties): [`docs/silver/SF_RESEARCH.md`](../../docs/silver/SF_RESEARCH.md).
