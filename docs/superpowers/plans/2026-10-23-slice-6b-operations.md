# Slice 6b: Audit view, usage limits and operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** An organisation-scoped audit view, enforced and race-safe usage limits on two seeded plans (mocked billing), a public status page, and Windows ops scripts (start-demo, tunnel, backup, restore) with a restore proven by manifest comparison.

**Architecture:** `audit` gains a scoped read repo and service. `billing` (empty stub) gets `plans`, `organisation_plans` and a limit service that takes counts from the router; counts live in each owning module's `public.py`. Routers `audit.py` and `usage.py` plus a status route in `main.py`. Frontend pages `/audit`, `/settings/usage`, `/status`. Scripts in `scripts/ops/` (PowerShell 7) with stdlib-only Python `scripts/ops_preflight.py` for testable rules.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres, pytest, import-linter, ruff; Next.js, TypeScript, Vitest, openapi-typescript; PowerShell 7, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-23-slice-6b-operations-design.md` (read first; "D" numbers are its decisions).

## Global Constraints

- Every new organisation-owned table has `organisation_id` and composite FKs (F3). Another organisation always gets 404/empty, never data. Modules import each other only through `public.py`; `billing` imports only `kernel`, `db`, `audit`.
- No raw SQL outside repositories (F2), except the advisory-lock call inside `billing/repo.py`.
- Audit metadata is rendered as text only; the response re-filters to `SAFE_METADATA_KEYS`.
- Limits are enforced server-side in the request transaction under `pg_advisory_xact_lock`; counts are computed live, never stored.
- Scripts never print secrets, never write outside the repo, and `restore -Apply` refuses the live project without `-IKnowThisReplacesLiveData`.
- Ruff line length 100. Do not claim a check that was not run; list gaps under "Not covered" in the gate note.
- Backend check before each commit touching it, in `backend/`: `uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run pytest -q` (set `DB_HOST_PORT` if Postgres is not on 5432; the `db` service must be up). Frontend, in `frontend/`: `npm run lint && npm run typecheck && npm run build && npx vitest run`. After DTO changes: `uv run python -m app.api.export_openapi` in `backend/`, `npm run gen:api` in `frontend/`.

## Review Focus

1. **Tenancy:** audit list/facets and usage counts never include another organisation (Tasks 1, 3, 4).
2. **Race:** two concurrent creates for the last slot yield exactly one success, for tenders and members (Task 4).
3. **No bypass:** every creating path is guarded: tender create, document upload and new version, export create, member create and reactivate (Task 4).
4. **Restore honesty:** `-Verify` fails on a tampered dump, a tampered archive and a count mismatch; `-Apply` refuses the live project (Task 8).
5. **Unsafe config cannot reach the tunnel** (Task 7).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/modules/audit/repo.py`, `schemas.py`, `service.py`, `public.py` | Scoped keyset read, DTOs, `list_events`, `facets` |
| `backend/app/api/routers/audit.py` | `GET /api/v1/audit`, `/audit/facets` |
| `backend/app/modules/billing/models.py`, `repo.py`, `schemas.py`, `service.py`, `public.py` | Plans, org plan, `check_limit`, `usage_for`, `set_plan` |
| `backend/app/api/routers/usage.py`, `backend/app/api/limits.py` | `GET /usage`, `PUT /usage/plan`; `enforce(...)` helper that gathers counts and calls billing |
| `backend/migrations/versions/0008_plans_usage.py` | `plans` (seeded), `organisation_plans` |
| `public.py` of tenders, documents, identity, reporting | `count_*` functions |
| `backend/app/api/main.py`, `backend/app/api/status.py` | `GET /api/v1/health/status` |
| `backend/tests/test_audit_api.py`, `test_billing_store.py`, `test_usage_api.py`, `test_limits_enforcement.py`, `test_status_api.py`, `test_ops_preflight.py`, `test_ops_scripts.py` | Tests |
| `scripts/ops_preflight.py` | Pure config validation |
| `scripts/ops/start-demo.ps1`, `tunnel.ps1`, `backup.ps1`, `restore.ps1`, `common.ps1` | Ops scripts |
| `docker-compose.restore-test.yml` | Second-project override (Caddy on 8081, no DB port) |
| `frontend/src/api/audit.ts`, `usage.ts`, `status.ts` (+ tests) | Hooks |
| `frontend/src/app/(app)/audit/`, `(app)/settings/usage/`, `app/status/` | Pages (+ tests) |
| `frontend/src/components/app-shell.tsx` | Nav links |
| `docs/prd.md`, `docs/plan.md`, `docs/architecture/architecture.md`, `docs/known-limitations.md`, `README.md`, `.env.example`, `.gitignore`, `docs/spikes/slice-6b-gate.md` | Documentation |

---

## Task 1: Audit read API

**Interfaces:** Produces `audit.list_events(session, ctx, filters, cursor, limit) -> AuditPage`, `audit.facets(session, ctx) -> AuditFacets`, DTOs `AuditEventDTO{id, created_at, user_id, entity_type, entity_id, action, metadata}`, `AuditPage{items, next_cursor}`; router adds `user_name`. Consumes `identity.member_names`.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_audit_api.py` (use the fixtures of `test_exports_api.py` for orgs/roles): `test_admin_and_pm_can_list`, `test_estimator_and_reviewer_get_403`, `test_unauthenticated_401`, `test_newest_first_and_cursor_paging_has_no_gaps_or_duplicates` (60 events, limit 25, three pages, ids unique, descending), `test_filters_action_entity_type_user_and_dates`, `test_other_organisation_events_never_returned` (and null-organisation events), `test_metadata_only_safe_keys` (insert an event row directly with an unsafe key via the model; response omits it), `test_user_name_resolved_and_unknown_is_null`, `test_bad_cursor_422`, `test_limit_bounds` (0 and 101 give 422), `test_facets_distinct_and_scoped`.
- [ ] **Step 2:** Run `uv run pytest -q tests/test_audit_api.py`. Expected: FAIL (404 route / import errors).
- [ ] **Step 3: Implement.** `repo.py`: `AuditRepo(session, ctx)` with `page(filters, cursor, limit)` selecting `AuditEvent` where `organisation_id == ctx.organisation_id` (never null), ordered `created_at desc, id desc`, keyset `(created_at, id) < cursor`, fetch `limit+1`; `facets()` distinct `entity_type`, `action`. Cursor = urlsafe base64 of `"{iso}|{uuid}"`, parsed strictly (ValidationFailed on junk). `service.py`: `ctx.require(Permission.VIEW_AUDIT)`; build DTOs filtering metadata to `SAFE_METADATA_KEYS`. Router: collect `user_id`s, call `identity.member_names`, map to `user_name`. Register in `main.py`. Date filters: `from` start of day UTC, `to` end of day UTC.
- [ ] **Step 4:** Add the audit list to `test_f1_lists_never_mix_organisations` in `tests/test_fitness_functions.py` (two organisations each with events; assert disjoint). Run `uv run pytest -q tests/test_audit_api.py tests/test_fitness_functions.py`. Expected: PASS.
- [ ] **Step 5:** Export openapi, run the backend check, commit `feat: audit view API (admin and project manager), scoped keyset paging`.

**Task test command:** `cd backend && uv run pytest -q tests/test_audit_api.py tests/test_fitness_functions.py`

## Task 2: Audit view page

**Interfaces:** Consumes the Task 1 OpenAPI types and `me` (role) from `session.ts`.

- [ ] **Step 1:** `npm run gen:api`. Write failing Vitest tests: `frontend/src/api/audit.test.tsx` (hooks call `/audit` with filters, `useInfiniteQuery` follows `next_cursor`), `frontend/src/app/(app)/audit/audit-view.test.tsx`: renders rows with humanised "Estimate approved", shows "Unknown user" when `user_name` null, metadata as text (a value `<b>x</b>` renders literally), filters send params, "Load more" appears only with a cursor and appends, empty state wording, 403 shows "You do not have access to the audit trail", dark/light classes follow the existing tokens (copy the table styling of `members-view.tsx`), and `app-shell.test` (extend existing if present) shows the Audit link for admin and project manager only.
- [ ] **Step 2:** Run `npx vitest run src/app/\(app\)/audit src/api/audit`. Expected: FAIL.
- [ ] **Step 3:** Implement `api/audit.ts`, `(app)/audit/page.tsx`, `audit-view.tsx` (follow `frontend/AGENTS.md` and the layout of `members-view.tsx`), add the nav link in `app-shell.tsx`. Humanise: `` `${Entity} ${action with _ as space}` `` capitalised once.
- [ ] **Step 4:** Run the same tests, then the frontend check. Expected: PASS. Commit `feat: audit page and nav link`.

**Task test command:** `cd frontend && npx vitest run`

## Task 3: Plans, usage store and API

**Interfaces:** Produces `billing.public`: `Resource` (`StrEnum`: `tenders`, `uploads`, `storage_mb`, `exports`, `members`), `Counts` (dataclass, one int per resource), `usage_for(session, ctx, counts) -> UsageDTO`, `check_limit(session, ctx, resource, counts_fn, adding=1)`, `set_plan(session, ctx, plan_code)`. Count functions: `tenders.count_active(session, ctx)`, `documents.count_uploads_since(session, ctx, since)` and `documents.storage_bytes(session, ctx)`, `reporting.count_exports_since(session, ctx, since)`, `identity.count_active_members(session, ctx)`. `since` = first instant of the current UTC month, computed in `billing` (`month_start(now)`).

- [ ] **Step 1: Write failing tests.** `tests/test_billing_store.py`: migration seeds exactly `demo` and `starter` with the D4 numbers; no plan row means `demo`; `plans` check constraints reject zero and negative limits; `organisation_plans` composite FK to memberships (F3 tests in `test_fitness_functions` must still pass); `month_start` at 2026-10-31T23:59:59Z and 2026-11-01T00:00:00Z; each `count_*` is organisation-scoped and ignores archived tenders; `storage_bytes` sums `document_versions.file_size`. `tests/test_usage_api.py`: `GET /usage` as every role (200), shape and `period` values, 401 anonymous; `PUT /usage/plan` admin 200 and audited (`plan_changed`, appears in the audit API), estimator/PM/reviewer 403, unknown code 404, malformed 422; usage reflects the new plan; another organisation's plan unaffected.
- [ ] **Step 2:** Run both files. Expected: FAIL.
- [ ] **Step 3: Implement.** Migration `0008` (revision `0008`, down `0007`): `plans` seeded with `op.bulk_insert`; `organisation_plans`. Models in `billing/models.py` registered via `model_registry`. `repo.py`: `PlanRepo` (get plan, get org plan, upsert), `lock(session, organisation_id, resource)` using `pg_advisory_xact_lock(hashtextextended(:key, 0))`. Add `billing` to the import-linter isolation contracts (new contract "billing is isolated" forbidding all other modules). Router `usage.py`; `api/limits.py` holds `gather_counts(session, ctx)` calling the five count functions. Count functions go into each module's `repo`/`service`/`public` (scoped repositories only).
- [ ] **Step 4:** Run both files plus `tests/test_fitness_functions.py tests/test_migrations*` if present. Expected: PASS.
- [ ] **Step 5:** Export openapi, backend check, commit `feat: plans, organisation plan and usage API (mocked billing)`.

**Task test command:** `cd backend && uv run pytest -q tests/test_billing_store.py tests/test_usage_api.py tests/test_fitness_functions.py`

## Task 4: Enforce limits

**Interfaces:** Consumes Task 3. Produces `api.limits.enforce(session, ctx, resource, adding=1)` which locks, counts the one needed resource, raises `LimitExceeded("{Label} limit reached on the {plan} plan ({used} of {limit}).")`.

- [ ] **Step 1: Write failing tests** `tests/test_limits_enforcement.py` (switch the test organisation to `starter` via `PUT /usage/plan`): `test_fourth_tender_refused_403_limit_exceeded_and_nothing_created`, `test_archive_frees_a_tender_slot`, `test_eleventh_upload_in_month_refused` (and a previous-month upload, backdated `created_at`, does not count), `test_new_version_counts_as_an_upload`, `test_storage_limit_counts_incoming_bytes` (set storage via a 50 MB plan: upload that would pass it is refused, the file is not stored), `test_twenty_first_export_refused`, `test_fourth_member_refused_and_reactivation_refused_at_limit`, `test_message_names_resource_limit_and_plan`, `test_reads_and_edits_not_blocked_when_over_limit` (downgrade to starter with 5 tenders: list/get/patch still 200, create 403), `test_demo_plan_does_not_limit_normal_use`, `test_other_organisation_usage_does_not_count`, `test_last_slot_race_tenders` and `test_last_slot_race_members` (two threads through the test client or two sessions, barrier-started; exactly one 201, one 403).
- [ ] **Step 2:** Run. Expected: FAIL (creates succeed past the limit).
- [ ] **Step 3: Implement** `api/limits.py` and call it in the routers: `tenders.create_tender`, documents upload and new-version routes (pass the incoming size: read it from the request body length the router already has; for storage, `adding` is bytes converted to MB rounded up), exports create (before rendering), `members.create_member` and the reactivate route. Keep the check before the service call and before any file write. Read each router first and place the call after authentication but before side effects.
- [ ] **Step 4:** Run the file. Expected: PASS. Run the full backend check (existing tests must not trip a limit; if one does, the test used the `starter` plan unintentionally, fix the test setup, not the limit).
- [ ] **Step 5:** Commit `feat: enforce plan limits on tenders, uploads, storage, exports and members`.

**Task test command:** `cd backend && uv run pytest -q tests/test_limits_enforcement.py tests/test_usage_api.py`

## Task 5: Usage page

**Interfaces:** Consumes `GET /usage`, `PUT /usage/plan`.

- [ ] **Step 1:** `npm run gen:api`. Failing tests: `api/usage.test.tsx`; `(app)/settings/usage/usage-view.test.tsx`: a row per resource with "used of limit" text and a `role="progressbar"` with `aria-valuenow/max`; "per month" label for uploads and exports; at or over the limit shows "Limit reached" text (not colour only); non-admin sees no plan switch; admin sees the switch with the text "This is a demo plan switch. No payment is taken." and switching calls the PUT and refetches; a 403 `limit_exceeded` error from any create shows its server message (assert the existing error-surface helper surfaces `message`; extend only if it does not).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement hooks, page and nav link ("Usage" under the settings group in `app-shell.tsx`).
- [ ] **Step 4:** Frontend check. Expected: PASS. Commit `feat: usage page with demo plan switch`.

**Task test command:** `cd frontend && npx vitest run`

## Task 6: Status endpoint and page

- [ ] **Step 1: Failing tests** `backend/tests/test_status_api.py`: no login needed, 200 with exactly keys `api`, `database`, `model`; no version/host/model name in the body; database down is reported `down` (monkeypatch `ping` to raise) with HTTP 200; `model` is `not_configured` when provider is `fake`, `ok`/`down` for `ollama` with the HTTP call monkeypatched, 2 s timeout used, cached for 10 s (second call does not call again); 31st call in a minute from one IP is 429. Frontend: `app/status/status-view.test.tsx` renders the three rows in words, polls every 15 s (fake timers), shows "Cannot reach the server" when the fetch fails, and the page is reachable without a session (check how `AuthGate` and the route group work; the page lives outside `(app)`).
- [ ] **Step 2:** Run both. Expected: FAIL.
- [ ] **Step 3:** Implement `api/status.py` (function `get_status()`, `urllib.request` with timeout, module-level cache with `time.monotonic`), route in `main.py` using `limiter` and `client_ip`; add the route to the openapi export; frontend `app/status/page.tsx` and view using plain `fetch` (no session client).
- [ ] **Step 4:** Both test sets and checks. Expected: PASS. Commit `feat: public status endpoint and page`.

**Task test command:** `cd backend && uv run pytest -q tests/test_status_api.py && cd ../frontend && npx vitest run src/app/status`

## Task 7: Preflight, start-demo and tunnel

**Interfaces:** `scripts/ops_preflight.py` exposes `check(env: Mapping[str,str], tunnel: bool, accept_hosted: bool) -> list[Finding]` (`Finding(level, code, message)`) and a CLI `python scripts/ops_preflight.py [--tunnel] [--accept-hosted-llm] [--env-file .env]` exiting 1 on errors; prints findings, never values.

- [ ] **Step 1: Failing tests** `backend/tests/test_ops_preflight.py` (load the script with `importlib.util.spec_from_file_location`): each D12 rule for tunnel and non-tunnel (`SECRET_KEY` missing/`change-me`/31 chars/32 chars, `POSTGRES_PASSWORD=intel` with tunnel, `ENVIRONMENT`, `COOKIE_SECURE`, hosted LLM with and without `accept_hosted`), a clean env gives no findings, findings never contain the secret value, `.env` parsing (comments, blank lines, quotes). `backend/tests/test_ops_scripts.py`: each `.ps1` exists; if `pwsh` is on PATH, each parses without errors via `[System.Management.Automation.Language.Parser]::ParseFile` (skip with reason otherwise); `start-demo.ps1` contains `-Tunnel`, `-Stop`, calls `ops_preflight.py`, and never contains `COOKIE_SECURE=false`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement** `ops_preflight.py`, `common.ps1` (functions `Assert-Docker`, `Wait-Health`, `Get-EnvValue`, `Write-Step`), `start-demo.ps1` and `tunnel.ps1` per D15, D16 (model check and preload with `Invoke-RestMethod` against `LLM_BASE_URL` rewritten from `host.docker.internal` to `127.0.0.1` for the host side; `.demo/` created and git-ignored). `tunnel.ps1` background process via `Start-Process -WindowStyle Hidden -RedirectStandardError .demo/cloudflared.log`.
- [ ] **Step 4:** Run the two test files. Expected: PASS. Then run `pwsh -NoProfile -File scripts/ops/start-demo.ps1 -SkipModel` against the real Docker stack (stack up from a clean state) and read the output; run `-Stop`. Record real outputs in the ledger (these are gate evidence, not unit tests).
- [ ] **Step 5:** Commit `feat: preflight, start-demo and tunnel scripts`.

**Task test command:** `cd backend && uv run pytest -q tests/test_ops_preflight.py tests/test_ops_scripts.py`

## Task 8: Backup and restore

**Interfaces:** `backup.ps1 [-Project inteltps] [-OutDir backups]` prints the backup directory. `restore.ps1 -Backup <dir> (-Verify | -Apply -Project <name> [-IKnowThisReplacesLiveData])`. Manifest keys per D13.

- [ ] **Step 1: Failing tests** extend `tests/test_ops_scripts.py`: scripts exist and parse; `restore.ps1` text refuses `-Apply` without `-Project`; a manifest checker. To keep the verifying logic testable, put manifest comparison in `scripts/ops_manifest.py` (stdlib): `verify_manifest(manifest: dict, actual: dict) -> list[str]` mismatches for checksums, `file_count`, each table count (missing table, extra table); `sha256_file(path)`. Tests in `tests/test_ops_manifest.py`: equal passes; a tampered `db_sha256`, `files_sha256`, one count, a missing table, and an extra table each yield a named mismatch.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3: Implement** `ops_manifest.py` (CLI: `write`, `verify`), `backup.ps1` (pg_dump inside `db`, archive via `docker run --rm -v <project>_files:/data:ro alpine tar czf -`, table counts via `psql -At` over `information_schema`, alembic head from `alembic_version`), `restore.ps1` per D14, `docker-compose.restore-test.yml` (Caddy port `127.0.0.1:8081:80`, `db` ports reset), `.gitignore` entries for `backups/` and `.demo/`.
- [ ] **Step 4:** Run the tests. Then, on the real stack with some data (register, create a tender, upload one document): `backup.ps1`, `restore.ps1 -Backup <dir> -Verify` (expect PASS), tamper a copy of the dump (flip a byte) and run `-Verify` (expect FAIL naming `db_sha256`), then `docker compose -p inteltps_gate -f docker-compose.yml -f docker-compose.restore-test.yml up -d db` and `restore.ps1 -Backup <dir> -Apply -Project inteltps_gate`, then log in through `http://127.0.0.1:8081`, see the tender, download the document. Also run `-Apply -Project inteltps` and confirm it refuses. Tear the gate project down with `-v`. Record outputs in the ledger.
- [ ] **Step 5:** Commit `feat: backup and restore scripts with manifest verification`.

**Task test command:** `cd backend && uv run pytest -q tests/test_ops_manifest.py tests/test_ops_scripts.py`

## Task 9: Documentation, gate on the real stack, final checks

- [ ] **Step 1:** Update docs: `docs/prd.md` (FR-47 to FR-50 note: the two plans and what is counted; section 9 `GET /audit`, `/usage`, `PUT /usage/plan`, `/health/status`), `docs/architecture/architecture.md` (audit read, billing module, ops scripts), `docs/known-limitations.md` (in-memory rate limits reset on restart; usage is live-counted; plan downgrade leaves the org over limit; no off-machine backup; scripts are Windows PowerShell only; quick tunnel URL changes; audit has no export or retention), `README.md` (ops section: start-demo, tunnel, backup, restore, status page), `.env.example` (nothing new unless a setting was added), `docs/plan.md` (Slice 6 status: 6b implemented with the real counts and gate result, no claim for anything not run).
- [ ] **Step 2: Gate on the real Docker stack through Caddy.** Run exit-gate items 1 to 6 of the spec against the stack started by `start-demo.ps1`. Check the status page and audit view in the browser (Claude in Chrome if available, otherwise HTTP and the built bundle). For the tunnel: if `cloudflared` is not installed, write "not run". Write `docs/spikes/slice-6b-gate.md` with each item PASS, FAIL or NOT RUN and the evidence.
- [ ] **Step 3:** Run the full backend and frontend checks plus `uv run pip-audit` (in `backend/`). Expected: all green; record counts.
- [ ] **Step 4:** Commit `docs: slice 6b gate record, status and known limitations`.

**Task test command:** `cd backend && uv run pytest -q`
