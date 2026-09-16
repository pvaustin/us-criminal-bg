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
- Silver `court_party`: [`docs/silver/COURT_PARTY.md`](docs/silver/COURT_PARTY.md)
- SF HF research parties (experiment-only): [`docs/silver/SF_RESEARCH.md`](docs/silver/SF_RESEARCH.md)
- WCCA HTML SSR parseability: [`docs/silver/WCCA_HTML_SSR.md`](docs/silver/WCCA_HTML_SSR.md)
- Match / review sketch: [`docs/silver/MATCH_REVIEW.md`](docs/silver/MATCH_REVIEW.md)
- SF name-only match experiment (research, not CRA): [`docs/silver/SF_MATCH_EXPERIMENT.md`](docs/silver/SF_MATCH_EXPERIMENT.md)
- Pilot order subject + search audit: [`docs/silver/ORDER_AUDIT.md`](docs/silver/ORDER_AUDIT.md)
- Source access / ToS notes: [`docs/bronze/ACCESS.md`](docs/bronze/ACCESS.md)
- VA research (gated named; no anonymized load): [`docs/bronze/ACCESS_VA_COURT_DATA.md`](docs/bronze/ACCESS_VA_COURT_DATA.md)
- SF HF research named corpus: [`docs/bronze/ACCESS_SF_CRIMINAL_HF.md`](docs/bronze/ACCESS_SF_CRIMINAL_HF.md)
- WCCA adapter + parser: [`sources/wcca/`](sources/wcca/)
- SF HF research mapper + party parser: [`sources/sf_criminal_hf/`](sources/sf_criminal_hf/)
- Bronze jobs: [`bronze/jobs/README.md`](bronze/jobs/README.md)
- Silver jobs: [`silver/jobs/README.md`](silver/jobs/README.md)

## Product docs

Product concept, PRD sketch, roadmap, strategy, and market personas live in [`docs/product/`](docs/product/). Beachhead is locked: WI employers/HR now; staffing next; individuals later.

- Concept: [`docs/product/01-product-concept.md`](docs/product/01-product-concept.md)
- PRD sketch: [`docs/product/02-prd-sketch.md`](docs/product/02-prd-sketch.md)
- Roadmap: [`docs/product/03-roadmap.md`](docs/product/03-roadmap.md)
- Strategy: [`docs/product/04-strategy.md`](docs/product/04-strategy.md)
- Market + personas: [`docs/product/05-market-personas.md`](docs/product/05-market-personas.md)
- AC4 acceptance: [`docs/product/06-ac4-acceptance.md`](docs/product/06-ac4-acceptance.md)

## Databricks (non-secret)

- Host: `dbc-a0dcbe75-2647.cloud.databricks.com`
- Workspace ID: `7474648418210162`
- Catalog: `us_criminal_bg`
- Schemas: `us_criminal_bg.bronze`, `us_criminal_bg.silver`
