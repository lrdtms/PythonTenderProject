# Slice 4, Phase 5: Checklist Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** A tender-wide checklist of requirements (grouped by type, filterable by review status, type and mandatory status) that links each requirement to its place in the review screen.

**Architecture:** One client view at `/tenders/[id]/checklist` using `GET /tenders/{id}/requirements` (server filters `review_status` and `requirement_type`; the mandatory filter is client-side because the API has no such parameter), paged with "Load more" like the review lists. Rows link to `/tenders/{id}/review/{versionId}?row={requirementId}`; the review screen preselects that row. The BoQ editor from phase 4 already edits item no, section, description, unit, quantity and rate inline with decimal-string validation, so no further editor work is planned here.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-4-review-ui-design.md` section 5 "Checklist and BoQ editor (phase 5)". Known limitation to honour: rows from several documents interleave in the API list (`known-limitations.md`), so the page shows the document name on each row.

## Global Constraints

- Same as phase 4: page is a server component exporting `export const instant = false;` (enforced by `app-pages.test.ts`); no `dangerouslySetInnerHTML`; document text is untrusted and rendered as text nodes; read-only for roles without `review_data` (the checklist itself is read-only for everyone; review actions stay on the review screen).
- Frontend commands from `frontend/`: `npm run lint`, `npm run typecheck`, `npm test`, `npm run build`; delete `.next` afterwards. Branch `feat/slice-4-phase-5-checklist`.

## Review Focus

1. A tender with no documents, no processed documents, or no requirements: clear empty state, not a blank page (Task 1).
2. A filter that matches nothing, and changing a filter after "Load more": the list restarts from offset 0 (Task 1).
3. A requirement whose version is not in the document list (stale cache): the link still works and the document name falls back to "Document" (Task 1).
4. Mandatory filter applied client-side must not hide that more server pages exist: show "Load more" and a note while a client filter is active (Task 1).

### Task 1: Checklist page

**Files:** Create `src/api/checklist.ts`, `src/app/(app)/tenders/[id]/checklist/page.tsx`, `checklist-view.tsx`, `checklist-view.test.tsx`. Modify `review-screen.tsx` (+ test) to preselect `?row=`, `tender-workspace.tsx` (link "Checklist"), `app-pages.test.ts` needs no change (it discovers pages).

**Interfaces:** `useTenderRequirements(tenderId, { reviewStatus?, requirementType? })` returns `{ rows, hasNextPage, fetchNextPage, isFetchingNextPage, isPending, isError }`; query key `["checklist", tenderId, reviewStatus ?? null, requirementType ?? null]`, page size `REVIEW_PAGE_SIZE`.

- [ ] Write failing tests (groups by type with headings, shows document name and status, mandatory filter narrows client-side, review-status filter refetches with `review_status=` and `offset=0`, empty states, link href, Load more only after a full page).
- [ ] Implement hook, view, page; add the `?row=` preselect to the review screen and a test; add the Checklist link to the tender page.
- [ ] Run lint, typecheck, test, build; update `docs/plan.md` status and `known-limitations.md`; commit.
