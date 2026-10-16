# IntelTPS Delivery Plan (solo build)

**Version:** 2.0, solo build · **Date:** 15 October 2026 · supersedes the 4-person plan (v1.0, kept in git history)
**Inputs:** `prd.md` v0.3, `architecture/architecture.md`, `Python_Project.pdf` (rubric)
**Window:** Day 1 = Fri 16 Oct 2026 … Day 32 = Mon 16 Nov 2026. Days are targets: the gates matter, not the dates. Adjust the dates to the hours you actually have.

## 1. What changes for a solo build

- **No coordination overhead:** no contract freeze, no mocks for another developer, no interface hand-offs. The module boundaries stay (they keep the code testable), enforced by import-linter.
- **Vertical slices, not parallel tracks:** each slice ends with something that runs end to end and is committed. If time runs out, the last finished slice is the demo.
- **Foundation first, UI early:** the UI is built as each backend slice lands, so there is never a "big UI week at the end".
- **Scope cuts** (the earlier cut order, applied up front; recorded in ADR-0010):
  - Q&A (US-06) is out of scope.
  - Email notifications and invite emails are out. The admin creates member accounts directly; in-app reminders stay.
  - No separate Platform Admin role or console. Roles: admin, estimator, project manager, reviewer.
  - Auth uses server-side sessions (simpler than JWT + refresh rotation; ADR-0008 option 4).
  - Billing/usage limits: a plan table with enforced upload limits, no payment gateway (already mocked).
  - No RLS, no Celery, no staging environment.
  - Scanned documents: OCR for text requirements only; scanned BoQs are flagged for manual entry.
- **Never cut:** tenant isolation tests, deterministic Decimal calculations, human review of extracted values, source references, Excel export, audit trail, backups, documentation.

## 2. Already done (Slice 0)

Repo, Compose stack (Postgres + pgvector, API, worker, web, Caddy), CI, architecture and ADRs, synthetic data generator with ground truth, evaluation harness, Ollama speed test, pre-filter and prompt experiments (prompt v3 + pre-filter, ~3 min for a 96-page pack), docs.

## 3. Slices

| Slice | Target days | Goal | Exit gate |
|---|---|---|---|
| 1 Foundation | 1-4 | Schema + migrations, kernel types, auth (sessions), organisations and roles, tenders CRUD, audit, error format | Register, log in, create a tender; cross-tenant route sweep (F1), schema tenancy (F3) and import rules (F2) green in CI |
| 2 Documents and jobs | 5-9 | Upload with validation, storage port, versions, Postgres job queue, worker, ingest (text, tables, OCR, chunking, embeddings) | Upload a synthetic PDF, watch the job progress, see pages and chunks stored; idempotent re-run (F6). **Status (2026-10-15): verified on the Docker stack through Caddy** (native PDF, scanned PDF via Tesseract OCR, XLSX; job progress, pages, full-text search; worker log free of document text); embeddings deferred, search is full-text |
| 3 Extraction | 10-14 | Deterministic BoQ parser; requirement extraction (pre-filter + prompt v3); provenance by code; failure paths | Synthetic packs score at the harness targets; requirements and BoQ lines stored with sources **Status (2026-10-15): gate run on the real Docker stack with host Ollama (qwen3:4b, prompt v3, filter pf-1); all PRD targets pass on the native packs and every critical counter is 0.** Seed 42 native: requirement recall 96%, precision 98%, BoQ quantity/unit/description 100%/100%/100%. Seed 43 native: recall 98%, precision 95%, BoQ 100%/100%/100%. Scanned packs reported separately (recall 100%, precision 94%; scanned PDF BoQ deliberately not auto-extracted, `BOQ_NEEDS_MANUAL_ENTRY`). About 90-140 s per pack. Details: [slice-3-scores.md](spikes/slice-3-scores.md). Scored before the final review fix wave (see that file); open items: [known-limitations.md](known-limitations.md) |
| 4 Review UI | 12-18 | Next.js: auth, tender workspace, upload with progress, PDF.js review beside extracted fields, checklist, BoQ editor | Review and correct extracted values next to the source page (starts in parallel with slice 3's tail) **Status (2026-10-16): phase 1 (backend review API) done: review routes, source_order, tender requirements list (commits adbb726..26a7219), merged to `main`. Phase 2 (frontend foundation) done on `feat/slice-4-phase-2-frontend-foundation`: typed API client generated from a committed `openapi.json`, cookie-session auth pages and route guard, app shell, Vitest in CI, and a PDF.js page renderer proven in dev and production builds (see [slice-4-pdfjs.md](spikes/slice-4-pdfjs.md)). Phase 3 (tender workspace) done on `feat/slice-4-phase-3-tender-workspace`: tender list with create and archive, tender page with documents and versions, upload with progress and client-side validation, job progress with bounded polling and retry, extraction status with deep-scan re-run, and a global 401 re-check; verified in a real browser with the real worker (upload, failure and retry, 25 MB block, archive read-only, reviewer read-only, stopped worker, expired session). Phase 4 (review screen) done on `feat/slice-4-phase-4-review-screen`: review screen at `/tenders/[id]/review/[versionId]` with requirement and BoQ rows (state badges, flag chips, original versus corrected values, reviewer and time), confirm, reject and inline edit with optimistic update and per-row rollback, a "replaced by a re-run" notice that keeps an unsaved edit, keyboard (arrows, c, r, e), a source viewer (PDF.js canvas plus the page text with the quote marked, sheet grid with the cited range, text-only DOCX and OCR badge), and "Load more" paging. Verified in a real browser on the rebuilt Docker stack (register, upload, extract, review, correct, confirm, reject, reload, BoQ re-run keeps reviewed rows, reviewer role read-only); a Fable review of the branch found 3 high and 6 medium issues (quote offsets, OCR badge, replaced notice, shortcut and rollback bugs, 422 messages) that were fixed before merge. Phase 5 (checklist) done on `feat/slice-4-phase-5-checklist`: tender-wide requirements checklist at `/tenders/[id]/checklist` grouped by type with review-status and type filters (server) and a mandatory-status filter (client), document name and page on each row, and "Open in review" links that preselect the row (`?row=`); the inline BoQ editor from phase 4 already covers item no, section, description, unit, quantity and rate. Phase 6 (members) is next.** |
| 5 Estimating and suppliers | 17-22 | Decimal calculations, estimate versions and statuses, suppliers, quotations, rule-based matching, confirm/reject | Totals correct; ambiguous matches need a click; golden-file tests (F7) |
| 6 Reports and operations | 22-26 | Excel export, PDF checklist report, audit view, usage limits, start-demo script, backup/restore, tunnel | Export approved estimate; restore tested; demo starts with one command |
| 7 Hardening and evidence | 26-30 | Security tests, evaluation runs and model comparison, real/public-document check, UAT, documentation | Evaluation report; security checklist; documentation drafted |
| 8 Freeze and submit | 31-32 | Bug fixes only, demo rehearsal, recording, submission pack | Submission complete |

Slice 1 is the only one that blocks everything else. Slices 2 and 3 are the heaviest and the highest-risk for the rubric (AI and document processing, 15 marks).

## 4. Slice 1 task list (Foundation)

1. Dependencies: Alembic, Argon2, email validation. Add the `app.db` persistence package (Base, session factory, tenant-scoped repository base) below `modules` in the import contract.
2. Kernel: `OrgContext`, `Role` and permissions, domain errors.
3. Schema + migration: users, organisations, memberships, sessions, tenders, audit_events. `organisation_id` on every org-owned table, composite foreign keys.
4. Identity module: register (creates user, organisation, admin membership), login, logout, `/me`, member management (admin creates and deactivates members, role change), password rules.
5. Audit module: append-only events with safe metadata only.
6. Tenders module: create, list, get, update, archive with role checks.
7. API: cookie sessions, CSRF header, consistent error format, `/api/v1` routes.
8. Tests: unit and API tests, **F1 route sweep, F2 boundary and raw-SQL checks, F3 schema tenancy**; CI with a pgvector service container.
9. Compose: the API container runs migrations on start.

## 5. Working agreements (solo)

- One short-lived branch per slice or task; merge when its gate passes. `main` is always runnable.
- CI green before merging (pytest, ruff, import-linter, frontend build, dependency audit, eval tests).
- Write the test for a security rule before relying on it; the F-numbered fitness functions are the safety net.
- Update the docs when a decision changes (ADR or PRD note), not at the end.
- Keep a running list of known limitations for the documentation.

## 6. Risks and cut order (solo)

| Risk | Response |
|---|---|
| Time runs short | Slices are ordered by value; cut from the end: reports polish, then matching extras, then dashboard extras. Slices 1-3 plus a basic review UI are the minimum credible demo |
| Extraction quality on real documents is worse than on synthetic data | Deep scan fallback, review UI, public-document check in slice 7, honest evaluation write-up |
| Laptop unavailable or tunnel down at marking | Recorded walkthrough; one-command start script; backup recording |
| Burn-out or an unavailable week | Slices are independent commits; scope is already cut; the PRD cut order still applies |
