# Court source access (Bronze)

## Wisconsin — WCCA (MVP)

- **Public UI:** https://wcca.wicourts.gov/
- **What it is:** Public circuit court case summaries entered by county staff (not the official judgment/lien docket; no confidential case types).
- **CAPTCHA:** Present on search flows (re-check roughly every 10 searches historically). Automated bulk scraping that bypasses CAPTCHA, logins, paywalls, or ToS is **forbidden**.
- **MVP extract mode:** Low-volume interactive use and/or manual export/upload into Bronze landing paths. Prototype only; rate-limit and human-in-the-loop expected.
- **Scale path (documented, not implemented until subscribed):** CCAP paid REST bulk subscription. Annual fee historically ~$12,500; formal Data Subscription Agreement required. Contact path is published on WCCA (“Data Extraction Option”). Subscribers build their own client; CCAP does not provide analysis tooling.
- **References (public):**
  - WCCA site / FAQ and bulk REST mention on wcca.wicourts.gov
  - Paid REST agreement PDF: https://www.wicourts.gov/courts/resources/docs/RESTagreementpaid.pdf
  - CAPTCHA announcement context: Wisconsin court system news on WCCA CAPTCHA (2018)

## Virginia — virginiacourtdata.org (research notes only)

Research spike, **not** MVP, **not** employer product, **not** for commercial CRA claims. Independent hobby redistribution (not Commonwealth-affiliated). Public CSVs are anonymized — **do not load** into Bronze. Named export is requestable and gated; **Prasanth will request the account himself.** **No VA loader. Do not scrape Virginia court websites.** Details: [`ACCESS_VA_COURT_DATA.md`](ACCESS_VA_COURT_DATA.md).

## San Francisco — Hugging Face `sf_criminal_court` (research named corpus)

Research spike, **isolated from the WI product path**, **not** employer product, **not** for commercial CRA claims. Third-party HF parquet (`cases.parquet`). Live Bronze load 2026-09-16: **77,406** named rows (`defendant_name` nonempty 77,399/77,406); grain `sf_case:{case_id}`. CC-BY-NC-4.0. Published-file download only; **do not scrape** SF court sites. **Do not load Cook County.** Details: [`ACCESS_SF_CRIMINAL_HF.md`](ACCESS_SF_CRIMINAL_HF.md). Loader: `bronze/jobs/load_sf_criminal_hf.py`.

## Multi-state

Architecture is national-first (`state_code` dimension). Wisconsin WCCA remains the employer MVP extract path. Research sources (`sf_criminal_hf`, gated `va_court_data_org`) do not expand product scope and are not live court scrapes.
