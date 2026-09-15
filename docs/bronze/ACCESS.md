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

## Multi-state

Architecture is national-first (`state_code` dimension). Do not add live extractors for other states until product explicitly expands scope.
