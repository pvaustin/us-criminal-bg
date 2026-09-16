# Virginia — virginiacourtdata.org (research notes)

**Status:** Spike paused. Research-only. **Not** employer product. **Not** for commercial CRA / FCRA claims. **No Bronze load.**

This is a source-access note so Prasanth / Charlie can decide whether to request named data. It is **not** a loader spec. Do not treat anything here as landed court facts.

## Provenance

- **Site:** https://virginiacourtdata.org/
- **What it is:** Independent hobby third-party redistribution of Virginia Circuit and District public dockets (CSV zip downloads). Site copy states it is **not** affiliated with the Commonwealth of Virginia or Virginia’s Court System, and is **not** an official bulk license.
- **Last update noted on site (verified):** April 4, 2025 — “All cases heard through the end of 2024 have been added.”
- **Field reference:** https://virginiacourtdata.medium.com/virginia-court-data-fields-e224a9a41e15 (Mar 24, 2017; amateur observations, not legal definitions)
- **Contact published on site:** info@virginiacourtdata.org
- **Format:** Compressed CSV. Files with more than 250,000 cases are split. Public “raw” CSVs are organized by filed date; criminal “by defendant” files are a separate reorganization (see below).

## Critical access split (verified from site copy)

1. **Public downloads (anonymized).** Site states **case numbers, names, and dates of birth have been removed** from public CSVs. These files are **not** suitable for `court_party` / name-match research. Do **not** treat them as a named corpus. Do **not** load anonymized public files into Bronze for name-match.

2. **Requestable named / un-anonymized.** Site copy: journalists, or people who work for a non-profit, research institution, or government body, may request un-anonymized data by creating a **free** account and providing a few pieces of information; requests are reviewed (“we’ll be in touch”). Even in the full dataset, **DOB year is censored on the state website**; schema docs set year to **1004** (a leap year). Prefer this path **only if** access stays free and a legitimate approval is granted.

Hard rule: **published files only.** Do **not** scrape Virginia court websites (official or otherwise). Do **not** invent records.

## Proposed identifiers (if named export is later approved)

Provisional until named export exists. Do not create catalogs, volumes, jobs, or fixtures for this source beforehand.

| Identifier | Value |
|------------|--------|
| `source_system` | `va_court_data_org` |
| `state_code` | `VA` |
| `extract_method` | `rest_bulk` — published zip-CSV download, **not** a court scrape and **not** an official Commonwealth bulk license |

Natural key / `source_record_id` composition is **not** defined here. Document it in `sources/` only when a real named sample lands (likely `fips` + `CaseNumber` per the field post; Case Number is unique **within a court**, not statewide).

## Field inventory (from Medium field post — full schema; public files redact PII)

Source: [Virginia Court Data Fields](https://virginiacourtdata.medium.com/virginia-court-data-fields-e224a9a41e15). Author is not a lawyer; value lists are observations. Nearly every field can be empty. Enumerated value lists live in that post; this inventory is the **field set**, not a recitation of every code.

**Public-file redaction (site copy):** `CaseNumber`, names, and DOB are removed from public CSVs. Named export (if approved) is the only path that could populate party/name fields. Race is in the source schema; Silver `court_party` does **not** persist race and matching must not require it.

Exports are the **primary case table** plus the **most recent hearing**. Full child tables (all hearings, pleadings/orders, services) are **not** in the standard files.

### Circuit Criminal

One primary table; child tables: hearings, pleadings, services.

| Field | Notes |
|-------|--------|
| `fips` | Court FIPS (circuit court list linked from the field post) |
| `CaseNumber` | Case number (redacted in public files) |
| `Filed` | File date |
| `Commencedby` | How the case commenced (enumerated) |
| `Locality` | Locality |
| `Defendant` | Defendant name (redacted in public files) |
| `AKA`, `AKA2` | Aliases (redacted in public files) |
| `Sex` | `Female` / `Male` |
| `Race` | Enumerated on source; **not** a Silver match key |
| `DOB` | Year censored on the state site; schema sets year to **1004** |
| `Address` | City and zip (not a full street address) |
| `Charge` | Free-form charge |
| `CodeSection` | State or local law citation |
| `ChargeType` | e.g. Felony / Misdemeanor / Infraction / … |
| `Class` | Charge class |
| `OffenseDate`, `ArrestDate` | Dates |
| `DispositionCode`, `DispositionDate`, `ConcludedBy` | Disposition |
| `AmendedCharge`, `AmendedCodeSection`, `AmendedChargeType` | Amended charge |
| `JailPenitentiary`, `ConcurrentConsecutive`, `LifeDeath` | Sentence shape |
| `SentenceTime`, `SentenceSuspended` | Days |
| `OperatorLicenseSuspensionTime` | Days |
| `FineAmount`, `Costs`, `FinesCostPaid` | Money / paid flag |
| `ProgramType`, `ProbationType`, `ProbationTime`, `ProbationStarts` | Programs / probation (`ProbationTime` = 36135 for indefinite) |
| `CourtDMVSurrender`, `DriverImprovementClinic`, `DrivingRestrictions` | License-related |
| `RestrictionEffectiveDate`, `RestrictionEndDate` | Restriction window |
| `VAAlcoholSafetyAction` | Flag |
| `RestitutionPaid`, `RestitutionAmount` | Restitution |
| `Military`, `TrafficFatality`, `AppealedDate` | Other |

Most recent hearing columns in the export: `Date`, `Type`, `Room`, `Plea`, `Duration`, `Jury`, `Result`.

### District Criminal

One primary table; child tables: hearings, services.

| Field | Notes |
|-------|--------|
| `fips` | Court FIPS (district court list linked from the field post) |
| `CaseNumber` | Case number (redacted in public files) |
| `FiledDate` | File date |
| `Locality` | Locality |
| `Name` | Defendant name (redacted in public files) |
| `Status` | e.g. Adult / Minor / Custody / … |
| `DefenseAttorney` | Attorney name / public defender variant |
| `Address` | City and zip |
| `AKA1`, `AKA2` | Aliases (redacted in public files) |
| `Gender` | `Female` / `Male` / Other (includes N/A, unknown) |
| `Race` | Enumerated on source; **not** a Silver match key |
| `DOB` | Year censored; schema sets year to **1004** |
| `Charge` | Free-form charge |
| `CodeSection` | State or local law citation |
| `CaseType` | e.g. Felony / Misdemeanor / Infraction / … |
| `Class` | Charge class |
| `OffenseDate`, `ArrestDate` | Dates |
| `Complainant` | Complainant |
| `AmendedCharge`, `AmendedCodeSection`, `AmendedCaseType` | Amended charge |
| `FinalDisposition` | Disposition |
| `SentenceTime`, `SentenceSuspended` | Days |
| `ProbationType`, `ProbationTime`, `ProbationStarts` | Probation |
| `OperatorLicenseSuspensionTime` | Days |
| `RestrictionEffectiveDate`, `RestrictionEndDate`, `OperatorLicenseRestrictionCodes` | License restrictions (codes may be comma-combined) |
| `Fine`, `Costs`, `FineCostsDue`, `FineCostsPaid`, `FineCostsPaidDate`, `FineCostsPastDue` | Money / due / paid |
| `VASAP` | Flag |

Most recent hearing is included the same way as circuit criminal.

### `person_id` / by-defendant reorganization

From the field post and [Data Quality: Part I — Names](https://virginiacourtdata.medium.com/data-quality-part-i-names-a4d48522f5ce) (Jun 15, 2017):

- A hobby `person_id` is attached to criminal cases. A separate download set is **circuit + district criminal reorganized by defendant** (`person_id`) instead of most-recent-hearing date.
- Methodology (hobby, not official identity): compare names that share **DOB** (year already censored), **sex**, and the **first two letters of last name**; FuzzyWuzzy `partial_ratio`; address used when name scores are ambiguous (~80–90). IDs stored in a junction table.
- **Do not** treat `person_id` as our identity graph, as a `court_party` grain, or as a certified same-person key.

### Coverage gaps (site copy)

- **Alexandria and Fairfax circuit** data are **not available**.
- April 2019: ~100,000 duplicate cases removed (see site / Medium duplicate note).
- January 2025 find: District **Civil** cases heard April–June 2022 were missed in collection and added April 2025 (civil; noted for completeness, not a criminal name-match input).

Circuit/District **civil** files also exist on the site (eviction/debt reporting is a common third-party use). They are **out of scope** for this name-match spike.

## Status

- Spike **paused** pending Prasanth / Charlie: **request named access** (free account, legitimate journalist / non-profit / research / government approval) **vs pivot**.
- **No anonymized load** into Bronze for name-match.
- **No loader**, no Databricks download job, no CSV in git, no invented sample records.
- If named export is approved later: land published zip-CSV only under `source_system=va_court_data_org`, `state_code=VA`, `extract_method=rest_bulk`, and extend [`NAMING.md`](NAMING.md) natural keys then — not before.
