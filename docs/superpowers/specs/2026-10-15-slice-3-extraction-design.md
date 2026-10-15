# Slice 3: Extraction (design)

**Date:** 2026-10-15 · **Branch:** `feat/slice-3-extraction` · **Status:** revision 2 (after Fable review), for owner review
**Authority:** `docs/plan.md` section 3 (Slice 3), `docs/prd.md` FR-18 to FR-26, FR-55, FR-61, FR-64 to FR-66 and section 13 (targets), `docs/architecture/architecture.md`, ADR-0003 (LLM behind ports), ADR-0004 (deterministic-first extraction, code-attached provenance), ADR-0005 (tenancy), ADR-0006 (queue, idempotent stages), ADR-0010 (solo scope). Measured results: `docs/spikes/m2-1b-prefilter-experiment.md`, `docs/spikes/m2-1c-prompt-evaluation.md`.

## 1. Goal and scope

After a document version finishes ingest, the worker automatically extracts two things from it:

- **BoQ items** with a deterministic table parser (no LLM).
- **Tenderer requirements** with the deterministic pre-filter followed by prompt v3 on Qwen3-4B (Ollama, on the host).

Every stored item carries a source found by code (page, or sheet and cell range), never by the model.

**Exit gate (PRD section 13 thresholds, not the spike's best numbers):**

- Requirements: recall >= 85%, precision >= 80%.
- BoQ on native documents: quantity and unit >= 95%, description >= 90%.
- Harness critical counters are zero: `boq_zero_for_missing`, `req_injection_followed`, and unverifiable quotes stored as verified.
- Measured on the standard 8 packs for seeds 42 and 43, through the real stack (upload, worker, GET endpoints). Scanned packs (05, 06) are reported separately because they were never measured in the spikes. The spike figures (about 95% recall, 98% precision on native packs) are expectations, not the gate.

**Out of scope:** review edits and UI (Slice 4), checklist generation, quotation parsing (Slice 5), embeddings and Q&A, model comparison (Slice 7), prompt tuning beyond v3. Scanned BoQs are flagged for manual entry (FR-55, ADR-0004).

## 2. Decisions taken

| Decision | Choice |
|---|---|
| Delivery | One spec, one plan, one branch for the whole slice |
| Trigger | Automatic: a successful ingest enqueues the extract jobs. Manual re-run endpoint, optional `deep_scan` |
| Failure model | Extraction state is tracked separately from ingest. The version stays `ready` when extraction fails |
| Jobs | Two job types, `extract_boq` and `extract_requirements` (ADR-0006: one job type per stage). The BoQ output is committed even if the LLM is down |
| Storage | One run row per (job, kind); items link to their run |
| Evidence | ADR-0004 rule: fuzzy locate, then keep and flag. Nothing is dropped for unverifiable evidence |
| Proof of the gate | Two layers: CI with `FakeLLM` plus committed fixtures and deterministic BoQ scoring; a manual real-stack scoring script |
| LLM runtime | Ollama on the host (not in Compose), configurable URL |

## 3. Module placement

The import-linter contract forbids `sqlalchemy` in `app.modules.extraction`, and the architecture assigns tables to modules. So:

- **`extraction`**: pure core only. No ORM, no repositories, no models.
- **`pipeline`** (new module): owns `extraction_runs`; exposes run create/reset/finish/fail and "current runs for a version" via `public.py`.
- **`estimating`**: owns `boq_items`; exposes `replace_unreviewed(ctx, version_id, run_id, cands)` and list queries (the architecture's contract).
- **`checklist`**: owns `requirements`; same two methods.
- **`knowledge`**: gains a read method (below).
- **`worker`**: orchestrates. It calls `knowledge`, `extraction`, the LLM port, and the `pipeline`/`estimating`/`checklist` public facades, and calls `jobs.enqueue`. Import-linter facade-only rules and the F2 raw-SQL ban apply to all of them; the registry registers the new models.

### 3.1 `extraction` core

- `boq.parse_boq(pages) -> BoqResult`: header-row detection, column mapping (item no, description, unit, quantity, rate, section), unit and quantity normalisation. The header carries across pages of the same table. A missing quantity is `null`, never 0. Flags: `missing_quantity`, `rate_only`, `unit_alias`, `provisional_sum`, `needs_review` (low-confidence page). Subtotals are skipped. Numeric cells arrive from ingest as strings such as `"1250.0"` or `"1e-05"`, and the parser accepts those plus comma decimals and spaced thousands. Values with more than 4 decimal places are flagged, never silently rounded. A scanned BoQ is an OCR page whose text contains BoQ header words but whose `tables` is empty: it yields `BOQ_NEEDS_MANUAL_ENTRY`, not `NO_BOQ_FOUND`.
- `requirements.prefilter(pages, exclude_pages) -> list[Window]`: trigger sentences plus one sentence of context, batched into windows of about 1,350 tokens. Pages where `parse_boq` found BoQ rows are excluded. `deep_scan` bypasses the filter.
- `requirements.extract(windows, llm) -> list[RequirementCandidate]`: prompt v3, schema-validated output, and a retry that appends the validation error. `done_reason == "length"` counts as invalid output.
- `requirements.merge_requirements(cands)`: de-duplicates candidates from overlapping windows by normalised quote overlap (FR-61).
- `provenance.locate(quote, pages) -> Location | None`: exact match, then whitespace-normalised, then fuzzy match with a ratio of at least 0.9, searched over the concatenated page text so quotes spanning a page break resolve to the page where they start.

### 3.2 LLM port (ADR-0003)

`kernel/ports.py`: `LLMPort.generate_structured(system, user, json_schema, options) -> StructuredResult(raw_json, done_reason, tokens, latency_ms, model)`. Adapters live in `infrastructure`: Ollama (`think: false`, temperature 0) and `FakeLLM`. Settings: `LLM_PROVIDER` (`ollama`/`fake`), `LLM_BASE_URL`, `LLM_MODEL`, `LLM_TIMEOUT_S`, `LLM_NUM_CTX` (>= 4096), `LLM_NUM_PREDICT`. The adapter converts httpx errors into `ProcessingFailed("LLM_UNAVAILABLE", transient=True)`, because the runner's `_is_transient` only treats `OSError`-like errors as transient. The worker builds the adapter from settings through a factory that tests override; `LLM_PROVIDER=fake` is the default in the test environment, so no test can reach a real Ollama. `LLM_TIMEOUT_S` must be shorter than the job lease (300 s), and the handler reports progress after every window so the lease is renewed.

### 3.3 `knowledge` read method

`get_extraction_input(ctx, version_id)` returns, per page: `page_number`, `label`, `text`, `text_source`, `status`, `tables`. The document kind comes from `documents`.

## 4. Routing and data flow

Which extraction runs depends on `Document.kind`:

| Kind | `extract_boq` | `extract_requirements` |
|---|---|---|
| `tender_document` | yes | yes |
| `boq` | yes | no |
| `quotation` | no (Slice 5) | no |
| `other` | no | yes |

```
ingest handler (ready / ready_with_warnings) ──jobs.enqueue, same transaction, created_by = ingest job's created_by──▶
   extract_boq (version_id)          pages/tables ─▶ parse_boq ─▶ estimating.replace_unreviewed + run row
   extract_requirements (version_id) pages ─▶ prefilter ─▶ LLM ─▶ validate ─▶ merge ─▶ locate ─▶ checklist.replace_unreviewed + run row
POST /api/v1/document-versions/{version_id}/extract      enqueue one or both (deep_scan only affects requirements)
GET  /api/v1/document-versions/{version_id}/extraction   current run per kind
GET  /api/v1/document-versions/{version_id}/boq-items | /requirements
```

The two jobs are independent: each has its own transaction, retries, status, and `on_failure`. Requirements read BoQ-row pages from the BoQ result by re-running the cheap `parse_boq` itself, so there is no job ordering dependency.

Existing code that must change:

- `JobRepo.latest_for_subject` gets a `job_type` filter and the documents service passes `INGEST_JOB`, so `DocumentDTO.job_id` and `VersionDTO.job_id` keep pointing at the ingest job once extract jobs exist. A regression test covers it.
- The generic `POST /jobs/{id}/retry` archived-tender guard is extended from `INGEST_JOB` to both extract job types, and the worker refuses to extract for an archived tender.
- Flat route style as in `routers/documents.py` (`/api/v1/document-versions/{version_id}/...`). The permission for POST is `REVIEW_DATA`.
- `POST /extract` returns 409 when the version is not `ready`/`ready_with_warnings`. If a job of that type is already active it returns that job, with its `deep_scan` value, and never silently ignores a different `deep_scan` request (409 in that case).

## 5. Schema (migration `0003`)

All tables carry `organisation_id`, composite FKs, and org-scoped repositories.

- **`extraction_runs`** (`pipeline`): `id`, `organisation_id`, `document_version_id` (composite FK to the version), `job_id` (composite FK to `jobs(organisation_id, id)`), `kind`, `status` (`queued`/`running`/`succeeded`/`succeeded_with_warnings`/`failed`), `deep_scan`, `prompt_version`, `filter_version`, `schema_version`, `model`, `warnings`, `counts`, `error_code`, `created_at`, `started_at`, `finished_at`. Constraints: `UNIQUE(job_id, kind)` and `UNIQUE(organisation_id, id, document_version_id)`.
  - The API enqueues jobs; the worker's `on_start` creates the run (or resets it on retry); `on_failure` (including the reaper path) marks it failed. No run can stay `running` after a final failure, and a retry resets the existing row.
  - The current run per (version, kind) is the one with the latest `created_at`. Its older siblings are kept for evaluation.
- **`boq_items`** (`estimating`): `id`, `organisation_id`, `run_id` and `document_version_id` (composite FK `(organisation_id, run_id, document_version_id)` so an item cannot point at another version's run), `section`, `item_no`, `description`, `unit`, `quantity` (`NUMERIC(18,4)`, nullable), `rate` (nullable), `raw_unit`, `raw_quantity`, `flags`, source (`page_number`, or `sheet` + `cell_range` such as `A12:F12`, end column from the header width), `review_status` (`unreviewed`/`confirmed`/`corrected`/`rejected`), `original_value`, `corrected_value`, `ai_suggested`, `suggested_value`, `reviewed_by` (composite FK to `memberships(organisation_id, user_id)`), `reviewed_at`. No separate `tender_id`: the tender is reachable through the version.
- **`requirements`** (`checklist`): same run/version/review columns, plus `text`, `requirement_type`, `mandatory_status`, `evidence_quote`, `page_number` (nullable), `quote_start`/`quote_end` (nullable), `evidence_status` (`verified`/`evidence_unverified`).

**Re-run rule (ADR-0006):**

- In one transaction the job locks the version's run row (`SELECT ... FOR UPDATE`), deletes **all** rows of that version and kind with `review_status = 'unreviewed'` (from every earlier run), and inserts the new ones.
- Slice 4's review updates take the same lock and update conditionally (`WHERE review_status = 'unreviewed'`), returning 409 if the row is gone.
- A candidate is skipped with `DUPLICATE_OF_REVIEWED` when it matches a reviewed row: BoQ by (section or sheet, `item_no`), requirements by normalised quote; corrected rows are compared on `original_value`. A rejected row suppresses re-extraction of the same item, deliberately.
- Item GETs return reviewed rows from older runs as well as the current run's.

## 6. Error handling

Infrastructure errors retry; output errors degrade (FR-65).

| Situation | Behaviour |
|---|---|
| Ollama unreachable | Job-level transient retry with backoff; after the cap the run is `failed` with `LLM_UNAVAILABLE`. Ingest stays `ready`; `extract_boq` is unaffected |
| One call times out | Retry that call once; then the section is marked `not_analysed` with `WINDOW_TIMEOUT` and the run ends `succeeded_with_warnings` |
| Invalid JSON, schema violation, or `done_reason == "length"` | One retry with the validation error appended; then the window is dropped with `WINDOW_INVALID_OUTPUT` |
| Quote not locatable | The candidate is **kept** with `page_number` null and `evidence_status = evidence_unverified`; an `EVIDENCE_UNVERIFIED` warning counts them (ADR-0004: flagged, not hidden) |
| Filter yields suspiciously few candidates | `succeeded_with_warnings` with `FILTER_LOW_YIELD`, suggesting a deep scan |
| Scanned BoQ | No rows, `BOQ_NEEDS_MANUAL_ENTRY` |
| Items from a low-confidence OCR page | Kept with the `needs_review` flag |
| No recognisable BoQ | `succeeded`, zero items, `NO_BOQ_FOUND` |
| Reaped or crashed job | `on_failure` marks the run failed (the I-3 lesson) |
| Archived tender | Worker refuses; API rejects with 409 |

**Security and hygiene:**

- Document text never reaches logs or warnings. Warning `detail` holds ids, page numbers and counts only. `pydantic.ValidationError` text contains document text, so it is never logged; the log-hygiene tests assert on the full formatted traceback, not only `getMessage()`.
- Document text is data: the prompt fences it, and output is schema-validated. A prompt-injection pack is part of the tests.
- Resource caps are numeric settings: maximum windows per run, characters per window, items per response and rows per run. Past a cap the run adds `WINDOW_CAP_REACHED` (or the matching warning) and continues with what it has; deep scan of a large workbook cannot exhaust the worker.

## 7. Testing

**CI, no model:**

- A small fixture set of generated packs and ground truth is committed under `backend/tests/fixtures` (the `eval/generated` folder is git-ignored and `eval` is a separate uv project). BoQ parser results are scored against that ground truth with the stated thresholds, using the harness's field names (`description`, `cell_range`, `section`).
- Unit tests for the messy cases: comma decimals, spaced thousands, merged cells, subtotals, rate-only, unit aliases, float-string cells, more than 4 decimals, header carried across pages.
- Pre-filter, `merge_requirements` and provenance (exact, normalised, fuzzy, cross-page, not found).
- Pipeline end to end with `FakeLLM`: auto-enqueue after ingest, routing by document kind, idempotent re-run, reviewed rows surviving, every row of the error table, retry mapping to runs, the reaper path, and `DocumentDTO.job_id` still pointing at the ingest job.
- The worker-isolation subprocess test, and F6: kill the worker mid-stage and the resumed run leaves no duplicates.
- F1 tenancy sweep over every new route, and the repository contract test for the new repositories.

**Manual, real stack:** `scripts/score_slice3` uploads each pack through the API, waits for the jobs, reads the GET endpoints, aggregates across versions per pack, and writes predictions in the harness format. Results go into `docs/spikes/slice-3-scores.md` and are checked against section 1. About 3 minutes per pack; not part of CI.

## 8. Task order

1. **ADR addenda first:** ADR-0006 (`extraction_runs`, no `extraction_unit_results` resumability in this slice, F6 satisfied by replace-unreviewed), ADR-0004 (what is stored for unverifiable evidence, `ai_suggested`/`suggested_value`), module placement note. They change the schema and job types, so they come before code.
2. Schema and repositories: migration `0003`, models via the central registry, `pipeline`/`estimating`/`checklist` facades, tenancy contract test, `job_type` filter fix in `JobRepo`.
3. BoQ parser (pure), fixtures and scoring tests.
4. Requirement core (pure): pre-filter, windows, prompt v3, validation, merge, provenance.
5. LLM port, adapters, settings and the test factory.
6. Worker pipeline: two job types, enqueue from ingest, run lifecycle, re-run rule, retries and reaper, routing by kind, log-hygiene tests.
7. API: extract trigger and reads, archived-tender and retry guards, extended F1 sweep.
8. Real-stack check and docs: `scripts/score_slice3`, Docker smoke test through Caddy with Ollama on the host, plan, PRD notes and architecture updates.

## 9. Risks

- **Real-document recall:** all measured numbers are from synthetic, templated data. The gate is on synthetic packs and the limitation is documented.
- **OCR packs:** scanned packs are unmeasured; the fuzzy tier and the `evidence_unverified` flag exist for them, and they are reported separately.
- **Ollama contention and speed:** about 3 minutes per pack on CPU. The worker runs one job at a time and the timeouts are capped.
- **Messy PDF tables:** table detection uses pdfplumber and varies by layout. Task 3's scoring exposes this early; if PDF recall is poor the fallback is flagging for manual entry rather than guessing.
- **FR-18 to FR-26 text** comes from the base specification, which is not in the repo. Their wording is summarised here from the PRD's FR-61 and the ground-truth schema, and should be confirmed against the original.
