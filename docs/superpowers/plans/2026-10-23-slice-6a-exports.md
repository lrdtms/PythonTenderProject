# Slice 6a: Exports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export an estimate version to a Decimal-exact Excel workbook (DRAFT-marked unless approved) and a tender's requirement checklist to a PDF report, stored through the storage port, recorded in an `exports` table, and served through an authenticated same-origin download, with Export buttons on the estimate and checklist pages.

**Architecture:** The `reporting` module (today an empty stub) holds the `exports` table, pure renderers (`xlsx.py`, `pdf.py`) that take plain input dataclasses, a single funnel for user text (`safe_text.py`), and a service that renders, stores, records and audits. As in 5b, `reporting` imports no module except `audit` (plus `kernel` and `db`); a new router `app/api/routers/exports.py` reads the estimate, tender, member names, requirements and document titles through the other modules' public APIs and maps them to the input dataclasses. Generation is synchronous in the request (spec D6). A Next.js `ExportButton` component is used by the estimate page and the checklist page.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres, openpyxl 3.1.5 (present), ReportLab 5.1.0 (new), pytest, Hypothesis, import-linter, ruff; Next.js, TypeScript, Vitest, openapi-typescript (`npm run gen:api`).

**Spec:** `docs/superpowers/specs/2026-10-23-slice-6a-exports-design.md` (read it first; "D" numbers below are its decisions).

## Global Constraints

- Money is `Decimal`, never `float`. Every Excel amount cell is a `Decimal` taken from a stored value or from the estimate DTO; **no Excel formulas anywhere**; `reporting` never recomputes a total, line amount or VAT (D10). A test fails on any `float` token in `reporting/xlsx.py` and `reporting/schemas.py`. **openpyxl stores numbers as `%.16g` of a float** (verified: `Decimal("8.174")` is stored as `8.173999999999999`), so the normative rule (spec D10) is: a value with at most 15 significant digits, counted on `value.normalize()`, is a numeric cell and is exact as Excel loads and displays it (15 digits); anything longer is an inline text cell. Tests assert the 15-digit display value, never `Decimal(raw_xml) == expected`.
- Every user-controlled string reaches Excel only through `safe_text.xlsx_text` and the PDF only through `safe_text.pdf_text` (D11, D12). No hyperlink cell, no `Paragraph` built from raw text.
- A non-approved estimate export is marked DRAFT in every place listed in D1; an approved one in none of them. The only labels are the FR-62 statuses `draft`, `reviewed`, `approved`; a checklist report is `approved` only when every non-rejected requirement is reviewed (D3).
- Files go through `StoragePort` with the server-built key `org/{organisation_id}/tenders/{tender_id}/exports/{export_id}.{ext}`; the client never supplies a key or filename; the file is deleted if the transaction rolls back (D13).
- Permissions: create and download need `Permission.EXPORT`; metadata needs `READ`. No new permission and no role-matrix change (D5).
- `exports` carries `organisation_id` with composite foreign keys (F3); every new route with an id is in the F1 sweep; another organisation always gets 404, never 403.
- Modules import each other only through `public.py`; `reporting` imports only `kernel`, `db` and `audit`; the renderers import neither `sqlalchemy` nor `fastapi` nor `app.db`.
- Ruff line length 100. Decimals travel in JSON as strings.
- Model routing: **Haiku** = mechanical (golden data entry, corpora, word tables, boilerplate, regeneration, doc edits); **Sonnet** implements the rest; **Opus** reviews every task and does the final branch review. Before each commit that touches them run, in `backend/`: `uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run pytest -q` (set `DB_HOST_PORT` as in earlier slices), and in `frontend/`: `npm run lint && npm run typecheck && npm run build && npx vitest run`.
- Do not claim a check that was not run. Anything not run is listed under "Not covered" in the gate note.

## Review Focus

1. **Screen equals file.** Every figure in the Summary and Lines sheets equals the DTO value the estimate page shows, compared as the 15-significant-digit value Excel displays (spec D10), for a VAT-inclusive quote, a labour line, a markup override and a half-cent line (Task 3).
2. **Draft cannot pass as approved.** A draft or reviewed export has all five markings plus the filename suffix; an approved one has none; the pre-click wording on the page matches (Tasks 3, 7, 10).
3. **Injection.** Formula starters in every text field, XML-illegal control characters, 40,000-character strings, and PDF markup (`<img src="file:///...">`, `<a href>`, `<font>`) are inert (Tasks 2, 3, 4).
4. **Tenancy.** Another organisation gets 404 on create (foreign tender or foreign `estimate_id`), metadata and download, with no leak of the tender title or file name; the download resolves the file only from the organisation-scoped row, never from client input (Tasks 7, 8).
5. **Frozen means frozen.** Exporting an approved version before and after BoQ and quotation edits gives identical cells; a draft export honestly shows "Source changed" (Task 7).
6. **Performance and failure.** 1,000 lines under 10 s through HTTP; the caps and the rate limit hold; a failure after the file is stored leaves no orphan file and no row (Tasks 6, 8).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/db/stored_files.py` | `delete_on_rollback(session, storage, key)` shared by documents and reporting |
| `backend/app/api/estimate_inputs.py` | `current_boq`, `live_inputs`, `boq_inputs` moved out of `routers/estimates.py` so exports can reuse them |
| `backend/app/modules/estimates/service.py`, `public.py` | New `export_snapshot(session, ctx, estimate_id, live)` |
| `backend/app/modules/reporting/models.py` | `Export` ORM model |
| `backend/app/modules/reporting/repo.py` | `ExportRepo` |
| `backend/app/modules/reporting/schemas.py` | `ExportCreate`, `ExportDTO`, input dataclasses |
| `backend/app/modules/reporting/safe_text.py` | `xlsx_text`, `xlsx_header_text`, `pdf_text`, `pdf_plain`, `export_filename` |
| `backend/app/modules/reporting/words.py` | Plain-words vocabulary |
| `backend/app/modules/reporting/xlsx.py` | `render_estimate_xlsx` |
| `backend/app/modules/reporting/pdf.py` | `render_checklist_pdf` |
| `backend/app/modules/reporting/service.py`, `public.py` | `create_export`, `get_export`, `open_export_file` |
| `backend/app/api/routers/exports.py` | The three routes and the mapping to inputs; registered in `app/api/main.py` |
| `backend/migrations/versions/0007_exports.py` | Table `exports` |
| `backend/tests/test_reporting_safe_text.py`, `test_reporting_xlsx.py`, `test_reporting_pdf.py`, `test_reporting_store.py`, `test_reporting_service.py`, `test_exports_api.py`, `test_exports_perf.py` | Tests |
| `backend/tests/fixtures/exports/golden_estimate.json`, `injection_corpus.json` | Golden cell values; hostile strings |
| `backend/pyproject.toml`, `backend/uv.lock` | `reportlab` dependency; new import-linter contracts |
| `frontend/src/api/exports.ts`, `frontend/src/lib/export-words.ts`, `frontend/src/components/export-button.tsx` (+ tests) | Hooks, plain words, the button |
| `frontend/src/app/(app)/tenders/[id]/estimate/estimate-view.tsx`, `.../checklist/checklist-view.tsx` (+ tests) | Button placement and wording |
| `docs/prd.md`, `docs/architecture/architecture.md`, `docs/plan.md`, `docs/known-limitations.md`, `docs/spikes/slice-6a-gate.md` | Documentation |

---

### Task 1: Shared plumbing and the approved-only wording (Sonnet; Haiku doc edit; Opus review)

**Files:**
- Create: `backend/app/db/stored_files.py`, `backend/app/api/estimate_inputs.py`
- Modify: `docs/prd.md` (section 10 step 8 and FR-62), `docs/architecture/architecture.md` (reporting row line 39 and Contracts line 172), `backend/app/modules/documents/service.py` (use the shared helper), `backend/app/api/routers/estimates.py` (import from `estimate_inputs`), `backend/app/modules/estimates/service.py`, `backend/app/modules/estimates/public.py`
- Test: `backend/tests/test_transactions.py` (existing, must stay green), `backend/tests/test_estimates_api.py` (add one test)

**Interfaces:**
- Produces: `delete_on_rollback(session: Session, storage: StoragePort, key: str) -> None` (the body of today's `documents.service._delete_on_rollback`, same `session.info` key and listeners). `estimate_inputs.current_boq(session, ctx, tender_id) -> tuple[list[BoqItemDTO], list[UUID]]`, `estimate_inputs.boq_inputs(boq) -> list[estimates.BoqInput]`, `estimate_inputs.live_inputs(session, ctx, tender_id) -> estimates.LiveInputs` (the bodies of `_current`, `_boq_inputs`, `_live`, moved together with the `PAGE` constant and the `_decimal` helper they depend on). `estimates.export_snapshot(session, ctx, estimate_id, live) -> tuple[EstimateDTO, list[EstimateLineDTO]]`: the estimate DTO and all its lines in BoQ order, both built from one `_lines_of` pass over the same rows (`READ`; for a non-draft estimate `live` is ignored, so callers pass an empty `LiveInputs()`). One call, so totals and lines cannot come from different moments.
- Consumes: the existing functions above; `StoragePort` from `app.kernel`.

- [ ] **Step 1: Write the failing tests** in `test_estimates_api.py` and `test_estimates_races.py`: `estimates.export_snapshot` on a created estimate returns every line in position order (same ids and order as `list_lines(..., limit=1000, offset=0)`) and an estimate DTO whose counts match those lines; on an approved estimate called with `LiveInputs()` it returns the stored statuses, stored totals and no candidates; a race test in the style of `test_estimates_races.py`: with the tender lock held by one transaction that reopens a reviewed estimate and prices a line, a second transaction calling the lock-then-`export_snapshot` sequence either sees the reviewed state entirely or the draft state entirely (totals and lines agree), never a mix.
- [ ] **Step 2: Run** `uv run pytest tests/test_estimates_api.py tests/test_estimates_races.py -q -k export_snapshot`; expected FAIL (no attribute).
- [ ] **Step 3: Implement `export_snapshot`** as `rows = _lines_of(repo, est, live); return _estimate_dto(est, rows), [dto for _, dto in rows]` after `ctx.require(Permission.READ)`; export it from `public.py`.
- [ ] **Step 4: Move the helpers.** Create `stored_files.py` with the function moved verbatim (rename to public, keep the log message), have `documents/service.py` call it. Create `estimate_inputs.py` with the three helpers moved verbatim and update `routers/estimates.py` to import them. `app/db` and `app/api` may import `app.kernel`; `estimate_inputs` imports only module `public`s.
- [ ] **Step 4a (Haiku): Reword the documents (Ruling, spec section 11a).** `docs/prd.md` section 10 step 8: "Export any estimate version. A version that is not approved is clearly labelled DRAFT"; FR-62: add "Checklist reports have no version and carry `draft`, or `approved` when every non-rejected requirement has been reviewed by a person". `docs/architecture/architecture.md` lines 39 and 172: replace "approved-only unless labelled draft" / "Approved-only content" with the same wording. Do not change anything else in those files yet (Task 8 adds the signature and storage-key text).
- [ ] **Step 5: Run the whole backend suite** plus `uv run lint-imports`; expected PASS with the same counts as before the move plus the new test (the move must change no behaviour).
- [ ] **Step 6: Commit** `refactor: share delete_on_rollback and the estimate live-input readers`.

### Task 2: Dependency and the text-safety funnel (Sonnet; corpus Haiku; Opus review)

**Files:**
- Modify: `backend/pyproject.toml` (add `"reportlab>=5.1.0"`), `backend/uv.lock`
- Create: `backend/app/modules/reporting/safe_text.py`, `backend/app/modules/reporting/words.py`, `backend/tests/fixtures/exports/injection_corpus.json`, `backend/tests/test_reporting_safe_text.py`

**Interfaces:**
- Produces (`safe_text.py`):
  - `xlsx_text(value: str | None, limit: int = 32_000) -> str`: removes characters outside the XML 1.0 range (the set openpyxl rejects: `\x00-\x08`, `\x0b`, `\x0c`, `\x0e-\x1f`), truncates the cleaned text to `limit - 4` characters (adds `...` when cut) so the final result, prefix included, is at most `limit`, then, on the cleaned text, if `text.lstrip(" \t\r\n")` starts with `=`, `+`, `-` or `@`, or the text starts with `\t` or `\r`, returns `"'" + text`. `None` gives `""`.
  - `xlsx_header_text(value: str | None, limit: int = 60) -> str`: for Excel print headers and footers: strips the same control characters, doubles every `&` (a literal ampersand in header/footer syntax), truncates to `limit`. Callers assemble each header or footer section from fixed codes plus this output and keep it under 255 characters.
  - `pdf_plain(value: str | None, limit: int = 300) -> str`: for canvas text and PDF metadata (not markup): strips control characters, truncates, replaces characters `cp1252` cannot encode with `?`, no escaping.
  - `pdf_text(value: str | None, limit: int = 2_000) -> str`: strips control characters, truncates (when cut, the text ends with `... (truncated, see source)` and the whole result still fits `limit`), replaces every character that `cp1252` cannot encode with `?`, then XML-escapes `&`, `<`, `>` (so the result is safe inside `Paragraph`).
  - `export_filename(tender_title: str, kind: str, version: int | None, draft: bool, on: date) -> str`: ASCII letters, digits and hyphens; title slug at most 40 characters (`tender` when empty); `{slug}-estimate-v{version}[-DRAFT]-{YYYYMMDD}.xlsx` or `{slug}-checklist[-DRAFT]-{YYYYMMDD}.pdf`; never contains a quote, slash, backslash, space, control character or a leading dot.
  - `words.py`: dicts and functions `flag_text(code) -> str` (every flag the estimates module can emit: `currency_differs`, `currency_missing`, `vat_basis_unknown`, `price_missing`, `quantity_missing`, `unit_missing`, `unit_mismatch`, `unreviewed_source`, `source_changed`; unknown code returns "Needs attention"), `markup_basis_text`, `vat_basis_text(bool | None)`, `estimate_status_text`, `review_status_text`, `mandatory_text`, `price_source_text`.
- Consumes: nothing.

- [ ] **Step 1 (Haiku): Corpus.** `injection_corpus.json`: a list of strings including `=1+1`, `+SUM(A1:A9)`, `-2+3`, `@SUM(1)`, `\t=1+1`, `\r=1`, ` =cmd|' /C calc'!A0`, `=HYPERLINK("http://example.com","click")`, `=1+1` preceded by four spaces, a 40,000-character string, a string with `\x00`, `\x0b`, `\x1f`, `<script>alert(1)</script>`, `<img src="file:///etc/passwd"/>`, `<a href="http://x">y</a>`, `<font color=red>x</font>`, `&amp; & <`, a Zulu/Afrikaans accented sample (`Ngiyabonga, môre, ê, ü`), `≤ 5 Ω`, an emoji, an ordinary "Cable 4mm2", and header/footer cases `A & B`, `&Z&F`, `&"Arial,Bold"x` and a 300-character title.
- [ ] **Step 2: Write failing tests** in `test_reporting_safe_text.py`: for every corpus string, `xlsx_text` output (a) contains no character in the illegal set, (b) is at most 32,000 characters including any prefix, (c) starts with `'` exactly when the rule says so, (d) is accepted by openpyxl when assigned to a cell and saved (no exception). `pdf_text` output: contains no raw `<` or `>` except as `&lt;`/`&gt;`, the `<img ...>` sample contains no `<img`, `≤`/emoji become `?`, `môre` stays intact, and `reportlab.platypus.Paragraph(pdf_text(s), style)` constructs without raising for every sample. `xlsx_header_text`: `A & B` becomes `A && B`, `&Z&F` becomes `&&Z&&F`, a 300-character title is cut to 60, no single `&` remains. `pdf_plain`: `Smith & Sons` stays `Smith & Sons`, `≤` becomes `?`. A 5,000-character requirement through `pdf_text` ends with the truncation marker. `export_filename`: table of titles (`"Greenvale Hall / Phase 2"`, `'x"; rm'`, `"../../etc"`, empty, 200 characters, non-ASCII) all match `^[A-Za-z0-9][A-Za-z0-9.\-]*$` and end with the right extension; `-DRAFT` present exactly when `draft=True`. `words`: each of the nine flag codes has a non-empty sentence not equal to the fallback; a test collects, from `backend/app/modules/estimates/service.py`, the string keys assigned as `flags["..."] = True` or returned by `_blockers`, the strings in `out.append("...")` inside `_warnings`, and the strings in `flags.append("...")` inside `_line_dto`, and fails if any of them has no word (the collection must find at least the nine known codes, so the test cannot pass vacuously).
- [ ] **Step 3: Run;** expected FAIL.
- [ ] **Step 4: Add the dependency.** In `backend/`: `uv add reportlab` (expect `reportlab 5.1.0`, `charset-normalizer` already locked, pillow stays 13.0.0). Run `uv export --frozen --no-dev --no-hashes --no-emit-project -o <scratch>/req.txt` then `uvx pip-audit -r <scratch>/req.txt --no-deps --disable-pip`; expected "No known vulnerabilities found". If the audit reports one, stop and record it instead of pinning around it.
- [ ] **Step 5: Implement** `safe_text.py` and `words.py`.
- [ ] **Step 6: Run** the new tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 7: Commit** `feat: reportlab dependency and the export text-safety funnel`.

### Task 3: Excel renderer with golden file (Sonnet; golden data Haiku; Opus review)

**Files:**
- Create: `backend/app/modules/reporting/schemas.py` (inputs only in this task), `backend/app/modules/reporting/xlsx.py`, `backend/tests/fixtures/exports/golden_estimate.json`, `backend/tests/test_reporting_xlsx.py`
- Modify: `backend/app/modules/reporting/__init__.py` (stays a docstring)

**Interfaces:**
- Produces (`schemas.py`, frozen dataclasses):
  - `ExportTotals(subtotal_cost, markup_total, subtotal_ex_vat, vat_total, total_inc_vat: Decimal)`
  - `ExportLine(position: int, section: str | None, item_no: str | None, description: str, unit: str | None, quantity: Decimal | None, price_source: Literal["supplier","manual","excluded","unresolved"], supplier_name: str | None, quoted_unit_price: Decimal | None, quoted_currency: str | None, quoted_includes_vat: bool | None, unit_price_ex_vat: Decimal | None, labour_rate: Decimal | None, material_cost: Decimal | None, labour_cost: Decimal | None, cost: Decimal | None, markup_percent: Decimal | None, markup: Decimal | None, total: Decimal | None, status: Literal["priced","excluded","unresolved","changed"], flags: tuple[str, ...], exclude_reason: str | None)`
  - `EstimateExportInput(tender_title, tender_reference, client_name: str | None, version: int, status: Literal["draft","reviewed","approved"], currency: str, vat_rate: Decimal, markup_basis: Literal["cost","selling_price"], markup_percent: Decimal, totals: ExportTotals | None, priced: int, excluded: int, unresolved: int, changed: int, incomplete: bool, reviewed_by_name: str | None, reviewed_at: datetime | None, approved_by_name: str | None, approved_at: datetime | None, generated_by_name: str, lines: tuple[ExportLine, ...], generated_at: datetime | None = None, export_id: UUID | None = None)` (the service fills the last two with `dataclasses.replace`; the renderer asserts they are set).
- Produces (`xlsx.py`): `render_estimate_xlsx(data: EstimateExportInput) -> bytes`; `SUMMARY_SHEET = "Summary"`, `LINES_SHEET = "Lines"`, `LINE_COLUMNS: tuple[str, ...]` (the 21 header texts of spec section 5, in order), `is_draft(status) -> bool`.
- Consumes: `safe_text.xlsx_text`, `words.*`.

- [ ] **Step 1 (Haiku): Golden file.** `golden_estimate.json`: an input (8 lines in three sections) and the expected output. Lines: a supplier line (quote ex VAT), a supplier line with a VAT-inclusive quote (quoted 115.0000, ex VAT 100.0000 at 15%), a labour line with a markup override, a half-cent line (qty 1, price 0.0050, material 0.01), a manual line, an excluded line with a reason, an unresolved line (flags `vat_basis_unknown`), a changed line. Totals by hand from the 5b rules (reuse figures from `tests/fixtures/estimates/golden_a.json` where possible and say so in a `_comment`). Expected: for each of the two sheets, a map of cell address to `{value, number_format}` for every non-empty cell, with amounts as decimal strings. Fixed `generated_at` (2026-10-23T12:00:00Z) and `export_id`.
- [ ] **Step 2: Write failing tests** in `test_reporting_xlsx.py`:
  - **Golden:** render the golden input; open with `openpyxl.load_workbook(BytesIO(...))`; sheet names are exactly `["Summary", "Lines"]`; every expected cell matches; no extra non-empty cells; numeric cells compared through the 15-significant-digit display value: read the raw `<v>` by unzipping `xl/worksheets/sheet2.xml` and assert `Decimal(format(float(raw_v), ".15g")) == expected` (never `Decimal(raw_v) == expected`, which fails for about 6% of ordinary amounts because openpyxl writes `%.16g` of a float); every value with more than 15 normalised significant digits must be an inline string; number formats `#,##0.00`, `#,##0.0000`, `0.00` as specified.
  - **No formulas:** no `<f>` element in any sheet XML; no `hyperlink` or `externalLink` part in the zip.
  - **Totals tie:** the Summary total cells equal `data.totals` exactly; the sum of the Lines sheet "Line total" cells of priced lines (as `Decimal`) equals the Summary "Subtotal ex VAT" for the golden input (a consistency check of the fixture, not a recomputation in the renderer).
  - **Excluded and unresolved lines:** excluded row has status "Excluded", the reason in Notes, grey fill, no amount cells; unresolved row has "Not priced" and the flag in plain words.
  - **Draft label:** parametrised over `draft`, `reviewed`, `approved`. For non-approved: banner row text `DRAFT: version N is not approved. Do not submit.` in A1 of both sheets (merged, red fill), `ws.oddHeader.center.text` contains `DRAFT`, Summary status cell reads "Draft" / "Reviewed: not yet approved", `wb.properties.title` contains `DRAFT`, both sheets have a red `tabColor`. For approved: none of those, status "Approved", approver name and time present.
  - **Incomplete:** an input with `incomplete=True` shows `Incomplete: excludes N lines` next to the total; with `totals=None` the total cells say "Not available".
  - **Injection:** for each corpus string, put it in every user-text field (title, reference, client, member names, section, item no, description, unit, supplier, exclude reason); render; assert no `<f>` in the XML, no cell has `data_type == "f"`, every such cell's value starts with `'` when the rule says so, and the render does not raise.
  - **Precision:** the golden or a parametrised fixture includes `8.174`, `91356.93` and `9735177631648.39` (which openpyxl writes as `8.173999999999999`, `91356.92999999999`, `9735177631648.391`) and asserts the 15-digit display value equals the Decimal; `10.5000` counts as 3 digits (trailing zeros ignored); `Decimal("12345678901234.5678")` (18 digits) and a 16-digit total are inline text cells and the Summary notes "Some values have more than 15 digits and are shown as text." Assert both branches.
  - **Header and footer:** tender titles `A & B`, `&Z&F`, `&"Arial,Bold"x` and a 300-character title: the footer and header XML contain the escaped form, no unescaped single `&` from user text, and every header and footer section is under 255 characters.
  - **Datetimes:** timezone-aware `reviewed_at`, `approved_at` and `generated_at` do not raise and appear as text `YYYY-MM-DD HH:MM UTC`.
  - **Float ban:** `test_no_float_in_reporting_money_path` walks `reporting/xlsx.py` and `reporting/schemas.py` with `ast`; fails on `Name(id="float")` or float `Constant`.
  - **Determinism:** two renders of the same input produce cell-identical workbooks (compare cell maps, not bytes: the zip timestamps differ).
- [ ] **Step 3: Run;** expected FAIL (import error).
- [ ] **Step 4: Implement `schemas.py` (inputs) and `xlsx.py`.** Use `Workbook()`, a single helper `_put(ws, row, col, value, fmt=None)` that routes strings through `xlsx_text` and sets `data_type = "s"`, writes `Decimal` as a numeric cell when `len(value.normalize().as_tuple().digits) <= 15` and as an inline text cell otherwise (setting a flag that makes the Summary note appear), writes datetimes as `YYYY-MM-DD HH:MM UTC` text, and never writes formulas; freeze panes below the header, auto-filter on the Lines header row, `print_title_rows`, landscape, `fitToWidth`, column widths, header and footer text built only from fixed codes plus `xlsx_header_text(...)` (footer: tender and version, page number; header: the DRAFT code string when not approved), each section under 255 characters, `wb.properties.title`, `creator = "IntelTPS"`, no other properties. Set `wb.properties.created`/`modified` from `generated_at` converted to a naive UTC datetime (openpyxl rejects aware ones) so the render is a pure function of its input.
- [ ] **Step 5: Run** `uv run pytest tests/test_reporting_xlsx.py -q`, ruff, `lint-imports`; expected PASS.
- [ ] **Step 6: Commit** `feat: Excel estimate renderer with golden file and injection tests`.

### Task 4: PDF checklist renderer (Sonnet; Opus review)

**Files:**
- Modify: `backend/app/modules/reporting/schemas.py` (add checklist inputs)
- Create: `backend/app/modules/reporting/pdf.py`, `backend/tests/test_reporting_pdf.py`

**Interfaces:**
- Produces (`schemas.py`): `ChecklistRow(requirement_type: str, mandatory_status: str, description: str, review_status: str, document_title: str, page_number: int | None, evidence_verified: bool)`; `ChecklistExportInput(tender_title: str, tender_reference: str | None, client_name: str | None, closing_at: datetime | None, generated_by_name: str, rows: tuple[ChecklistRow, ...], rejected_count: int, generated_at: datetime | None = None, export_id: UUID | None = None)`. `pdf.py`: `render_checklist_pdf(data: ChecklistExportInput) -> bytes`; `checklist_label(data) -> Literal["draft","approved"]` (`approved` only when there is at least one row and none is `unreviewed`).
- Consumes: `safe_text.pdf_text`, `words.*`, `kernel.vocab.REQUIREMENT_TYPES` for the fixed type order.

- [ ] **Step 1: Write failing tests** (`test_reporting_pdf.py`; read the output with `pdfplumber`, already a dependency):
  - The bytes start with `%PDF` and open; page 1 text contains the tender title, reference, client, "Requirements checklist", the generated-at text, the export id, and the count table figures.
  - Type headings appear in `REQUIREMENT_TYPES` order and only for types with rows; "MANDATORY", "Conditional", "Information only" appear for the matching rows; "Confirmed"/"Corrected" for reviewed rows; the source cell shows `<document title>, page N`, "page not recorded" when `page_number` is None, and "(source not verified)" when `evidence_verified` is False.
  - **Label:** with only reviewed rows: no "DRAFT" on any page (label `approved`); with one unreviewed row: "DRAFT" on every page (header line) and a final section titled "Not yet reviewed" containing that row only (and that row absent from its type section); zero rows: "DRAFT" and "No requirements to list".
  - "N rejected, not listed" appears when `rejected_count > 0`.
  - **Injection:** requirements containing the corpus markup strings render as literal text (extract text and find `<img src="file:///etc/passwd"/>` verbatim; no image objects on the page: `page.images == []`); `&amp;` renders as `&amp;`; a 5,000-character description ends with "(truncated, see source)" and lays out without raising, as does a 300-character document title; a tender titled `Smith & Sons` prints as `Smith & Sons` in the footer and metadata (canvas text uses `pdf_plain`, not `pdf_text`); `≤ 5 Ω` becomes `? 5 ?`.
  - Footer: every page has "Page i of N" with the right N for a 300-row input (more than one page); table header rows repeat on continuation pages.
  - Determinism of text: two renders extract identical text. (Byte equality is not required; set `invariant=1` in the ReportLab canvas so it is stable anyway, and assert it.)
  - **Perf:** 1,000 rows render in under 8 s (the HTTP budget is 10 s).
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement `pdf.py`** with `SimpleDocTemplate`, a `NumberedCanvas` (two-pass "Page X of Y"), `Paragraph` for every text cell built only from `pdf_text(...)`, canvas text and metadata only from `pdf_plain(...)`, `Table(..., repeatRows=1, splitByRow=1)` with `colWidths` fixed so long words wrap (`splitLongWords`), built-in `Helvetica` only, a diagonal watermark drawn in the page template `onPage` when the label is `draft`, `invariant=1`, document title/author metadata set from safe text. Enforce `len(rows)` is not checked here (the service owns the cap).
- [ ] **Step 4: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 5: Commit** `feat: PDF checklist report renderer`.

### Task 5: `exports` table, model, repository (Sonnet; Opus review)

**Files:**
- Create: `backend/app/modules/reporting/models.py`, `backend/app/modules/reporting/repo.py`, `backend/migrations/versions/0007_exports.py`
- Modify: `backend/tests/test_fitness_functions.py` only if F3 needs the table registered
- Test: `backend/tests/test_reporting_store.py`

**Interfaces:**
- Produces: ORM `Export` with the columns in spec section 4 (`id` via `uuid_pk()`, `file_size` Integer, `sha256` String(64), `generated_at` an explicit `DateTime(timezone=True)`, NOT NULL, no server default, so the row stores the value printed in the file), `UniqueConstraint("organisation_id", "id")`, composite FKs `fk_exports_tender`, `fk_exports_estimate`, `fk_exports_generator_membership`, CHECK constraints `ck_exports_kind`, `ck_exports_label`, `ck_exports_estimate_cols` (`(kind = 'estimate_xlsx' AND estimate_id IS NOT NULL AND estimate_version IS NOT NULL) OR (kind = 'checklist_pdf' AND estimate_id IS NULL AND estimate_version IS NULL)`), `ck_exports_checklist_label` (`kind <> 'checklist_pdf' OR label IN ('draft','approved')`), index `ix_exports_tender` on `(organisation_id, tender_id, generated_at)`. `ExportRepo(session, ctx)` extends `ScopedRepository[Export]` and only sets `model = Export`; `add` and `get` come from the base (NotFound across organisations). The model registry discovers `reporting.models` automatically.
- Consumes: `app.db.base`, `app.db.scoped`.

- [ ] **Step 1: Write failing tests** (`test_reporting_store.py`): insert succeeds for a valid estimate export and a valid checklist export; each half-null combination violates the CHECK (checklist with only `estimate_id`, checklist with only `estimate_version`, estimate export with only one of the two, estimate export with neither); a checklist row with label `reviewed` violates its CHECK; an unknown `kind` or `label` violates its CHECK; an `estimate_id` of another organisation's estimate violates the composite FK; a `generated_by` who is not a member of the organisation violates the membership FK; `ExportRepo` of organisation B raises `NotFound` for A's row.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** the model, repo and migration `0007` (`down_revision = '0006'`; follow `0006_estimates.py` style; `downgrade` drops the table). 
- [ ] **Step 4: Run** `uv run pytest tests/test_reporting_store.py tests/test_fitness_functions.py -q`, `uv run lint-imports`; `test_migrations_match_the_models` and F3 must pass.
- [ ] **Step 5: Commit** `feat: exports table, model and repository`.

### Task 6: Reporting service and public API (Sonnet; Opus review)

**Files:**
- Modify: `backend/app/modules/reporting/schemas.py` (add `ExportKind`, `ExportLabel`, `ExportCreate`, `ExportDTO`)
- Create: `backend/app/modules/reporting/service.py`, `backend/app/modules/reporting/public.py`, `backend/tests/test_reporting_service.py`

**Interfaces:**
- Produces: `ExportCreate(kind: ExportKind, estimate_id: UUID | None = None)` with `extra="forbid"` and a validator: `estimate_id` is allowed only for `estimate_xlsx`. `ExportDTO(id, tender_id, kind, estimate_id, estimate_version, label, file_name, content_type, file_size, row_count, generated_by, generated_by_name: str | None = None, generated_at)`. `MAX_ROWS = 5_000` in `service.py`, read at call time by `service.max_rows()` (exported in `public.py` as `max_rows()`) so a test patching `app.modules.reporting.service.MAX_ROWS` is honoured by the router too; rejected requirements do not count toward the cap. Service functions:
  - `create_export(session, ctx, storage, tender_id, kind, payload, estimate_id=None) -> ExportDTO`: `ctx.require(EXPORT)`; payload type must match `kind` (else `ValidationFailed`); `len(payload.lines or rows) > MAX_ROWS` -> `ValidationFailed(code="export_too_large")`; build `export_id = uuid4()`, `generated_at = datetime.now(UTC)`, `dataclasses.replace(payload, ...)`; assert the estimate's tender (given by the router) equals `tender_id` (`ValidationFailed` otherwise); label (estimate: its status; checklist: `checklist_label`); render; key `org/{org}/tenders/{tender}/exports/{export_id}.{xlsx|pdf}`; `storage.put`; `delete_on_rollback`; insert the row with `sha256`, `file_size`, `row_count`, `file_name = export_filename(...)`, `content_type`; `audit.record(session, ctx, "export", export_id, "export_created", {"kind", "estimate_id": str(estimate_id) or None, "version", "status": label, "count"}; JSONB cannot hold a UUID)`; flush; return the DTO.
  - `get_export(session, ctx, export_id) -> ExportDTO` (`READ`).
  - `open_export_file(session, ctx, storage, export_id) -> tuple[ExportDTO, BinaryIO]` (`EXPORT`; `NotFound` when the stored file is missing; records `export_downloaded` with `{"kind"}`).
  - `public.py` exports the three functions, `ExportCreate`, `ExportDTO`, the input dataclasses, `render_*` are not exported (internal).
- Consumes: Tasks 2 to 5; `app.db.stored_files.delete_on_rollback`; `audit.public.record`.

- [ ] **Step 1: Write failing tests** (`test_reporting_service.py`, using the real database and a `LocalVolumeStorage` on a tmp path, inputs built from the golden fixture): a created estimate export has a row, a stored file whose SHA-256 equals the row, `file_size` equal to the stored length, `generated_at` on the row equal to the time printed in the file, a label equal to the status, `file_name` ending `.xlsx` with `-DRAFT` for draft and reviewed only; checklist label follows D3; audit has `export_created` with exactly the safe keys and none of the tender title, description, file name or any amount (assert the metadata dict equality); reviewer role raises `Forbidden`; wrong payload type for the kind raises `ValidationFailed`; 5,001 rows raises `export_too_large` and stores nothing; **failure path:** monkeypatch the renderer to succeed and the row insert to raise after `put` -> the file is gone after rollback and no row exists; `open_export_file` records `export_downloaded` and returns the exact bytes; a deleted stored file gives `NotFound`; a second `create_export` makes a second row and file (no overwrite).
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** the service and `public.py`.
- [ ] **Step 4: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 5: Commit** `feat: reporting service, storage and audit for exports`.

### Task 7: Routes, orchestration and API tests (Sonnet; openapi regeneration Haiku; Opus review)

**Files:**
- Create: `backend/app/api/routers/exports.py`, `backend/tests/test_exports_api.py`
- Modify: `backend/app/api/main.py` (register the router), `frontend/openapi.json` and `frontend/src/api/schema.d.ts` (regenerated)

**Interfaces:**
- Produces: `POST /api/v1/tenders/{tender_id}/exports` (201, `ExportDTO`), `GET /api/v1/exports/{export_id}` (`ExportDTO`), `GET /api/v1/exports/{export_id}/download` (`StreamingResponse`, headers per D14). Router logic for `POST`: `tenders.get_tender` (404 across organisations, also gives the title, reference, client, closing date); `ctx.require(EXPORT)`; `limiter.check(f"export:{ctx.user_id}", 10, 60)`; for `estimate_xlsx` resolve the version per D2 (`estimates.list_estimates` gives versions and the highest approved; an `estimate_id` not in that list is 404); when the chosen version is not approved (draft **or reviewed**, since a reviewed estimate can be reopened) take `suppliers.lock_tender` first, then re-read the version's status after the lock and choose `estimate_inputs.live_inputs` (draft) or `LiveInputs()` (reviewed, approved) from that status; one call `estimates.export_snapshot` -> `EstimateExportInput`; an approved version takes no lock (Decimals parsed from the DTO strings; `markup_percent` per line = the override if present else the estimate default, `None` for lines without amounts); names via `with_estimate_names` and `identity.member_names`; for `checklist_pdf` read `documents.list_documents`, then `checklist.list_for_versions` in pages of 1000 until `reporting.max_rows() + 1` non-rejected rows are seen, partition rejected (count only) from the rest, sort the rest by (document order from `list_documents`, `source_order`, `position`), map `document_title` from the document's `title` (fallback the version filename) and `evidence_verified = evidence_status == "verified"`. Then `reporting.create_export`. `GET /exports/{id}`: fills `generated_by_name`. `GET .../download`: `reporting.open_export_file`, headers `Content-Disposition: attachment; filename="<file_name>"` (always attachment, for the PDF too), `X-Content-Type-Options: nosniff`, `Cache-Control: private, no-store`, `Content-Security-Policy: sandbox`, `Content-Length`, media type from the row; reuse the `_stream` generator idea (copy, do not import another router).
- Consumes: Tasks 1 and 6; `estimates.public`, `tenders.public`, `documents.public`, `checklist.public`, `identity.public`, `suppliers.public.lock_tender`, `app.api.ratelimit.limiter`.

- [ ] **Step 1: Write failing API tests** (`test_exports_api.py`; reuse `_matched_org`, `_priced_setup` style helpers from `test_estimates_api.py` / `test_suppliers_api.py` to build a priced, reviewed and approved estimate, and `review_helpers.py` for requirements):
  - Roles: admin, estimator, project manager get 201; reviewer 403 on POST and on download; reviewer 200 on `GET /exports/{id}`.
  - Version rules (D2): no `estimate_id` with an approved version exports the highest approved; with only a draft exports the draft (label `draft`); with no estimate 409 `no_estimate`; `estimate_id` from another tender or organisation 404; `estimate_id` with `kind=checklist_pdf` is 422; unknown `kind` 422.
  - Excel content (open the downloaded bytes with openpyxl): Summary and Lines equal the `GET /estimates/{id}` and `/lines` values for every priced line and the totals; approved file has no DRAFT marking and no `-DRAFT` filename; the same estimate's draft/reviewed file has all markings; a draft with a BoQ quantity edited after pricing shows "Source changed" and its amount cells empty.
  - **Frozen:** approve, export (A); edit a BoQ quantity and a quotation price; export again (B); A and B are identical in the whole Lines sheet and in every Summary cell except "Generated at" and "Export reference" (named in the test); a new draft version exported does not change A.
  - Reviewed-then-reopened race: with the tender lock held by a transaction that reopens a reviewed estimate and prices a line, an export waits for the lock and then returns a file whose totals and lines are from the same state.
  - Checklist PDF with two documents: rows are ordered by document order then source order; bytes open with pdfplumber; confirmed and corrected requirements appear under their type; an unreviewed one forces DRAFT and sits in "Not yet reviewed"; a rejected one is absent and counted; superseded document versions are not listed.
  - Download headers: `content-type` (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` / `application/pdf`), `content-disposition` is `attachment; filename="..."` with the stored name, `x-content-type-options: nosniff`, `cache-control: private, no-store`, `content-security-policy: sandbox`, `content-length` equals the body length; a tender titled `x"; evil=1 /../é` yields a safe filename; deleting the stored file gives 404 on download.
  - Archived tender: export still 201.
  - Audit: after create and download there are `export_created` and `export_downloaded` rows with only allowlisted keys.
  - Rate limit: the 11th create in a minute is 429 (reset the limiter in the test; use the helper existing tests use for the auth limiter).
  - Caps: patch `app.modules.reporting.service.MAX_ROWS` down to 3 with `monkeypatch` and show a 4-line estimate gives 422 `export_too_large`.
  - Injection end to end: a BoQ description `=HYPERLINK("http://example.com","x")` and a supplier name `@SUM(1)` appear in the downloaded workbook as text starting with `'`, and a requirement `<img src="file:///etc/passwd"/>` appears literally in the PDF text.
- [ ] **Step 2: Run;** expected FAIL (404 on the routes).
- [ ] **Step 3: Implement** the router and register it.
- [ ] **Step 4 (Haiku): Regenerate the contract.** In `backend/`: `uv run python -m app.api.export_openapi`; in `frontend/`: `npm run gen:api`. Run `uv run pytest tests/test_openapi_contract.py -q`; expected PASS.
- [ ] **Step 4b (Haiku): Register the routes in the F1 sweep (`tests/test_fitness_functions.py`) in this same task, so no commit has a red suite.** Add `REQUESTS[("POST", "/api/v1/tenders/{tender_id}/exports")] = lambda: {"json": {"kind": "checklist_pdf"}}`; add `known["export_id"]` from a real export that org B creates in the sweep setup (`POST /tenders/{tender_b}/exports` with `kind=checklist_pdf`); add org B's export file name to `forbidden`; add `"exports"` to the `for needle in (...)` list; after the sweep assert org B can still download its export (200, same SHA-256 as its row) and that org A's attempts created no export for org B.
- [ ] **Step 5: Run the full backend suite** (`uv run pytest -q`), ruff, `lint-imports`; expected PASS, including the F1 sweep and the `openapi.json` drift test.
- [ ] **Step 6: Commit** `feat: export routes for the estimate workbook and the checklist report`.

### Task 8: Performance smoke, import contracts, architecture docs (Haiku boilerplate; Sonnet perf; Opus review)

**Files:**
- Modify: `backend/pyproject.toml` (two import-linter contracts), `docs/architecture/architecture.md`, `docs/architecture/diagrams/backend-components.md`
- Create: `backend/tests/test_exports_perf.py`

**Interfaces:**
- Produces: import-linter contracts (the F1 registration is in Task 7): `reporting is isolated from the other modules` (forbidden: every module under `app.modules` except `audit` and `reporting` itself, listed out: `estimates`, `estimating`, `suppliers`, `documents`, `tenders`, `identity`, `checklist`, `knowledge`, `pipeline`, `jobs`, `extraction`, `billing`, `qa`) and `export renderers are pure` (`app.modules.reporting.xlsx`, `app.modules.reporting.pdf`, `app.modules.reporting.safe_text` must not import `sqlalchemy`, `fastapi`, `app.db`, `app.infrastructure`, `app.modules.audit`, `app.modules.reporting.service` or `app.modules.reporting.models`).

- [ ] **Step 1: (moved to Task 7 Step 4b.)** Confirm the F1 sweep still passes with the exports routes registered.
- [ ] **Step 2 (Haiku): Contracts.** Add the two import-linter contracts; run `uv run lint-imports`; expected PASS (the reporting module imports only `kernel`, `db`, `audit`). (The existing `test_role_permission_matrix` already covers `export`; add no duplicate.)
- [ ] **Step 3: Perf smoke** (`test_exports_perf.py`; the repo has no slow-test marker, so the test runs in every CI job and uses the budgets below with headroom): seed an approved estimate with 1,000 lines directly through the ORM (random but valid snapshots, three sections, 10 percent excluded) and assert: `POST .../exports` with `estimate_xlsx` returns 201 in under 10 s wall time (F11), the pure `render_estimate_xlsx` is under 3 s, and the downloaded workbook has exactly 1,001 Lines rows (header plus 1,000 lines; an approved estimate has no banner). Then seed 1,000 requirements and assert the PDF POST is under 10 s. Time with `time.perf_counter`; print the figures (they are recorded in the gate note).
- [ ] **Step 4: Docs.** `architecture.md`: reporting row (signature `create_export(session, ctx, storage, tender_id, kind, payload, estimate_id=None)`, owns `exports`, router-built plain inputs, synchronous), Contracts section line for reporting, the storage key shape for exports, resolve the "PDF report library" open question with a pointer to spec D7, F11 note that the smoke test exists. `backend-components.md`: reporting depends only on kernel, db, audit.
- [ ] **Step 5: Run** the full backend suite, `lint-imports`, ruff; expected PASS.
- [ ] **Step 6: Commit** `test: F11 smoke and import contracts for exports`.

### Task 9: Frontend API hooks, plain words and the ExportButton (Haiku hooks and words; Sonnet component; Opus review)

**Files:**
- Create: `frontend/src/api/exports.ts`, `frontend/src/api/exports.test.tsx`, `frontend/src/lib/export-words.ts`, `frontend/src/lib/export-words.test.ts`, `frontend/src/components/export-button.tsx`, `frontend/src/components/export-button.test.tsx`

**Interfaces:**
- Produces: `type Export = components["schemas"]["ExportDTO"]`; `useCreateExport(tenderId: string)` (a mutation: `post<Export>("/api/v1/tenders/{id}/exports", { kind, estimate_id? })`); `exportDownloadPath(id: string): string`; `exportErrorText(error: unknown): string` mapping `no_estimate`, `export_too_large`, `forbidden` (403), rate limited (429), `not_found` (404), network errors and a generic fallback to plain sentences (never raw codes). `ExportButton({ tenderId, kind, estimateId?, label, draftNote? })`: hidden unless `useCan("export")`; click -> `mutate`; while pending it is disabled and reads "Preparing file"; on success it triggers the download by creating an anchor with `href = exportDownloadPath(id)` and `download = file_name` and clicking it, invalidates the estimates queries, then shows "Downloaded {file_name}" plus "(marked DRAFT)" when the returned `label` is not `approved`, with the same anchor as a visible link; on error it shows `exportErrorText` in a `role="alert"` region; `draftNote`, when given, is rendered above the button as text.
- Consumes: `api/client.ts` (`post`), `components/auth-gate` (`useCan`), regenerated `schema.d.ts`.

- [ ] **Step 1 (Haiku): Tests first:** words (each known code gives a non-empty sentence that does not contain the raw code; unknown gives the fallback); hook (posts the right body and path with the CSRF header, `estimate_id` omitted for the checklist); component (hidden without the permission; calls create once on click and not twice on double click; shows "Preparing file" and is disabled while pending; on success renders a link whose `href` is `/api/v1/exports/{id}/download` and `download` attribute is the returned file name, and clicks an anchor with that href; on `no_estimate` shows the plain sentence; `draftNote` text is visible before any click; after success the shown text follows the returned `label`, so a server label of `approved` shows no DRAFT wording even if `draftNote` was given).
- [ ] **Step 2: Run** `npx vitest run src/api/exports.test.tsx src/lib/export-words.test.ts src/components/export-button.test.tsx`; expected FAIL.
- [ ] **Step 3: Implement** (Haiku: hooks and words; Sonnet: component).
- [ ] **Step 4: Run** vitest, lint, typecheck, build; expected PASS.
- [ ] **Step 5: Commit** `feat: export hooks, plain-words errors and the ExportButton`.

### Task 10: Place the buttons on the estimate and checklist pages (Sonnet; Opus review)

**Files:**
- Modify: `frontend/src/app/(app)/tenders/[id]/estimate/estimate-view.tsx`, `frontend/src/app/(app)/tenders/[id]/checklist/checklist-view.tsx`, their `.test.tsx` files

**Interfaces:**
- Consumes: `ExportButton` (Task 9), the shown `Estimate` (`status`, `version`) and the checklist rows' `review_status`.
- Produces: on the estimate page, beside the version picker, `<ExportButton kind="estimate_xlsx" estimateId={shown.id} label=... draftNote=... />` where the label is "Download Excel" for an approved version and "Download Excel (DRAFT)" otherwise, and `draftNote` is "This file will be marked DRAFT because version {n} is not approved." (omitted when approved); no button when the tender has no estimate. On the checklist page, `<ExportButton kind="checklist_pdf" label="Download PDF report" draftNote=... />` where `draftNote` is "{n} requirements are not reviewed yet. The report will list them separately and be marked DRAFT." computed from a **separate, unfiltered** query (`useTenderRequirements(id, { reviewStatus: "unreviewed" })` with the page limit and no type or mandatory filter), never from the filtered list on screen, so the note is correct whichever filter is selected; when that query has another page the note says "at least {n}".

- [ ] **Step 1: Write failing tests:** estimate page with an approved version shows "Download Excel" and no note; with a draft or reviewed version shows "Download Excel (DRAFT)" and the note naming the version; switching the version picker changes the `estimate_id` sent; no export button for a role without `export` and none when there are no versions; checklist page shows the button, shows the note only when unreviewed rows exist, the note says "at least" while more pages exist, and **with the Review status filter set to Confirmed while unreviewed rows exist the note is still shown**.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npx vitest run`, lint, typecheck, build; expected PASS.
- [ ] **Step 5: Commit** `feat: export buttons on the estimate and checklist pages`.

### Task 11: Real-stack gate and docs (Sonnet drives; Haiku edits docs; Opus whole-branch review)

**Files:**
- Create: `docs/spikes/slice-6a-gate.md`
- Modify: `docs/plan.md` (Slice 6 row: 6a result and "6b pending"; remove "Slice 6 pending" wording from the Slice 5 row), `docs/known-limitations.md` (new section "Slice 6a (exports)" with the spec section 11 items), `docs/dependency-audit.md` (one line: reportlab added, audit result and date)

- [ ] **Step 1: Rebuild and migrate:** `docker compose up -d --build`; check `/health`, `/health/db`, `alembic_version` is `0007` and the `exports` table exists; no Traceback or 5xx in the api or worker logs.
- [ ] **Step 2: Drive the spec section 1 journey in a real browser through Caddy** (approved version, then a draft/reviewed version, then the checklist with and without unreviewed rows, then the hostile strings, then reviewer/other-organisation checks). For each file also run from a terminal: `curl -i -b <cookie> .../exports/{id}/download` and record content type, disposition, `nosniff`, `no-store`, and that Caddy's gzip does not corrupt the bytes (compare SHA-256 of the saved file with `exports.sha256`). Open the workbook in Excel if installed and say which application and version; if not, record "opened by reading the XML only". Save the PDF (it is served as an attachment) and open it in a PDF viewer. Time the draft path and the 1,000-line smoke figure.
- [ ] **Step 3:** run the full backend suite, ruff, `lint-imports`, `pip-audit` on the exported runtime requirements, and frontend lint, typecheck, build, vitest; record exact counts and the commit they were measured at. Fix defects test-first; re-run the touched tests and say so. Confirm `docs/prd.md` and `docs/architecture/architecture.md` carry the Task 1 wording.
- [ ] **Step 4 (Haiku): Docs:** write `slice-6a-gate.md` in the style of `slice-5b-gate.md` (steps table with PASS/FAIL and evidence, automated checks, defects found and fixed, **Not covered**, local test data), update the three docs with the exact outcome; claim nothing that was not run.
- [ ] **Step 5:** Opus reviews the whole branch against the spec (all of Review Focus); fix findings test-first.
- [ ] **Step 6: Commit** `docs: slice 6a gate result and known limitations`.

---

## Self-review

- **Spec coverage:** D1 draft marking (T3, T4, T7, T10); D2 version rule (T7); D3 labels (T4, T6); D4 checklist content (T4, T7); D5 permission (T6, T7, T8); D6 sync, caps, rate limit, perf (T6, T7, T8, T11); D7 ReportLab and audit (T2); D8 openpyxl (T3); D9 module shape and import contracts (T3 to T8); D10 Decimal-exact, no formulas, 15-digit rule (T3); D11 and D12 injection funnels (T2, T3, T4, T7); D13 storage and rollback cleanup (T1, T6); D14 download headers and filename (T2, T7); D15 archived allowed (T7); D16 lock only for drafts (T7); D17 audit (T6, T7); D18 repeat exports (T6); D19 sheets (T3); D20 UTC (T3, T4); exports table and migration (T5); F1/F3/F11/openapi drift (T5, T7, T8); frontend (T9, T10); gate and docs (T11); 6b items listed in spec section 12 and not planned.
- **Deliberate deviations to flag for the reviewer:** (1) `create_export` takes the storage port and a payload, unlike the architecture sketch; the architecture doc is updated in T8. (2) `_delete_on_rollback` moves from `documents` to `app/db/stored_files.py` (T1) and the live-input readers move from `routers/estimates.py` to `app/api/estimate_inputs.py`; both are behaviour-neutral refactors guarded by the existing suite.
- **Type consistency:** `ExportLine`, `EstimateExportInput`, `ChecklistRow`, `ChecklistExportInput` are defined in T3/T4 and used by name in T6 to T8; `ExportDTO`/`ExportCreate` in T6 and the generated `Export` type in T9; `MAX_ROWS` in T6 and patched in T7; `all_lines` in T1 and used in T7.
- **Review fixes applied (Opus review of 2026-10-23):** openpyxl float writing (D10 and Task 3), `export_snapshot` with lock-first for every non-approved version (D16, Tasks 1 and 7), the exports CHECK, F1 registration moved into Task 7, identical-cells test with named exclusions, unfiltered checklist note, header/footer funnel, `pdf_plain`, truncation marker, `generated_at` stored explicitly, string `estimate_id` in audit, document ordering, and the owner's rulings (draft exports allowed; FR-62 labels only; PDF always attachment; PRD and architecture wording updated in Task 1).
- **Unverified at plan time:** whether `useCan` is mocked the same way in every page test (follow the nearest existing test). The limiter is reset by the autouse `clean_state` fixture and the repo has no slow-test marker (checked).
