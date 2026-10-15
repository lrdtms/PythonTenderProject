# ADR-0006: Postgres-backed job queue, staged pipeline, idempotent and resumable stages

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
Processing a 100-page pack can take tens of minutes on CPU (OCR, then one LLM call per section). Jobs must show progress (base spec §4.1), survive worker crashes and laptop sleep, be retryable by users (FR-16), never create duplicates (§4.2, FR-59), never lose the original file, and never run OCR and LLM generation at the same time (FR-60, RAM budget).

## Decision Drivers
- Reliability and idempotency; visible progress
- No extra infrastructure (RAM, ops)
- Memory cap on a 16 GB laptop

## Considered Options
1. **`jobs` table in Postgres, claimed with `FOR UPDATE SKIP LOCKED`, leases, one worker process at concurrency 1**
2. Celery + Redis
3. FastAPI BackgroundTasks / in-process threads

## Decision Outcome
Chosen option: **Option 1**.
- **Table** `jobs(id, organisation_id, job_type, subject_id, status, attempt_count, max_attempts, run_after, lease_expires_at, locked_by, progress_done, progress_total, error_code, error_message_safe, created_at, started_at, completed_at)`.
- **Status machine:** `queued -> running -> succeeded | succeeded_with_warnings | failed`; `running` with an expired lease -> `queued` (attempt + 1); `failed` -> `queued` only via user retry.
- **No duplicate jobs:** partial unique index on `(job_type, subject_id) WHERE status IN ('queued','running')`; enqueue is `INSERT ... ON CONFLICT DO NOTHING` and returns the existing job.
- **Stages are separate job types**, each enqueuing the next in the same transaction that commits its output: `ingest` (parse/OCR, pages, chunks, embeddings) -> `extract_boq` -> `extract_requirements` (tender docs) or `extract_quotation` -> `match_suppliers`. A failure retries one stage, not the whole pipeline, and deterministic BoQ output exists even if the LLM is down.
- **Idempotent outputs:** each stage replaces its own *unreviewed* output for the document version inside one transaction. Chunks: delete-and-insert per `document_version_id` with `UNIQUE (document_version_id, ordinal)`; `text_hash` is used to reuse embeddings, not as the uniqueness key (it would merge identical text on different pages). Candidates: rows with `review_status != 'unreviewed'` are never deleted or overwritten.
- **Resumable LLM stage:** per-unit results go to `extraction_unit_results (document_version_id, unit_id, prompt_version) UNIQUE`, where a unit is an extraction section (about 1,200-1,500 tokens; see architecture.md section 5). A retry skips units already done, then runs the merge/de-dupe step.
- **Leases and heartbeats:** lease 5 min, renewed after each page/unit; a reaper on worker start-up and every minute requeues expired leases.
- **Retry policy:** transient errors (`LLM_UNAVAILABLE`, `LLM_TIMEOUT`, DB disconnect) back off 30 s / 2 min / 10 min up to `max_attempts = 3`; permanent errors (`FILE_CORRUPT`, `PDF_ENCRYPTED`, `UNSUPPORTED_TYPE`) fail immediately.
- **Concurrency 1** (one worker, one job at a time) satisfies FR-60 and the "no OCR during generation" rule. The UI polls `GET /api/v1/jobs/{id}` every 2 s.
- **Usage counting** (FR-48) increments once at upload/enqueue, in the same transaction; retries do not count.

### Consequences
- Positive: no Redis; job state is in the same backup and transaction as results; crash-safe; progress for free.
- Negative / Tradeoff: polling adds a few queries per second. Throughput is one job at a time, so a large pack blocks the queue for everyone; this is acceptable for < 10 users and shown as "queued" with position. We own ~200 lines of queue code including leases.
- Follow-ups: the design already holds for more than one worker (SKIP LOCKED); migrate to Celery/Redis only when polling or throughput hurts.

## Pros and Cons of the Options

### Option 1
- Good: transactional enqueue with business writes (no dual-write), zero new infra.
- Bad: hand-built leases/backoff; polling.

### Option 2
- Good: mature retries, scheduling, monitoring.
- Bad: +2 containers and RAM; dual-write problem between Postgres and Redis (would need an outbox); more to learn.

### Option 3
- Good: trivial.
- Bad: lost on restart, no retry or progress, blocks API memory.

## Links / References
- Base spec §4.1, §4.2, FR-15, FR-16; PRD FR-59, FR-60, FR-61; Kleppmann, *DDIA* ch. 11; PostgreSQL `SKIP LOCKED`

## Addendum 2026-10-15 (Slice 3)

- **Stage = job type.** Extraction runs as two job types, `extract_boq` and `extract_requirements`, enqueued by the ingest handler in the ingest transaction. The deterministic BoQ output is therefore committed even when the LLM is down.
- **Run records.** `extraction_runs` (module `pipeline`) holds one row per (job, kind): status, warnings, counts, `prompt_version`, `filter_version`, `schema_version`, model. The current run per (version, kind) is the latest by `created_at`.
- **Idempotency.** Re-running locks the version's run rows, deletes all `unreviewed` rows of that version and kind (from every earlier run), then inserts. Reviewed rows are never touched. A candidate that duplicates a reviewed row (BoQ: section/sheet + item number; requirements: normalised quote; corrected rows compare on `original_value`) is skipped with `DUPLICATE_OF_REVIEWED`. A rejected row suppresses re-extraction of the same item, deliberately.
- **Not built.** `extraction_unit_results` (per-window resumability) is dropped for this slice: a window is a few seconds to a minute of work and the whole stage restarts on retry. F6 (kill mid-stage, resume without duplicates) is met by replace-unreviewed.
