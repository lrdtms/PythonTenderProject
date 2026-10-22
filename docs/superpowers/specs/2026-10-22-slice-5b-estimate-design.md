# Slice 5b: The estimate (design)

**Date:** 2026-10-22 · **Branch:** `feat/slice-5b-estimate` (to be created) · **Status:** draft for owner review, revised after an Opus builder check (see section 13). Calls marked **(my call)** are the author's choices, not agreed with the owner.
**Authority:** `docs/plan.md` section 3 (Slice 5, exit gate "totals correct; golden-file tests (F7)"), `docs/prd.md` FR-62, section 10 (financial maths), architecture section 2 (`estimating.compute`, `set_status`) and fitness function F7, base spec `Python_Project.pdf` (FR-26 to FR-30, FR-37 to FR-42, BR-01, BR-03, BR-04, BR-08, US-05, section 7.4, section 9.2), the 5a spec for matches. Frontend rules: `frontend/AGENTS.md`.

5a ends with confirmed matches: a human has said which supplier quotation item prices a BoQ line. 5b turns those into a priced, versioned, approvable **estimate** for a tender. Slice 6 exports the approved estimate to Excel and PDF; 5b stops before any file is produced.

## 1. Goal and scope

An estimator opens the estimate of a tender and sees every BoQ line with a price source. For each line they pick which confirmed supplier price to use (or type a manual price, or exclude the line with a reason). They set markup and VAT behaviour. The system computes line totals, section subtotals and the tender total with `Decimal`, shows what is still unpriced or unsafe, and moves the estimate through draft, reviewed and approved. The AI never picks a price and the lowest price is never selected for them (FR-37, BR-04).

**Exit gate (real Docker stack through Caddy, synthetic pack with two quotations and confirmed matches):**

1. Create an estimate from a tender with confirmed matches; every current, non-rejected BoQ line appears, in BoQ order, with its candidate prices side by side and nothing pre-selected.
2. Select a supplier price per line, type a manual price on one line, exclude one line with a reason. Totals update and equal the golden file figures to the cent.
3. A line whose chosen quote has `prices_include_vat` unknown, or a currency different from the estimate's, is blocked with a plain-words reason and does not enter the total until resolved.
4. Edit a BoQ quantity or a quotation price after selecting: the line shows "source changed" and approval is refused until the line is refreshed or acknowledged.
5. Mark reviewed, approve, reload: the approved version is frozen (every write is 409 `estimate_frozen`). "New version" creates a draft copy; the approved one is untouched.
6. Reviewer role sees everything and has no controls (API 403 on writes); estimator cannot approve; project manager and admin can.
7. F7 green (golden files, Hypothesis properties, no `float` in `estimating/`); F1 green for every new route; F3 and F2 still green; backend and frontend CI green.

## 2. Goals, non-goals, anti-goals

**Goals:** correct deterministic totals; every number traceable to a BoQ line, a confirmed match or a typed manual value and a person; an approved estimate that cannot change underneath the user; honest gaps (unpriced, unsafe, changed).

**Non-goals (out of scope):** Excel and PDF export (Slice 6); automatic supplier selection or "best price" ranking; currency conversion; unit conversion; preliminaries, provisional sums, contingency and discounts as first-class concepts (a provisional sum line is handled like any other line with a manual price); multi-currency estimates; email or in-app approval requests; submission to a procurement authority (BR-08); usage limits.

**Anti-goals (failure even if it technically works):** a total that silently counts a missing price as 0; a total that mixes VAT-inclusive and VAT-exclusive prices; an approved estimate whose numbers change after approval; any code path that picks a supplier without a click; `float` anywhere in money code.

## 3. Decisions taken

| Decision | Choice |
|---|---|
| Estimates per tender | Many versions, numbered from 1; one draft at a time per tender (partial unique index). **(my call)** |
| Versions | A version is a self-contained snapshot (lines copy the prices they use). Reviewed and approved versions are frozen. "New version" creates a fresh draft (BoQ lines from the current tender, nothing priced), allowed whenever no draft exists. Carrying price choices over from an older version is deferred. The highest approved version is "the approved estimate" for Slice 6 |
| Status flow | `draft` -> `reviewed` -> `approved`. `reviewed` can go back to `draft` (reopen) only when no other draft exists (409 `draft_exists`); `approved` cannot change, only be superseded by a newer approved version. Marking reviewed uses the same readiness gate as approving. FR-41, FR-62 |
| Who may do what | Edit draft and mark reviewed: `review_data` (admin, estimator). Approve: new permission `approve_estimate` for admin and project manager (base spec: project manager reviews approved estimates). Pricing defaults: new permission `manage_pricing`, admin only. Reviewer reads only. **(my call; adds two permissions)** |
| Four eyes | Not enforced: the approver may be the person who marked it reviewed. The audit row records both. **Confirmed by the owner** |
| Price choice | A human selects one **confirmed** match per BoQ line, or types a manual price, or excludes the line. Nothing is pre-selected, not even when only one candidate exists |
| Currency | One currency per estimate, set at creation from the organisation default; a line priced in another currency is blocked, never converted |
| VAT | VAT is always on (owner decision): the estimate carries an explicit `vat_rate` (a percentage, 0 to 100) and the total adds VAT at the end. There is no VAT off mode. Quote prices that include VAT are converted to ex VAT by dividing by `(1 + rate/100)`, and the line shows that it was. An unknown VAT basis blocks the line (PRD: never assumed). No default rate is hard-coded in code: the rate comes from organisation pricing defaults, which the admin must set before the first estimate (the screen offers 15% as a typed-in suggestion, which the owner agreed to) |
| Markup | A percentage with an estimate-level default plus an optional per-line override, applied to each line's cost ex VAT, before VAT. **The basis is an option** (`markup_basis`, set in pricing defaults and per estimate): `cost` (markup = cost x pct) or `selling_price` (a margin: price = cost / (1 - pct), so pct must be below 100). Material and labour (FR-27): lines carry material (the chosen unit price) and an optional manual `labour_rate` per unit, **kept in scope at the owner's request**; markup applies to both |
| Rounding | Quantities and unit prices keep 4 decimals. Material cost, labour cost, line markup and the VAT amount are each rounded to 2 decimals, `ROUND_HALF_UP`, in that order; `cost = material + labour`; totals are sums of rounded values, never re-derived. `calc.py` runs in an explicit local `Decimal` context (precision 40, `ROUND_HALF_UP` passed to every `quantize`) so the default 28-digit context cannot round silently. Rounding the unit price to 4 decimals first costs at most quantity x 0.00005 per line; golden files encode it. **(my call)** |
| Unpriced lines | Never 0. A line is `priced`, `excluded` (with a mandatory reason) or `unresolved`. Approval needs zero `unresolved` lines |
| Change detection | `source_changed` is computed live, never stored. A draft line is changed when its stored input hash (quantity, unit, chosen unit price, VAT basis, currency) differs from the live inputs, **or** the chosen match is no longer confirmed and current (reset, rejected, released as stale, quotation item rejected or superseded, BoQ line rejected or no longer current, supplier switched or merged). Review and approval are refused until each changed line is refreshed (re-snapshotted) or re-chosen. There is no "keep" |
| Incomplete totals | While lines are unresolved or changed, the headline total is labelled "Incomplete: excludes N lines"; a bare partial total is never shown |
| Approval and BoQ review (BR-01) | Owner decision: unreviewed inputs block. A line built on a BoQ line or a quotation item that is still `unreviewed` is flagged `unreviewed_source` and counts as unresolved until the BoQ line and the quotation item are confirmed or corrected in the review screens. Marking reviewed and approving require none |
| Provisional-sum and rate-only lines | These BoQ lines have no quantity by design. Owner decision: in 5b they can only be excluded (with a reason). No lump sum, no manual quantity |
| Concurrency | Every write and status move takes `SELECT ... FOR UPDATE` on the `estimates` row, so approve cannot race a line write |
| Computation | Pure function `compute(inputs) -> EstimateTotals` with no database access; the service loads rows and persists snapshots. Totals are recomputed on every read of a draft and stored when status changes, so a frozen estimate stores its own totals |

## 4. Module placement and data model

**New module `estimates`** (not `estimating`). `estimating` may not import `suppliers` (the component graph has `suppliers -> estimating` only, and import-linter checks layers, not cycles), so the estimate logic lives in a module that depends on both: `estimates` reads BoQ lines through `estimating.public` and confirmed matches through `suppliers.public`. The pure `calc.py` has no imports from either. The router takes the tender lock (`suppliers.lock_tender`, then archive re-check with `fresh=True`, as `api/routers/matches.py` does) and passes DTOs in. `docs/architecture/architecture.md` section 2 and `backend-components.md` are updated in phase 1 (the old `estimating.compute(ctx, tender_id)` becomes a pure `compute`). **(my call)**

**Foreign keys.** `estimate_lines` has composite foreign keys only to `estimates` (and `estimates` to `tenders`). `boq_item_id`, `match_suggestion_id`, `quotation_item_id` and `supplier_id` are plain UUID columns with snapshots: a BoQ re-run, a match cascade or a supplier merge must neither fail nor delete lines of a frozen estimate. F3 checks only foreign keys that exist, so this passes. **(my call)**

Migration `0006_estimates`. All tables carry `organisation_id` with composite foreign keys, like `boq_items` (F3 target-column check applies). Money columns are `Numeric(18,4)` (quantities and unit prices) and `Numeric(18,2)` (rounded amounts). No `float`.

- `pricing_defaults`: organisation_id (primary key), currency (3 letters), vat_rate `Numeric(5,2)`, markup_basis (`cost` or `selling_price`), default_markup_percent `Numeric(6,2)`, updated_by, updated_at. Validation: `vat_rate` 0 to 100; markup 0 to 1000 for `cost`, below 100 for `selling_price`. One row per organisation. Absent until an admin saves it.
- `estimates`: id, organisation_id, tender_id, `version` (unique per tender), status (`draft`, `reviewed`, `approved`), currency, vat_rate, markup_basis, markup_percent (default for lines), `based_on_version` (nullable), totals (`subtotal_cost`, `markup_total`, `subtotal_ex_vat`, `vat_total`, `total_inc_vat`, `NULL` until frozen), `created_by`, `created_at`, `reviewed_by`, `reviewed_at`, `approved_by`, `approved_at`. Partial unique index: one `draft` per tender.
- `estimate_lines`: id, organisation_id, estimate_id, `boq_item_id`, position (BoQ order), section, item_no, description, unit, quantity (snapshots of the BoQ line), `price_source` (`supplier`, `manual`, `excluded`, `unresolved`), `match_suggestion_id` (nullable; the confirmed match chosen), supplier_id and supplier_name snapshot, quotation_item_id, `quoted_unit_price`, `quoted_currency`, `quoted_includes_vat` (true, false or unknown), `unit_price_ex_vat` (the value used), `labour_rate` (nullable), `markup_override_percent` (nullable), `exclude_reason` (nullable), `unit_mismatch_acknowledged`, line amounts (`material_cost`, `labour_cost`, `cost`, `markup`, `total`, nullable while unresolved), `flags` JSONB (`currency_differs`, `currency_missing`, `vat_basis_unknown`, `price_missing`, `quantity_missing`, `unit_missing`, `unreviewed_source`; `source_changed` is computed on read), `input_hash`, `updated_by`, `updated_at`. Unique on (estimate_id, boq_item_id).
- Amounts are computed from the line snapshots; a settings change recomputes every line and is audited. Audit events (existing module): `estimate_created`, `estimate_line_priced`, `estimate_line_excluded`, `estimate_settings_changed`, `estimate_reviewed`, `estimate_reopened`, `estimate_approved`, `estimate_version_created`, `pricing_defaults_changed`. Ids, field names and statuses only; no prices or descriptions beyond what the rows hold.

## 5. Calculation

Pure module `estimating/calc.py`, `Decimal` only, with a test that fails on any `float` in the package.

For each line with a usable quantity and a unit price:

1. `unit_price_ex_vat` = quoted price if the quote is ex VAT; `quoted / (1 + vat_rate/100)` if it includes VAT (stored at 4 decimals, `ROUND_HALF_UP`); a manual price is entered ex VAT by definition.
2. `material_cost = round2(quantity * unit_price_ex_vat)`; `labour_cost = round2(quantity * labour_rate)` (0 when absent); `cost = material_cost + labour_cost`.
3. `markup`: basis `cost`: `round2(cost * pct/100)`; basis `selling_price`: `round2(cost / (1 - pct/100)) - cost`. `pct` = line override else estimate default.
4. `line_total = cost + markup`.

Totals: section subtotals and `subtotal_ex_vat` are sums of line totals; `vat_total = round2(subtotal_ex_vat * vat_rate/100)` ; `total_inc_vat = subtotal_ex_vat + vat_total`. Excluded lines add nothing and are listed with their reason. A line is blocked (`unresolved`, no amounts) when: quantity, unit or price is missing; the unit of the chosen quote item differs from the BoQ unit (read from the 5a evidence warning `unit_mismatch`, so the estimates module needs no unit canonicaliser; acknowledged on selection with `unit_mismatch_acknowledged`); currency differs; VAT basis unknown (resolved once at the source by setting `prices_include_vat` on the quotation with `PATCH /quotations/{id}`, after which the line shows `source_changed` and is refreshed); the quote has no currency (`currency_missing`, resolved the same way); or `price_source` is `unresolved`.

`compute(...)` also returns counts: priced, excluded, unresolved, changed, and the list of blockers by line. Marking reviewed and approving require zero unresolved and zero changed lines.

## 6. API

Flat under `/api/v1`, org-scoped (unknown or other-organisation id is 404, as F1 requires), audit on every write, the 5a tender lock taken in the router (`suppliers.lock_tender`; BoQ corrections take only the per-version `lock_runs`, so the live change check, not the lock, covers them) on writes that read matches or BoQ lines. Archived tenders refuse writes with 409 `tender_archived`.

| Endpoint | Does |
|---|---|
| `GET`/`PUT /pricing-defaults` | Read for `read`; write needs `manage_pricing` |
| `GET /tenders/{id}/estimates` | Versions with status and totals |
| `POST /tenders/{id}/estimates` | Create the first draft from the pricing defaults and the current BoQ (409 `pricing_defaults_missing`, `draft_exists`). Lines start `unresolved`. Allowed whenever no draft exists, so it also serves as "new version". Needs `review_data` |
| `GET /estimates/{id}` | Header, settings and totals (computed live for drafts) |
| `GET /estimates/{id}/lines` | Paged by BoQ order (`limit`/`offset`), each with its confirmed candidates (supplier, item, price, currency, VAT basis, warnings from 5a), chosen source, flags, amounts. Filter: `status` (priced, excluded, unresolved, changed). No price sort or filter by design |
| `PUT /estimate-lines/{id}` | Set source: `{match_suggestion_id}` (must be confirmed and current), or `{manual_unit_price}`, or `{exclude_reason}`; optional `labour_rate`, `markup_override_percent`, `unit_mismatch_acknowledged`. The match must belong to the line's BoQ item. Validation: manual price above 0, quantity above 0, markup within the section 4 ranges. 409 `stale_match` (also when the line's BoQ item is no longer current), `estimate_frozen` |
| `POST /estimate-lines/{id}/refresh` | Re-read the live inputs and clear `source_changed` (the chosen price is re-snapshotted) |
| `PATCH /estimates/{id}` | Currency (only while no line is priced), `vat_rate`, markup basis, default markup, draft only |
| `POST /estimates/{id}/review` / `/reopen` / `/approve` | Status moves. `review` and `reopen` need `review_data`; `approve` needs `approve_estimate` (a project manager can therefore approve but not reopen). Freezing stores totals, reviewer and time. 409 `estimate_not_ready` with the list of blockers, 409 `draft_exists` on reopen |

## 7. Frontend

- **Estimate page** `/tenders/[id]/estimate`, linked from the tender page and navigation: version picker and status badge; a markup-basis choice (on cost or on selling price) beside the markup field; settings card (currency, VAT, default markup); summary (subtotal, markup, VAT, total, counts of unresolved and changed lines, shown as figures with text, never colour alone); BoQ lines grouped by section with each line's candidates as radio-style choices (nothing pre-selected, no cheapest highlight), a manual price field, an exclude control with a required reason, optional labour and markup override; line totals; blockers listed in plain words; "Mark reviewed", "Approve", "New version" buttons shown according to role and state.
- Decimal inputs are text with validation, never `type=number`. Prices are shown as sent with currency and VAT basis (the 5a convention).
- A frozen estimate shows the same page read-only with who reviewed and approved and when. Draft outputs carry a visible "Draft" label (US-05).
- Same optimistic-update, per-row rollback and "replaced by a re-run" handling as the 5a comparison page. Keyboard operable.
- Types from the regenerated `openapi.json` (the equality test stays).

## 8. Testing

- **F7 golden files:** at least three tenders (the committed synthetic packs) with hand-checked totals in committed JSON; exact `Decimal` equality. VAT-inclusive quote conversion, rounding edge cases (half-cent), markup override, labour, excluded lines.
- **Hypothesis properties:** totals independent of line order; adding an excluded line changes nothing; section subtotals sum to `subtotal_ex_vat`; selling-price markup is rejected at 100% or more; `compute` is deterministic; unresolved lines never produce amounts; a VAT-inclusive quote converted at 4 decimals is within quantity x 0.00005 of the exact value.
- **API:** per endpoint and role; frozen estimates refuse every write; one draft per tender under concurrent creates; approve refused with unresolved or changed lines; selecting an unconfirmed, rejected or stale match is refused; extended F1 sweep (register `estimate_id`, `estimate_line_id`; org B owns rows); F3 for the new tables; ban on `float` in `estimating/`.
- **Frontend:** Vitest for no pre-selection, no cheapest highlight, manual and exclude flows, blocked-line wording, role gating, frozen read-only view, decimal validation.
- **Real stack:** the exit-gate journey driven in a browser and recorded in the plan status line.

## 9. Phases (each ends committed and working)

| Phase | Content | Model routing |
|---|---|---|
| 1 Calculation and data | Migration 0006, models, repos, `calc.py`, golden files, Hypothesis tests, float ban | Implementation: Sonnet. Fixtures and golden-file data entry, lint fixes: Haiku. Review: Opus |
| 2 API | Pricing defaults, estimates, lines, status moves, permissions, F1 sweep, `openapi.json` | Routes and schemas: Sonnet. Role and F1 test boilerplate, openapi regeneration: Haiku. Review: Opus |
| 3 Estimate UI | Page, settings, line choices, summary, status actions | Components: Sonnet. Plain-words strings, hook wrappers, simple tests: Haiku. Review: Opus |
| 4 Gate and docs | Real-stack journey, docs, known limitations, plan status | Journey and fixes: Sonnet. Doc edits: Haiku. Final branch review: Opus |

Cut order if time runs short: the `selling_price` basis, then labour rate (both kept in scope at the owner's request, so cut last), then section subtotals. Phases 1 to 3 are the minimum credible demo. Phase 1 also updates architecture.md and the component diagram for the new `estimates` module.

## 10. Risks

- **Wrong money:** the worst failure for a pricing tool. Mitigation: pure `Decimal` code, golden files checked by hand, properties, float ban, frozen approved snapshots.
- **VAT and currency assumptions:** quotes often omit them (`VAT_UNKNOWN`, `NO_CURRENCY`). Mitigation: blocked lines with a user decision, never a default.
- **Stale inputs after approval work starts:** BoQ or quotes edited late. Mitigation: `source_changed` plus the approval gate.
- **Permission change:** two new permissions touch every role test. They need no migration (they live in `ROLE_PERMISSIONS`), but the role matrix test, the F1 request bodies and `openapi.json` change. Mitigation: tests per role in phase 2.
- **Scope:** four phases; the cut order above applies.

## 11. Known limitations this slice will add

One currency per estimate; no conversion of currency, VAT basis or units; no preliminaries, contingency or discounts as concepts; no per-supplier totals comparison; approver may equal reviewer; a scanned quote needs a manual price typed per line (manual quotation entry still does not exist); markup is on cost only.

## 12. Open questions

**Answered by the owner earlier:** markup basis is an option (cost or selling price); the 15% VAT suggestion is fine; the approver may equal the reviewer; labour per line is wanted.

**All four open questions were answered by the owner (2026-10-22):** VAT is always on (no off mode); provisional-sum and rate-only lines are excluded only; unreviewed BoQ lines and quotation items block approval; the highest approved version is the approved estimate for export.

## 13. Review log

An Opus builder check (2026-10-22) found: a module cycle (estimating cannot import suppliers; fixed by the new `estimates` module), foreign keys that would break BoQ re-extraction and supplier merges (fixed: plain UUID columns plus snapshots), an incomplete change-detection rule, a `Decimal` context risk, the labour and material split, the reopen-with-two-drafts hazard, missing validation ranges and an undefined `row_replaced`. All are addressed above. It suggested cutting labour and carry-over of choices into a new version: labour stays at the owner's request, carry-over is deferred.
