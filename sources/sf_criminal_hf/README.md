# Source: `sf_criminal_hf` (San Francisco, research)

Hugging Face published `cases.parquet` → Bronze. **Not** the WI employer MVP.

- `source_system` = `sf_criminal_hf`
- `state_code` = `CA`
- Dataset: https://huggingface.co/datasets/cfahlgren1/sf_criminal_court
- Access notes: [`docs/bronze/ACCESS_SF_CRIMINAL_HF.md`](../../docs/bronze/ACCESS_SF_CRIMINAL_HF.md)

This package must never scrape court sites, download Virginia anonymized CSVs, or load Cook County.

## Layout

- `map.py` — identifiers, payload JSON, volume paths, SQL builders
- `tests/` — synthetic rows only (never claimed as real court records)

```bash
python3 -m unittest discover -s sources/sf_criminal_hf/tests -v
```
