# Market analysis + client personas

**Status:** Draft for Prasanth review · 2026-09-15 (CT)  
**Owner:** PM Pam · **Does not change:** locked AC1→AC3 engineering bar (Uma continues AC2)

## Market snapshot (directional)

Public estimates for US employment / background screening vary by scope; treat as order-of-magnitude, not a forecast we own:

| Signal | Figure (source) | Use for us |
| --- | --- | --- |
| US employment screening services | ~**$2.4B** in 2026, ~6.5% CAGR to 2033 ([Persistence Market Research](https://www.persistencemarketresearch.com/market-research/us-employment-screening-services-market.asp)) | Employer CRA category is large and compliance-driven |
| Broader US background-check services (incl. tenant) | ~**$3.2B** in 2026 ([IBISWorld](https://script.ibisworld.com/united-states/industry/background-check-services/6058/)) | Adjacent categories; we are not tenant screening |
| Employer practice | SHRM 2025 cited: **~82%** of employers run criminal checks in hiring (via PMR summary) | Demand for *some* criminal check is near-universal among employers who screen |
| Regulatory pressure | FCRA disclosure/auth/adverse-action; EEOC; 37+ states / 180+ localities with fair-chance / ban-the-box (PMR summary); WI arrest/conviction rules ([DWD](https://dwd.wi.gov/er/civilrights/discrimination/arrest.htm), [Wis. Stat. 111.335](https://law.justia.com/codes/wisconsin/chapter-111/section-111-335/)) | Compliance is a purchase driver *and* a lawsuit risk; overclaiming kills pilots |

**Wisconsin WCCA reality (product-defining):** WCCA/CCAP is **free public circuit-court docket** access — case events, charges, dispositions, parties — **not** a national criminal database, **not** arrest records, **not** certified copies. Coverage and retention vary; dismissed/acquitted criminal cases generally drop after ~2 years. Important results are still verified with the county Clerk of Court ([WI Law Library](https://wilawlibrary.gov/learn/wlaWCCA.pdf), [Legis brief](https://docs.legis.wisconsin.gov/misc/lc/issue_briefs/2019/courts_and_criminal_law/ib_court_records_ph_2019_10_01)).

**Strategic implication:** Our wedge is **honest WI docket infrastructure** (search → party match/review → provenance → audit). Full CRA / multi-state / certified history is a later product decision, not the MVP claim.

---

## Persona 1 — Employers (HR / hiring managers)

**Beachhead recommendation:** **Near-term primary** (current MVP default).

| Lens | Assessment |
| --- | --- |
| **Job-to-be-done** | Before advancing a hire, see whether a candidate appears in WI circuit court criminal dockets, with clear provenance and an audit trail, without the team hand-searching WCCA. |
| **Willingness to pay (signals)** | Already budget for screening or CRA fees; pay for time saved, auditability, and lower compliance mistake risk. Price sensitivity highest among small WI employers; larger employers may stay on national CRAs unless we are cheaper for a WI add-on or faster for WI-only roles. |
| **Must-have surfaces** | Order/subject capture, consent path (even if placeholder→real), report with case/charge/provenance, match/review for ambiguous parties, search audit log, explicit “dockets ≠ certified history” labeling. |
| **Nice-to-have** | Metrics dashboard, dispute polish, SSO/RBAC, multi-user seats, integrations (ATS). |
| **FCRA / compliance sensitivity** | **Highest.** If we furnish reports for employment purposes as a CRA, FCRA disclosure, authorization, accuracy duties, and adverse-action process apply ([FTC employer guidance](https://www.ftc.gov/business-guidance/blog/2017/04/background-checks-prospective-employees-keep-required-disclosures-simple)). WI also constrains arrest vs conviction use in hiring. **MVP posture:** labeled pilot, no CRA/adverse-action claims until Prasanth + Charlie decide. |
| **Does WI-first MVP serve them?** | **Yes — if they hire for WI roles or need WI court depth.** Weak for employers who need 50-state CRA packages on day one. |

---

## Persona 2 — Recruiters / staffing agencies

**Beachhead recommendation:** **Next** (same data plane; different packaging, volume, and SLAs).

| Lens | Assessment |
| --- | --- |
| **Job-to-be-done** | Run repeatable WI checks across many candidates/clients with consistent turnaround, clear deliverables they can pass to employer clients, and billing that fits agency margins. |
| **Willingness to pay (signals)** | High volume, per-check or seat pricing; will pay for speed, API/bulk, white-label or client-ready PDFs, and fewer support tickets. More sensitive to unit cost than a single employer. |
| **Must-have surfaces** | Bulk/queue ordering, status at scale, report export, client/account separation, audit by client, match/review that doesn’t bottleneck every hit. |
| **Nice-to-have** | API, webhooks, reseller portal, multi-state later, branded reports. |
| **FCRA / compliance sensitivity** | **High** (often acting for employer clients). Same CRA/employment-purpose risks; plus contractual flow-down to end employers. Need crystal-clear “what this report is / isn’t.” |
| **Does WI-first MVP serve them?** | **Partially.** Useful as a WI specialty feed; not enough alone if clients demand national packages. Build **after** employer loop works (order → match/review → report → audit). |

---

## Persona 3 — Individuals (self-check / personal records access)

**Beachhead recommendation:** **Later horizon** (different UX, trust, and often different legal packaging).

| Lens | Assessment |
| --- | --- |
| **Job-to-be-done** | “What does WI court have on me?” before a job application, housing, or peace of mind — or to prepare to dispute errors. |
| **Willingness to pay (signals)** | Consumer one-off or subscription; lower AOV than B2B; high marketing CAC risk; competitors include free WCCA self-search and consumer “background check” apps of uneven quality. |
| **Must-have surfaces** | Simple self-serve search, identity proofing (to avoid doxxing others), plain-language results, download/history, dispute education — **not** employer order/consent flows. |
| **Nice-to-have** | Alerts on new cases, multi-state later, credit-adjacent bundles (out of scope). |
| **FCRA / compliance sensitivity** | **Different shape.** A person reviewing their own public dockets is not the same as an employer procuring a consumer report for hiring. If we later sell “share with employer” or operate as a CRA, FCRA snaps back on. Abuse risk (searching other people) needs product/legal controls. |
| **Does WI-first MVP serve them?** | **Data yes, product no.** Same Silver dockets could power a consumer UI later; current employer order / match-decision / pilot operator model is the wrong primary UX. |

---

## Who owns near-term build vs later

| Persona | Horizon | What we build now |
| --- | --- | --- |
| **Employers (HR / hiring mgrs)** | **Now — beachhead** | AC2 review queue, AC3 subject + audit, report/metrics regression, compliance labels |
| **Recruiters / staffing** | **Next** | Volume UX, exports, multi-client audit — after employer path is proven |
| **Individuals** | **Later** | Separate self-serve product + identity rules; do not bend MVP into consumer app |

**Engineering note:** Charlie owns sequencing; Uma AC2 continues regardless of beachhead lock. Persona choice changes **messaging, GTM, and Next roadmap packaging**, not the AC1→AC3 bar.

## Decision (locked)

**Primary beachhead locked 2026-09-15:** Employers (WI HR / hiring managers).

Staffing = Next · Individuals = Later.

Optional still open (not blocking): paid WCCA API timing; any hard “never claim X” lines for demos.
