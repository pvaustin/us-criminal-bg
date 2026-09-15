# us-criminal-bg

US criminal background verification — court-source data platform.

**MVP first slice:** Wisconsin WCCA → Databricks **Bronze** (national-first naming; state is a dimension).

| Lane | Agent | Owns |
|------|-------|------|
| Bronze | brian bronze | Raw / near-raw landing, naming contract, WCCA ingest skeleton |
| Silver | silva silver | Cleanses / transforms over Bronze — not this tree’s write target |
| Plan | court-cto | Technical plan and orchestration |

## Quick links

- Bronze naming contract: [`docs/bronze/NAMING.md`](docs/bronze/NAMING.md)
- Source access / ToS notes: [`docs/bronze/ACCESS.md`](docs/bronze/ACCESS.md)
- WCCA adapter stub: [`sources/wcca/`](sources/wcca/)

## Databricks (non-secret)

- Host: `dbc-a0dcbe75-2647.cloud.databricks.com`
- Workspace ID: `7474648418210162`
- Catalog / schema (target): `us_criminal_bg.bronze`
