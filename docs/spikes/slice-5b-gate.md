# Slice 5b gate: the estimate

Date: 2026-10-22. Branch `feat/slice-5b-estimate`, gate run at HEAD 81809e4. The stack was rebuilt with `docker compose up -d --build`; `/health` and `/health/db` returned ok, `alembic_version` was 0006 and the `pricing_defaults` table existed. No Traceback, ERROR or 5xx appeared in the api or worker logs.

The journey was driven in Chrome through Caddy. Pack02 was used because pack01 has only one quotation (tender.pdf and quotation_1_voltline), and the gate needs two. All data is synthetic. Upload, extraction and requirements extraction each finished within seconds. Tender requirements: 10, with one warning ("1 could not be matched to page text").

## Gate steps

| # | Step | Result | Evidence |
|---|---|---|---|
| 1 | Create estimate, all lines, candidates side by side, nothing pre-selected | PASS | 20 lines in BoQ order grouped by section, all "Unresolved", candidates side by side on 10 lines, no radio selected, "Use this price" disabled until one is chosen. Summary "Incomplete: excludes 20 lines". |
| 2 | Price lines (supplier and manual), exclude one, totals match hand arithmetic | PASS | Partial set checked by hand (for example B1 54917 x 2 = 109834.00, markup 10983.40). Full estimate with 17 priced and 3 excluded: an independent Python Decimal calculation gave total 539339.71, identical to the screen. |
| 3 | Blocked line when VAT basis is unknown | PASS | Greenvale quote "VAT not stated": the line stayed Unresolved, with amounts empty and excluded from totals. Setting the quotation header to "exclude VAT" turned the lines "Source changed"; Refresh then gave priced lines (C6 53 x 1075 = 56975.00). |
| 4 | Source changed after pricing; review refused until refresh | PASS | BoQ quantity edit made a line "Source changed" and dropped it from totals. "Mark reviewed" was refused until the changed line was refreshed; Mark reviewed with 14 unresolved lines was also refused. |
| 5 | Review, approve, reload, frozen, New version | PASS | Approve needed the inline confirm. After reload, version 1 showed "Approved" with reviewer and approver names and no line controls. Writes on the approved estimate returned 409 `estimate_frozen`. "New version" created a version 2 draft; version 1 stayed approved. |
| 6 | Roles | PASS | Reviewer: no controls, writes 403. Estimator: can mark reviewed, no Approve, approve API 403. Project manager: can approve, no Reopen or New version on the reviewed version. |
| 7 | Console errors and UX defects | PASS with caveat | No console messages, but the console tool only recorded from its first call late in the journey. No 5xx or tracebacks in the logs. Two UX defects were found (below). |

## Automated checks

Run after the browser journey, at commit 81809e4:

| Command | Result |
|---|---|
| `uv run pytest` (backend, `DB_HOST_PORT=5433`) | 863 passed, 0 failed |
| `uv run ruff check`, `ruff format --check`, `lint-imports` | clean; 2 contracts kept |
| `npm run lint`, `npm run typecheck`, `npm run build` | clean |
| `npx vitest run` (frontend) | 46 files, 528 tests passed |

These counts were measured before the two UX fixes below. After those fixes only the touched backend and frontend test files were re-run: backend estimate API, races, calc, store, fitness-function and OpenAPI tests (107 passed), plus ruff, ruff format and lint-imports; frontend app, words and API tests (308 passed), plus lint, typecheck and build. No full-suite run was done after the fixes.

## Defects found and fixed

1. **Generic, repeated blockers.** "Mark reviewed" listed 14 identical "Some lines still have no price" rows with no line label. Fixed in `3b9d8b0`: each blocker names its line (item no and description) and its reason, and the list shows the first 10 and then "and N more".
2. **Stale numbers on a changed line.** A line marked "Source changed" still showed its old quantity and total next to the badge. Fixed in `ebe2b44`: the quantity and amounts are labelled "(old)", dimmed, and the total is marked "not counted until refreshed".

Not fixed, recorded in [known-limitations.md](../known-limitations.md): the "Reopen" and "New version" wording on a reviewed estimate, and the Slice 5a "Confirm all clear matches" skip for cable-notation rows.

## Not covered

- Currency-differs and currency-missing blocked cases (the pack did not produce them).
- Labour rate and markup override fields, the "selling price" markup basis, settings (currency, VAT, markup) changes in the UI.
- The unit-mismatch acknowledgement checkbox.
- "Reopen" in the browser; the approve API on a never-reviewed draft.
- A quotation-price edit as the source-change trigger (BoQ quantity edits were used).
- Second-organisation isolation in the browser (covered by the backend suite).
- Keyboard operability and mobile layout.
- Console messages for the earlier part of the journey.

## Local test data

The gate data stays in the local Docker database and is not committed: organisation "Gate5b Org", tender "Greenvale Hall Electrical (gate)", four users, and estimates version 1 (approved) and version 2 (approved). Nothing was pushed.
