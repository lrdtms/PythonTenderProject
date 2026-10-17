# Slice 5a, Phase 5: Suppliers Page, Polish and Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A suppliers page (list, create, rename, notes, merge a duplicate with a two-step confirm) reachable from the header, plus the small fixes deferred from phases 3 and 4, then the real-stack gate run for all of Slice 5a.

**Architecture:** One client view at `/suppliers` built on the hooks from phase 4 (`suppliersQueryOptions`, `useCreateSupplier`, `useUpdateSupplier`, `useMergeSupplier`); a header nav link; a polish task touching the quotation review UI and two backend review routes. The gate run and the overall Fable review are controller-run steps after the tasks.

**Tech Stack:** Next.js 16.4.1 (`cacheComponents`), React 19.3, TypeScript, Tailwind 4, TanStack Query 5, Vitest 5 (frontend); FastAPI + pytest for the two backend polish items.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` section 7 ("Suppliers list: rename, notes, merge with a two-step confirm") and section 1 (exit gate steps 1 to 7). Phases 1 to 4 are on this branch.

## Global Constraints

- Frontend rules as in phase 4: read `frontend/AGENTS.md`; `cacheComponents` stays ON; pages are server components exporting `export const instant = false;` (enforced by `src/app/app-pages.test.ts`); untrusted text as text nodes only; no `dangerouslySetInnerHTML`; state never by colour alone; keyboard operable; works at phone width; no native `confirm()`/`alert()`; controls that submit are disabled while pending.
- Permissions: the list is visible to everyone who can read; create, rename, notes and merge need `review_data` (`useCan("review_data")`); other roles see no write controls. Errors by code: `supplier_exists` ("A supplier with this name already exists. Merge them instead."), `match_conflict` ("These suppliers both have a confirmed match for the same line. Resolve that first."), `tender_archived` ("A tender that uses this supplier is archived."), `try_again`, `forbidden`; anything else shows the server's message.
- Merge is destructive-ish (the source supplier disappears): a two-step confirm that names both suppliers, and success text "Merged A into B." Never auto-merge.
- Frontend commands from `frontend/`: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (delete `.next`). Backend commands from `backend/` with `DB_HOST_PORT=5433 uv run pytest ...`; never run two full backend suites at once.
- Branch `feat/slice-5a-phase-2-matching` (current). Commit messages end with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).
- Shell: the Bash tool here mishandles long heredocs; create files with the editor tools.

## Review Focus

1. Merge two-step: choosing a target and clicking Merge shows the confirmation naming both suppliers; Cancel sends nothing; confirm sends exactly one request; merging into itself is impossible in the UI (the target list excludes the source) (Task 1).
2. Rename to an existing name shows the `supplier_exists` message inline and keeps the editor open with the typed value (Task 1).
3. Reviewer and project-manager roles see the list and no controls; the nav link "Suppliers" is visible to every signed-in user (Task 1).

---

### Task 1: Suppliers page and navigation

**Files:**
- Create: `frontend/src/app/(app)/suppliers/page.tsx`, `suppliers-view.tsx`, `suppliers-view.test.tsx`; `frontend/src/lib/supplier-text.ts`, `supplier-text.test.ts` (error mapping)
- Modify: `frontend/src/components/app-shell.tsx` (+ test): "Suppliers" link to `/suppliers` for everyone signed in, placed after "Tenders"

**Interfaces:**
- `supplierErrorText(error: unknown): string` (the Global Constraints mapping, falling back to the API message, then to "Something went wrong. Try again.").
- `<SuppliersView />`: heading "Suppliers"; create form (name required 1-200, notes optional); list of suppliers (name, quotation count in words "1 quotation" / "n quotations", notes) in API order; each row has Edit (inline name + notes form, Save/Cancel, disabled while pending, only changed fields sent) and Merge (a `<select>` of the OTHER suppliers, a "Merge into…" button, then an inline confirmation "Merge {source} into {target}? {source} will disappear and its quotations move to {target}." with Merge / Cancel); success shows "Merged A into B." and the list refreshes; empty state "No suppliers yet. They appear when you upload a quotation."; loading and error states; read-only roles see no create form and no Edit/Merge.

- [ ] **Step 1: Write the failing tests**
`supplier-text.test.ts`: each code's text, unknown code uses the API message, a plain `Error`, `null`.
`suppliers-view.test.tsx` (mock `next/navigation`; `mockApi` routes for `/api/v1/suppliers`, PATCH, POST merge): lists suppliers with counts and notes; create posts `{name, notes}` (notes omitted when blank) and the form clears; duplicate create shows the `supplier_exists` message and keeps the typed name; edit sends only changed fields (rename only, notes only, clearing notes sends `null`); rename conflict keeps the editor open with the typed value; merge: select lists only other suppliers, Merge button disabled until chosen, clicking it shows the confirmation naming both, Cancel sends nothing, Confirm posts `{into_id}` once and shows "Merged A into B."; `match_conflict` on merge shows its text; reviewer role sees the list and no controls; empty state; 401 handled by the global handler (not tested).
`app-shell.test.tsx`: the "Suppliers" link is present for a reviewer and an admin.

- [ ] **Step 2: Run, see them fail.** `cd frontend && npx vitest run "src/app/(app)/suppliers" src/lib src/components/app-shell.test.tsx`
- [ ] **Step 3: Implement** (mirror `members-view.tsx`: row component with its own mutations, outcome state, two-step confirm, `Field` component, `useCan`). The page file follows the `instant = false` pattern.
- [ ] **Step 4: Checks.** lint, typecheck, full `npm test`, `npm run build` (the build must list `/suppliers`; delete `.next`).
- [ ] **Step 5: Docs.** `docs/plan.md` Slice 5 row: a Phase 5 sentence (suppliers page and nav; real-stack gate pending, the controller does it); `docs/known-limitations.md`: a merged supplier cannot be split again.
- [ ] **Step 6: Commit** `feat: suppliers page and navigation`.

---

### Task 2: Polish deferred from phases 3 and 4

**Files:** `frontend/src/components/review/quotation-panel.tsx`, `quotation-row.tsx`, `frontend/src/app/(app)/tenders/[id]/review/[versionId]/review-screen.tsx` (+ tests); `backend/app/api/routers/tenders.py` (archive), `backend/tests/` (a tender-archive race test)

Items (each with a test; all are small):
1. **Review screen documents-list failure:** if `GET /tenders/{id}/documents` errors and there is no cached data, show the existing "Could not load the document" alert with a Try again button instead of an empty quotation view. Test: documents route returns 500 → alert + retry refetches.
2. **`<QuotationForm key={quotation.id}>` and reset `editing` when `versionId` changes** in the panel. Test: switching the version while the form is open shows the new quotation's values.
3. **Quotation row "(was …)" formatting:** show the ORIGINAL unit price exactly as stored (un-stripped), keep stripping only for the quantity display; use the normalised form only for the "changed?" comparison. Update the test (`Price 130.0000 (was 125.5000)`).
4. **Missing tests:** 5-decimal input refused in the quotation editor (nothing sent); archived tender hides Edit and shows no controls on a quotation row and in the review screen; VAT radio sends `true`, `false` and `null`; "No quotation details for this document yet." note when the panel has no quotation record for the version (add the note).
5. **Backend: archiving a tender takes the tender advisory lock** so a match decision or extraction cannot interleave with the archive: `POST /tenders/{tender_id}/archive` (router) first calls `suppliers.lock_tender(session, ctx, tender_id)` (the router already imports module public APIs) then archives. Test: `test_archive_waits_for_the_tender_lock` (hold the lock in a second transaction; the archive request blocks until it is released, using the pattern of `tests/test_supplier_races.py`).
6. **Backend: real `row_replaced` race for quotation items:** replace the weak test with one that resolves `quotation_item_version`, deletes the row in a second session (simulating a re-run that replaced it), then calls the review service under the locks and expects 409 `row_replaced` (template: `tests/test_review_boq.py`).

- [ ] **Step 1: Write the failing tests** for items 1 to 6.
- [ ] **Step 2: Run, see them fail** (frontend files with `npx vitest run`, backend with `DB_HOST_PORT=5433 uv run pytest tests/test_supplier_races.py tests/test_quotation_items_review.py -q`).
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Full checks:** frontend lint, typecheck, `npm test`, `npm run build`; backend full suite once (about 7 minutes), `uv run ruff check . && uv run ruff format --check . && uv run lint-imports`.
- [ ] **Step 5: Commit** `fix: phase 3 and 4 polish (documents failure state, form reset, price display, archive lock, row_replaced race test)`.

---

### Gate (controller-run after the tasks)

1. Rebuild and restart the stack (`docker compose up -d --build api worker web`; migrations are at head).
2. Drive the exit-gate journey from the spec in a real browser with the pack02 fixtures (BoQ + two quotations): upload, extraction, quotation review (header, items, source), matching, comparison page (clear and ambiguous, evidence, prices side by side with no cheapest cue), confirm one, reject one, reset one, "Confirm all clear matches", re-run BoQ and quotation extraction (decisions survive), replace a quotation version (stale confirmed released, new candidate confirmable), suppliers page rename and merge, reviewer role read-only, archived tender read-only.
3. Run the scoring script and the full backend and frontend suites; update `docs/plan.md` Slice 5a status with the real numbers; then the overall Fable review of Slice 5a and one fix wave.
