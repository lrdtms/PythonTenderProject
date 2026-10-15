# IntelTPS Delivery Plan

**Version:** 1.0 (draft) · **Date:** 15 October 2026
**Inputs:** `prd.md` v0.3, `docs/architecture/architecture.md` (modules, fitness functions F1–F11, Implementation Brief), `Python_Project.pdf` (rubric)
**Window:** Day 1 = Fri 16 Oct 2026 … Day 32 = Mon 16 Nov 2026 (weekends included in the day count; each member decides their own weekend work)

Members (from the architecture): **M1** Platform & trust · **M2** Ingestion & AI · **M3** Frontend · **M4** Estimating & delivery. Names to be assigned.

---

## 1. Principles

1. **Walking skeleton first.** By day 12 a document can go from upload to an editable result, even if crude. Everything after refines a working flow.
2. **Contracts before code.** Day 4 is a hard freeze of the shared interfaces (§4). M3 builds against mocks from then on.
3. **Safety nets before features.** Import boundaries (F2), schema tenancy (F3) and the CI pipeline exist before module code.
4. **Deterministic before AI.** The BoQ parser and calculations are shipped and tested before the LLM adds anything.
5. **Scope is protected.** Cut order is fixed in advance (§8). Q&A is the first thing to go.
6. **The rubric drives priority.** Weak spots cost marks: AI/doc processing (15), requirements (10), architecture (10), backend (10), BoQ/suppliers (10), security (10).

## 2. Phases and milestones

| Phase | Days (dates) | Goal | Exit gate (must be true to move on) |
|---|---|---|---|
| P0 Setup and spikes | 1–4 (16–19 Oct) | Repo, CI, Compose, spikes, contract freeze | CI green on an empty skeleton; spike results recorded; **contracts frozen** |
| P1 Core and extraction | 5–12 (20–27 Oct) | Auth, tenancy, upload, ingest, first BoQ extraction | **M-A (day 12):** upload a synthetic PDF, see extracted BoQ lines with source pages in the UI, edit one. F1 and F4 green and blocking |
| P2 Estimating | 13–17 (28 Oct–1 Nov) | BoQ editor, calculations, LLM refine, suppliers | **M-B (day 17):** import a quotation, see match suggestions, confirm one, see correct totals |
| P3 Tender intelligence | 18–21 (2–5 Nov) | Requirements, checklist, tasks, deadlines | **M-C (day 21):** requirements extracted with page links, reviewed, assigned; checklist report downloads |
| P4 Reports and hardening | 22–25 (6–9 Nov) | Exports, audit, limits, backups, security tests, demo script | **M-D (day 25):** Excel and PDF exports, full CI gates green, backup/restore tested, **Q&A go/no-go**, RLS go/no-go |
| P5 Pilot, evaluation, docs | 26–30 (10–14 Nov) | UAT, AI evaluation numbers, pricing test, documentation | **M-E (day 30):** evaluation report and UAT feedback recorded; documentation drafted |
| P6 Freeze and submit | 31–32 (15–16 Nov) | Bug fixes only, demo rehearsal, submission | Submission pack complete; tunnel demo rehearsed; backup recording saved |

Weekend days (17–18, 24–25 Oct, 31 Oct–1 Nov, 7–8, 14–15 Nov) are buffer. Plan assumes no one is required to work them, but P5 and P6 may need them.

## 3. Critical path

`Repo + CI + contracts (d4)` → `auth + tenancy + upload (d12)` → `ingest + BoQ parse (d12)` → `BoQ editor + calcs (d17)` → `requirements + checklist (d21)` → `exports + hardening (d25)` → `UAT + evaluation (d30)`.

Parallel tracks that do **not** block it: synthetic data generation (M1), contractor interviews (everyone, weeks 1–3), frontend against mocks (M3), ops scripts (M4), model spikes (M2).

## 4. Day 1–4 deliverables (contract freeze)

By end of day 4 these exist, are reviewed by all four, and then change only by agreement:

- `kernel` types and ports: `OrgContext`, `Role`, `SourceRef` (document version, physical page or sheet+range), `Money`, error types, `LLMPort`, `EmbeddingPort`, `StoragePort`, `JobQueuePort`.
- ERD v1 with `organisation_id` on every org-owned table and composite foreign keys.
- Job types and statuses; `GET /api/v1/jobs/{id}` shape.
- Candidate DTOs: `BoqCandidate`, `RequirementCandidate`, `QuotationItemCandidate` (with `evidence_quote`, no provenance fields).
- Error format and an OpenAPI stub; the frontend generates a TypeScript client from it.
- Ground-truth JSON schema for synthetic tenders (the evaluation set generator reads this).

## 5. Work by member

Task IDs are for the board. Days are targets, not promises; the gates in §2 are what matter.

### M1 Platform & trust (kernel, identity, billing, audit, tenders, documents, checklist; evaluation set)
| ID | Task | Days | Done when |
|---|---|---|---|
| M1-1 | Ground-truth JSON schema and first synthetic generator (tender PDF, XLSX BoQ, quotation) | 1–4 | 3 documents generated from JSON, including one scanned and one messy |
| M1-2 | `kernel` types, `OrgContext`, scoped repository base, error format | 2–4 | Frozen contracts merged |
| M1-3 | Identity: register/login/refresh/logout, memberships, roles from DB, invites | 5–9 | Auth flow works; roles checked on backend |
| M1-4 | Tenders CRUD + archive; documents upload with validation (python-magic, size, limits), versions, signed links | 7–12 | Upload returns a job id; F1 route sweep passing |
| M1-5 | F1, F3, F4 (with canary data), F5 tests | 6–12 | Blocking in CI |
| M1-6 | Billing (mocked limits) and audit events | 10–14 | Limits enforced; audit has no document text (F9) |
| M1-7 | Expand synthetic set to the §13 size (≥8 packs, ≥5 quotations, ~150 BoQ lines, ~60 requirements) | 8–20 | Set stored with ground truth |
| M1-8 | Checklist: requirements review, assignment, tasks, deadlines, reminders | 18–21 | M-C |
| M1-9 | Evaluation script (metrics from PRD §13) and first baseline run | 20–25 | Baseline numbers recorded |
| M1-10 | Security test pass, POPIA notes, privacy notice | 22–25 | Checklist items in the documentation |
| M1-11 | Run full evaluation, model comparison, write results | 26–30 | Evaluation section drafted |

### M2 Ingestion & AI (knowledge, extraction, worker, adapters, qa)
| ID | Task | Days | Done when |
|---|---|---|---|
| M2-1 | **Day 1 spike:** Ollama reachable from a container; structured output with each candidate model; tokens/s and per-section latency; thinking mode off | 1–2 | Numbers recorded; model shortlist; confirms or revises the 45-minute target |
| M2-2 | **Day 2 spike:** pgvector + FTS + RRF query on 20k fake chunks | 2–3 | p95 recorded; query design agreed |
| M2-3 | Port adapters: `OllamaAdapter`, `FakeLLM`, `FastEmbedAdapter`; Postgres job queue (SKIP LOCKED, leases, reaper) | 3–8 | Worker runs a no-op job end to end; F6 queue part |
| M2-4 | `knowledge.ingest`: PyMuPDF text, pdfplumber tables, Tesseract OCR with per-page timeout, chunking, embeddings | 5–12 | A synthetic PDF is ingested with pages and chunks; replace-set idempotency |
| M2-5 | `extraction.parse_boq` (deterministic) for PDF tables and XLSX | 7–12 | BoQ lines with source page/range appear; unit tests |
| M2-6 | `knowledge.search` (tenant + tender + current version filters inside both CTEs) | 9–12 | F4 green |
| M2-7 | LLM refine for BoQ; quotation extraction (`parse_quotation`) | 13–17 | Schema-constrained output, evidence check, flags |
| M2-8 | Requirement extraction over sections (map-then-merge), evidence-quote page lookup, validators | 16–21 | Recall measured on the synthetic set |
| M2-9 | Failure paths from architecture §5: OCR, timeout, invalid output, partial results; job warnings | 14–22 | F6 and F8 green |
| M2-10 | Q&A (stretch): `ask_stream`, citations, feature flag | 22–25 | Only if go on day 25 |
| M2-11 | Prompt and retrieval tuning from the evaluation | 26–30 | Metrics improve on the baseline |

### M3 Frontend (Next.js, PDF.js, editors)
| ID | Task | Days | Done when |
|---|---|---|---|
| M3-1 | App shell, Tailwind setup, generated API client, auth pages, mock server | 2–8 | Login and navigation work against mocks |
| M3-2 | Tender list and workspace; upload with progress polling | 7–12 | Upload shows job status and failures |
| M3-3 | Document review screen: PDF.js at the cited page beside extracted fields; review state badges | 9–14 | Click a field, source page opens (**M-A**) |
| M3-4 | BoQ editor (editable table, flags, original vs corrected, totals) | 13–17 | M-B |
| M3-5 | Supplier comparison screen (evidence, unit differences, confirm/reject) | 15–19 | Ambiguous matches need an explicit click |
| M3-6 | Checklist screen, tasks, dashboard (deadlines, failures) | 18–22 | M-C |
| M3-7 | Settings, usage page, exports download, mobile and keyboard polish | 22–25 | M-D |
| M3-8 | Q&A panel with stream reader (stretch) | 24–27 | Only if go |
| M3-9 | Accessibility and responsive fixes from UAT | 26–30 | UAT issues closed |

### M4 Estimating & delivery (estimating, suppliers, reporting, DevOps, CI)
| ID | Task | Days | Done when |
|---|---|---|---|
| M4-1 | Repo, branching, Docker Compose (Postgres+pgvector, API, worker, web, Caddy), `.env.example` | 1–3 | `docker compose up` works on every laptop |
| M4-2 | CI: pytest, ruff, import-linter (F2), frontend tests; migrations check | 2–4 | Green on skeleton; F2 contracts in place |
| M4-3 | ERD draft and Alembic baseline | 3–5 | ERD v1 in contract freeze |
| M4-4 | `estimating`: BoQ items with original/corrected values, review states, `replace_unreviewed` | 8–14 | Edits survive re-runs |
| M4-5 | Deterministic calculations (Decimal, markup, VAT on/off) with golden and property tests (F7) | 10–16 | No `float`; tests green |
| M4-6 | `suppliers`: records, quotation items, rule-based matching with evidence | 13–19 | Matches need confirmation; lowest price never auto-selected |
| M4-7 | `reporting`: Excel export (approved vs labelled draft) and PDF checklist report | 19–25 | Export <10 s for 1,000 lines (F11) |
| M4-8 | Ops: `start-demo` script (Compose, preload model, tunnel, health check), backup and restore | 18–25 | Restore tested from a backup |
| M4-9 | Performance smoke (F11), rate limits, upload limits | 22–25 | Targets met or documented |
| M4-10 | Deployment notes, user guide, technical documentation structure | 24–30 | Docs skeleton filled |

## 6. Cross-cutting tracks

**Contractor interviews and UAT (everyone).** Aim for 5–10 short interviews during days 1–21 (a shared notes document: pains, current process, willingness to pay, price reaction). UAT with 3–5 people on days 26–30, using synthetic or permissioned documents only. This is the evidence for the business-feasibility rubric item (8 marks).

**Documentation (everyone, M4 coordinates).** Write as you build, not at the end:
- Background/objectives and requirements: from the PRD.
- Architecture, ERD, API design: from `docs/architecture/` plus the generated OpenAPI.
- AI/evaluation: M1/M2 results.
- Security and POPIA: M1.
- Testing: CI results, F1–F11 table, UAT notes.
- Cover page: group name, 4 members' names and student numbers.

**Rubric tracker.** Review it at the end of every phase: does each of the 11 rubric rows have visible evidence yet?

## 7. Working agreements

- Short-lived feature branches, pull request per task, at least one reviewer; CI must be green to merge.
- A task is done per base spec Appendix B (validation, permissions, tests, errors handled, no sensitive logging, documented, limitations recorded).
- 15-minute stand-up each working day (what shipped, what is blocked, which contract needs to change).
- Contract changes after day 4 need a one-line note in the shared channel and an update to the OpenAPI/DTOs before code.
- Frontend flows: each backend owner writes the Playwright journey for their own flow; M3 owns shared components.
- Demo machine: one person (M4) owns the demo laptop setup; others use their own Compose stack.

## 8. Risks and cut order

| Risk | Trigger | Response |
|---|---|---|
| Model too slow or poor on the laptop | Day 1–2 spike misses the 45-minute target, or evaluation below target | Use the smaller model, larger sections, pre-process demo documents; fall back to a hosted model on synthetic data (config switch) |
| Contract freeze slips | Day 4 passes with open contract items | Freeze what exists; list the rest; M3 uses mocks for the unfrozen items |
| M3 overloaded (8 screens) | Day 12 gate missed or UI backlog > 1 week | Backend owners build their own basic forms; prioritise the review screen and BoQ editor |
| Scanned-document quality | OCR confidence low on test packs | Documented limitation; scanned BoQs flagged for manual entry |
| Tenant-isolation bug | F1/F4 red | Stop feature merges until fixed; this beats everything else |
| Tunnel or laptop down at marking | Demo unavailable | Recorded walkthrough; restart script; second machine with the same Compose stack |
| Illness or absence | Any member out > 3 days | Reassign by module table; use the interface docs to hand over |

**Cut order if time runs out (first to cut first):**
1. Q&A (US-06) and its UI.
2. Optional RLS hardening.
3. Email notifications (in-app reminders stay).
4. PDF checklist report polish (keep Excel export).
5. Supplier-matching extras beyond unit, price, spec and confirm/reject.
6. Dashboard extras.

**Never cut:** tenant isolation tests, deterministic calculations, human review of extracted values, source references, Excel export, audit trail, backups, documentation.

## 9. Immediate next actions (day 1)

1. M4: create the repo, branching rules and Compose skeleton; run CI.
2. M2: Ollama and structured-output spike; record tokens/s per model.
3. M1: ground-truth schema and first synthetic documents.
4. M3: Next.js shell and mock API.
5. Everyone: book the first contractor interviews; agree names and ownership in the board; record the day-1 spike results in the architecture notes.
6. Group: decide the model shortlist and confirm or revise the 45-minute target (PRD open item 5).
