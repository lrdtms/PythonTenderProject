# Slice 4: Review UI (design)

**Date:** 2026-10-16 · **Branch:** `feat/slice-4-review-ui` (to be created) · **Status:** revision 2 after Fable review (findings checked against the code), for owner review
**Authority:** `docs/plan.md` section 3 (Slice 4), `docs/prd.md` US-07, FR-26, FR-54, FR-64, FR-66, section 11, `docs/architecture/architecture.md` (domain invariants), ADR-0004, ADR-0005, ADR-0006 and its Slice 3 addendum, ADR-0009, ADR-0010, `docs/known-limitations.md` (Slice 3 section). Frontend rules: `frontend/AGENTS.md` (this is Next 16; read `node_modules/next/dist/docs/` before writing frontend code).

## 1. Goal and scope

An estimator can log in, create a tender, upload a pack, watch it process, then check every extracted requirement and BoQ line against its source page and confirm, correct or reject it. The AI suggests and a human decides (BR-01). Nothing extracted is approved without a human action.

**Exit gate:** on the real Docker stack through Caddy, with a synthetic pack:

1. Register, create a tender, upload, see job progress.
2. Open the review screen: a PDF row jumps to its page and an XLSX row highlights its cell range in the grid.
3. Correct a BoQ quantity, confirm a requirement, reject one; reload and the review state persists.
4. Re-run BoQ extraction (deterministic, needs no Ollama): reviewed rows survive and unreviewed rows are replaced. A row write against a row the re-run replaced shows the "replaced by a re-run" state.
5. A reviewer-role user sees no review controls and gets 403 from the API. A project manager likewise (see section 3).
6. F1 green for every new route; frontend CI green (lint, `tsc --noEmit`, build, Vitest, schema drift).

Requirements re-run is checked only when host Ollama is available; step 4 does not depend on it.

**Scope (user decision: full set, in ordered phases; each phase ends committed and working, so the last finished phase is the demo).** Timeboxes assume about 12 to 15 days for the slice, since Slices 5 to 8 still need the rest of the window (plan.md days 17 to 32):

| Phase | Content | Timebox |
|---|---|---|
| 1 Backend review API | Review endpoints, DTO fields, tender-wide requirements list, `GET /document-versions/{id}`, the four Slice 3 fixes | 2 to 3 days |
| 2 Frontend foundation | Typed API client, session, app shell, login and register, **PDF.js + Turbopack + cacheComponents spike** (top technical risk, proven here, not in phase 4) | 2 days |
| 3 Tender workspace | Tender list and create, documents, upload with progress, retry, extraction status and re-run | 2 days |
| 4 Review screen | Source viewer (PDF.js, sheet grid) beside requirements and BoQ, review actions | 4 days |
| 5 Checklist and BoQ editor | Tender-wide checklist page, BoQ inline editing | 2 days |
| 6 Members | Admin screens for members and roles | 1 day |

**Cut order if time runs short:** 6 (the API already exists; tests create reviewers through it), then the BoQ inline editing polish in 5, then the checklist page. Phases 1 to 4 are the minimum credible demo. The tender list serves as the dashboard (PRD section 11).

**Out of scope:** totals, markup, VAT and any calculation (Slice 5, Decimal); suppliers and quotations; exports; Q&A; email; multi-organisation switching; Playwright coverage beyond the single gate journey; manual creation of BoQ lines (scanned BoQs stay `BOQ_NEEDS_MANUAL_ENTRY` and go in the known-limitations list, `ai_suggested=false` stays unused); a rendered view of DOCX sources (a text-only fallback of the extracted page text is shown).

## 2. Decisions taken

| Decision | Choice |
|---|---|
| Scoping | Option B: the full set from the plan, phased |
| API types | Generated from FastAPI OpenAPI with `openapi-typescript`, committed, regenerated and diff-checked in CI |
| Data fetching | Client components with TanStack Query; no server prefetch (see section 4) |
| Spreadsheet sources | Read-only sheet grid built from `/pages` table data, cited rows highlighted |
| Auth | Server-side session cookie owned by the API (ADR-0010); the Next server never reads it |

## 3. Phase 1: Backend review API

All routes are flat under `/api/v1`. Writes need `REVIEW_DATA`, which the code (`kernel/types.py`, pinned by `tests/test_fitness_functions.py`) grants to **admin and estimator only**. Project managers and reviewers get 403 on review writes; this follows ADR-0010 and the existing matrix, and no permission change is made. The UI hides controls using `me.permissions`.

| Endpoint | Does |
|---|---|
| `PATCH /boq-items/{id}` | Edit `description`, `unit`, `quantity`, `rate`, `section`, `item_no` |
| `POST /boq-items/{id}/confirm`, `/reject` | Accept as extracted, or reject |
| `PATCH /requirements/{id}` | Edit `description`, `requirement_type`, `mandatory_status` (validated against the prompt's enums) |
| `POST /requirements/{id}/confirm`, `/reject` | Same |
| `GET /tenders/{id}/requirements` | Requirements across the tender's current document versions, for the checklist page (paginated, filterable by `review_status`, `requirement_type`) |
| `GET /document-versions/{id}` | Version detail (the review route has a version id, not a document id); the service method exists, the route does not |
| `GET /document-versions/{id}/pages/{n}?row_from&row_to` | Existing page route gains an optional row window so a large sheet is not sent whole (up to 2M cells) |

**Data model rules (verified against `estimating/models.py`, `checklist/models.py`, the services):**

- `original_value` is the **immutable AI snapshot written at insert** (it already is, and re-run dedupe reads it). It is never rewritten.
- The main columns (`description`, `unit`, `quantity`, ...) hold the **effective value**. A PATCH updates them, so Slice 5 can compute from columns, and records only the changed fields in `corrected_value` (JSON, decimals as strings) with `reviewed_by` and `reviewed_at`. Confirm sets status `confirmed` without changing values.
- Allowed transitions: `unreviewed` to `confirmed`, `corrected` or `rejected`; `confirmed`, `corrected` or `rejected` to any of the others (a reviewer may change their mind, including un-reject). Written out as a table in the code and tested.
- `suggested_value` is never written today and `ai_suggested` is always true; neither is exposed. DTOs gain `original_value`, `reviewed_by` and `reviewed_at`.
- Quantity and rate are `Decimal` text: the PATCH schema takes JSON strings matching a decimal regex, never JSON numbers (Pydantic's `Decimal` would accept floats). A blank quantity stays `NULL`, never 0; adding a quantity clears the `missing_quantity` flag. More than 4 decimal places is rejected (422), not rounded.
- Reviewer names: `GET /members` needs `MANAGE_MEMBERS`, so estimators cannot resolve `reviewed_by`. The DTOs carry `reviewed_by_name` from the membership join.
- Concurrent edits of the same row are last-write-wins. Accepted and documented; the UI shows `reviewed_at`/`reviewed_by` so a reviewer can see someone else's change.
- Each action is audited with IDs and field names only, never document text.

**Locking and error codes.** A PATCH or confirm must: look up the row (org-scoped; unknown or other-organisation id gives **404**, which F1 requires), take `pipeline.lock_runs(version, kind)` (the same lock extraction takes), re-read the row, then write. If the row vanished between lookup and lock (a re-run replaced it), return **409 `row_replaced`**. A row that was already replaced before the request is a plain 404, and the UI treats 404 and `row_replaced` on a row write the same way: "replaced by a re-run", reload. No `WHERE review_status = 'unreviewed'` guard is needed on later edits because the lock serialises them against extraction; the extraction side already only deletes unreviewed rows.

`Conflict` gains a code override. The existing three 409s from `request_extraction` get distinct codes (`tender_archived`, `not_processed`, `extraction_options_conflict`) so the client can explain each; today they all carry `conflict`. The CSRF failure is a 403 with code `csrf_failed`, which the client distinguishes from `forbidden`.

**Module boundaries.** `checklist` has no arrow to `documents` or `pipeline`, and requirements have no `tender_id`. The router orchestrates: it calls `documents.list_documents`/current versions for the tender, then `checklist.list_for_versions(ids, filters)`; for writes, `pipeline.lock_runs` then `estimating.correct_item` or `checklist.review` (names from architecture.md section 2). Requirement type and mandatory enums move to `kernel` (or are validated in the router) because `checklist` may not import `extraction`. No new cross-module arrow is added without updating `diagrams/backend-components.md`.

**Slice 3 fixes folded in (from `known-limitations.md`), in this order:**

1. **Section carry-over across continuation pages.** The parser resets `section` per table (`extraction/boq.py`). This changes the re-run duplicate key, so it **lands first, before any reviewed rows can exist**. Parser tests and the committed ground-truth scoring are re-run to show scores do not regress.
2. **List ordering.** `position` is a per-run index, so slotting rows from different runs by it is meaningless, and sheet BoQ rows have no `page_number`. Add a persisted `source_order` (page or sheet index times a large constant, plus row, or `quote_start` for requirements) with a migration, and order lists by it. This is the largest of the four fixes and is sized into the phase 1 timebox.
3. **Locked review writes.** As above.
4. **Ambiguous comma.** `numbers.py` reads `1,500` as 1500. A single comma followed by exactly three digits gets the `ambiguous_separator` flag; the value is **kept** as 1500 (not nulled) so nothing is lost, and the reviewer decides. Applies to quantity and rate. Existing parser tests and eval scores are re-run.

**Tests:** API tests per endpoint and per role (admin, estimator pass; project manager, reviewer 403); 404 versus `row_replaced`; reviewed rows survive a BoQ re-run; `original_value` unchanged across repeated edits; transition table; decimal-string validation; reviewer-name join.

**F1 sweep changes (it does not pick the new routes up unaided):** register `boq_item_id` and `requirement_id` in the sweep's `known` registry and add PATCH and confirm bodies to `REQUESTS`; run `extract_boq` and a `FakeLLM` `extract_requirements` for org B so B actually owns rows. Otherwise the new routes would 404 trivially and prove nothing. The `row_replaced` 409 is only reachable after the 404 pre-lookup, so it does not conflict with the sweep.

## 4. Phase 2: Frontend foundation

- **Dependencies:** `@tanstack/react-query`, `openapi-typescript` (dev), Vitest and Testing Library (dev). `pdfjs-dist` arrives in phase 4.
- **Typed client:** `src/api/schema.d.ts` is generated by `openapi-typescript` from a **committed `frontend/openapi.json`**. A backend test asserts that file equals `app.openapi()`, so drift fails the backend CI job (the frontend job has no Python). The frontend job regenerates the types from the committed JSON and fails on a diff. `src/api/client.ts` is a thin typed `fetch` wrapper: same-origin cookies, the required header `X-Requested-With: IntelTPS` on every POST, PUT, PATCH and DELETE (login, register and logout included; there are no exemptions), the error format `{"error":{"code","message","details"?}}` mapped to `ApiError`, with 422 details as `[{field,message}]`. It distinguishes 403 `csrf_failed` from 403 `forbidden`, and maps the distinct 409 codes from section 3 to messages.
- **Upload progress:** `fetch` has no upload progress, so the upload call uses `XMLHttpRequest` with the same header. After the upload the job is polled.
- **Next 16 constraints (from the bundled docs):** `cacheComponents` and `partialPrefetching` are enabled in `next.config.ts`. Any client component that reads a query on first render sits behind `<Suspense>`, and so does anything calling `useParams`, `usePathname` or `useSearchParams` on a dynamic route (every `[id]` page), or the build fails. No server-side `dehydrate()` (it reads the current time during prerender and errors). Pages are client-rendered shells that fetch after hydration. The reason there is no server prefetch is structural: the session cookie has path `/api`, so the Next server never receives it and cannot call the API as the user.
- **Session:** the app shell calls `GET /me` (it returns user, organisation, `role` and `permissions[]`) behind Suspense. 401 redirects to `/login`; a signed-in user on `/login` goes to `/tenders`. There is no `proxy.ts` auth redirect: the cookie path means it could not see the cookie at all. Authorisation lives in the API; the UI hides disallowed controls using `permissions[]` as a convenience only.
- **Routes:** `(auth)/login`, `(auth)/register`; `(app)/tenders`, `(app)/tenders/[id]`, `(app)/tenders/[id]/checklist`, `(app)/tenders/[id]/review/[versionId]`, `(app)/members` (admin only).
- **Dev wiring:** Caddy serves `/api/*` from FastAPI in Docker. For `npm run dev` without Docker, a `next.config.ts` rewrite sends `/api/*` to the local API, **gated on an environment variable** so the standalone production build does not contain it. The session cookie is `Secure` by default (`COOKIE_SECURE`); local plain-http dev sets `COOKIE_SECURE=false`, and Safari rejects `Secure` cookies on `http://localhost` regardless, so development is on Chrome or Edge.
- **PDF.js spike (done in this phase):** a throwaway page loads `pdfjs-dist` through a dynamic import with `ssr: false` inside a client component (allowed only in client components), renders one page of a synthetic PDF fetched from `/document-versions/{id}/file`, and survives `next build` with `cacheComponents`. Worker bundling is settled here. If it fails, fall back to `react-pdf` or an `iframe`-free canvas-only wrapper before phase 4 starts.
- **CI:** the frontend job gains `tsc --noEmit` and Vitest alongside lint and build.
- **Tests:** Vitest for the wrapper (CSRF header on each mutating method, error and 409-code mapping, `csrf_failed` versus `forbidden`) and the auth guard.

## 5. Phases 3 to 6: Screens

**Tender workspace (phase 3).** Tender list with create and archive. Tender page lists documents with versions and `processing_status`, an upload form (kind selector, validation messages from the API, 25 MB limit shown), and job progress via `GET /jobs/{id}` polled every 2 s with `refetchInterval` that stops on a terminal status. Version DTOs carry the ingest `job_id`, so progress resumes after a reload. Failed jobs show the error code in plain words and a retry button, shown only to roles holding `UPLOAD_DOCUMENTS` (job retry requires it, so a project manager cannot retry). Per-version extraction status shows the job and run per kind (`/extraction`), warnings, and a re-run button with a deep-scan toggle. The UI displays the job status (not the run status) while a job is queued for retry, as noted in known-limitations. A 409 on re-run with a different `deep_scan` is explained, not hidden.

**Review screen (phase 4, US-07).** Two panes on desktop, stacked tabs on mobile. Left: source viewer. Right: tabs for Requirements and BoQ items.

- *PDF source:* `pdfjs-dist` renders the page from `/document-versions/{id}/file` (same-origin `fetch`, cookie sent; the sandbox CSP does not affect it; no Range support, so the whole file downloads and stays in memory because of `no-store`). Selecting a row jumps to its `page_number` (physical 1-based, FR-66). Requirements already store `quote_start`/`quote_end` against the page text after whitespace is collapsed and lower-cased (the client maps them back onto the raw text), so the **deterministic highlight** is that exact span shown in the page's extracted text next to the canvas (`/pages/{n}.text`); matching the quote in the PDF.js text layer is a best-effort bonus, never an error. Scanned (OCR) pages have no text layer, show an amber badge, and rely on the text span only.
- *Spreadsheet source:* sheet BoQ rows have `page_number = NULL`, so the client maps `sheet` to a page through the `label` in the `/pages` list, then loads `/pages/{n}` (with the `row_from`/`row_to` window) whose sheet table is `{kind: "sheet", first_row, rows}`. A read-only grid highlights the `cell_range` (`A{row}:{col}{row}`) and scrolls it into view.
- *DOCX source:* no rendered view; the extracted page text is shown with the quote span highlighted, labelled as text-only.
- *Rows:* a visible review-state badge on every row (unreviewed, confirmed, corrected, rejected), chips for the requirement columns `evidence_status = evidence_unverified` and `needs_review` and for BoQ `flags` (`missing_quantity`, `ambiguous_separator`, `rate_unparsed`, ...), original versus effective value for corrected rows, and who reviewed it and when. Keyboard: arrows to move, `c` confirm, `r` reject, `e` edit.
- *Writes:* optimistic update with rollback. A 404 or 409 `row_replaced` on a row write marks the row "replaced by a re-run" and reloads the list; a 403 shows a permission message.
- *Lists* are bare arrays with no total, paginated by `limit`/`offset` (default 200); the screen loads the next page on scroll and stops on a short page. A re-run can shift offsets, so the list reloads from the start after any "replaced" event.

**Checklist and BoQ editor (phase 5).** The checklist page lists requirements across the tender's current versions, grouped by type, filterable by status and mandatory status, linking back to the review screen at the source. The BoQ editor edits lines inline. Quantity and rate are text inputs validated against a decimal pattern, never `number`/`parseFloat`; there are no totals in this slice.

**Members (phase 6).** Admin-only list, create member, change role, deactivate and reactivate, reset password, using the existing `/members` endpoints. Own-row and last-admin protections stay on the server; the UI surfaces its errors.

**Accessibility and responsiveness:** keyboard operable, focus-visible, state never conveyed by colour alone, layouts work at phone width.

## 6. Security and hygiene

- Document text, quotes and search snippets are untrusted: rendered as text nodes only, never `dangerouslySetInnerHTML`. Search highlight markers `⟦ ⟧` are parsed into spans by code.
- The PDF is fetched same-origin with the session and rendered to canvas; the file route's `nosniff`, `no-store` and sandbox CSP stay as they are.
- No tokens or session data in `localStorage`; the CSRF header is required on every state-changing call.
- No document text in client logs or analytics; error toasts carry codes, not content.

## 7. Testing

- **Backend (CI):** as in section 3, plus the existing suites staying green.
- **Frontend (CI):** lint, `tsc --noEmit`, build, schema-drift check, Vitest unit and component tests (client wrapper, auth guard, review row state machine, decimal input validation, permission-based hiding of controls).
- **Gate journey (manual, real stack):** the exit-gate journey in section 1, recorded in the plan status line, with one scripted Playwright run if time allows. Reviewer and project-manager users are created through the members API.

## 8. Risks

- **PDF.js under Next 16 / Turbopack:** worker bundling and `cacheComponents` prerendering can fail. Mitigation: the spike in phase 2 (section 4), with a named fallback.
- **Quote highlighting accuracy:** the text-layer match may miss. The deterministic text-span highlight and the quote are always shown.
- **Scope size:** six phases solo inside the timeboxes in section 1; the cut order applies. Phase 1 is the likeliest to overrun because of the `source_order` migration and the F1 changes.
- **Typed client drift:** guarded by the committed `openapi.json`, the backend equality test and the frontend regenerate-and-diff check.
- **Large lists and sheets:** pagination and the sheet row window; virtualisation only if measured to be needed.
- **Parser changes move scores:** fixes 1 and 4 touch the BoQ parser. The committed-ground-truth scoring tests must not regress, and the real-stack scores in `slice-3-scores.md` are re-run if they change.
- **Known limitations added by this slice:** scanned BoQs have no manual line entry yet; DOCX sources are text-only; last-write-wins on concurrent edits.
