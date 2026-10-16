# Slice 4, Phase 4: Review Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reviewer with `review_data` opens a processed document version, sees each extracted requirement and BoQ line beside its source (PDF page, sheet cells, or extracted text), and confirms, corrects or rejects it; read-only roles see the same screen without controls.

**Architecture:** One client view at `/tenders/[id]/review/[versionId]`. TanStack Query hooks in `src/api/review.ts` (paginated lists, page detail, optimistic row mutations). A `SourceViewer` picks a renderer from the selected row (PDF canvas, sheet grid, or text-only) and always shows the stored quote span in the page's extracted text. Pure helper modules (decimal validation, review-state text, sheet range parsing, quote-span splitting) carry the logic and are unit-tested first.

**Tech Stack:** Next.js 16.4.1 (`cacheComponents`), React 19.3, TypeScript, Tailwind 4, TanStack Query 5, pdfjs-dist 6.4.299, Vitest 5 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-4-review-ui-design.md` (sections 5 "Review screen", 6, 7); `docs/spikes/slice-4-pdfjs.md` ("Decisions for phase 4"). Phases 1 to 3 are merged to `main`; the review API exists.

## Global Constraints

- Read `frontend/AGENTS.md` and the bundled Next docs before writing frontend code. `cacheComponents` and `partialPrefetching` stay ON. The page is a server component exporting `export const instant = false;` (same comment as `tenders/[id]/page.tsx`) that renders a client view; `src/app/app-pages.test.ts` enforces it. Dynamic params via `useParams()`. No `cookies()`, no `dangerouslySetInnerHTML`: quotes, descriptions, page text and cell values are untrusted and rendered as text nodes.
- API (all under `/api/v1`, generated types in `src/api/schema.d.ts`): `GET /document-versions/{id}` (VersionDTO), `GET /document-versions/{id}/requirements|boq-items?limit&offset` (bare arrays, `limit` max 1000, default 200), `GET /document-versions/{id}/pages` (`PageDTO[]`: `page_number`, `label`, `status`, `text_source`, `ocr_confidence`), `GET /document-versions/{id}/pages/{n}?row_from&row_to` (`PageDetailDTO`: `text`, `tables[]`; a sheet table is `{kind:"sheet", first_row, rows: string[][]}`, a document table `{kind:"table", rows}`), `GET /document-versions/{id}/file`. Row writes: `PATCH|POST confirm|POST reject` on `/boq-items/{id}` and `/requirements/{id}`. `BoqPatch` fields: `section,item_no,description,unit,quantity,rate` (quantity/rate JSON strings matching `^-?\d{1,14}(\.\d{1,4})?$`, never numbers; `null` clears). `RequirementPatch`: `description` (1-2000), `requirement_type` in `deadline|meeting|eligibility|document|pricing|technical|other`, `mandatory_status` in `mandatory|conditional|informational`. Row fields used: `review_status` (`unreviewed|confirmed|corrected|rejected`), `original_value`, `corrected_value`, `reviewed_by_name`, `reviewed_at`, `page_number` (null for sheet rows), `sheet`, `cell_range` (`A{row}:{col}{row}`), `flags[]`, requirement `evidence_status`, `needs_review`, `quote_start`, `quote_end` (character offsets into the page's `text`), `evidence_quote`.
- Errors on a row write: 404 or 409 `row_replaced` = "replaced by a re-run" (mark the row, reload the list from offset 0); 403 `forbidden` = permission message; 409 `tender_archived` = archived message; 422 = field messages from `details`.
- Writes need `review_data` (`useCan`). Hide controls for everyone else; the API still enforces. Archived tenders: no controls.
- Optimistic updates with rollback. Mutating controls are disabled while pending. No native `confirm()`/`alert()`.
- Quantity and rate inputs are `type="text"` validated against the decimal pattern; never `parseFloat`, `Number()` or `type="number"`. A blank quantity sends `null`.
- State is never colour alone (text badges). Keyboard: arrows move selection, `c` confirm, `r` reject, `e` edit (ignored while typing in an input).
- Commands from `frontend/`: after each task `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` pass; delete `.next` afterwards.
- Branch `feat/slice-4-phase-4-review-screen` from `main`. Commit messages end with the attribution lines from the session's system reminder.

## Review Focus

1. A PDF page number past the document, a null `page_number` on a requirement, or a sheet name missing from `/pages`: show a clear "source not available" note, never a blank pane or a crash (Tasks 3, 4).
2. `quote_start`/`quote_end` null, reversed, or beyond the page text (an `evidence_unverified` requirement): show the quote as plain text and no highlight; never slice with bad offsets (Task 3).
3. A row replaced by a re-run while the user edits it: the row shows "replaced by a re-run", the list reloads, the edit is not silently lost into a different row (Task 2).
4. Quantity typed as `1,500`, `1e3`, `.5`, `10.12345`, or `-`: rejected inline with a message, never sent (Task 1).
5. A reviewer or project manager opens the screen: no confirm/reject/edit controls and no keyboard shortcuts act (Tasks 2, 4).

---

### Task 1: Review data layer and pure helpers

**Files:**
- Create: `src/api/review.ts`, `src/api/review.test.tsx`
- Create: `src/lib/decimal.ts`, `src/lib/decimal.test.ts`, `src/lib/review-text.ts`, `src/lib/review-text.test.ts`, `src/lib/source-span.ts`, `src/lib/source-span.test.ts`, `src/lib/cell-range.ts`, `src/lib/cell-range.test.ts`
- Modify: `src/api/types.ts`, `src/test/fixtures.ts`

**Interfaces (Produces):**
- `types.ts`: `Requirement`, `BoqItem`, `BoqPatch`, `RequirementPatch`, `PageSummary`, `PageDetail` (aliases of `RequirementDTO`, `BoqItemDTO`, `BoqPatch`, `RequirementPatch`, `PageDTO`, `PageDetailDTO`); `ReviewStatus = "unreviewed"|"confirmed"|"corrected"|"rejected"`.
- `decimal.ts`: `DECIMAL_PATTERN: RegExp`; `validateDecimal(text: string): string | null` (null = valid; `""` is valid and means clear).
- `review-text.ts`: `reviewStatusLabel(s)`, `reviewTone(s): Tone`, `flagLabel(code)`, `requirementTypeLabel`, `mandatoryLabel`, `REQUIREMENT_TYPES`, `MANDATORY_STATUSES`, `writeErrorText(error: unknown): { text: string; replaced: boolean }`.
- `source-span.ts`: `splitSpan(text: string, start: number | null, end: number | null): { before: string; mark: string; after: string } | null` (null when offsets are null, non-integer, reversed, empty, or out of range).
- `cell-range.ts`: `parseCellRange(range: string | null): { firstRow: number; lastRow: number; firstCol: number; lastCol: number } | null` (1-based; `A12:F12`, single cell `B3` allowed); `columnLetters(n: number): string`.
- `review.ts`: `versionQueryOptions(id)`, `pagesQueryOptions(id)`, `pageDetailQueryOptions(id, page, rowWindow?)`, `useRequirements(id)` and `useBoqItems(id)` (each `useInfiniteQuery`, page size 200, `getNextPageParam` stops on a short page; return `{ rows, hasNextPage, fetchNextPage, ... }`), `useReviewMutation(kind: "requirement"|"boq-item", versionId)` returning `{ confirm(id), reject(id), correct(id, patch) }` mutations that optimistically set `review_status` in the cached list and roll back on error; on 404/409 `row_replaced` they resets the list (`queryClient.resetQueries` for that list key) and rethrow.

- [ ] **Step 1: Failing tests for the pure helpers.** `decimal.test.ts`: valid `"10"`, `"10.5"`, `"-3.1234"`, `""`; invalid `"1,500"`, `"1e3"`, `".5"`, `"10.12345"`, `"-"`, `"abc"`, `"1 000"` each return a message. `source-span.test.ts`: valid span splits; `null`, `start>=end`, `end>text.length`, negative, `1.5` return null. `cell-range.test.ts`: `"A12:F12"` -> `{12,12,1,6}`; `"B3"` -> single cell; `"AA1:AB2"` -> cols 27..28; `null`/`"garbage"` -> null; `columnLetters(1)==="A"`, `(27)==="AA"`. `review-text.test.ts`: `writeErrorText(new ApiError(404,"not_found","x"))` and `(409,"row_replaced",...)` give `replaced: true`; `(403,"forbidden")` gives a permission message; `(409,"tender_archived")` an archived message; other errors return their own message, `replaced:false`.
- [ ] **Step 2: Run** `npx vitest run src/lib` — expect FAIL (modules missing).
- [ ] **Step 3: Implement** the four helper modules.

```ts
// decimal.ts
export const DECIMAL_PATTERN = /^-?\d{1,14}(\.\d{1,4})?$/;
export function validateDecimal(text: string): string | null {
  const t = text.trim();
  if (t === "") return null;
  if (DECIMAL_PATTERN.test(t)) return null;
  if (/^-?\d{1,14}\.\d{5,}$/.test(t)) return "Use at most 4 decimal places.";
  return "Enter a plain number such as 1500 or 12.5 (no commas or letters).";
}
```

```ts
// source-span.ts
export function splitSpan(text: string, start: number | null, end: number | null) {
  if (start === null || end === null) return null;
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end <= start || end > text.length) return null;
  return { before: text.slice(0, start), mark: text.slice(start, end), after: text.slice(end) };
}
```

```ts
// cell-range.ts
export function columnLetters(n: number): string {
  let s = "";
  for (let x = n; x > 0; x = Math.floor((x - 1) / 26)) s = String.fromCharCode(65 + ((x - 1) % 26)) + s;
  return s;
}
function colNumber(letters: string): number {
  return [...letters].reduce((a, c) => a * 26 + (c.charCodeAt(0) - 64), 0);
}
export function parseCellRange(range: string | null) {
  if (!range) return null;
  const m = /^([A-Z]{1,3})(\d{1,7})(?::([A-Z]{1,3})(\d{1,7}))?$/.exec(range.trim());
  if (!m) return null;
  const c1 = colNumber(m[1]), r1 = Number(m[2]);
  const c2 = m[3] ? colNumber(m[3]) : c1, r2 = m[4] ? Number(m[4]) : r1;
  return { firstRow: Math.min(r1, r2), lastRow: Math.max(r1, r2), firstCol: Math.min(c1, c2), lastCol: Math.max(c1, c2) };
}
```

`review-text.ts` implements the labels (plain words, e.g. `missing_quantity` -> "Quantity missing", `ambiguous_separator` -> "Check the thousands separator", `rate_unparsed` -> "Rate could not be read", unknown codes shown as the code) and `writeErrorText`.
- [ ] **Step 4: Run** `npx vitest run src/lib` — PASS.
- [ ] **Step 5: Failing test for `review.ts`** (`review.test.tsx`, using `mockApi`/`renderSignedIn`): (a) `useBoqItems` fetches `limit=200&offset=0`, then a full page enables `fetchNextPage` with `offset=200`, a short page sets `hasNextPage` false; (b) `confirm` sets the row to `confirmed` in the cache before the request resolves, and restores `unreviewed` if the server answers 403; (c) a 404 on `confirm` resets the list query (a second `GET boq-items?offset=0` happens) and `writeErrorText(...).replaced` is true; (d) `correct` sends `PATCH` with exactly the patch body and the `X-Requested-With` header (the client adds it).
- [ ] **Step 6: Implement `review.ts` and the type aliases and fixtures** (`makeRequirement`, `makeBoqItem`, `makePage`, `makePageDetail` in `fixtures.ts`). Query keys: `["review","requirements",versionId]`, `["review","boq-items",versionId]`, `["version",id]`, `["pages",id]`, `["page",id,n,window]`. Mutations carry `meta` nothing special (a 401 should re-check the session as everywhere).
- [ ] **Step 7: Run all four commands** (lint, typecheck, test, build) — PASS.
- [ ] **Step 8: Commit** `feat: review data layer and helpers`.

---

### Task 2: Review rows (requirement and BoQ) with actions and editing

**Files:**
- Create: `src/components/review/requirement-row.tsx`, `src/components/review/boq-row.tsx`, `src/components/review/row-actions.tsx`, `src/components/review/review-row.test.tsx`

**Interfaces:**
- Consumes: Task 1 (`useReviewMutation`, `validateDecimal`, `review-text`, types, fixtures), `useCan` from `@/components/auth-gate`, `StatusBadge`.
- Produces: `<RequirementRow row selected onSelect archived />` and `<BoqRow row selected onSelect archived />`: a `role="row"`-free `<li>` with `aria-current` when selected, a `button` that selects it, review-state `StatusBadge`, chips (requirement: `Evidence unverified` when `evidence_status === "evidence_unverified"`, `Needs review` when `needs_review`; BoQ: `flagLabel` per flag), "Reviewed by {name} on {date}" when set, for `corrected` rows the original value shown beside the effective one (`original_value` vs the row), and an inline "Replaced by a re-run. The list was reloaded." note after a replaced error. `<RowActions>` renders Confirm / Edit / Reject buttons only when `useCan("review_data") && !archived`; exposes the imperative handlers via props `onConfirm/onReject/onEdit` so Task 4's keyboard handler can drive the selected row (the row components accept an optional `editSignal: number` that opens the editor when it changes).

- [ ] **Step 1: Failing tests** (`review-row.test.tsx`): reviewer role (`meWith(["read"],"reviewer")`) sees badge and chips but no buttons; estimator sees Confirm/Edit/Reject; clicking Confirm sends `POST /api/v1/boq-items/{id}/confirm` and the badge reads "Confirmed" with the button disabled while pending; Reject likewise on a requirement; editing a BoQ line: typing `1,500` in Quantity shows the decimal message and Save is disabled (no PATCH sent); typing `1500` and Save sends `PATCH` with `{ "quantity": "1500" }` only (unchanged fields omitted); clearing quantity sends `{ "quantity": null }`; requirement edit offers type and mandatory selects with only the enum values and description; a 404 on Confirm shows the replaced note; a 403 shows the permission message and the badge returns to Unreviewed; archived hides actions.
- [ ] **Step 2: Run** `npx vitest run src/components/review` — FAIL.
- [ ] **Step 3: Implement** the three components. Edit state is local to the row; Save disables while pending and closes on success; field errors from a 422 (`details: [{field,message}]`) display beside the field. Only changed fields enter the patch.
- [ ] **Step 4: Run** the four commands — PASS.
- [ ] **Step 5: Commit** `feat: review rows with confirm, reject and edit`.

---

### Task 3: Source viewer (PDF, sheet grid, text-only)

**Files:**
- Modify: `src/components/pdf/pdf-page.tsx`, `src/components/pdf/pdf-page.test.tsx`
- Create: `src/components/source/source-viewer.tsx`, `src/components/source/page-text.tsx`, `src/components/source/sheet-grid.tsx`, `src/components/source/source-viewer.test.tsx`

**Interfaces:**
- Consumes: Task 1 (`pagesQueryOptions`, `pageDetailQueryOptions`, `splitSpan`, `parseCellRange`, `columnLetters`).
- Produces: `type Source = { page: number | null; sheet: string | null; cellRange: string | null; quoteStart: number | null; quoteEnd: number | null; quote: string | null }`; `<SourceViewer versionId fileFormat source />`. `<PageText text start end />` (text nodes plus one `<mark>`; scrolls the mark into view; when `splitSpan` is null shows the text unmarked and, if a quote is given, a "Quote (not located on the page)" line). `<SheetGrid table range />` (read-only `<table>`, row numbers from `first_row`, cited range cells carry `aria-selected` and a visible outline, first cited row scrolled into view). `PdfPage` gains: one document load per `url` with a separate page-render effect (page changes do not re-download), `devicePixelRatio` scaling, an `onDocument?(numPages)` callback; keep render-task cancellation and destroy-on-cleanup.

Resolution rules in `SourceViewer`: `fileFormat === "pdf"` -> `PdfPage` at `source.page` (clamped) over `PageText` for the same page; `xlsx`/`csv` -> find the page in `pagesQueryOptions` whose `label === source.sheet` (CSV: the only page), load detail with a row window of `range.firstRow - 20` to `range.lastRow + 20` (min 1) and render `SheetGrid`; `docx` -> `PageText` with a "Text only: the original layout is not shown" label. A scanned page (`text_source` is not the native source, or `ocr_confidence` present) shows an amber "Scanned page (OCR)" badge. Any unresolvable source (null page and no sheet, sheet not in `/pages`, request error) renders `role="status"` "Source not available for this row."

- [ ] **Step 1: Failing tests:** `PageText` with valid span marks exactly the quote; with null/bad offsets renders no `<mark>` and shows the not-located line; text containing `<b>x</b>` renders literally (no element). `SheetGrid` highlights only cells in `A12:C12`; with `first_row: 10` the row number column shows 10, 11, 12…; invalid range highlights nothing. `SourceViewer`: xlsx row with sheet "BoQ" requests `/pages` then `/pages/2` with `row_from`/`row_to`, and highlights; sheet name absent from `/pages` shows "Source not available"; docx shows the text-only label; null source shows the note. PdfPage: changing `pageNumber` does not call `getDocument` again (mock `pdfjs-dist` as the existing test does).
- [ ] **Step 2: Run** `npx vitest run src/components` — FAIL.
- [ ] **Step 3: Implement.** For `PdfPage`, split into a document effect (keyed on `url`, stores the `PDFDocumentProxy` in state, destroys on cleanup, `getDocument({ url, withCredentials: true })`) and a render effect (keyed on document, page, scale) that cancels the previous `RenderTask` first. Canvas size `viewport.width * dpr`, CSS width `viewport.width`.
- [ ] **Step 4: Run** the four commands — PASS.
- [ ] **Step 5: Commit** `feat: source viewer for pdf, sheet and text sources`.

---

### Task 4: Review screen, navigation, cleanup, docs, real-stack check

**Files:**
- Create: `src/app/(app)/tenders/[id]/review/[versionId]/page.tsx`, `src/app/(app)/tenders/[id]/review/[versionId]/review-screen.tsx`, `src/app/(app)/tenders/[id]/review/[versionId]/review-screen.test.tsx`
- Modify: `src/app/app-pages.test.ts` (route list), `src/components/extraction-panel.tsx` or `document-card.tsx` (a "Review" link to the screen for a `ready`/`ready_with_warnings` version, shown to users holding `read`), `docs/plan.md` (Slice 4 status), `docs/known-limitations.md`
- Delete: `src/app/(app)/dev/pdf-spike/` (page and component) and its entry in any test

**Interfaces:**
- Consumes: Tasks 1 to 3. Produces: the route; `ReviewScreen` (client): header with filename, back link to the tender, tabs `Requirements (n)` / `BoQ lines (n)` (`role="tablist"`), list of rows with "Load more" while `hasNextPage`, selection state driving `SourceViewer` (requirement -> `{page: row.page_number, quote offsets}`; BoQ -> `{page: row.page_number, sheet, cellRange}`), two panes from `lg` and a single column below it with a Rows/Source toggle, empty states ("Nothing was extracted from this document yet" with a link to the tender page to run extraction), and keyboard handling (`ArrowUp/Down` move selection, `c`, `r`, `e` act on the selected row only if the user can review, is not archived, and focus is not in an input/textarea/select).

- [ ] **Step 1: Failing tests:** renders requirement rows, selecting one requests its page text and marks the quote; switching to the BoQ tab lists lines; ArrowDown moves selection; pressing `c` as an estimator posts confirm for the selected row, and as a reviewer posts nothing; focus inside an input ignores `c`; a short first page shows no "Load more", a full page shows it and clicking fetches `offset=200`; archived tender (tender fetched via the existing tender query) shows a read-only note and no controls; unknown version id (404) shows a not-found message.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** page (with `instant = false`) and screen; add the Review link; delete the spike route; update `app-pages.test.ts`.
- [ ] **Step 4: Run** the four commands — PASS.
- [ ] **Step 5: Real-stack check** (skill `run`): bring up the Docker stack through Caddy, register, create a tender, upload a synthetic PDF pack and an XLSX BoQ (`backend/` synthetic generator), wait for ingest, run extraction (BoQ needs no Ollama), open the review screen in the browser and verify gate steps 2, 3, 4 (re-run keeps reviewed rows and shows "replaced by a re-run" for a stale write) and 5 (reviewer user sees no controls; create them through `POST /members`). Poll for "Page N of M", no fixed waits. Record results and any defects in the plan status line; fix defects before merge.
- [ ] **Step 6: Update docs:** `docs/plan.md` Slice 4 status (phase 4 done, phases 5 and 6 next); `docs/known-limitations.md` (text-layer quote matching not implemented, only the stored span; DOCX text-only).
- [ ] **Step 7: Commit** `feat: review screen (Slice 4 phase 4)`, then run `superpowers:finishing-a-development-branch`.
