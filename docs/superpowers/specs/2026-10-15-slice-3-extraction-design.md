# Slice 3: Extraction (design)

**Date:** 2026-10-15 · **Branch:** `feat/slice-3-extraction` · **Status:** draft for review
**Authority:** `docs/plan.md` section 3 (Slice 3), `docs/prd.md` FR-18 to FR-26, FR-61, `docs/architecture/architecture.md`, ADR-0003 (LLM behind ports), ADR-0004 (deterministic-first extraction, code-attached provenance), ADR-0005 (tenancy), ADR-0006 (queue, idempotent stages), ADR-0010 (solo scope). Measured prompt and filter results: `docs/spikes/m2-1b-prefilter-experiment.md`, `docs/spikes/m2-1c-prompt-evaluation.md`.

## 1. Goal and scope

After a document version finishes ingest, the worker automatically extracts two things from it:

- **BoQ items** with a deterministic table parser (no LLM).
- **Tenderer requirements** with the deterministic pre-filter followed by prompt v3 on Qwen3-4B (Ollama, on the host).

Every stored item carries a page (or sheet and cell) reference found by code, never by the model.

**Exit gate:** synthetic packs score at the harness targets (about 95% requirement recall, 98% precision; BoQ fields scored against ground truth), with results stored with their sources, `prompt_version` and `filter_version`.

**Out of scope:** review edits and UI (Slice 4), checklist generation, quotation parsing (Slice 5), embeddings and Q&A, model comparison (Slice 7), prompt tuning beyond v3. Scanned BoQs are flagged for manual entry (ADR-0010).

## 2. Decisions taken

| Decision | Choice |
|---|---|
| Delivery | One spec, one plan, one branch for the whole slice |
| Trigger | Automatic: a successful ingest enqueues an `extract` job. A manual endpoint re-runs, with optional `deep_scan` |
| Failure model | Extraction state is tracked separately from ingest. The version stays `ready` when extraction fails |
| Storage | One `extraction_runs` row per (version, kind, run); items link to their run |
| Proof of the gate | Two layers: CI with `FakeLLM` plus deterministic BoQ scoring; a manual real-model scoring script |
| LLM runtime | Ollama on the host (not in Compose), reached from the worker by a configurable URL |

## 3. Components

- **`extraction` (pure core; imports neither `fastapi` nor `sqlalchemy`)**
  - `boq.parse_boq(tables) -> list[BoqCandidate]`: header-row detection, column mapping, unit and quantity normalisation. A missing quantity is `null`, never 0. Flags: `missing_quantity`, `rate_only`, `unit_alias`, `provisional_sum`. Subtotals are skipped. Scanned/OCR tables yield a "needs manual entry" result.
  - `requirements.prefilter(pages) -> list[Window]`: trigger sentences (obligation words, dates, times, grades, amounts, standards, periods) plus one sentence of context, batched into windows of about 1,350 tokens. `deep_scan` bypasses the filter and sends every section.
  - `requirements.extract(windows, llm) -> list[RequirementCandidate]`: prompt v3, schema-validated output, items without an `evidence_quote` dropped.
  - `provenance.locate(quote, pages) -> (page, start, end) | None`: exact match, then whitespace-normalised match.
- **`llm` port (ADR-0003):** `LlmClient.complete_json(prompt, schema)`. Adapters: Ollama (`think: false`, temperature 0, request timeout, response size cap) and `FakeLLM` for tests.
- **`knowledge`:** gains a read method returning a version's pages and tables through its public facade.
- **`worker`:** new `extract` job kind. It reads pages and tables, calls the pure core, and persists through the `extraction` repository. The model registry is the single registration point (as in the Slice 2 fix).

## 4. Data flow

```
ingest ok ──enqueue──▶ extract job (version_id, deep_scan=false)
   ├─ boq:          tables ─▶ parse_boq ─▶ boq_items (unreviewed) + run row
   └─ requirements: pages ─▶ prefilter ─▶ LlmClient ─▶ validate ─▶ locate ─▶ requirements (unreviewed) + run row
POST   .../versions/{v}/extract       same job, re-run rule below
GET    .../versions/{v}/extraction    current run per kind
GET    .../versions/{v}/boq-items | /requirements
```

The two kinds run independently inside the job; one failing does not block the other, and each has its own run status.

## 5. Schema (migration `0003`)

All tables carry `organisation_id` with composite FKs to their parents and are accessed only through org-scoped repositories.

- **`extraction_runs`:** `id`, `organisation_id`, `tender_id`, `document_version_id`, `kind` (`boq`/`requirements`), `status` (`queued`/`running`/`succeeded`/`succeeded_with_warnings`/`failed`), `deep_scan`, `prompt_version`, `filter_version`, `model`, `warnings` (JSON list of `{code, detail}`), `counts` (JSON), `error_code`, `started_at`, `finished_at`. The latest run per (version, kind) is current; older runs are kept for evaluation.
- **`boq_items`:** `id`, `organisation_id`, `tender_id`, `run_id`, `document_version_id`, `item_no`, `description`, `unit`, `quantity` (`NUMERIC(18,4)`, nullable), `raw_unit`, `raw_quantity`, `flags`, source (`page_number` or `sheet` + `cell_ref`), `review_status` (`unreviewed`/`confirmed`/`corrected`/`rejected`), `original_value` (JSON), `corrected_value` (JSON, nullable), `reviewed_by`, `reviewed_at`.
- **`requirements`:** `id`, `organisation_id`, `tender_id`, `run_id`, `document_version_id`, `text`, `requirement_type`, `mandatory_status`, `evidence_quote`, `page_number`, `quote_start`, `quote_end`, plus the same review columns.

Quantities are `Decimal` end to end (comma decimals and spaced thousands handled), never floats.

**Re-run rule (ADR-0006):** delete the previous run's `unreviewed` rows and insert the new ones. Reviewed rows are never touched. A candidate that duplicates a reviewed row (same item number, or same normalised quote) is skipped with a `DUPLICATE_OF_REVIEWED` warning.

## 6. API

Authenticated and org-scoped. Archived tenders reject writes with the existing 409.

- `POST /tenders/{t}/documents/{d}/versions/{v}/extract` with `{deep_scan: bool}` returns 202 and the run ids. Idempotent while a run is queued or running.
- `GET .../versions/{v}/extraction` returns the current run per kind: status, warnings, counts.
- `GET .../versions/{v}/boq-items` and `.../requirements` are paginated and include source and `review_status`.

Review edits (confirm, correct, reject) belong to Slice 4. The columns exist now so Slice 4 needs no migration.

## 7. Error handling

| Situation | Behaviour |
|---|---|
| Ollama unreachable or times out | Job retries with backoff (as I-5). After the cap the run is `failed` with `LLM_UNAVAILABLE`. Ingest stays `ready`; the user can re-run |
| Invalid JSON or schema violation | One retry of that window; then the window is dropped with `WINDOW_INVALID_OUTPUT`, and the run ends `succeeded_with_warnings` |
| `evidence_quote` not locatable | Item dropped with `EVIDENCE_NOT_FOUND`. No requirement is stored without verifiable provenance |
| Filter yields suspiciously few candidates | `succeeded_with_warnings` with `FILTER_LOW_YIELD`, suggesting a deep scan |
| Scanned/OCR BoQ table | No rows; `succeeded_with_warnings` with `BOQ_NEEDS_MANUAL_ENTRY` |
| No tables / no recognisable header | `succeeded`, zero items, `NO_BOQ_FOUND` |
| Worker crash or reaped job | The reaper fails the run as well as the job (the I-3 lesson), so no run stays `running` |

**Security and hygiene (Slice 2 review lessons):**

- Document text never reaches logs, including SQLAlchemy error parameters. Log-hygiene tests assert on the full formatted traceback, not only `getMessage()`.
- Document text is data, not instructions: the prompt fences it, and output is schema-validated so injected text cannot change fields. A prompt-injection pack is part of the tests.
- Caps on windows per run, window size and LLM response size.

## 8. Testing

**CI, no model:**

- BoQ parser scored against ground truth for every pack with a BoQ (item number, unit, quantity, flags), plus unit tests for the messy cases (comma decimals, merged cells, subtotals, rate-only, unit aliases).
- Pre-filter unit tests; filter recall measured separately from LLM recall.
- Provenance: exact, whitespace-normalised and not-found.
- Pipeline end to end with `FakeLLM`: auto-enqueue after ingest, idempotent re-run, reviewed rows surviving, every failure path above, and the worker-isolation subprocess test.
- F1 tenancy sweep extended to all new routes; repository contract test for the new repositories.

**Manual, real model:** `scripts/score_slice3` runs Ollama over the packs and writes predictions in the harness format. Results go into `docs/spikes/slice-3-scores.md` and are checked against the gate. Runs take about 3 minutes per pack and are not part of CI.

## 9. Task order

1. Schema: migration `0003`, ORM models via the central registry, repositories, tenancy contract test.
2. BoQ parser (pure), scored against ground truth in CI.
3. Requirement core (pure): pre-filter, windowing, prompt v3, validation, provenance locator.
4. LLM port: `LlmClient`, Ollama adapter (host URL setting, `think: false`, timeout, caps), `FakeLLM`.
5. Worker pipeline: `extract` job kind, auto-enqueue after ingest, run records, re-run rule, retries and reaper handling, log-hygiene tests.
6. API: trigger and read endpoints, extended F1 sweep, archived-tender behaviour.
7. Real-stack check and docs: `scripts/score_slice3`, Docker smoke test through Caddy with Ollama on the host, updates to the plan, PRD notes, architecture, and an ADR addendum recording the `extraction_runs` decision.

## 10. Risks

- **Real-document recall:** all measured numbers are from synthetic, templated data. The gate is on synthetic packs and the limitation is documented.
- **Ollama contention and speed:** about 3 minutes per pack on CPU. The worker runs one extract job at a time; timeouts are generous but capped.
- **Messy PDF tables:** pymupdf table detection varies. Task 2's ground-truth scoring exposes this early. If PDF recall is poor, the fallback is flagging for manual entry rather than guessing.
