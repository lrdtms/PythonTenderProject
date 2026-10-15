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
| 3 Extraction | 10-14 | Deterministic BoQ parser; requirement extraction (pre-filter + prompt v3); provenance by code; failure paths | Synthetic packs score at the harness targets; requirements and BoQ lines stored with sources |
| 4 Review UI | 12-18 | Next.js: auth, tender workspace, upload with progress, PDF.js review beside extracted fields, checklist, BoQ editor | Review and correct extracted values next to the source page (starts in parallel with slice 3's tail) |
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
