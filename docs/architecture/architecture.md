# IntelTPS Architecture (v1.0, 15 Oct 2026)

Formalises PRD v0.2. Decisions are in [adr/](adr/README.md); diagrams in [diagrams/](diagrams/). Where this document and the PRD differ, the "PRD issues" section explains why.

## 1. Overview

IntelTPS is a **modular monolith** (FastAPI) plus **one background worker** that use the same code. A Next.js frontend sits beside them, and everything is served from a single origin through Caddy (ADR-0001, ADR-0009). **PostgreSQL** is the only database. It holds relational data, the job queue, chunk vectors (pgvector) and keyword indexes (tsvector) (ADR-0002, ADR-0006). The LLM (native Ollama) and the embedding model sit behind ports configured by environment variables (ADR-0003). Uploaded files sit behind a storage port on a local volume (ADR-0007). The public link is a Cloudflare Tunnel to the laptop.

Diagrams: [C1 Context](diagrams/c4-context.md) | [C2 Containers](diagrams/c4-container.md) | [C3 Backend components + allowed dependencies](diagrams/backend-components.md)

**Quality attributes, in priority order:**
1. **Tenant isolation and privacy.** Leaks are unrecoverable. BR-05 and POPIA apply.
2. **Correctness of critical fields.** Quantities, units, money and provenance must be right (BR-02, BR-03).
3. **Recoverability of processing.** Jobs must be idempotent, resumable and visible (§4.2).
4. **Deliverability.** 4 people work in parallel for 32 days.
5. **Portability.** Moving from the laptop to a VM is a config change.

Raw performance comes last. We deliberately give it up: one job at a time, exact vector search, and CPU inference.

## 2. Module boundaries

Each backend module is a package `modules/<name>/` containing `public.py` (the only importable surface), `domain/` (pure rules), `service.py`, `repo.py` (tenant-scoped) and `schemas.py` (DTOs). Each module owns its tables, and no other module reads or writes them.

| Module | Owner | Responsibility | Public interface (sketch) | Owns tables |
|---|---|---|---|---|
| `kernel` | M1 | Shared types and ports. No I/O | `OrgContext`, `Role`, `SourceRef`, `Money`, `DomainError`s, `LLMPort`, `EmbeddingPort`, `StoragePort`, `JobQueuePort` | none |
| `identity` | M1 | Users, organisations, memberships, invites, sessions, RBAC | `resolve_context(user_id, org_id) -> OrgContext`, `require_role(ctx, *roles)`, `list_members(ctx)` | users, organisations, memberships, invites, refresh_tokens |
| `billing` | M1 | Plans and limits (mocked) | `check_and_increment(ctx, metric)` raises `LimitExceeded`; `usage(ctx)` | plans, organisation_usage |
| `audit` | M1 | Append-only events, with no document text | `record(ctx, entity_type, entity_id, action, safe_metadata)` | audit_events |
| `tenders` | M1 | Tender workspace and archive | `get(ctx, tender_id) -> TenderDTO` (404 if other org) | tenders |
| `documents` | M1 | Upload validation, versions, file access | `upload(ctx, tender_id, kind, file) -> (DocumentVersionDTO, job_id)`, `get_version(ctx, id)`, `open_original(ctx, version_id)`, `current_versions(ctx, tender_id)` (downloads are an authenticated same-origin endpoint, not signed links) | documents, document_versions |
| `knowledge` | M2 | Parse, OCR, page text and tables, chunking, embeddings, **the only retrieval path** | `ingest(ctx, version_id, progress) -> IngestResult`, `get_tables(ctx, version_id)`, `iter_sections(ctx, version_id)`, `search(ctx, tender_id, query, k) -> [ChunkHit]` | document_pages, document_chunks |
| `extraction` | M2 | **Pure core.** BoQ table parser, LLM prompts and schemas, validators, evidence check, merge/de-dupe | `parse_boq(pages) -> BoqResult`, `prefilter(pages, ...) -> PrefilterResult`, `extract_requirements(windows, llm, ...) -> ExtractOutcome`, `merge_requirements(cands)`, `attach_provenance(cands, pages)`, `locate(quote, pages)`. Quotation parsing (`parse_quotation`) arrives in Slice 5; there is no LLM refinement step for BoQ | none (pure core) |
| `pipeline` | M2 | Extraction run lifecycle, extraction trigger and routing by document kind | `start_run(ctx, job, kind, ...)` (creates or resets the run), `run_for_job`, `lock_runs`, `finish_run(ctx, job_id, kind, warnings, counts)`, `fail_run(ctx, job_id, kind, error_code)`, `current_runs(ctx, version_id)`, `request_extraction(ctx, version_id, deep_scan)`, `extraction_status(ctx, version_id)` | extraction_runs |
| `estimating` | M4 | BoQ items and review | `replace_unreviewed(ctx, version_id, cands)`, `version_of(ctx, id)`, `review_item(ctx, id, action, patch)` (BoqPatch DTO; correct, confirm, reject), `list_boq_items(ctx, version_id)` | boq_items |
| `estimates` | M4 | Pricing defaults, estimates and lines, Decimal calculations (pure `calc.py`), review, approval, readiness gate | `get_defaults`, `save_defaults`, `create_estimate(ctx, tender_id, boq)`, `get_estimate`, `list_estimates`, `patch_estimate`, `price_line`, `refresh_line`, `review_estimate`, `reopen_estimate`, `approve_estimate`, `readiness` | pricing_defaults, estimates, estimate_lines |
| `suppliers` | M4 | Suppliers, quotations, deterministic matching, confirm/reject | `replace_quotation_items(ctx, quotation_id, cands)`, `suggest_matches(ctx, tender_id)`, `decide(ctx, suggestion_id, confirm/reject)` | suppliers, supplier_quotations, quotation_items, match_suggestions |
| `checklist` | M1 | Requirements review, checklist, tasks, deadlines, reminders | `replace_unreviewed(ctx, version_id, cands)`, `version_of(ctx, id)`, `review_item(ctx, id, action, patch)` (RequirementPatch DTO; correct, confirm, reject), task CRUD | requirements, tasks, reminders |
| `reporting` | M4 | Excel/PDF exports with status and version | `create_export(ctx, tender_id, kind) -> ExportDTO` (approved-only unless labelled draft) | exports |
| `qa` (stretch) | M2 | Grounded Q&A | `ask_stream(ctx, tender_id, question) -> AsyncIterator[Event]` | chat_queries |
| `worker/` | M2 | Job loop, stage orchestration, leases | job handlers per `job_type` | jobs (queue adapter) |
| `api/` | each owner for their routers | HTTP, auth dependency, error format, OpenAPI | `/api/v1/...` | none |

## 3. Dependency rule

- Dependencies point inward: `api`/`worker` -> `modules` -> `kernel`. Adapters in `infrastructure/` implement kernel ports and are wired only in `api/main.py` and `worker/main.py`.
- Modules import other modules **only through `public.py`**, and only along the arrows in [backend-components.md](diagrams/backend-components.md). The graph has no cycles.
- `extraction/` and every `domain/` package import neither `fastapi` nor `sqlalchemy`.
- Cross-module data travels as Pydantic DTOs, never ORM objects.
- The rules are enforced by **import-linter** in CI (fitness function F2).

## 4. Tenant isolation stress test

Controls are defined in ADR-0005. Each attack path below names the control and the test that proves it.

| Attack / failure path | Control | Proof (test) |
|---|---|---|
| Guess another org's tender/document/BoQ ID | `get(ctx, id)` filters by org and returns 404; UUIDs | F1 route sweep |
| Forget a `WHERE organisation_id` in a new query | All repos extend the scoped base; review checklist; CI check that bans `session.execute(` outside `infrastructure/db` and `*/repo.py` | F1, F2 |
| Child row attached to another org's parent (e.g. BoQ item to a foreign tender) | Composite FKs `(organisation_id, parent_id)` | F3 schema test + DB rejects |
| Retrieval returns another org's chunks | `knowledge.search` filters org + tender + current version **inside both CTEs before RRF**; no unscoped search function exists | F4 canary retrieval test |
| Q&A cites a chunk the user may not see | Citations are mapped by code from the retrieved set only | F4 |
| Stale or superseded document version answers (BR-06) | `is_current` join in search; extraction is tied to a version | F4 variant |
| Worker writes results under the wrong org | Job row carries `organisation_id`; ctx comes from the job, never from content; composite FKs | F5 |
| File URL shared or guessed | Server-generated `org/{id}/...` keys; HMAC link bound to org, version, user, 5-min expiry; membership re-check | F1 (expired/foreign token) |
| Removed user keeps access | Role and membership read from DB each request; refresh family revoked | security test |
| Platform admin browses tenant docs | No such endpoint in MVP | route inventory review |
| Document text leaks into logs or audit | Structured logs carry IDs only; audit `safe_metadata` allowlist | F9 canary-in-logs |
| HNSW post-filtering drops results (correctness, not a leak) | No ANN index in MVP (ADR-0002) | retrieval hit-rate metric |

## 5. AI pipeline and failure paths

**Stages (each its own job, ADR-0006):** `ingest` -> `extract_boq` -> `extract_requirements` (tender docs) / `extract_quotation` (quotes) -> `match_suppliers`. Each stage commits its outputs and enqueues the next stage in one transaction.

**As built in Slice 3.** Ingest enqueues the extraction jobs for the document's kind in one transaction: a tender document gets `extract_boq` and `extract_requirements` (two independent job types, so one can fail or be retried without the other), a `boq` document gets `extract_boq` only, and a quotation gets none yet. `POST /api/v1/document-versions/{id}/extract` re-enqueues them (optionally with `deep_scan`). The `pipeline` module records one `extraction_runs` row per job and kind (status, prompt/filter/schema versions, model, warnings, counts) and `GET .../extraction` reports job and run per kind. Re-runs replace only unreviewed rows. The worker reaches the host's Ollama through `LLM_BASE_URL` (Compose default `http://host.docker.internal:11434`; local non-Docker runs use `http://127.0.0.1:11434`) and the model comes from `LLM_MODEL`. Real-stack scores: `docs/spikes/slice-3-scores.md`.

**As built in Slice 4 phase 1 (review API).** `PATCH`, `POST .../confirm` and `POST .../reject` exist for `/boq-items/{id}` and `/requirements/{id}` (admin and estimator only; audit stores field names, not values). The router calls `version_of`, refuses the write with 409 `tender_archived` if the tender is archived (archived tenders are read-only, as everywhere else), takes `pipeline.lock_runs` for that version and kind, and then `review_item` re-reads the row under the lock: an unknown id is 404, a row deleted by a re-run in between is 409 `row_replaced`. Review actions may be applied from any state; none returns a row to unreviewed (so every transition to `confirmed`, `corrected` or `rejected` is allowed, and that is the whole transition rule). `original_value` is immutable; the main columns always hold the effective value and `corrected_value` holds only the changed fields. DTOs also carry `reviewed_by`, `reviewed_by_name` (via `identity.member_names`) and `reviewed_at`. Lists order by `(source_order, position, id)`; `GET /tenders/{id}/requirements`, `GET /document-versions/{id}` and a row window on page detail serve the review UI. `POST .../extract` returns distinct 409 codes: `tender_archived`, `not_processed`, `extraction_options_conflict`.

**Two retry layers. Define them once and do not mix them:**
- *Call level* (inside a stage): one LLM call that returns invalid output is retried **once** (FR-56) with the validation error appended. If it fails again, that chunk/row is flagged and the stage continues.
- *Job level*: transient infrastructure errors retry up to 3 attempts with backoff. Permanent errors fail immediately. Users can retry failed jobs (FR-16).

| Failure | Detected by | System behaviour | User sees |
|---|---|---|---|
| Wrong type / oversize / encrypted / corrupt file | `python-magic` sniff + size check at upload; parser open fails in `ingest` | Upload rejected (4xx), or job `failed` with `FILE_CORRUPT` / `PDF_ENCRYPTED` and no retries. Original file kept | Clear error with a "replace file" action |
| OCR fails on a page (crash, timeout, blank) | Per-page try/timeout (60 s) | Page marked `ocr_failed`, other pages continue. If more than 30% of pages fail, the job ends `succeeded_with_warnings` | "Pages 12-14 could not be read", with a link to the source |
| OCR low confidence | Tesseract mean confidence < threshold | Page `low_confidence`; its candidates get `needs_review`; BoQ from scanned pages is never auto-extracted (FR-55) | Amber badge on the page and its fields |
| Ollama down or not loaded | Connection error / 404 model | `LLM_UNAVAILABLE`, transient job retry. **Deterministic BoQ output from earlier stages is already saved** | "AI step waiting / retrying"; BoQ lines are already editable |
| LLM timeout (slow CPU) | `LLM_TIMEOUT_S` (e.g. 180 s) and a `num_predict` cap | Retry the call once. If it still fails, the section is marked `not_analysed` and the stage continues. The job ends `succeeded_with_warnings` | "3 sections not analysed: retry or review manually" |
| Output truncated | `done_reason == "length"`, or prompt tokens close to `num_ctx` | Treated as invalid output (see next row). Section sizes are set so that prompt + schema + output stay under `num_ctx` | as below |
| Invalid structured output | JSON parse / Pydantic error | Retry once with the error message, then `LLM_INVALID_OUTPUT` on that section and the stage continues | Section flagged for manual entry |
| Valid JSON, wrong values | Business validators (numeric quantity, known unit, currency, dates); `evidence_quote` not found in the section | Candidate kept with flags (`missing_unit`, `evidence_unverified`). Missing values are stored as `NULL` + flag, never 0 | Flags beside each field; nothing is auto-approved (BR-01) |
| Prompt injection in a document | Document text sits in a delimited data block; no tools; output must match the schema | At worst a bad candidate, caught by review and evidence checks | Normal review |
| Duplicate job (double click, re-upload, retry while running) | Partial unique index on active `(job_type, subject_id)` | Enqueue returns the existing job | Same progress bar |
| Worker crash / OOM kill / laptop sleep | Lease expiry (5 min) | Reaper requeues the job. The stage resumes: chunks with stored results are skipped | Job returns to "running" |
| Re-run after the user has edited results | Stage replace logic | Only `unreviewed` rows are replaced. Reviewed or corrected rows are never touched | Edits preserved |
| Plan limit reached | `billing.check_and_increment` at upload | 402/403 with the `LIMIT_EXCEEDED` error code; nothing stored | Usage page link |

**Throughput reality check (needs measuring on day 1).** A 3-4B Q4 model on the laptop CPU or a partially offloaded GTX 1050 processes prompts at about 30-80 tokens/s and generates at 5-15 tokens/s. With FR-61 mapped over 300-450-token retrieval chunks, a 100-page pack (~150 chunks) needs about 150 calls x 20-55 s, which is **1-2+ hours**. Recommendation: run requirement extraction over **sections of about 1,200-1,500 tokens** (separate from the retrieval chunks; still "every section", so FR-61's recall intent holds). That is about 35 calls and roughly 25-40 minutes. Page provenance comes from locating the `evidence_quote` in the page text. Disable Qwen3 "thinking" output (`think: false`), or it spends tokens on reasoning. Pre-process demo documents.

**Measured update (spikes M2-1, M2-1b, M2-1c; synthetic data, Qwen3-4B).** Generation runs at about 15 tokens/s and time is driven by output length, not input. Sending every section to the LLM takes about 100 minutes for a 96-page pack. A deterministic pre-filter (obligation, date, grade, amount, standard and period triggers, plus one sentence of context) sends about 3% of the text and finishes in about 3 minutes with equal or better recall on the packs tested, so **FR-61 now means pre-filter then LLM, with a manual deep scan as the fallback**. The filter's recall on real tenders is unknown and must be measured; filter recall is reported separately from LLM recall. The extraction prompt (v3) defines a tenderer requirement, each type and each status; see `docs/spikes/m2-1c-prompt-evaluation.md`.

## 6. Fitness functions (run in CI unless noted)

| ID | Fitness function | Guards |
|---|---|---|
| F1 | **Cross-tenant route sweep.** Seed orgs A and B; for every route with an ID parameter, call it as A with B's IDs and expect 404, with no data in the body. New routes are picked up from the FastAPI route table automatically | BR-05, FR-05 |
| F2 | **Import boundaries.** import-linter contracts (layers, facade-only, pure `extraction`/`domain`) plus a check that bans raw `session.execute` outside the repo layer | Dependency Rule |
| F3 | **Schema tenancy.** Introspect SQLAlchemy metadata: every table not on an allowlist (`users`, `plans`) has a non-null `organisation_id`, and every FK to an org-owned parent is composite | ADR-0005 |
| F4 | **Cross-tenant retrieval canary.** A and B hold near-identical packs; B's pack contains a unique canary string. Searching or asking in A for the canary returns 0 B chunks; searching with B's `tender_id` as A returns 404; superseded versions never appear | FR-58 |
| F5 | **Worker tenancy.** A job for org A cannot write rows with org B (composite FK violation is asserted) | ADR-0005 |
| F6 | **Idempotent re-ingestion.** Run every stage twice: identical row counts. Run, correct one BoQ item, re-run: the correction survives. Enqueue twice concurrently: one job. Kill the worker mid-stage: resume with no duplicates | FR-59, §4.2 |
| F7 | **Deterministic calculations.** Golden-file and property-based (Hypothesis) tests of totals, markup, VAT on/off and rounding; same input gives the same output; a check that bans `float` in `estimates/` | BR-03, FR-28 |
| F8 | **Provenance by construction.** LLM output schemas contain no `document_id`/`page` fields; every persisted candidate has a `SourceRef` or a flag | FR-56, BR-02 |
| F9 | **Log hygiene.** Process the canary document and assert the canary text is absent from logs and `audit_events` | §4.2, POPIA |
| F10 | **AI regression (manual/nightly, not per PR).** The §13 evaluation script on the synthetic set; fail the release if critical-field metrics drop more than 3 points. CI uses `FakeLLM` fixtures | §13 |
| F11 | **Performance smoke.** Upload of a 20 MB file confirmed in < 5 s; Excel export of 1,000 lines in < 10 s; search p95 < 300 ms on 20k chunks | §4.1 |

## 7. Team split and parallel work

Conway's Law: four owners, four seams. **Contract freeze by end of day 4:** `kernel` types, ERD v1 (with `organisation_id` and composite FKs), job types and statuses, candidate DTOs (`BoqCandidate`, `RequirementCandidate`, `QuotationItemCandidate`, `SourceRef`), error format, and an OpenAPI stub. The frontend generates a TypeScript client from OpenAPI and builds against mocks.

| Member | Owns | Front-loaded work | Interfaces they publish first |
|---|---|---|---|
| **M1 Platform & trust** | kernel, identity, billing, audit, tenders, documents, checklist; F1/F3/F4/F5/F9; **evaluation set + script (recommended, see issue 14)** | Days 1-4 ground-truth JSON schema; days 5-12 auth/tenancy/upload; days 18-21 checklist | `OrgContext`, scoped repo base, `documents.upload`, `audit.record` |
| **M2 Ingestion & AI** | knowledge, extraction, worker/queue, LLM/embedding adapters, qa (stretch); F6/F8 | Day 1 spike: Ollama from a container, tokens/s, structured output; day 2 RRF spike | `IngestResult`, `ChunkHit`, candidate DTOs, `FakeLLM` fixtures |
| **M3 Frontend** | Next.js app, PDF.js review view, BoQ editor, comparison, checklist UI, stream reader (stretch); Playwright journeys | App shell, auth pages, review layout against mocks | UI states for draft/processing/failed/approved |
| **M4 Estimating & delivery** | estimating, suppliers, reporting; Compose, Caddy, tunnel script, backup/restore, CI (pytest, ruff, import-linter); F2/F7/F10/F11 | Days 1-4 repo, CI, Compose skeleton; days 13-17 BoQ + calcs | `EstimateDTO`, export formats, CI gates |

Workload risk: M3 is the only frontend developer for about 8 screens. Mitigation: each backend owner writes the Playwright journey for their own flow, and M3 owns shared components.

## 8. PRD v0.2 issues and risks found (prd.md not edited)

1. **FR-59 idempotency key is flawed.** `(document_id, document_version, text_hash)` merges identical text appearing on different pages (losing the second page's provenance). It also leaves stale chunks behind when chunking parameters change. Use replace-set per version with `UNIQUE(document_version_id, ordinal)`; `text_hash` is only for embedding reuse (ADR-0006).
2. **Idempotency is missing for structured outputs.** Re-running extraction could duplicate BoQ items/requirements or overwrite human corrections. Rule: replace only `unreviewed` rows (ADR-0006).
3. **`organisation_id` on child tables.** The base spec omits it on requirements, BoQ items, quotation items, tasks and extraction jobs. PRD §8 says "every organisation-owned record"; make this explicit and add composite FKs.
4. **Environment wording is stale.** §6 ("deployed VM acts as staging/production") and the §7 diagram ("Blob when deployed") conflict with the §21 decision (laptop + tunnel). Production is the tunnelled laptop, and "tested in staging" means tested via the tunnel URL.
5. **Two exposure stories.** §9 suggests calling FastAPI directly with CORS; §21 says to tunnel only the frontend or Caddy. Resolved: single origin via Caddy (ADR-0009).
6. **POPIA and the tunnel.** Cloudflare terminates TLS at its edge, which may be outside South Africa. That makes it a processor that sees plaintext, so it is a cross-border consideration, not just "hosting region" (§12). Keep synthetic data only and document this in the assessment.
7. **No processing-time target, and FR-61 is costly on CPU** (section 5; resolved by the pre-filter, see the measured update above). Suggested NFR: "100-page native pack fully processed in < 45 min on the reference laptop, with progress visible."
8. **Retry semantics undefined.** FR-56 "retry once" and job `attempt_count` are different layers; they are defined in section 5.
9. **JWT role claims go stale** after role change or deactivation. Roles are loaded from the DB instead (ADR-0008).
10. **Retrieval must filter to the current document version** (BR-06). FR-52/58 mention only the tenant filter.
11. **One Ollama serves both worker and Q&A.** Questions queue behind extraction. Pause the worker during Q&A demos.
12. **The RAM budget assumes the Next.js dev server.** Demo with `next build && next start`. Also, Ollama may need `OLLAMA_HOST=0.0.0.0` to be reachable from containers; firewall port 11434 if so.
13. **Qwen3 thinking mode** must be disabled for extraction; verify licences (already flagged in the PRD).
14. **Evaluation owner.** §13 points to §19, which lists it as open, while §15 implies M2. M2 already carries the heaviest stream and builds the system being measured. Recommend M1 (or M1 and M4 jointly).
15. **API prefix.** The base spec uses `/api/v1/...`; PRD §9 additions omit it. Use `/api/v1` everywhere.
16. **Page numbering.** Store the physical 1-based page index (what PDF.js opens), not the printed page label. XLSX provenance needs sheet + row/cell range, not only the worksheet name.

## 9. Implementation Brief — for stack-specialist agent

### Components to Build
- **Edge (Caddy, plus cloudflared on the host):** Caddy is the only edge container, published on `127.0.0.1:8080`; `cloudflared` runs as a host process outside the Compose stack and connects to it. Single origin. `/api/*` goes to FastAPI and `/*` to Next.js, with no buffering on the ask route.
- **API (FastAPI):** HTTP surface `/api/v1`, auth dependency producing `OrgContext`, consistent error format, rate limits.
- **Worker:** Postgres job loop (SKIP LOCKED, leases, reaper, backoff), concurrency 1, stage handlers.
- **kernel:** shared types and ports (`OrgContext`, `SourceRef`, `Money`, `LLMPort`, `EmbeddingPort`, `StoragePort`, `JobQueuePort`).
- **infrastructure:** tenant-scoped session/repository base (emits `SET LOCAL app.org_id`), queue adapter, `OllamaAdapter`, `OpenAICompatibleAdapter` (disabled unless `LLM_ALLOW_HOSTED=true`), `FakeLLM`, `FastEmbedAdapter`, `LocalVolumeStorage`.
- **identity / billing / audit / tenders / documents / checklist / knowledge / extraction / estimating / estimates / suppliers / reporting / qa:** as in section 2.
- **Web (Next.js production build):** screens in PRD §11; PDF.js page-jump; job polling; stream reader (stretch).
- **Ops scripts:** `start-demo` (Compose up, preload model, start tunnel, health check), `backup`/`restore` (DB dump + volume tar, same timestamp).

### Contracts (Interfaces)
- `identity.resolve_context(user_id, org_id) -> OrgContext`; raises `NotAMember`. Role always comes from the DB.
- `documents.upload(ctx, tender_id, kind, file) -> (DocumentVersionDTO, job_id)`. Invariants: type sniffed, file stored before commit, a single transaction writes version + usage + audit + job; duplicate active job returns the existing one.
- `knowledge.ingest(ctx, version_id, progress) -> IngestResult(pages, chunks, warnings)`. Replaces that version's chunks atomically.
- `knowledge.search(ctx, tender_id, query, k=6) -> list[ChunkHit(chunk_id, document_version_id, page|sheet, text, score)]`. Invariant: every hit has `organisation_id == ctx.organisation_id`, the given tender, and a current version.
- `extraction.parse_boq(tables) -> list[BoqCandidate]` (pure, no LLM). `extraction.extract_requirements(section, llm) -> list[RequirementCandidate]` (with `evidence_quote`; no provenance fields).
- `estimating.replace_unreviewed(ctx, version_id, candidates) -> ReplaceResult`; never touches reviewed rows. Same contract for `checklist.replace_unreviewed` and `suppliers.replace_quotation_items`.
- `estimates.calc` is pure (Decimal, configurable VAT, markup; no I/O). The router reads BoQ lines and confirmed matches through `estimating.public` and `suppliers.public`, passes plain inputs to `estimates`, and `estimates` imports only kernel, db and audit. Estimates are versioned, with status draft/reviewed/approved.
- `suppliers.suggest_matches(ctx, tender_id) -> list[MatchSuggestion(evidence, score, needs_confirmation)]`; `decide(ctx, id, confirm|reject)` records reviewer + time.
- `reporting.create_export(ctx, tender_id, kind) -> ExportDTO`. Approved-only content; otherwise the export is labelled DRAFT; audited.
- `LLMPort.generate_structured(system, user, json_schema, options) -> StructuredResult(raw_json, done_reason, tokens, latency_ms, model)`.
- `GET /api/v1/jobs/{id} -> {status, progress_done, progress_total, error_code, warnings[]}`.

### Domain Invariants
- Every org-owned row has `organisation_id`, equal to its parent's (enforced by composite FK).
- The LLM never sets provenance or computes money. Code attaches `SourceRef`; unverifiable evidence is flagged, not hidden.
- `original_value` is immutable; corrections go in `corrected_value` with reviewer and timestamp.
- Missing is `NULL` + flag, never 0. All money is `Decimal` with explicit rounding.
- Nothing extracted is "approved" without a human action (BR-01). Matches are never auto-confirmed; lowest price is never auto-selected.
- At most one active job per `(job_type, subject_id)`. Re-running a stage never duplicates rows or alters reviewed rows.
- Original files are never modified or deleted by processing.
- Logs and audit metadata contain IDs, never document text or secrets.

### Quality Attributes (must satisfy)
- Isolation: F1, F3, F4, F5 at 100% pass, blocking in CI.
- Upload confirmation p95 < 5 s for files up to 20 MB; Excel export < 10 s for 1,000 lines; non-AI API p95 < 500 ms; search p95 < 300 ms.
- Ingest (no LLM) of a 100-page native PDF < 3 min; full pipeline < 45 min on the reference laptop (proposed); progress updates at least every 10 s of work.
- RAM: whole stack plus browser < 13 GB; WSL2 capped via `.wslconfig`.
- AI: PRD §13 targets, measured by the evaluation script.
- Coverage >= 70% on business logic; CI green on every PR (pytest, ruff, import-linter, frontend tests).

### Explicit Non-Goals
- Postgres RLS (optional hardening on `document_chunks`/`documents` only, days 22-25), HNSW/ANN indexes, Celery/Redis, multiple workers, microservices.
- LLM in supplier matching; vision table parsing; fine-tuning; hosted LLM with real data.
- Payment gateway; email password reset (admin reset instead); WebSockets; MinIO.
- Separate staging environment.

### Open Questions for Specialist
- SQLAlchemy sync (simpler; FastAPI threadpool) vs async. Recommendation: sync for both API and worker unless Q&A streaming forces async for that route.
- FastEmbed inside the API image (for query embeddings) vs embedding queries via Ollama: measure RAM.
- `tsvector` as a generated column with `simple` config, and whether to add an `english` column.
- PDF report library: ReportLab (pure Python) vs WeasyPrint (needs Pango system libraries in the image).
- ~~Tesseract settings~~ Resolved: `eng` pack, 300 DPI, 60 s per-page timeout.
- Ollama and NVIDIA driver versions that work with Pascal (GTX 1050); the `num_ctx`/`num_gpu` split for 2 GB VRAM.
- PDF.js integration (`pdfjs-dist` directly vs `react-pdf`) with App Router.
- Exact import-linter contract set and the CI check for raw `session.execute`.

## Slice 2 notes

- **Search is full-text for now.** Chunks are searched with Postgres `tsvector` (current document versions only, tenant-scoped). Embeddings are deferred to a later slice; the chunk table is unchanged by that.
- **Downloads are authenticated, not signed links.** `GET /api/v1/document-versions/{id}/file` checks the session and tenant on every request and streams the file (PDFs inline, others as attachment) with `nosniff`, `private, no-store` and `Content-Security-Policy: sandbox`. No signed URLs exist (this supersedes the signed-link text in ADR-0005 item 7 and ADR-0007).
- **Storage keys** are `org/{org}/tenders/{tender}/{document}/v{n}/{uuid}.{ext}`; the user's (sanitised) filename is metadata only. A stored file is deleted if the upload transaction rolls back.
- **Search snippets are plain text.** Matches are wrapped in `⟦` and `⟧` (U+27E6/U+27E7), never HTML; snippets are untrusted document text that clients must escape.
- **OCR route.** A PDF page with no embedded text is rendered at `OCR_DPI` and sent to Tesseract (`tesseract-ocr`, English model, installed in the backend image) one page at a time with a per-page timeout and `OMP_THREAD_LIMIT=1`. The rendered image is capped at `OCR_MAX_MEGAPIXELS` (40): a larger page is rendered at a lower DPI (never below 100), and a page still too large is marked `ocr_failed` without rendering. Text and mean word confidence are stored on the page (`text_source = "ocr"`).
- **Spreadsheet caps.** The declared sheet dimension is ignored (rows are not padded to it) and trailing empty cells are trimmed. More than `XLSX_MAX_COLUMNS` (200) columns in a row, more than `XLSX_MAX_CELLS` (2,000,000) cells in a file (XLSX or CSV), or more than 100,000 rows in a sheet fails the job with `SHEET_TOO_LARGE`. NUL characters are removed from all extracted text, labels and cells.
- **`processing_status`** of a document version: `pending`, `processing`, `ready`, `ready_with_warnings`, `failed`. `processing` is committed on its own as soon as the worker claims the job, so clients see it while ingest runs. When a job fails for good (including a job reaped as `LEASE_EXPIRED`), its version becomes `failed`; a version whose ingest already committed (`ready`) is never set back to `failed`.
- **Job warning codes** (job ends `succeeded_with_warnings`): `OCR_FAILED`, `OCR_LOW_CONFIDENCE`, `OCR_UNAVAILABLE`, each with the affected page numbers. **Failure codes** (job `failed`, never contain document text): `FILE_CORRUPT`, `PDF_ENCRYPTED`, `UNSUPPORTED_FORMAT`, `SHEET_TOO_LARGE` (permanent), `NO_HANDLER`, `UNEXPECTED`, `LEASE_EXPIRED` (the worker died on the last attempt), and `INFRASTRUCTURE` once retries are used up.
- **Transient errors.** Database connection errors (`OperationalError`, `InterfaceError`, invalidated connections) and storage `OSError`s requeue the job with backoff (`INFRASTRUCTURE`, 30 s x attempt) up to `max_attempts` (3); anything else is permanent. If the handler's transaction committed but recording success fails, completion is retried and then left to the lease reaper; the version is not failed.
- **Worker logs** carry job IDs, error codes and exception type names only: no tracebacks or exception messages (they can hold document text), and the engine uses `hide_parameters=True`.
- **Restart policy.** Every Compose service has `restart: unless-stopped`, so a worker killed by the kernel comes back on its own.
- **Every entry point registers all models.** `app.infrastructure.model_registry.import_all_models()` imports each `app.modules.*.models`; the API, worker and Alembic env call it, so SQLAlchemy can resolve foreign keys in any process. `tests/test_worker_isolation.py` guards the worker.

## 10. Next steps

1. **Day 1 spikes (M2, M4):** container reaches host Ollama; structured output with each candidate model; measure tokens/s and per-section latency; RRF query on 20k fake chunks.
2. **Day 2:** import-linter contracts and the F3 schema test in CI before any module code.
3. **Day 4:** contract freeze (section 7). Draft the ERD from the module table.
4. **Day 12:** F1 and F4 green, blocking merges.
5. **Day 25:** Q&A go/no-go (ADR-0009); RLS hardening go/no-go (ADR-0005).
6. Revisit ADR-0002 (ANN index) and ADR-0006 (Celery) only if F11 or real usage shows the need.
