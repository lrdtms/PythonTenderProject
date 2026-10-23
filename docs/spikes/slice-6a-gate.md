# Slice 6a gate: exports

Date: 2026-10-23. Branch `feat/slice-6a-exports` (based on `feat/slice-5b-estimate`). Gate run at commit `b917d37`, with the working tree clean; the gate run changed no code or docs. The gate was measured at `b917d37`, before the final-review fix wave (see "Defects found and fixed"); the figures below describe that commit, not the fix-wave commits. The stack was rebuilt with `docker compose up -d --build`, and the app was driven through Caddy at http://localhost:8080 in Chrome (one tab, closed at the end). All data is synthetic. Downloaded files were read as untrusted data in a scratch folder with `python -I`.

Exit-gate items 1 to 5 PASS on the real stack. Two checks are weaker than the spec asks: the Excel check (item 4) was made by reading the XML only, because no spreadsheet application was installed, and the PDF (item 3) was checked with PyMuPDF only, not a desktop viewer.

## Gate steps

| Step | Spec section 1 item | Result | Evidence |
|---|---|---|---|
| 1. Rebuild and migrate | (setup) | PASS | `/api/v1/health` returned `{"status":"ok"}` and `/api/v1/health/db` returned `{"status":"ok","database":"reachable"}`. `alembic_version` is `0007`. The `exports` table exists with columns id, organisation_id, tender_id, kind, estimate_id, estimate_version, label, file_key, file_name, content_type, file_size, sha256, row_count, generated_by, generated_at. The api and worker logs (`--since 90m`) had 0 lines matching Traceback, ERROR or 5xx. |
| 2. Approved estimate workbook | 1 | PASS | "Download Excel" on approved v2 gave `greenvale-hall-electrical-gate-estimate-v2-20261023.xlsx`. No DRAFT in the name, title, banner, header or Status cell (Status "Approved"). Summary equals the page and the API to the cent: subtotal cost 504166.00, markup 50416.60, ex VAT 554582.60, VAT 83187.39, total 637769.99; 17 priced, 3 excluded, 0 unresolved, 0 changed. A Decimal comparison of every priced line (material, labour, cost, markup, total) against `/estimates/{id}/lines` found 0 mismatches over 20 lines; line totals sum to 554582.60. No `<f>` formula elements in either sheet. |
| 3. Draft version marked DRAFT | 2 | PASS | Before the click the page shows "This file will be marked DRAFT because version 3 is not approved." and the button reads "Download Excel (DRAFT)". File `...-estimate-v3-DRAFT-20261023.xlsx`: document title "DRAFT: Tender estimate: ...", banner row "DRAFT: version 3 is not approved. Do not submit." on Summary and Lines, print header with the same text on both sheets, Summary Status "Draft", Approved by "Not approved". Screen figures 1546.89 / 154.69 / 1701.58 / 255.24 / 1956.82 equal the workbook. A "reviewed" (not approved) version was not exercised in the browser (see Not covered). |
| 4. Checklist PDF | 3 | PASS (PyMuPDF only) | Before the click the page shows "9 requirements are not reviewed yet. The report will list them separately and be marked DRAFT.", and this stayed visible with the Review-status filter set to Corrected (unreviewed rows hidden on screen). "Download PDF report" gave `greenvale-hall-electrical-gate-checklist-DRAFT-20261023.pdf`, served as an attachment. The PDF was opened with PyMuPDF (text extraction and a rendered PNG viewed): DRAFT watermark and red banner, summary table by type, groups by type with mandatory flag, review status and source "tender.pdf, page N", a separate "Not yet reviewed (9)" section, one row "page not recorded (source not verified)", footer and export id. After all 9 rows were confirmed through the API, a new PDF (`...-checklist-20261023.pdf`) has no DRAFT text and "0 not yet reviewed". No desktop PDF viewer was opened. |
| 5. Hostile strings inert | 4 | PASS (XML only) | BoQ A1 description set to `=HYPERLINK("http://x","click")` and a supplier renamed to `+HYPERLINK("http://x","sup")`. The estimate line was refreshed (the BoQ edit alone did not reach the estimate) and the workbook downloaded through the page. Cells Lines!D3 and Lines!G14 are `t="inlineStr"` with the text `'=HYPERLINK(...)` and `'+HYPERLINK(...)` (leading apostrophe added by the safe-text funnel); zero `<f>` elements. The requirement text `Hostile <img src="file:///etc/passwd"/> & <b>bold</b> test` appears literally in the PDF text and in the rendered PNG. Excel is not installed (the Microsoft Office folder holds only Appx stubs; no LibreOffice), so no application confirmed the inert behaviour. |
| 6. Permissions and immutability | 5 | PASS | Reviewer: create xlsx 403, create pdf 403, download 403, metadata GET 200. Other organisation: create xlsx and pdf 404, GET metadata 404, download xlsx and pdf 404. No session: download 401, create 401. Estimator create 201; project manager download 200. Admin create with an `estimate_id` from another tender 404. Exports made before the edits were re-downloaded after the BoQ edit, supplier rename, line refresh, requirement edit and confirmations: v2 export 4666c604, v3 draft export 8a4583a7 and pre-edit export 09e408e6 all returned the same SHA-256 as `exports.sha256`. Reviewer, other-organisation and no-session checks were made with curl, not in the browser UI. |
| 7. Automated suite | 6 | PASS (local commands) | See the automated checks table below. F1, F3 and the openapi drift check are covered by the full pytest run; lint-imports reported 5 contracts kept. No CI run is recorded in the evidence; the local commands are the CI equivalents. |

### Download headers

All five files (curl with the session cookie, with and without `Accept-Encoding: gzip`) returned `200` with `Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: sandbox`, `Content-Disposition: attachment; filename="<name>"` matching `exports.file_name`, and `Content-Length` equal to `file_size`. Content-Type was `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` for xlsx and `application/pdf` for the PDFs. No `Content-Encoding` header was returned even when gzip was requested, so Caddy did not compress these types. The "gzip does not corrupt" check therefore shows the bytes are unchanged through Caddy, not that compression was applied and decoded.

SHA-256 of the bytes (with and without gzip requested) and of the Chrome-saved copy equal `exports.sha256` for each file:

| Export | sha256 (first 12) |
|---|---|
| v2 approved xlsx 4666c604 | 10eb78c1b195 |
| v3 draft xlsx 8a4583a7 | 77b33c36598a |
| v3 draft xlsx 09e408e6 (curl-created) | 4c8c1e5514ec |
| v3 draft xlsx 8b708803 (post-supplier-edit, pre-refresh) | 59393a14e5c8 |
| v3 draft xlsx 093d5b6e (hostile strings) | 5be8e0a85bbc |
| checklist PDF a2237979 (draft) | 2b84631a084c |
| checklist PDF 26954165 (clean) | not recorded in this table; same method used, bytes parsed |

Chrome-saved copies were checked for the first, second, fourth, fifth and the draft PDF. Export 09e408e6 and the clean PDF were fetched with curl only.

### Timing

| Measurement | Result | Note |
|---|---|---|
| POST create, 20-line draft estimate workbook (curl, through Caddy) | 0.28 s | Docker stack |
| Clean checklist PDF, 10 rows (curl, through Caddy) | 0.28 s | Docker stack |
| `test_f11_estimate_workbook_of_1000_lines_is_fast` | 3.61 s call (limit 10 s) | Backend test, not a Docker-stack measurement |
| `test_f11_checklist_pdf_of_1000_requirements_is_fast` | 2.34 s call (limit 10 s) | Backend test, not a Docker-stack measurement |

## Automated checks

Run at commit `b917d37`.

| Command | Result |
|---|---|
| `DB_HOST_PORT=5433 uv run pytest -q` (backend) | 1089 passed, 1 warning (starlette/httpx deprecation), 0 failed, 560 s |
| `uv run ruff check` | All checks passed |
| `uv run ruff format --check` | 201 files already formatted |
| `uv run lint-imports` | Contracts: 5 kept, 0 broken |
| `uv export --no-dev --no-hashes --no-emit-project` then `uvx pip-audit -r ... --no-deps --disable-pip` (path elided in the evidence file) | No known vulnerabilities found (reportlab is in the exported file) |
| `npm run lint` | clean |
| `npm run typecheck` | clean (exit 0) |
| `npm run build` | succeeded (output tail inspected; no error lines) |
| `npx vitest run` (frontend) | 50 test files passed, 602 tests passed |
| PRD and architecture wording | `docs/prd.md` FR-62 and line 211, and `docs/architecture/architecture.md` lines 39 and 172, carry the draft-labelling and `create_export(... payload ...)` wording |

The backend suite uses its own test database; the gate data in the app database was intact afterwards (8 export rows).

## Defects found and fixed

The gate run itself made no code changes and no commits. The final whole-branch review that followed found two defects that bear on gate items 2 and 3, both fixed in the fix wave (frontend commit d27be3f):

- I1: the pre-click DRAFT note and the error text had no dark-theme colour (the "very dim" note seen in the gate). The note is now amber with a `dark:` variant, the error has a `dark:` variant.
- I2: the export button kept its state across a version switch, so after downloading an approved version and switching back to a cached draft version the DRAFT note was hidden and the other version's "Downloaded" line showed. The button is now keyed by estimate id.

The same wave also did the recommended items M1, M2, M5, M8, M9, M10 and M12 (backend commit 139d402). After the wave, only automated checks were re-run (not the browser gate steps): backend ruff check, ruff format --check, lint-imports and the full pytest run; frontend lint, typecheck, the full vitest run (50 files, 607 tests) and the production build. The real-stack browser steps were not repeated, so the dark-theme appearance of the note was verified by a class assertion in a unit test, not by eye.

## Observations not fixed

- (Fixed after the gate, see above: the dim pre-click DRAFT note on the dark theme.)
- A BoQ line text edit does not mark an estimate line "Source changed"; the line stayed "Priced". The text reaches the estimate only on Refresh. This is existing Slice 5b behaviour, and it affects when hostile text reaches an export.

## Not covered

- Excel, or any spreadsheet application, was not available. Workbooks were checked by reading the XML and with openpyxl only, so Excel's behaviour on the apostrophe-prefixed strings, the print header rendering and the auto-filter was not observed.
- No desktop PDF viewer was opened; the PDF was checked with PyMuPDF text extraction and a rendered image.
- A "reviewed" (not approved) estimate version was not exported; draft only. The reviewed label path is covered by backend tests, not by this gate.
- The browser journey did not click Download for the clean PDF (no unreviewed rows) or for the hostile workbook beyond the draft. The clean PDF was created through the API with curl.
- Reviewer, other-organisation and unauthenticated checks were made with curl, not in the browser UI. The reviewer's view of the export buttons was not inspected.
- The rate limit (10 exports per 60 s) was not exercised through the real stack. The 1,000-line figure comes from the test suite, not the stack.
- Console messages for the early part of the journey (the console tool only tracked from its first call, near the end of the journey), keyboard operability and mobile layout.
- Caddy gzip: no Content-Encoding was added, so compression was not exercised (see Download headers).

## Local test data left behind

In the local Docker database (not committed):

- Organisation "Gate5b Org": the four 5b users' passwords were reset to one synthetic value (local data change).
- Estimate v3 (draft) on the Greenvale tender, with lines A1 (manual price, labour rate), B1 (manual), A2 (excluded) and C6 (supplier priced).
- BoQ item A1 description changed to the `=HYPERLINK` string.
- Supplier "Greenvale Cable and Conduit" renamed to `+HYPERLINK("http://x","sup")`. This also changes its name in other estimates' refreshed lines.
- Requirement "Certificate of compliance..." description replaced with the `<img>` string.
- All 10 tender requirements confirmed or corrected.
- 8 or more export rows (with stored files) and audit rows.
- New organisation "Gate6a Other Org" with user gate6a+other@example.com.

In Chrome's Downloads folder: five `greenvale-hall-electrical-gate-*.xlsx` copies and one checklist PDF. Scratch files are under the session scratchpad. Nothing was pushed.
