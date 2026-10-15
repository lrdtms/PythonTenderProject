# ADR-0005: Tenant isolation: one scoped data-access path, organisation_id everywhere, composite FKs; RLS deferred

- **Status:** Accepted; superseded in part (item 7, file links) in Slice 2: see the note under item 7
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
BR-05 and FR-58: an organisation may see only its own data, including retrieval results and Q&A citations. Leaks can come from a forgotten `WHERE`, a guessed ID, a child row wired to the wrong parent, a worker writing under the wrong org, or a retrieval query that searches across tenants. What isolation mechanism fits a 4-person, 32-day team?

## Decision Drivers
- Security marks (10) and a must-pass cross-tenant test
- Low risk of subtle bugs that students cannot debug under time pressure
- Worker processes jobs for many orgs
- Path to stronger isolation later without a rewrite

## Considered Options
1. **Application-level: `OrgContext` + tenant-scoped repository base; `organisation_id` on every org-owned row; composite foreign keys**
2. Option 1 + Postgres Row-Level Security (RLS) on all org-owned tables now
3. Schema-per-tenant or database-per-tenant

## Decision Outcome
Chosen option: **Option 1, built so that Option 2 is a migration later.**
1. **OrgContext.** The auth dependency resolves `OrgContext(user_id, organisation_id, role)` from the session cookie **and a DB membership lookup** on every request. Org IDs from paths or bodies are never trusted.
2. **One data-access path.** All repositories extend a base that requires `ctx` and adds `organisation_id = ctx.organisation_id` to every select/update/delete. Lookups by ID are `get(ctx, id)`; a row of another org returns **404**, not 403 (no existence oracle). IDs are UUIDs.
3. **Denormalised `organisation_id` on every org-owned table**, including children the base spec left without it (requirements, BoQ items, quotation items, tasks, jobs, chunks, match suggestions, exports, chat queries).
4. **Composite FKs** make cross-org wiring impossible in the DB: parents expose `UNIQUE (organisation_id, id)`; children reference `(organisation_id, tender_id) -> tenders(organisation_id, id)`, and so on down to `document_chunks`.
5. **Retrieval** exists only as `knowledge.search(ctx, tender_id, query)`. The SQL filters by `organisation_id` **and** `tender_id` **and** current document version in both CTEs, before fusion. There is no "search all" function. Q&A citations are produced by code from the retrieved set; any citation index outside it is dropped.
6. **Worker.** Jobs carry `organisation_id`; the worker builds a system `OrgContext` from the job row (never from document content) and uses the same repositories.
7. **Files.** Storage keys start with `org/{organisation_id}/`; signed links are HMAC tokens binding `(organisation_id, document_version_id, user_id, expiry <= 5 min)` and are re-checked against membership.
   > **Superseded in part (Slice 2).** No signed links were built. With server-side sessions (ADR-0010) and a single origin (ADR-0009), downloads are an authenticated same-origin endpoint, `GET /api/v1/document-versions/{id}/file`, which checks the session cookie and the organisation on every request (a version of another organisation is a 404) and streams the file. The HMAC design above is kept for history only. See architecture.md, "Slice 2 notes".
8. **RLS-ready.** The session factory already runs `SET LOCAL app.org_id = :org` inside each transaction. Enabling RLS later is a migration (policies + `FORCE ROW LEVEL SECURITY` + non-owner app role), not a code change.
9. **Platform Admin** has no endpoint that reads customer documents in the MVP (aggregates and plans only).

### Consequences
- Positive: one place to review; DB-level guarantee against mis-wired children; simple to debug; tests cover every route.
- Negative / Tradeoff: isolation still depends on developers using the base repository. A raw `session.execute()` in a module bypasses it. We mitigate with code review and a CI check, but this is weaker than RLS. Denormalised `organisation_id` costs some storage and must be set on insert (composite FKs catch mistakes).
- Follow-ups: optional hardening on days 22-25 if the cross-tenant suite is green: enable RLS on `document_chunks` and `documents` only.

## Pros and Cons of the Options

### Option 1
- Good: simple, explicit, fast to build, debuggable.
- Bad: relies on discipline plus tests; no protection from a bypassing query.

### Option 2 (RLS now)
- Good: defence in depth; a forgotten filter returns nothing instead of leaking.
- Bad: the app must connect as a non-owner role (owners bypass RLS unless `FORCE`); `SET` without `LOCAL` leaks context across pooled connections; Alembic and test fixtures need a bypass role; failures show up as mysterious empty results; the worker needs per-job context switches. High risk of lost days for this team.

### Option 3
- Good: strongest isolation.
- Bad: migrations x N tenants, cross-tenant platform queries become hard; unjustified at < 10 users.

## Links / References
- Base spec FR-05, BR-05, §6.2; PRD FR-58, §12, §18; PostgreSQL docs "Row Security Policies"; OWASP ASVS V4 (access control)
