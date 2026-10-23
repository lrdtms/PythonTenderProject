# PRD: Intelligent Tender Preparation System (IntelTPS)

**Version:** 0.3 (draft; incorporates review fixes and the architecture review in `docs/architecture/`)
**Date:** 15 October 2026
**Project window:** 16 October – 16 November 2026 (32 days inclusive, group of 4)
**Base spec:** `Python_Project.pdf` (authoritative for scope, requirements and marking rubric)
**Supplement:** Local RAG tech-stack proposal (14 October 2026), merged where it fits

---

## 1. Summary

IntelTPS is a SaaS web app that helps South African construction subcontractors (initially electrical) prepare tenders. Users upload tender packs, and the system extracts requirements and Bill of Quantities (BoQ) lines with source references. The user reviews and corrects the results, compares supplier quotations, and exports an approved estimate to Excel/PDF.

The AI assists; humans decide. The system never approves prices, certifies compliance, or submits bids.

**Key change from the base spec:** AI processing runs **locally by default** (Ollama) on a hybrid-search (RAG) pipeline. Confidential tender data stays on infrastructure we control, which addresses the POPIA concerns in the base spec (§4.4). A hosted LLM is an optional, switchable fallback, used only with synthetic data until the contractual and privacy assessment the spec requires is done.

## 2. Problem and Goals

**Problems (base spec §1.3):** manual document analysis, BoQ extraction from inconsistent formats, supplier quotation comparison, compliance tracking, fragmented information.

**Goals**
1. Cut the time to review a tender pack and produce a requirements checklist.
2. Extract BoQ lines into an editable table with source page/worksheet.
3. Suggest supplier-to-BoQ matches with evidence; humans confirm.
4. Export approved estimates (Excel) and checklist reports (PDF).
5. Keep data private and fit on modest hardware (16 GB RAM laptop, GTX 1050).
6. Produce measurable AI accuracy results (a rubric priority, 15 marks).

**Non-goals (MVP):** post-award project management, accounting, live tender aggregation, automatic bid submission, scheduling, forecasting, microservices, vision-model table parsing, real payment processing (subscription limits are mocked, see FR-47 to FR-50 note in §5).

## 3. Users and Roles

| Role | Purpose |
|---|---|
| Business Admin | Manages workspaces, users, subscription, company information, pricing/markup defaults, document access and the activity log (base spec §2.2A) |
| Estimator / Tender Officer | Primary user: upload, review, correct, compare, export |
| Project Manager | Deadlines, task assignment, progress, approved estimates, reports |
| Read-only Reviewer | Inspect documents, estimates and checklists without modifying approved data |
| Platform Admin | Health, subscription operations, support. Access to customer documents is restricted, logged and limited to operational need. |

## 4. User Stories

US-01 to US-05 are carried over unchanged from base spec §2.3. Additions:

- **US-06 (stretch): Ask a question about a tender.** As an estimator, I want to ask a question about a tender pack and get a grounded answer with clickable citations, so that I can verify it in the source PDF.
  - Answer cites document and page.
  - Clicking a citation opens the PDF at that page.
  - If the pack doesn't contain the answer, the system says so instead of guessing.
  - Not in the base spec or rubric. Built only after the core flow works (see §15).
- **US-07: Review beside the source.** As a tender officer, I want the extracted fields next to the original document page so I can verify values quickly.

## 5. Functional Requirements

FR-01 to FR-50 from the base spec apply as written. Note: subscription and usage controls (FR-47 to FR-50) are implemented with a plan table and enforced limits but **no payment gateway**. Billing is mocked, and this is a deliberate scope choice.

Additions and clarifications:

| ID | Requirement |
|---|---|
| FR-51 | Documents are chunked section-aware (about 300–450 tokens with overlap, within the embedding model's 512-token limit). Each chunk retains document ID, document version, page/worksheet and section heading. |
| FR-52 | Retrieval is hybrid: vector similarity (pgvector) fused with Postgres full-text keyword search (`simple` config, so codes like "SANS 10142-1" match exactly) using Reciprocal Rank Fusion (RRF). Retrieval is filtered by organisation, tender and **current document version** (BR-06) before fusion. For Q&A, retrieve the top 4–6 fused chunks. No ANN index in the MVP (exact search). |
| FR-53 | (Stretch) A tender Q&A endpoint streams answers with citations to source chunks. |
| FR-54 | The UI embeds PDF.js and opens the cited page when a citation is clicked. |
| FR-55 | BoQ tables are parsed deterministically first (pdfplumber for native PDFs, openpyxl for spreadsheets). The LLM only classifies, cleans or suggests gap fills, never invents values. **Known limitation:** scanned BoQs lose table structure under OCR, so scanned input is supported for text requirements and flagged for manual review for BoQ lines. |
| FR-56 | LLM output must be JSON-schema constrained and Pydantic-validated. Invalid output is retried once, then flagged for manual entry. The LLM never produces `document_id`, `source_page` or other provenance fields. Code attaches those from chunk metadata (BR-02). |
| FR-57 | The model name, endpoint and provider are configuration, not code. The default is local Ollama. |
| FR-58 | Retrieval and extraction are tenant-scoped: every organisation-owned row (including child tables such as requirements, BoQ items, quotation items, tasks and jobs) carries `organisation_id`, child rows reference their parent with composite foreign keys, and all retrieval goes through one scoped function (`knowledge.search`), with must-pass cross-tenant tests. |
| FR-59 | Ingestion is idempotent: a document version's chunks are replaced **as a set** with `UNIQUE(document_version_id, ordinal)`. `text_hash` is used only to reuse embeddings, not as the uniqueness key (identical text on different pages must keep its own provenance). |
| FR-60 | OCR jobs run one document at a time to cap memory. |
| FR-61 | Requirement extraction (FR-18 to FR-22) screens **every sentence** of the tender pack with a deterministic pre-filter (obligation words, dates, times, grades, amounts, standards, periods). Matching sentences plus one sentence of context are batched into windows of about 1,350 tokens and sent to the LLM with a prompt that defines a tenderer requirement, its type and its status. The trigger vocabulary is configurable. A **deep scan** option sends every section to the LLM instead, for documents where the filter finds suspiciously few candidates and for evaluation. Page provenance is found by locating the LLM's `evidence_quote` in the page text. Top-k retrieval is for Q&A only. Measured results: `docs/spikes/m2-1b-prefilter-experiment.md` and `docs/spikes/m2-1c-prompt-evaluation.md`. |
| FR-62 | Estimates and exports carry a status of draft, reviewed or approved (FR-41) and a version number. Checklist reports have no version and carry `draft`, or `approved` when every non-rejected requirement has been reviewed by a person. |
| FR-63 | Supplier match suggestions and their human confirm/reject decisions are stored with evidence and reviewer (FR-34, FR-35). Matching is rule-based (no LLM). |
| FR-64 | Structured-output idempotency: re-running an extraction stage replaces only `unreviewed` rows. Reviewed or corrected rows are never overwritten or duplicated. |
| FR-65 | Retry semantics: an LLM call returning invalid output is retried once with the validation error (FR-56); transient infrastructure errors retry the job up to 3 times with backoff; permanent errors fail immediately. Users can retry failed jobs (FR-16). Partial failures end the job as "succeeded with warnings" and flag the affected pages/sections. |
| FR-66 | Provenance stores the physical 1-based page index (what PDF.js opens), and for spreadsheets the sheet plus row/cell range. |

## 6. Non-Functional Requirements

Performance, reliability, security, privacy (POPIA), usability, maintainability and scalability follow base spec §4. Additions:

- **Resource budget (local development, 16 GB laptop):** realistic working set including OS and tooling.

| Component | Approx. RAM |
|---|---|
| LLM (small model, Q4) | 1.5–3 GB |
| Embeddings (bge-small, CPU) | 0.3–0.5 GB |
| Postgres (with pgvector) | 0.3–0.5 GB |
| FastAPI + worker (Python) | 0.5–1 GB |
| Next.js dev server | 0.5–1.5 GB |
| Docker Desktop / WSL2 overhead | 1–2 GB (cap with `.wslconfig`) |
| Tesseract during OCR | 0.3–0.5 GB |
| Browser | 0.3–0.8 GB |
| Windows + other apps | 3–4 GB |
| **Total** | **~8–13 GB of 16 GB** |

  Leave headroom: close other apps during demos, and run OCR and LLM generation at different times.

- **GPU:** the GTX 1050 has 2 GB VRAM (the Ti has 4 GB), so expect partial GPU offload or CPU inference at roughly 5–15 tokens/second. Run Ollama **natively on the host**, not in Docker, to avoid GPU passthrough issues on Windows. Pin driver and Ollama versions known to support this Pascal-generation card, and treat CPU-only as an acceptable fallback.
- Set `num_ctx` explicitly (minimum 4096, since Ollama's default may silently truncate); low temperature; preload the model before demos instead of relying on a short `keep_alive`.
- Stream responses so slow generation feels responsive (fetch with a stream reader, see §9).
- Prompt-injection hardening: document text is data only. The LLM has no tools, no code execution and no cross-tenant access (base spec §7.6).
- **Processing-time target:** a 100-page native-PDF tender pack is fully processed in under 45 minutes on the reference laptop, with progress visible at least every 10 seconds of work. Ingestion without the LLM takes under 3 minutes. Demo documents are pre-processed. **Measured (M2-1b):** the pre-filter path processed a 96-page synthetic pack in about 3 minutes on the reference laptop; the deep scan (every section to the LLM) is estimated at about 100 minutes.
- **Other targets:** search p95 under 300 ms on 20k chunks; non-AI API p95 under 500 ms; one job at a time (worker concurrency 1).
- **Environments:** development and "production" are both the local Docker Compose stack; production is that stack exposed through the tunnel (§21). A separate staging environment is out of scope. "Tested in staging" in the Definition of Done means tested through the tunnel URL.
- **Demo build:** use `next build && next start` for demos, not the dev server (the RAM budget assumes this). If containers must reach host Ollama, `OLLAMA_HOST=0.0.0.0` may be needed; firewall port 11434.
- **Shared Ollama:** the worker and Q&A use the same Ollama instance, so questions queue behind extraction jobs. Pause the worker during Q&A demos. Disable Qwen3 "thinking" output for extraction.

Business rules BR-01 to BR-08 from the base spec apply unchanged.

## 7. Architecture

Modular monolith plus a background worker (base spec §5).

```
Next.js + TypeScript + Tailwind  (PDF.js for source viewing)
        |  HTTPS (fetch + streaming)
FastAPI (auth, RBAC, tenant checks, business rules)
        |
   +----+-----------------------------+
   |                                  |
Services (tenders, BoQ, suppliers,   Background worker (ingestion jobs)
 checklist, exports, audit)             |
   |                                    +--> PyMuPDF / pdfplumber / openpyxl / python-docx / Tesseract
   |                                    +--> chunker -> bge-small embeddings (CPU)
   |                                    +--> Ollama (on host) -> Pydantic validation
   v                                    |
PostgreSQL + pgvector + full-text search (relational data, vectors, keyword index; one store, one backup)
File storage (local volume behind a StoragePort; blob/S3 adapter possible later)
```

Edge: Caddy provides a single origin (`/api/*` to FastAPI, everything else to Next.js) behind the Cloudflare Tunnel. See `docs/architecture/` for the C4 diagrams, ADRs and module boundaries; where this PRD and the architecture differ, the architecture documents explain why.

### Stack decisions

| Layer | Choice | Source / rationale |
|---|---|---|
| Frontend | Next.js, TypeScript, Tailwind | Base spec. **Confirmed.** |
| PDF viewing | PDF.js | RAG proposal; enables citation click-through |
| Backend | FastAPI, Pydantic | Both |
| Auth | Argon2id password hashing; 15-minute access JWT in an httpOnly cookie **without a role claim**; rotating hashed refresh token; role and membership read from the database on every request (so role changes and deactivation take effect immediately); SameSite plus custom-header CSRF protection | Base spec §4.3; ADR-0008 |
| ORM / migrations | SQLAlchemy, Alembic | Base spec |
| Database | PostgreSQL with **pgvector** and built-in full-text search (`tsvector`) | Replaces ChromaDB + rank_bm25 from the RAG proposal: shared safely by API and worker, row-level tenant isolation via `organisation_id`, one backup, transactional idempotency |
| PDF text/tables | PyMuPDF, pdfplumber | Both |
| Spreadsheets / DOCX | openpyxl, pandas, python-docx | Base spec FR-11 |
| OCR | Tesseract | Both |
| Embeddings | bge-small-en-v1.5 (CPU), using the recommended query instruction prefix | RAG proposal |
| Hybrid fusion | Reciprocal Rank Fusion (RRF) of vector and keyword results | New |
| LLM runtime | Ollama (native on host) | RAG proposal |
| LLM model | Candidates: Qwen3-4B or Qwen2.5-1.5B (Apache-2.0), Llama 3.2 3B (community licence). **Qwen2.5-3B is not the default** because it carries a non-commercial research licence, which conflicts with the SaaS framing. The default is chosen from the §13 evaluation. Verify each model's current licence before deciding. | Review fix |
| Orchestration | Thin custom pipeline (LlamaIndex optional for retrieval helpers only) | Keeps AI code separate and unit-testable (base spec §4.6) |
| Background jobs | DB-backed job table with a simple worker; Celery/Redis later | Base spec |
| PDF reports | ReportLab or WeasyPrint | FR-39 |
| Excel export | openpyxl | FR-38 |
| Email | SMTP, with Mailpit locally; in-app reminders are the primary channel | FR-45 |
| Rate limiting | slowapi | Base spec §4.3 |
| Upload checks | `python-magic` content sniffing, size/type limits. ClamAV is optional; if skipped, document that choice. | Base spec §7.2 |
| Deployment | Docker Compose | Base spec |
| CI / version control | Git with feature branches and PRs; GitHub Actions running pytest and lint | Rubric item 10 |
| Testing | pytest, frontend tests (Vitest/Playwright) | Base spec |

**Not adopted from the RAG proposal:** SQLite as the main DB, HTMX/Svelte frontend, ChromaDB and rank_bm25 (replaced by pgvector + FTS), single-user assumption. A reranker, 7B model and vision fallback are deferred.

## 8. Data Model

Entities from base spec §6.1 (Users, Organizations, Memberships, Tenders, Documents, Extraction Jobs, Tender Requirements, BoQ Items, Suppliers, Supplier Quotations, Quotation Items, Tasks, Audit Events). Additions:

- **Document Versions** (or `version` on Documents): preserve versions and record which was analysed (FR-09).
- **Document Chunks**: id, organisation_id, document_id, document_version, page, section, text, text_hash, embedding (pgvector), tsv (tsvector). Unique on (document_id, document_version, text_hash).
- **Match Suggestions**: id, organisation_id, boq_item_id, quotation_item_id, evidence (signals and scores), status (suggested/confirmed/rejected), reviewed_by, reviewed_at.
- **Estimates / Exports**: id, organisation_id, tender_id, version, status (draft/reviewed/approved), generated_at, generated_by.
- **Plans / Usage**: plan limits and per-organisation usage counters (mocked billing).
- **Chat Queries** (stretch): id, organisation_id, user_id, tender_id, question, cited_chunk_ids, created_at. Store citation IDs, not full document text.
- BoQ Items and Requirements keep `original_value` separate from `corrected_value` (FR-26), plus reviewer and timestamp.

Every organisation-owned record carries `organisation_id` (including requirements, BoQ items, quotation items, tasks and extraction jobs, which the base spec omits), and child rows reference their parent through composite foreign keys `(organisation_id, parent_id)`. **Deliverable:** an ERD diagram (rubric item 3) generated from the final schema and included in the documentation.

## 9. API

Base endpoints from spec §6.3 remain. **All paths use the `/api/v1` prefix** (the additions below omit it for brevity). Additions needed for the features to function:

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `POST /auth/refresh`, `GET /me` |
| Org and members | `GET/PATCH /organisations/{id}`, `POST /organisations/{id}/invites`, `GET /organisations/{id}/members`, `PATCH /memberships/{id}` (role/deactivate) |
| Suppliers | `POST/GET /suppliers`, `GET/PATCH /suppliers/{id}` |
| Quotations and matching | `GET /quotations/{id}/items`, `GET /tenders/{id}/match-suggestions`, `POST /match-suggestions/{id}/confirm`, `POST /match-suggestions/{id}/reject` |
| Tasks | `POST /tenders/{id}/tasks`, `GET /tenders/{id}/tasks`, `PATCH /tasks/{id}` |
| Documents | `GET /documents/{id}/file` (authenticated same-origin download for PDF.js; the signed link was superseded in Slice 2, see ADR-0005/ADR-0007), `POST /documents/{id}/reindex`, `GET /documents/{id}/chunks` (admin/debug) |
| Exports | `POST /tenders/{id}/exports`, `GET /exports/{id}`, `GET /exports/{id}/download` |
| Usage | `GET /usage` |
| Q&A (stretch) | `POST /tenders/{id}/ask` |

**Streaming note:** the browser's `EventSource` only supports GET, so the Q&A endpoint is consumed with `fetch` and a `ReadableStream` reader (or switched to GET with a short-lived query token). Everything is served from a single origin through Caddy (no CORS needed), and the ask route is configured not to buffer.

All endpoints validate request bodies, enforce roles and organisation checks on the backend, and return a consistent error format.

## 10. Processing Pipeline

1. **Validate** type (by content sniffing, not filename), size, permissions and limits.
2. **Extract:** PDF embedded text first, OCR for scanned pages, direct reads for spreadsheets/DOCX, and pdfplumber for tables (keep row order, headers, source location).
3. **Chunk** section-aware, with page and version metadata.
4. **Index:** embed, then insert into the chunk table (vector + tsvector), scoped by `organisation_id`.
5. **Extract structured data:**
   - BoQ: deterministic parsing first, LLM only to classify/clean/suggest gap fills.
   - Requirements: deterministic pre-filter, then the LLM on candidate windows with a schema-constrained prompt (deep scan optional); merge and de-duplicate (FR-61). Filter recall and LLM recall are measured separately.
   - Provenance (document, page) is attached by code from chunk metadata, never generated by the LLM.
6. **Validate** with Pydantic and business rules (numeric quantities, units present or marked missing, known source reference, defined currency). Missing is never zero. Remember that schema-constrained output guarantees valid JSON, not correct values.
7. **Human review** beside the source PDF (edit/approve/reject, recording original value, correction, reviewer and timestamp).
8. **Export** any estimate version. A version that is not approved is clearly labelled DRAFT.

Financial maths uses `Decimal`. VAT behaviour is configurable and never assumed.

Supplier matching combines text similarity, product codes, dimensions/specs, units, manufacturer/model, price and date. Ambiguous matches require explicit human confirmation, and the lowest price is never auto-selected (FR-37).

## 11. UI Screens

Dashboard · Tender List · Tender Workspace · **Document Review (source PDF beside extracted fields)** · BoQ Editor · Supplier Comparison · Checklist · Settings · (stretch) Tender Q&A panel with streaming answer and citation chips. Mobile-responsive, keyboard-accessible, with a visible review state on every extracted value.

## 12. Security and Compliance

As base spec §4.3, §4.4 and §8.3: backend RBAC, tenant isolation (applied to chunk retrieval as well as relational data), authenticated same-origin downloads (signed links superseded in Slice 2, see ADR-0007), validated uploads, rate limits, secrets in environment variables, audit logging, tested backups. POPIA: privacy notice, retention/deletion, incident response, and a documented assessment before any data leaves our infrastructure.

**Tunnel and POPIA:** Cloudflare terminates TLS at its edge, which may be outside South Africa, so it sees plaintext and acts as a processor in a cross-border transfer. Use synthetic data only while the tunnel is the access path, and record this in the POPIA assessment.

**Hosting region:** hosting in a non-South African region is itself a cross-border transfer of personal information under POPIA (base spec §4.4), not only calls to a hosted LLM. Prefer an SA region where available, and document the assessment either way. Synthetic data only is used until that assessment is complete.

This is a planning document, not legal advice.

## 13. AI Evaluation

Build the test set early and generate synthetic documents from **ground-truth JSON** (items, quantities, units, requirements), so precision and recall are computed automatically and the set can be regenerated or expanded.

**Test set size (initial):** at least 8 synthetic tender packs (mix of native PDF, scanned PDF, XLSX BoQs, and messy layouts), at least 5 supplier quotations, about 150 BoQ lines in total, and about 60 labelled requirements.

**Targets (adjust after the first run):**

| Metric | Target |
|---|---|
| Quantity and unit accuracy (native PDF/XLSX BoQs) | ≥ 95% |
| Description accuracy | ≥ 90% (fuzzy match) |
| Requirement recall | ≥ 85% |
| Requirement precision | ≥ 80% |
| Supplier match accuracy (confirmed-correct among suggestions) | ≥ 80%, with all ambiguous cases flagged |
| Citation correctness (Q&A, if built) | ≥ 90% |

Also report: percentage of fields requiring correction, retrieval hit rate (right chunk in the top results), processing time and cost per document, and estimated time saved per tender. Critical fields (quantities, units, deadlines, specifications) get stricter criteria than summaries.

**Model comparison:** run the same set on the candidate models (§7) plus, optionally, one hosted model on synthetic documents only. Report the accuracy/latency trade-off and justify the default. Keep the synthetic set as a regression baseline.

**Owner:** the platform/trust member (M1) owns the test set and the evaluation script, so the person building the AI pipeline (M2) is not grading their own work.

## 14. Testing

Unit (calculations, validation, permissions, chunking, de-duplication), integration (upload to export, plus failure cases: corrupted file, OCR error, LLM timeout, invalid structured output, duplicate jobs, expired links), security (cross-tenant reads including chunk retrieval, ID guessing, privilege escalation, subscription bypass), and user acceptance testing with 3–5 contractors if available. Coverage goals: at least 70% on backend business logic (calculations, permissions, validation) and a passing CI run on every PR. Definition of Done follows base spec Appendix B.

## 15. Plan (32 days, 4 people)

The schedule follows the base spec's day-based roadmap (§10.1). Its "Weeks 26–30" is read as **days 26–30** (10–14 November), which falls inside the window, so the pilot/UAT stays in scope.

| Days | Focus | Deliverable |
|---|---|---|
| 1–4 | Discovery and setup: pick electrical, repo/CI/Docker skeleton, ERD draft, start the synthetic test set, line up contractor interviews | Validated scope + running skeleton |
| 5–12 | Auth, orgs/RBAC, tenders, secure upload, job model, PDF/OCR/spreadsheet extraction, chunking, pgvector + FTS index | Extraction prototype with editable results |
| 13–17 | BoQ schema/editor, deterministic calculations, validation, LLM structured extraction, review screen with PDF.js, supplier records and basic matching | Usable estimating workspace |
| 18–21 | Requirements (map over all chunks), checklist, tasks, source references | Tender preparation workspace |
| 22–25 | Excel/PDF exports, audit log, access controls, usage limits (mocked billing), backups, deployment, security tests | Controlled release |
| 26–30 | Pilot/UAT with 3–5 contractors, AI evaluation runs, pricing test; **stretch:** tender Q&A if the core is stable | Evidence and measured results |
| 31–32 | Documentation (ERD, architecture, evaluation, user guide), demo prep, final submission | Documentation + live link |

**Parallel track:** contractor interviews (5–10) run through weeks 1–3, not only in days 1–4, since rubric item 11 needs customer feedback and pricing evidence.

**Suggested split (4 members):** (1) backend/auth/tenancy/audit/security, (2) ingestion + AI pipeline + evaluation set, (3) frontend + PDF.js review UI, (4) BoQ/suppliers/exports + testing/DevOps/CI. Everyone contributes to documentation.

## 16. Deliverables and Marking Alignment

Final documentation (cover page: group name, 4 members' names and student numbers) and a working system (system folder **and a link to access it online**, both mandatory per Appendix D). Rubric weights, and where this PRD addresses each:

| Criterion | Marks | Covered by |
|---|---|---|
| Background & objectives | 5 | §1–2 |
| Requirements analysis | 10 | §4–6 |
| Architecture & database | 10 | §7–9 (ERD deliverable in §8) |
| UI/UX | 8 | §11 |
| Backend | 10 | §5, §9 |
| AI & document processing | 15 | §10, §13 |
| BoQ & supplier comparison | 10 | §10 |
| Security & compliance | 10 | §12 |
| Testing & QA | 8 | §13–14 |
| Deployment & documentation | 6 | §7 (CI), §21 (hosting), §15 (documentation) |
| Business feasibility & demo | 8 | §15 (interviews, UAT), §17 |

## 17. Business and Budget

SaaS subscription model; initial niche is electrical subcontractors, validated with contractor interviews. The base spec's **total** initial cash budget is R500–R1,500 (target under R2,000), not a monthly figure. Local models and open-source tooling cost nothing, but **hosting is a real cost** that must fit within the total: a domain, any paid VM or credits, and optional hosted-LLM API tests. Free options in §21 can bring cash spend near zero. Cost-control strategy and KPIs follow base spec §9.4 and §10.3. Pricing is tested during UAT, and the system makes no claims about tender success rates.

## 18. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Small model gives weak structured extraction | High | Deterministic table parsing first, schema-constrained output, human review, evaluation-driven model choice, configurable bigger-model fallback |
| Slow inference on GTX 1050 / CPU VM during demo | Medium | Streaming, small context, preload model, pre-processed demo documents, 1.5B fallback |
| Scanned or odd-format documents | Medium–high | Format limits, documented scanned-BoQ limitation, representative test set |
| Cross-tenant leakage via retrieval | High | Single tenant-filtered query function, `organisation_id` on every chunk, must-pass cross-tenant tests |
| Scope creep in 32 days | High | Strict MVP backlog (base spec Appendix A order); Q&A is stretch |
| Incorrect supplier matches | High | Multi-signal matching, mandatory confirmation |
| Memory spikes (OCR + LLM + Docker together) | Medium | Serial OCR, cap WSL2 memory, avoid running OCR and generation together |
| GPU driver / Ollama version breakage | Medium | Pin versions, CPU-only fallback |
| Free-tier hosting unavailable or removed | Medium | Keep a laptop + tunnel fallback (§21) |
| Data protection / cross-border hosting | High | Local-by-default AI, access controls, SA region where possible, synthetic data until POPIA assessment done |

## 19. Open Questions

**Decided**
- Frontend is **Next.js** + TypeScript + Tailwind.
- Develop and test locally (Docker Compose, Ollama on the host). An online link is **required** (Appendix D); it is provided by a free tunnel to the local machine (§21), and need not stay live after marking.
- **Synthetic** documents first; real ones can be added later (§20).
- Retrieval store is Postgres + pgvector + FTS.

**Still open**
1. ~~Hosting choice~~ **Decided:** local Docker Compose + native Ollama, exposed via a free tunnel (§21). The link need not stay live after marking.
2. Final default model, decided by the §13 evaluation.
3. ~~Evaluation owner~~ **Decided:** M1 (platform/trust).
4. Q&A is a stretch goal behind a feature flag, with a go/no-go on day 25.
5. ~~45-minute target and section-based extraction~~ **Decided:** pre-filter path with an optional deep scan (FR-61); the 45-minute target is met with a wide margin on synthetic data. Real-document recall of the filter is still unknown (§20).

## 20. Adding Real Documents Later

The system is designed so real tenders can be added without code changes. Tuning means adjusting the pipeline, not retraining the model:

- **What can be tuned:** extraction prompts and schemas, chunk size/overlap, RRF weighting, table-parsing rules per document layout, validation rules, and the model choice.
- **How:** add hand-verified real documents to the evaluation set, re-run the §13 metrics, and change one thing at a time. Keep the synthetic set as a regression baseline.
- **Not in scope:** fine-tuning the LLM. Prompt, retrieval and parsing improvements come first, and a bigger model is the next lever.
- **Synthetic set design:** make it deliberately messy (scanned pages, merged cells, inconsistent units, multi-page BoQs, near-identical cable specs) so tuning on real data later is a smaller step.
- **Handling rules for real documents:** only with the owner's written permission; anonymise client and personal details where possible; never commit them to git (keep them in an ignored, local-only folder); keep them out of any hosted LLM unless the POPIA assessment in §12 is done; delete them per the agreed retention period.

## 21. Hosting and Deployment

Local testing is the default. The online link is mandatory for submission, so one deployment is needed. The main constraint is the LLM: a small cloud VM has no GPU and little RAM.

### Options for the LLM in the deployed system

| Option | How | Trade-off |
|---|---|---|
| A. Everything on one CPU VM | Compose stack including Ollama on an 8 GB (ideally 16 GB) VM | Fully private, but slower than the laptop GPU and the most expensive. Use the 1.5B model or pre-processed demo documents. |
| B. Cloud app + hosted LLM API | Small VM (2–4 GB) for app and Postgres; model calls go to a hosted API | Cheap and fast. **Synthetic documents only** until the POPIA/contract assessment is done. The model is a config switch (FR-57). |
| C. Cloud app + local model via tunnel | Small VM for the app; the LLM stays on your machine | Keeps data local, but the demo breaks whenever your machine is off. Avoid for marking. |

### Indicative paid costs (list prices, about R17–18/USD, verify current)

| VM | Approx. per month | Fit with the R500–R1,500 total |
|---|---|---|
| Linode 8 GB | ~R850 | About one month |
| Azure B2ms (8 GB) | ~R1,100–1,250 | About one month |
| Linode 16 GB | ~R1,700 | Exceeds the whole budget |
| Azure B4ms (16 GB) | ~R2,100–2,500 | Exceeds the budget |

### Free or near-free options (verify current terms)

- **Laptop + Cloudflare Tunnel:** free public HTTPS link to the local Compose stack. Works only while the machine is on; keep as the backup.
- **Oracle Cloud Always Free (ARM, up to 4 CPU / 24 GB RAM):** can host the whole stack, including a small model on CPU. Needs a card for signup, and free ARM capacity can be unavailable in a region. Has a Johannesburg region.
- **Student or trial credits:** Azure for Students (about $100, no card), GitHub Student Developer Pack, and Azure/Google trial credits (about $200–300 for 30–90 days) would cover the marking window. Azure has a South Africa North region.
- **Free service tiers:** Vercel (Next.js), Neon or Supabase (Postgres with pgvector), free hosted-LLM API tiers (synthetic data only), Hugging Face Spaces (Docker, free CPU, sleeps when idle).

### Decision

Azure student credits and Oracle's free tier have already been used, and the link does not need to stay live after marking. The AI only has to run. **Decision: run everything locally (Docker Compose + native Ollama) and expose it through a free tunnel for the online link.**

- **Tunnel:** Cloudflare Tunnel (`cloudflared`). A quick tunnel needs no account and gives a random `trycloudflare.com` HTTPS URL, which changes on each restart. A named tunnel gives a stable URL but needs a domain on Cloudflare. ngrok's free plan with one static domain is an alternative.
- **Exposure:** tunnel only the Next.js frontend (or a single reverse proxy such as Caddy in front of frontend and API). Do not expose Postgres, Ollama or the worker.
- **Security while public:** HTTPS comes from the tunnel; enforce authentication on every route, rate limiting, and demo accounts with synthetic data only. Consider Cloudflare Access (free) or a shared demo password as an extra gate.
- **Marking-window checklist:**
  - Machine on, plugged in, sleep and hibernate disabled, Windows updates paused.
  - Stack and tunnel started via one script; model preloaded; health check page.
  - Post the current URL in the submission, and state that the demo is hosted on the developer's machine for marking.
  - Keep a short screen recording of the full flow as a backup in case the machine or tunnel is down.
- **Model:** the GTX 1050 and local CPU are the target, so the small model and pre-processed demo documents are the default. No hosted LLM is needed.
- **Portability rules (so moving to a VM stays easy):**
  - Everything except Ollama runs in Docker Compose; Ollama is reached through a single `LLM_BASE_URL` setting (host in dev, same VM or a sidecar container on a VM).
  - All configuration comes from environment variables (`.env.example` committed, real `.env` ignored): database URL, storage path/bucket, LLM URL and model name, allowed origins, secrets.
  - File storage sits behind one interface with a local-volume implementation now and a Blob/S3-compatible one later.
  - No hard-coded `localhost` or absolute paths; the frontend gets the API URL from configuration.
  - Postgres data and the file volume are named volumes with a documented backup/restore script.
  - A `docker-compose.yml` for local use and a small override file for a VM (reverse proxy with HTTPS, restart policies, no exposed DB port).
- **If the plan changes:** the stack is containerised, so it can move to any VM (A in the table above) with a config change, and a hosted LLM remains a config switch (FR-57) for synthetic data only.

### Operations

- HTTPS via a reverse proxy (Caddy or Nginx); secrets in environment variables; never reuse dev credentials.
- Back up Postgres (this now includes vectors and the keyword index) and the file volume, and test a restore.
- Stop or delete paid VMs after marking to avoid charges.
- Blob storage free tiers are typically time-limited (for example 12 months on new Azure accounts), so check before relying on them.
