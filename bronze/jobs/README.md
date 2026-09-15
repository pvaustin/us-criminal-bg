# Bronze jobs

Weekly WCCA → Bronze job stub lives here once Databricks Jobs / notebooks are wired.

Proposed cadence: weekly. Orchestration may be a Grok Bot routine — **paused until Prasanth explicitly enables**.

Job responsibilities:
1. Create `ingest_run` row (status=running)
2. Land files under the volume path from `docs/bronze/NAMING.md`
3. Upsert `court_case_raw` on `(source_system, state_code, source_record_id)`
4. Finalize `ingest_run` (status + row_count)

No CAPTCHA bypass. Prefer `manual_upload` / `interactive_export` until paid REST is subscribed.
