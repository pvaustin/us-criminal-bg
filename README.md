# us-criminal-bg

US criminal background verification — court-source data platform.

**MVP first slice:** Wisconsin WCCA → Databricks **Bronze**, then **Silver** (national-first naming; state is a dimension).

| Lane | Agent | Owns |
|------|-------|------|
| Bronze | brian bronze | Raw / near-raw landing, naming contract, WCCA ingest skeleton |
| Silver | silva silver | Cleanses / transforms over Bronze — [`docs/silver/NAMING.md`](docs/silver/NAMING.md) |
| Plan | court-cto | Technical plan and orchestration |

## Quick links

- Bronze naming contract: [`docs/bronze/NAMING.md`](docs/bronze/NAMING.md)
- Silver naming contract: [`docs/silver/NAMING.md`](docs/silver/NAMING.md)
- WCCA HTML SSR parseability: [`docs/silver/WCCA_HTML_SSR.md`](docs/silver/WCCA_HTML_SSR.md)
- Source access / ToS notes: [`docs/bronze/ACCESS.md`](docs/bronze/ACCESS.md)
- WCCA adapter + parser: [`sources/wcca/`](sources/wcca/)
- Bronze jobs: [`bronze/jobs/README.md`](bronze/jobs/README.md)
- Silver jobs: [`silver/jobs/README.md`](silver/jobs/README.md)

## Databricks (non-secret)

- Host: `dbc-a0dcbe75-2647.cloud.databricks.com`
- Workspace ID: `7474648418210162`
- Catalog: `us_criminal_bg`
- Schemas: `us_criminal_bg.bronze`, `us_criminal_bg.silver`
