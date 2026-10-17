# Slice 5a, Phase 4: Supplier Comparison UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An estimator reviews a quotation next to its source (items, header details, supplier), and compares suppliers per BoQ line: ranked candidates per supplier with their evidence, prices side by side with no cheapest highlight, confirm / reject / reset one match, "confirm all clear matches" in bulk, and re-run matching.

**Architecture:** TanStack Query hooks per resource in `frontend/src/api/` (`suppliers.ts`, `quotations.ts`, `matches.ts`; the review mutation hook gains a `quotation-item` kind), plain-words helper modules in `frontend/src/lib/`, a quotation row built on the existing `RowShell`, a quotation header panel in the review screen, and a new client page `/tenders/[id]/suppliers` (comparison). Pages are thin server components that export `instant = false` and render a client view, as in Slices 4 and 5a phase 5.

**Tech Stack:** Next.js 16.4.1 (App Router, `cacheComponents`), React 19.3, TypeScript, Tailwind 4, TanStack Query 5, Vitest 5 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` section 7 (Frontend), section 5 (classification), the Slice 4 spec section 5 for the review screen. The API (Phase 3) is on this branch: generated types are in `frontend/src/api/schema.d.ts` (`MatchLineDTO`, `MatchSuggestionDTO`, `MatchSupplierRef`, `MatchBoqRef`, `MatchQuoteRef`, `ConfirmClearResult`, `QuotationDTO`, `QuotationPatch`, `QuotationItemDTO`, `QuotationItemPatch`, `SupplierDTO`, `SupplierPatch`).

## Global Constraints

- Read the bundled Next docs before writing frontend code (`frontend/AGENTS.md`): this Next differs from older versions. `cacheComponents` and `partialPrefetching` stay ON. Every `src/app/(app)/**/page.tsx` is a **server component** exporting `export const instant = false;` (with the explanatory comment used in the existing pages) that renders a client view; `src/app/app-pages.test.ts` enforces it. Client views read route params with `useParams()` / `useSearchParams()` (the root `<Suspense>` already covers them). No `cookies()` on the Next server; no `dangerouslySetInnerHTML`: descriptions, SKUs, supplier names and evidence are untrusted text nodes.
- **The lowest price is never highlighted, selected, sorted first or defaulted** (PRD FR-37). Prices are shown as the API's decimal strings (never `parseFloat`/`Number`/`toFixed` for money), in the order the API returns (BoQ order, supplier name, rank). No sort control by price, no "best price" badge, no colour or bold on any price.
- **State is never colour alone** (text badges), keyboard operable, focus-visible, works at phone width (candidates stack as cards below `md`).
- Writes need `review_data` (`useCan("review_data")`) and a non-archived tender (`tender.status !== "archived"`); otherwise render no write controls (reads still work). Controls that submit are disabled while pending. No native `confirm()`/`alert()`.
- Error messages from the API's codes: `match_conflict` ("Another candidate from this supplier is already confirmed for this line. Reject or reset that one first."), `stale_match` ("This quotation was replaced. Reload the list."), `tender_archived`, `forbidden`, `row_replaced`, `try_again` ("Something changed at the same time. Try again."); anything else shows the server's message.
- Frontend commands from `frontend/`: `npm run lint`, `npm run typecheck` (runs `next typegen` first), `npm test`, `npm run build`; delete `.next` afterwards. Vitest full runs take about 1 minute; iterate on single files.
- Shell: the Bash tool here mishandles long heredocs; create files with the editor tools.
- Branch `feat/slice-5a-phase-2-matching` (current; phases 3 to 5 continue on it). Commit messages end with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. Confirm on a candidate when another candidate of the same supplier is already confirmed for that line: the 409 message appears on that candidate, the list reloads, nothing else changes (Task 3).
2. "Confirm all clear matches" reports exact counts, never touches ambiguous suggestions, is disabled with no clear suggestions, and a second click confirms nothing (Task 3).
3. Prices render exactly as the API sends them (`"54917.00"`), a missing price shows "Price missing" (never 0), and no element carries a "cheapest" cue; two suppliers with different prices keep API order (Task 3).
4. Quotation item correction with `1,500` or 5 decimals in price/quantity is refused inline and nothing is sent (Task 2).
5. Read-only roles and archived tenders see everything and no controls; a 401 anywhere re-checks the session (existing global handler) (Tasks 2, 3).

---

### Task 1: API layer, types and plain-words helpers

**Files:**
- Create: `frontend/src/api/suppliers.ts`, `frontend/src/api/quotations.ts`, `frontend/src/api/matches.ts`, `frontend/src/lib/match-text.ts`, `frontend/src/lib/match-text.test.ts`, `frontend/src/api/matches.test.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/review.ts` (kind `quotation-item`), `frontend/src/api/review.test.tsx`, `frontend/src/lib/review-text.ts` (+ test), `frontend/src/test/fixtures.ts`

**Interfaces (Produces):**
- `types.ts`: `Quotation`, `QuotationPatch`, `QuotationItem`, `QuotationItemPatch`, `Supplier`, `SupplierPatch`, `MatchLine`, `MatchSuggestion`, `MatchBoqRef`, `MatchQuoteRef`, `MatchSupplierRef`, `ConfirmClearResult` (aliases of the generated schemas).
- `review.ts`: `ReviewKind` becomes `"requirement" | "boq-item" | "quotation-item"`; `useQuotationItems(versionId, enabled?)` (same infinite list contract as `useBoqItems`); `useReviewMutation("quotation-item", versionId)` works for confirm/reject/correct with the same optimistic update and "replaced" handling (path segment `quotation-items`).
- `quotations.ts`: `quotationsQueryOptions(tenderId)` (key `["quotations", tenderId]`, `GET /tenders/{id}/quotations`), `useUpdateQuotation()` (PATCH `/quotations/{id}`, invalidates `["quotations"]`, `["matches"]` and `["suppliers"]`).
- `suppliers.ts`: `suppliersQueryOptions` (key `["suppliers"]`), `useCreateSupplier()`, `useUpdateSupplier()`, `useMergeSupplier()` (Phase 5 uses them; hooks only here).
- `matches.ts`: `useMatchLines(tenderId, filters)` (`useInfiniteQuery`, key `["matches", tenderId, filters]`, `GET /tenders/{id}/match-suggestions` with `limit` 100 and `offset`, filters `{status?, classification?, supplierId?, onlyWithSuggestions?}`, `getNextPageParam` stops on a short page (fewer than 100 lines)), `useDecideMatch(tenderId)` returning `{confirm(id), reject(id), reset(id)}` mutations (`POST /match-suggestions/{id}/confirm|reject|reset`) that on success replace the suggestion in the cached pages and on error leave the cache as is, `useConfirmClear(tenderId)` (`POST /tenders/{id}/match-suggestions/confirm-clear`, invalidates `["matches", tenderId]`), `useRunMatching(tenderId)` (`POST /tenders/{id}/match`, invalidates `["matches", tenderId]` after 2 s via the returned job being polled: simply invalidate on success and let the page's "Refresh" button re-read).
- `match-text.ts`: `classificationLabel(c)` ("Clear match" | "Needs a decision"), `classificationTone(c)`, `matchStatusLabel(s)` ("Suggested" | "Confirmed" | "Rejected"), `matchStatusTone`, `warningLabel(code)` for the evidence warnings (`spec_conflict` "Specification differs", `unit_mismatch` "Unit differs", `quote_expires_before_closing` "Quote expires before the tender closes", `spec_multi_value` "Quote lists more than one value", `quote_shared` "Fits another line as well", `core_notation_differs` "Cable core notation differs (3-core vs 3C+E)", `text_differs` "Wording differs on both sides", `spec_one_sided` "Only one side gives a specification", `accessory_word` "May be an accessory, not the item", `negation` "Says something is excluded"; unknown codes show the code), `reasonText(suggestion)` (one plain sentence for ambiguous suggestions built from the first two warnings, or "Several close candidates from this supplier." when there are no warnings), `matchErrorText(error)` (the Global Constraints mapping; unknown errors use the API message), `scoreText(score)` (percent with no decimals, display only), `evidenceSummary(evidence)` returning a list of `{label, value}` rows (text similarity, specification agreement, unit state `equal|mismatch|unknown` in words, matched / conflicting / one-sided specification kinds as comma lists, validity date) from the evidence JSON defensively (every field optional).
- Fixtures: `makeSupplier`, `makeQuotation`, `makeQuotationItem`, `makeMatchSuggestion`, `makeMatchLine`.

- [ ] **Step 1: Write the failing tests**

`match-text.test.ts`: every label above for known and unknown codes; `reasonText` with 0, 1, 2 and 3 warnings; `matchErrorText` for `ApiError` 409 `match_conflict`, 409 `stale_match`, 403 `forbidden`, 409 `tender_archived`, 409 `try_again`, a plain `Error`; `evidenceSummary` on a full evidence object, on `{}` and on garbage (strings where numbers expected) without throwing; `scoreText(0.8143) === "81%"`.
`matches.test.tsx` (use `mockApi`, `renderHook`, `createTestClient` as in `src/api/review.test.tsx`): `useMatchLines` requests `limit=100&offset=0`, next page `offset=100` only after a full page, stops after a short page, filters are sent as `status`, `classification`, `supplier_id`, `only_with_suggestions`, changing a filter restarts from offset 0; `useDecideMatch.confirm` posts to the right path with the CSRF header and replaces the suggestion in the cached page (status `confirmed`); on 409 `match_conflict` the cache is unchanged and the error is the `ApiError`; `useConfirmClear` posts and invalidates; `useRunMatching` posts.
`review.test.tsx`: add a case for `useQuotationItems` paging and for `useReviewMutation("quotation-item", ...)` confirm hitting `/api/v1/quotation-items/{id}/confirm`.
`review-text.test.ts`: flag labels for the quotation flags `missing_price` ("Price missing"), `price_unparsed` ("Price could not be read"), `zero_price` ("Price was zero, left blank"), `negative_price` ("Price was negative, left blank"), `zero_quantity` ("Quantity is zero"), `missing_description` ("Description missing").

- [ ] **Step 2: Run, see them fail.** `cd frontend && npx vitest run src/lib src/api`

- [ ] **Step 3: Implement** the modules above (copy the shapes of `src/api/review.ts`, `src/api/tenders.ts`, `src/api/session.ts`). Never format money; `scoreText` is the only number formatting and is for the match score only.

- [ ] **Step 4: Checks.** `npm run lint && npm run typecheck && npm test`; fix. 

- [ ] **Step 5: Commit** `feat: supplier, quotation and match API hooks and plain-words helpers`.

---

### Task 2: Quotation review in the review screen

**Files:**
- Create: `frontend/src/components/review/quotation-row.tsx`, `frontend/src/components/review/quotation-panel.tsx`, `frontend/src/components/review/quotation-row.test.tsx`, `frontend/src/components/review/quotation-panel.test.tsx`
- Modify: `frontend/src/components/review/row-shell.tsx` (kind type only if needed), `frontend/src/app/(app)/tenders/[id]/review/[versionId]/review-screen.tsx` and its test, `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx` or `document-card.tsx` (link label for quotations)

**Interfaces:**
- `<QuotationRow row versionId selected onSelect archived? command? editing? onEditingChange? onReplaced? />` built on `RowShell` (`kind="quotation-item"`): summary shows description, SKU chip, `Qty {quantity} · Unit {unit} · Price {unit_price}` (decimal strings as given; `Price missing` text when null, never 0), flags via `flagLabel`, original-versus-corrected values for corrected rows (compare normalised text like `BoqRow`), editor with description, SKU, unit, quantity and unit price (text inputs, `validateDecimal`, blank sends `null`, only changed fields sent).
- `<QuotationPanel tenderId versionId archived />` shows the quotation's header (supplier name, reference, quote date, valid until, currency, "Prices include VAT" / "exclude VAT" / "VAT not stated", header flags as warnings in plain words) and, for users who can review, an "Edit details" form: supplier `<select>` of the organisation's suppliers (from `suppliersQueryOptions`), reference, quote date, valid until (date inputs), currency (3 letters, upper-cased on input), VAT radio group (include / exclude / not stated → `null`); saves only changed fields via `useUpdateQuotation`; shows 409 `match_conflict` text from `matchErrorText`; a note that changing the supplier moves its matches.
- Review screen: it reads the documents list (`documentsQueryOptions(tenderId)`) to learn the kind of the document whose current version is `versionId`; for kind `quotation` it shows `QuotationPanel` above a single "Quotation items (n)" list (hide the Requirements and BoQ tabs); for every other kind the screen behaves exactly as today. Selecting a quotation item feeds `SourceViewer` with `{page, sheet, cellRange}` like BoQ rows (quotes never carry `quote_start/end`). Keyboard shortcuts (`c`, `r`, `e`, arrows) work on quotation rows like the other rows. While the documents list is loading, show the existing "Loading document…" state; if the version is not found in the list (stale cache) fall back to today's behaviour.
- The "Review extracted data" link on the document card is unchanged (works for quotations); its text for quotation documents is "Review quotation".

- [ ] **Step 1: Write the failing tests**

`quotation-row.test.tsx` (pattern: `review-row.test.tsx`; mock `next/navigation`): reviewer sees state badge, flags and prices but no buttons; estimator sees Confirm/Edit/Reject; confirm posts to `/api/v1/quotation-items/{id}/confirm`; typing `1,500` in Unit price shows the decimal message and disables Save (no PATCH sent), `1500` saves `{unit_price: "1500"}` only; clearing the quantity sends `{quantity: null}`; a null price renders "Price missing" and never "0"; a corrected row shows "(was …)"; a 404 shows the "Replaced by a re-run" note.
`quotation-panel.test.tsx`: header shows supplier, reference, dates, currency and VAT wording; header flags (`NO_CURRENCY`, `VAT_UNKNOWN`, `NO_VALIDITY`) appear as plain-words warnings via `warningText`; reviewer sees no Edit button; estimator edits currency "zar" (typed lower-case becomes "ZAR") and sends `{currency: "ZAR"}` only; switching supplier sends `{supplier_id}`; 409 `match_conflict` shows the mapped message and keeps the form open; archived hides Edit.
`review-screen.test.tsx`: for a quotation version (documents list says kind `quotation`) the screen shows the panel and the quotation items, hides Requirements/BoQ tabs, selecting an xlsx quotation item loads the sheet grid for its cell range, `c` confirms the selected quotation item for an estimator, a reviewer gets no controls; for a `boq` and a `tender_document` version nothing changed (existing tests stay green).

- [ ] **Step 2: Run, see them fail.** `cd frontend && npx vitest run src/components/review src/app`

- [ ] **Step 3: Implement.** Reuse `StatusBadge`, `Field`, `useCan`, `warningText` (export a `quotationWarningText(code)` helper from `status-text.ts` if the existing `warningText` needs a code-only entry point), `formatDateTime`/date formatting helpers in `src/lib/format.ts` (add `formatDate(iso)` if absent).

- [ ] **Step 4: Checks.** lint, typecheck, full `npm test`, `npm run build` (delete `.next`).

- [ ] **Step 5: Commit** `feat: quotation review in the review screen`.

---

### Task 3: Supplier comparison page

**Files:**
- Create: `frontend/src/app/(app)/tenders/[id]/suppliers/page.tsx`, `comparison-view.tsx`, `match-line.tsx`, `candidate-row.tsx`, `comparison-view.test.tsx`, `candidate-row.test.tsx`
- Modify: `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx` (link "Compare suppliers"), `frontend/src/components/app-shell.tsx` (nav link "Suppliers" → `/tenders` is not meaningful; the nav link is added in Phase 5 with the suppliers page, so do NOT add it here)

**Interfaces:**
- `<ComparisonView />` (client; `useParams` for the tender id): header with the tender title and a back link; summary line (lines on this page, lines with a clear match, lines needing a decision, confirmed count — computed from the loaded pages and labelled "loaded"); toolbar: filters (Classification: All / Clear match / Needs a decision; Status: All / Suggested / Confirmed / Rejected; Supplier: All + options from `quotationsQueryOptions`' suppliers; checkbox "Only lines with a suggestion"), "Confirm all clear matches (n)" where n is the count of loaded `clear` + `suggested` suggestions (disabled when 0 or pending or read-only; on success a status message "Confirmed N, skipped M" from `ConfirmClearResult`), "Run matching again" (`useRunMatching`), "Refresh". Below: the BoQ lines in API order grouped under section headings (`boq.section`); each `<MatchLine>` shows item no, description, unit, quantity and its candidates; a line without suggestions shows "No supplier quote matches this line." "Load more lines" while `hasNextPage`.
- `<CandidateRow suggestion tenderId canReview />`: supplier name, quotation item description, SKU chip, unit, quantity, unit price (as given, or "Price missing"), classification badge, status badge, warning chips (`warningLabel`) and, for ambiguous, the `reasonText` sentence; expandable "Why this match" `<details>` with `evidenceSummary` rows and `scoreText`; actions when `canReview`: Confirm (when status is `suggested` or `rejected`), Reject (when `suggested` or `confirmed`), Reset (when `confirmed` or `rejected`) — disabled while pending; errors via `matchErrorText` shown on that candidate with `role="alert"`; after `stale_match` or `row_replaced` the list is invalidated. "Decided by {name} on {date}" for decided rows. Layout: table row from `md` up, stacked card below.
- No price-based ordering, no "best", "cheapest", "lowest" text anywhere (a test greps the rendered output for those words).
- Tender page gets a "Compare suppliers" link next to "Requirements checklist".

- [ ] **Step 1: Write the failing tests**

`candidate-row.test.tsx`: renders supplier, description, SKU, unit, price string exactly (`"54917.00"`), "Price missing" for null; ambiguous shows the reason sentence and warning chips in words; evidence disclosure lists the rows; estimator sees Confirm/Reject on a suggested row, Reset/Reject on a confirmed one, Reset/Confirm on a rejected one; reviewer sees no buttons; confirm posts `/api/v1/match-suggestions/{id}/confirm`; a 409 `match_conflict` shows the mapped sentence on that row only and the other rows are untouched; `stale_match` invalidates the list query; no element has the words cheapest/lowest/best.
`comparison-view.test.tsx` (mock `next/navigation` `useParams`, `mockApi` routes for the tender, quotations, match-suggestions): renders lines grouped under section headings in API order; a line with no suggestions shows the empty sentence; two suppliers with different prices render in API order with no highlight (assert order of DOM text and that no price element has a special class marker such as `data-best`); filters send `classification=clear` and `status=suggested` and `supplier_id`, `only_with_suggestions=true`, each restarting from offset 0; "Load more lines" appears only after a full page (100 lines) and requests `offset=100`; "Confirm all clear matches (2)" posts, shows "Confirmed 2, skipped 0", is disabled at 0 and while pending; ambiguous suggestions are never counted in n; "Run matching again" posts `/api/v1/tenders/{id}/match`; archived tender and reviewer role: no controls, list still shows; 404 tender → not found message; the summary counts loaded lines only and says so.

- [ ] **Step 2: Run, see them fail.** `cd frontend && npx vitest run "src/app/(app)/tenders"`

- [ ] **Step 3: Implement.** Follow `checklist-view.tsx` for structure (useParams, tender query, not-found handling, Load more) and `candidate`/`row` styling of the review rows (borders, badges).

- [ ] **Step 4: Checks.** lint, typecheck, full `npm test`, `npm run build` (delete `.next`); confirm the build lists `/tenders/[id]/suppliers`.

- [ ] **Step 5: Docs.** `docs/plan.md` Slice 5 row: a Phase 4 sentence (what exists; real-stack check pending, the controller does it); `docs/known-limitations.md`: summary counts on the comparison page cover loaded lines only; the list fetches 100 BoQ lines per page.

- [ ] **Step 6: Commit** `feat: supplier comparison page`.
