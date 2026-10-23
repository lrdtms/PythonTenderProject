# Slice 5b: The Estimate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn confirmed supplier matches into a versioned, Decimal-exact tender estimate (draft, reviewed, approved) with a UI to price, review and approve it.

**Architecture:** A new backend module `estimates` that imports neither `estimating` nor `suppliers` (no import cycle): a pure `calc.py`, models/repo/service working on plain input dataclasses, and a router in `app/api/routers/estimates.py` that does the orchestration (tender lock, archive re-check, reading current BoQ lines and confirmed matches through the other modules' public APIs, mapping them to the estimates inputs). Estimate lines snapshot what they use and hold plain UUID columns (no foreign keys to BoQ, suppliers or matches). A Next.js page `/tenders/[id]/estimate` and a pricing-defaults page sit on the generated API types.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Postgres, pytest, Hypothesis, import-linter, ruff; Next.js, TypeScript, Tailwind, Vitest, openapi-typescript (`npm run gen:api`).

**Spec:** `docs/superpowers/specs/2026-10-22-slice-5b-estimate-design.md` (read it first; section numbers below refer to it).

## Global Constraints

- Money is `Decimal`, never `float`; a test fails on any `float` token in `backend/app/modules/estimates/`. Missing is NULL plus a flag, never 0.
- Quantities and unit prices `Numeric(18,4)`; rounded amounts `Numeric(18,2)`; rounding `ROUND_HALF_UP`; `calc.py` uses its own `Context(prec=40, rounding=ROUND_HALF_UP)`.
- Rounding order: material cost, labour cost, markup, then VAT on the summed `subtotal_ex_vat`; totals are sums of rounded values.
- VAT is always on; `vat_rate` is 0 to 100 and comes from `pricing_defaults` (no hard-coded rate). One currency per estimate; nothing is converted.
- Markup basis is `cost` (markup = cost x pct) or `selling_price` (price = cost / (1 - pct), pct < 100).
- Nothing is pre-selected; no price sort, filter or "cheapest" marker anywhere.
- Every organisation-owned table carries `organisation_id` with composite foreign keys to `estimates` only; every new route is in the F1 sweep; archived tenders refuse writes with 409 `tender_archived`.
- Decimals travel as JSON strings, never numbers (frontend inputs are text, never `type=number`).
- Ruff line length 100; modules import each other only through `public.py`; `estimates` imports no other module except `kernel`, `db` and `audit`.
- Model routing: tasks marked **Haiku** are mechanical (fixtures, strings, boilerplate, regeneration, doc edits); **Sonnet** implements the rest; **Opus** reviews every task and does the final branch review. Run `uv run ruff check . && uv run ruff format --check . && uv run lint-imports && uv run pytest -q` in `backend/` and `npm run lint && npm run build && npx vitest run` in `frontend/` before each commit that touches them.

## Review Focus

1. A VAT-inclusive quote on a line with no stated basis, or a quote with no currency: the line is blocked, never treated as ex-VAT or defaulted (test in Task 5).
2. A BoQ re-extraction, match reset, quotation re-run or supplier merge after a line was priced: the draft shows the line as changed or unresolved, a frozen estimate is untouched, nothing errors (Tasks 5 and 7).
3. Approve racing a line write, and two creates racing for the one draft: exactly one wins, the other gets a clean 409 (Task 7).
4. Half-cent and large-quantity rounding (qty 10,000 at a 4-decimal price): totals equal the golden figures to the cent (Task 1).
5. An estimate on a tender whose every line is excluded or empty: totals are zero but labelled, approval is allowed only if no line is unresolved, and the UI does not show "NaN" or a blank (Tasks 1 and 11).

## File Structure

| File | Responsibility |
|---|---|
| `backend/app/modules/estimates/calc.py` | Pure maths: `to_ex_vat`, `line_amounts`, `totals`; no imports beyond stdlib |
| `backend/app/modules/estimates/models.py` | `PricingDefaults`, `Estimate`, `EstimateLine` ORM models |
| `backend/app/modules/estimates/schemas.py` | DTOs and patch bodies; plain input dataclasses `BoqInput`, `CandidateInput` |
| `backend/app/modules/estimates/repo.py` | Queries scoped by organisation |
| `backend/app/modules/estimates/service.py` | Create, price, refresh, status moves, readiness; works on inputs passed in |
| `backend/app/modules/estimates/public.py` | The module's public surface |
| `backend/app/api/routers/estimates.py` | Routes, tender lock, archive check, mapping from BoQ and match DTOs to inputs |
| `backend/migrations/versions/0006_estimates.py` | Tables `pricing_defaults`, `estimates`, `estimate_lines` |
| `backend/tests/test_estimates_calc.py`, `test_estimates_golden.py`, `test_estimates_store.py`, `test_estimates_api.py`, `test_estimates_races.py` | Tests |
| `backend/tests/fixtures/estimates/*.json` | Golden files |
| `frontend/src/api/estimates.ts` | Query and mutation hooks |
| `frontend/src/lib/estimate-words.ts` | Plain-words labels for flags and blockers |
| `frontend/src/app/(app)/tenders/[id]/estimate/*` | Estimate page and components |
| `frontend/src/app/(app)/settings/pricing/*` | Pricing defaults page (admin) |

---

### Task 1: Pure calculation core and golden files (Sonnet; golden data entry Haiku; Opus review)

**Files:**
- Create: `backend/app/modules/estimates/__init__.py` (empty), `calc.py`
- Test: `backend/tests/test_estimates_calc.py`, `backend/tests/test_estimates_golden.py`, `backend/tests/fixtures/estimates/golden_*.json`

**Interfaces:**
- Produces (in `calc.py`):
  - `MarkupBasis = Literal["cost", "selling_price"]`
  - `@dataclass(frozen=True) class Settings: vat_rate: Decimal; markup_basis: MarkupBasis; markup_percent: Decimal`
  - `@dataclass(frozen=True) class LineInput: quantity: Decimal | None; unit_price_ex_vat: Decimal | None; labour_rate: Decimal | None; markup_override: Decimal | None`
  - `@dataclass(frozen=True) class LineAmounts: material_cost: Decimal; labour_cost: Decimal; cost: Decimal; markup: Decimal; total: Decimal`
  - `@dataclass(frozen=True) class Totals: subtotal_cost: Decimal; markup_total: Decimal; subtotal_ex_vat: Decimal; vat_total: Decimal; total_inc_vat: Decimal`
  - `def to_ex_vat(quoted: Decimal, includes_vat: bool, vat_rate: Decimal) -> Decimal` (4 dp)
  - `def line_amounts(line: LineInput, settings: Settings) -> LineAmounts | None` (None when quantity or price is missing)
  - `def totals(amounts: Sequence[LineAmounts], settings: Settings) -> Totals`
  - `def validate_settings(settings: Settings) -> None` raising `ValueError` for `vat_rate` outside 0..100, negative markup, or `selling_price` markup >= 100.

- [ ] **Step 1: Write failing unit tests** in `test_estimates_calc.py` with these exact assertions:
  - `to_ex_vat(Decimal("115"), True, Decimal("15")) == Decimal("100.0000")`; `to_ex_vat(Decimal("100"), False, Decimal("15")) == Decimal("100.0000")`.
  - Cost basis: qty `10`, price `125.5000`, labour `20.0000`, markup 10% gives `material_cost 1255.00`, `labour_cost 200.00`, `cost 1455.00`, `markup 145.50`, `total 1600.50`.
  - Selling-price basis, same line, 10%: `markup == Decimal("161.67")` (1455 / 0.9 = 1616.67).
  - Half-cent: qty `1`, price `0.0050` gives `material_cost == Decimal("0.01")`.
  - Large: qty `10000`, price `0.3333` gives `material_cost == Decimal("3333.00")`.
  - Per-line `markup_override=Decimal("0")` gives `markup == Decimal("0.00")`.
  - Missing quantity or price returns `None`.
  - `totals` with one line total `1600.50`, VAT 15: `vat_total == Decimal("240.08")` (240.075 half up), `total_inc_vat == Decimal("1840.58")`, and `subtotal_ex_vat == subtotal_cost + markup_total`.
  - `validate_settings` rejects vat 101, markup -1, selling_price markup 100.
- [ ] **Step 2: Run** `uv run pytest tests/test_estimates_calc.py -q` in `backend/`; expected: import error / FAIL.
- [ ] **Step 3: Implement `calc.py`** with the signatures above, quantizing every amount with an explicit `ROUND_HALF_UP` inside a local `Context(prec=40)`; no `float`.
- [ ] **Step 4: Add Hypothesis properties** (same file): totals independent of line order; adding an empty list of excluded lines changes nothing; `subtotal_ex_vat == sum(l.total)`; selling-price markup is never negative for pct in 0..99.99; a VAT-inclusive quote converted by `to_ex_vat` differs from the exact quotient by less than `0.00005`.
- [ ] **Step 5: Float ban test** `test_no_float_in_estimates_module` in `test_estimates_calc.py`: walks `app/modules/estimates/*.py` with `ast` and fails on `Name(id="float")` or float `Constant`.
- [ ] **Step 6 (Haiku): Golden files.** Create `golden_a.json`, `golden_b.json`, `golden_c.json` under `backend/tests/fixtures/estimates/`, each `{"settings": {...}, "lines": [...], "expected": {"lines": [...], "totals": {...}}}` with hand-checked figures: a: 3 lines, cost basis, VAT 15; b: selling-price basis, a labour line, an excluded line; c: half-cent and 10,000-quantity lines, VAT 0. Compute expected values by hand from the Global Constraints order and double-check each with a one-off script not committed. Write `test_estimates_golden.py` that loads each file and asserts exact `Decimal` equality of every line and total, plus an all-lines-excluded case with totals all `Decimal("0.00")`.
- [ ] **Step 7: Run** `uv run pytest tests/test_estimates_calc.py tests/test_estimates_golden.py -q` and ruff; expected: PASS.
- [ ] **Step 8: Commit** `feat: pure estimate calculation core with golden files (F7)`.

### Task 2: Models, migration and repository (Sonnet; Opus review)

**Files:**
- Create: `backend/app/modules/estimates/models.py`, `repo.py`, `backend/migrations/versions/0006_estimates.py`
- Modify: `backend/migrations/env.py` or the model registry the other modules use (follow `suppliers`), `backend/tests/test_fitness_functions.py` only if F3 needs the new tables registered
- Test: `backend/tests/test_estimates_store.py`

**Interfaces:**
- Produces: ORM classes `PricingDefaults`, `Estimate`, `EstimateLine` with the columns in spec section 4 (money columns `Numeric(18,4)` / `Numeric(18,2)`); partial unique index `uq_estimates_one_draft` on `(tender_id)` WHERE `status = 'draft'`; unique `(organisation_id, tender_id, version)`; unique `(estimate_id, boq_item_id)` on lines; composite foreign key `(organisation_id, estimate_id)` -> `estimates(organisation_id, id)`. `EstimateRepo(session, organisation_id)` with `get_for_update(estimate_id)`, `latest_version(tender_id)`, `draft_for(tender_id)`, `lines(estimate_id, limit, offset, status)`, `add_lines(rows)`, `defaults()`, `save_defaults(...)`.

- [ ] **Step 1: Write failing tests** in `test_estimates_store.py`: two drafts for one tender raise `IntegrityError`; a second organisation cannot read the first's estimate through `EstimateRepo`; deleting a BoQ row, a supplier row or a match row does not touch `estimate_lines` (insert a line with random UUIDs for those columns and assert insert succeeds, i.e. there are no foreign keys to them).
- [ ] **Step 2: Run** the new tests; expected FAIL.
- [ ] **Step 3: Implement models, repo and migration `0006`** following the style of `0005_suppliers_quotations.py` (autogenerate, then tidy; `down_revision = '0005'`).
- [ ] **Step 4: Run** `uv run pytest tests/test_estimates_store.py tests/test_fitness_functions.py -q`, `uv run lint-imports`; expected PASS (F3 covers the new tables).
- [ ] **Step 5: Commit** `feat: estimates tables, models and repository`.

### Task 3: Permissions (Haiku implements; Opus review)

**Files:**
- Modify: `backend/app/kernel/types.py` (enum and `ROLE_PERMISSIONS`), the role matrix test, `backend/openapi.json` (regenerated)
- Test: the existing `test_role_permission_matrix` (extend it)

**Interfaces:**
- Produces: `Permission.APPROVE_ESTIMATE = "approve_estimate"` (admin, project manager) and `Permission.MANAGE_PRICING = "manage_pricing"` (admin only). Estimator and reviewer unchanged.

- [ ] **Step 1: Extend the matrix test** to assert exactly those grants; run it; expected FAIL.
- [ ] **Step 2: Add the enum members and grants.**
- [ ] **Step 3: Regenerate OpenAPI** with `uv run python -m app.api.export_openapi` in `backend/` and `npm run gen:api` in `frontend/`; run backend tests `test_openapi_contract.py` and `test_members_and_tenders.py`; expected PASS.
- [ ] **Step 4: Commit** `feat: approve_estimate and manage_pricing permissions`.

### Task 4: Pricing defaults service and routes (Sonnet; Opus review)

**Files:**
- Create: `backend/app/modules/estimates/schemas.py` (defaults DTOs first), `service.py` (defaults part), `public.py`; `backend/app/api/routers/estimates.py` (defaults routes); register the router in `app/api/main.py`
- Test: `backend/tests/test_estimates_api.py` (defaults section)

**Interfaces:**
- Produces: `PricingDefaultsDTO(currency: str, vat_rate: str, markup_basis: Literal["cost","selling_price"], default_markup_percent: str, updated_at: datetime)`; `PricingDefaultsPut` with the same fields minus `updated_at` (`extra="forbid"`, `DecimalText`, currency 3 upper-case letters); `get_defaults(session, ctx) -> PricingDefaultsDTO | None`; `save_defaults(session, ctx, body) -> PricingDefaultsDTO`. Routes `GET /api/v1/pricing-defaults` (needs `read`; 404 `pricing_defaults_missing` when absent) and `PUT /api/v1/pricing-defaults` (needs `manage_pricing`; audit `pricing_defaults_changed`, ids and field names only).

- [ ] **Step 1: Write failing API tests:** admin PUT then GET round-trips; estimator PUT is 403; reviewer GET is 200; GET with none saved is 404 `pricing_defaults_missing`; `vat_rate` `"101"`, markup `"-1"`, and `selling_price` with `"100"` are 422; currency `"zar"` is 422.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** schema validators via `calc.validate_settings`, service, router.
- [ ] **Step 4: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 5: Commit** `feat: pricing defaults API`.

### Task 5: Create an estimate and read its lines with live inputs (Sonnet; Opus review)

**Files:**
- Modify: `estimates/schemas.py`, `service.py`, `public.py`, `api/routers/estimates.py`
- Test: `backend/tests/test_estimates_api.py` (create/read section)

**Interfaces:**
- Consumes: `suppliers.suggestions_for(session, ctx, boq_ids, quote_versions, status, classification, supplier_id) -> list[MatchSuggestionDTO]` (use `status="confirmed"`), `estimating.list_boq_items`, `documents.list_documents`; copy the `_current` helper idea from `api/routers/matches.py` into the new router (do not import from the other router).
- Produces (schemas.py): `@dataclass(frozen=True) BoqInput(id, section, item_no, description, unit, quantity: Decimal | None, review_status)`; `@dataclass(frozen=True) CandidateInput(match_id, boq_item_id, quotation_item_id, supplier_id, supplier_name, unit_price: Decimal | None, currency: str | None, includes_vat: bool | None, unit_mismatch: bool, quote_item_reviewed: bool)`; `EstimateDTO` (header, settings, status, `totals` or `None`, counts `priced/excluded/unresolved/changed`, `incomplete: bool`); `EstimateLineDTO` (snapshot fields, `candidates: list[CandidateDTO]`, chosen source, amounts, `flags: list[str]` including the computed `source_changed`); service functions `create_estimate(session, ctx, tender_id, boq: list[BoqInput]) -> EstimateDTO`, `get_estimate(session, ctx, estimate_id, live: LiveInputs) -> EstimateDTO`, `list_lines(session, ctx, estimate_id, live: LiveInputs, status, limit, offset) -> list[EstimateLineDTO]`, `list_estimates(session, ctx, tender_id) -> list[EstimateSummaryDTO]`, where `LiveInputs` holds `boq: dict[UUID, BoqInput]` and `candidates: dict[UUID, list[CandidateInput]]`.
- Routes: `POST /tenders/{id}/estimates`, `GET /tenders/{id}/estimates`, `GET /estimates/{id}`, `GET /estimates/{id}/lines` as in spec section 6. The router takes `suppliers.lock_tender` on create, then `refuse_archived(..., fresh=True)`, then reads the current BoQ lines and confirmed matches.

- [ ] **Step 1: Write failing API tests** (use `quotation_helpers.py` and `review_helpers.py` to build a tender with a BoQ, two quotations and confirmed matches): create returns version 1 and one `unresolved` line per current non-rejected BoQ line in BoQ order; a second create while a draft exists is 409 `draft_exists`; create without pricing defaults is 409 `pricing_defaults_missing`; archived tender is 409 `tender_archived`; reviewer create is 403; lines list shows confirmed candidates only, nothing pre-selected, no price ordering (candidates in supplier-name order); org B gets 404 for org A's estimate.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** the above. `source_changed` is computed in `list_lines`/`get_estimate` against `LiveInputs`: stored `input_hash` differs from the hash of live inputs, or the chosen match id is absent from `live.candidates[boq_item_id]`, or the BoQ line is absent. An unreviewed BoQ line or quote item adds flag `unreviewed_source` and counts as unresolved. A candidate with `includes_vat is None` or `currency is None` is shown with `vat_basis_unknown` / `currency_missing` warnings.
- [ ] **Step 4: Add Review Focus test 1:** a confirmed candidate with `prices_include_vat` unknown and one with no currency each produce a blocked line when chosen (chosen in Task 6; here assert the candidate warnings).
- [ ] **Step 5: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 6: Commit** `feat: create estimate and read lines with live change detection`.

### Task 6: Price a line, refresh, settings (Sonnet; Opus review)

**Files:**
- Modify: `estimates/schemas.py`, `service.py`, `public.py`, `api/routers/estimates.py`
- Test: `backend/tests/test_estimates_api.py` (pricing section)

**Interfaces:**
- Produces: `LinePut` (`extra="forbid"`): exactly one of `match_suggestion_id: UUID`, `manual_unit_price: DecimalText`, `exclude_reason: str` (1 to 300 chars), plus optional `labour_rate`, `markup_override_percent`, `unit_mismatch_acknowledged: bool`. `EstimatePatch`: `currency`, `vat_rate`, `markup_basis`, `markup_percent`. Service: `price_line(session, ctx, line_id, body, live) -> EstimateLineDTO`, `refresh_line(session, ctx, line_id, live) -> EstimateLineDTO`, `patch_estimate(session, ctx, estimate_id, body, live) -> EstimateDTO`. Routes `PUT /estimate-lines/{id}`, `POST /estimate-lines/{id}/refresh`, `PATCH /estimates/{id}`. All take `SELECT ... FOR UPDATE` on the estimate row via `EstimateRepo.get_for_update`, the router takes the tender lock first. 409 `estimate_frozen` when status is not `draft`; 409 `stale_match` when the match is not in `live.candidates[line.boq_item_id]` or its BoQ item differs from the line's; manual price must be above 0; a chosen candidate with `unit_mismatch` requires `unit_mismatch_acknowledged=true` else 422.

- [ ] **Step 1: Write failing tests:** choose a confirmed match -> `priced`, amounts equal the golden maths; VAT-inclusive quote is divided by `1 + rate/100`; manual price works; exclude needs a reason; two sources in one body is 422; choosing an unconfirmed or another line's match is 409 `stale_match`; unknown VAT basis or missing currency on the chosen candidate -> line `unresolved` with flag `vat_basis_unknown` / `currency_missing` and no amounts; currency differing from the estimate's -> `currency_differs`; PATCH `vat_rate` recomputes every line; PATCH currency refused (409 `currency_locked`) once any line is priced; archived tender 409; reviewer 403; after editing the BoQ quantity the line shows `source_changed` and `refresh` clears it with the new quantity.
- [ ] **Step 2: Run;** expected FAIL.
- [ ] **Step 3: Implement** using `calc.py` for every figure; store `input_hash` as a SHA-256 of `(quantity, unit, unit_price_ex_vat, includes_vat, currency)` text.
- [ ] **Step 4: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 5: Commit** `feat: price, exclude, refresh estimate lines and edit settings`.

### Task 7: Status moves, readiness and races (Sonnet; Opus review)

**Files:**
- Modify: `estimates/service.py`, `public.py`, `api/routers/estimates.py`
- Test: `backend/tests/test_estimates_api.py` (status section), `backend/tests/test_estimates_races.py`

**Interfaces:**
- Produces: `readiness(estimate, lines, live) -> list[Blocker]` where `Blocker(line_id: UUID | None, code: Literal["unresolved","source_changed","unreviewed_source","no_lines"])`; `review_estimate`, `reopen_estimate`, `approve_estimate(session, ctx, estimate_id, live) -> EstimateDTO`. Routes `POST /estimates/{id}/review` (`review_data`), `/reopen` (`review_data`), `/approve` (`approve_estimate`). Review and approve need zero blockers, else 409 `estimate_not_ready` with `blockers` in the body; freezing stores the totals, actor and time; reopen is 409 `draft_exists` when another draft exists; an approved estimate cannot be reopened (409 `estimate_frozen`). Audit events per spec section 4.

- [ ] **Step 1: Write failing tests:** estimator cannot approve (403); project manager can approve a reviewed estimate but cannot reopen (403); approve with an unresolved line, a changed line or an `unreviewed_source` line is 409 `estimate_not_ready` listing blockers; frozen totals still equal after the BoQ is edited later; every line write on a frozen estimate is 409 `estimate_frozen`; approve and reopen audit rows exist with ids only; the highest approved version is reported by `GET /tenders/{id}/estimates` (`is_current_approved: true`); all-excluded estimate approves with zero totals (Review Focus 5).
- [ ] **Step 2: Race tests** (`test_estimates_races.py`, pattern of `test_match_decisions_concurrency.py`): two concurrent `POST /tenders/{id}/estimates` give one 201 and one 409 `draft_exists`; concurrent approve and `PUT /estimate-lines` end either with a frozen estimate and the line write refused, or the line written and approve refused for readiness, never a frozen estimate with a changed line.
- [ ] **Step 3: Run;** expected FAIL. **Step 4: Implement.** **Step 5: Run** tests, ruff, `lint-imports`; expected PASS.
- [ ] **Step 6: Commit** `feat: estimate review, approval and readiness gate`.

### Task 8: F1 sweep, OpenAPI, architecture docs (Haiku; Opus review)

**Files:**
- Modify: `backend/tests/test_fitness_functions.py` (register `estimate_id`, `estimate_line_id` in `known`, add request bodies for the new PUT/PATCH/POST routes, create estimates for org B), `backend/openapi.json`, `frontend/src/api/schema.d.ts`, `docs/architecture/architecture.md` (section 2: new `estimates` module, pure `compute` replaced by `estimates.calc`; table `estimates`/`estimate_lines`/`pricing_defaults`), `docs/architecture/diagrams/backend-components.md` (add `EST2[estimates]` depending only on kernel/db/audit)
- Test: the F1 sweep itself

- [ ] **Step 1:** Run the F1 sweep; it fails on the unregistered routes. **Step 2:** add the registrations and bodies. **Step 3:** regenerate OpenAPI (`export_openapi`, `npm run gen:api`). **Step 4:** edit the two architecture docs. **Step 5:** run the full backend suite, `lint-imports`, frontend lint and build; expected PASS. **Step 6: Commit** `test: F1 sweep and docs for the estimates module`.

### Task 9: Frontend API hooks and plain-words helpers (Haiku; Opus review)

**Files:**
- Create: `frontend/src/api/estimates.ts`, `frontend/src/api/estimates.test.tsx`, `frontend/src/lib/estimate-words.ts`, `frontend/src/lib/estimate-words.test.ts`

**Interfaces:**
- Produces hooks (follow `api/matches.ts` conventions): `usePricingDefaults()`, `useSavePricingDefaults()`, `useEstimates(tenderId)`, `useEstimate(id)`, `useEstimateLines(id, filters)` (paged, "Load more"), `useCreateEstimate(tenderId)`, `usePriceLine()`, `useRefreshLine()`, `usePatchEstimate()`, `useReviewEstimate()`, `useReopenEstimate()`, `useApproveEstimate()`; each mutation invalidates `useEstimate`, `useEstimateLines` and `useEstimates`. `estimate-words.ts`: `flagText(code: string): string` for every flag in spec section 4 and `blockerText(code: string): string` for the four blocker codes, and `errorText(code: string): string` for `estimate_frozen`, `estimate_not_ready`, `draft_exists`, `pricing_defaults_missing`, `stale_match`, `currency_locked`, `tender_archived`.

- [ ] **Step 1:** tests for each helper (every known code returns a non-empty sentence, an unknown code returns a generic fallback) and one hook test that a mutation invalidates the estimate queries. **Step 2:** run, expect FAIL. **Step 3:** implement. **Step 4:** `npx vitest run`, lint, build; expect PASS. **Step 5: Commit** `feat: estimate API hooks and plain-words helpers`.

### Task 10: Pricing defaults page (Sonnet; Opus review)

**Files:**
- Create: `frontend/src/app/(app)/settings/pricing/page.tsx`, `pricing-form.tsx`, `pricing-form.test.tsx`
- Modify: `frontend/src/components/app-shell.tsx` (a "Pricing" nav link shown only with `manage_pricing`, mirroring the Members link), its test

**Interfaces:**
- Consumes: `usePricingDefaults`, `useSavePricingDefaults`, `/me` permissions. Fields: currency (text, 3 letters), VAT rate (text), markup basis (radio: "On cost" / "On selling price"), default markup (text). A hint beside VAT rate offers "15 is the usual South African rate" as text only, never prefilled.

- [ ] **Step 1:** tests: renders empty with no prefilled VAT; saving sends decimal strings; rate 101, markup 100 on selling price and a 2-letter currency show messages and send nothing; non-admin sees no nav link and a read-only notice. **Step 2:** run, expect FAIL. **Step 3:** implement. **Step 4:** vitest, lint, build, PASS. **Step 5: Commit** `feat: pricing defaults page`.

### Task 11: Estimate page: settings, summary, line list (Sonnet; strings Haiku; Opus review)

**Files:**
- Create: `frontend/src/app/(app)/tenders/[id]/estimate/page.tsx`, `estimate-view.tsx`, `settings-card.tsx`, `summary.tsx`, `line-row.tsx`, plus a `.test.tsx` for each
- Modify: `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx` (link "Estimate")

**Interfaces:**
- Consumes: the hooks and helpers from Task 9. Produces: version picker, status badge with a visible "Draft" label for non-approved versions, settings card (currency, VAT, markup basis, default markup; editable only on a draft), summary (subtotal, markup, VAT, total; the "Incomplete: excludes N lines" label when `incomplete`; counts of unresolved and changed), BoQ lines grouped by section with candidates as unselected radio choices, blockers in plain words; a frozen estimate renders read-only with reviewer, approver and times. Empty and all-excluded estimates render zero amounts, never "NaN" or blank.

- [ ] **Step 1: Write failing tests:** no candidate is pre-selected and none is highlighted; candidates render in supplier-name order, not price order; incomplete label shown while unresolved lines exist and hidden when none; frozen view has no inputs or buttons; reviewer role sees no controls; all-excluded shows "0.00"; markup-basis choice present; a 409 `estimate_frozen` response shows its plain-words message.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement. **Step 4:** vitest, lint, typecheck, build, PASS. **Step 5: Commit** `feat: estimate page with settings, summary and lines`.

### Task 12: Line pricing controls and status actions (Sonnet; Opus review)

**Files:**
- Modify: `line-row.tsx`, `estimate-view.tsx`; Create: `line-controls.tsx`, `status-actions.tsx` with tests

**Interfaces:**
- Produces: choose-a-candidate (radio; a candidate with a unit mismatch asks for an acknowledge tick before it can be chosen), manual price (text, decimal validation), exclude with required reason, optional labour rate and markup override fields (text), "Refresh" on changed lines; optimistic update with per-row rollback like the 5a comparison page; actions "Mark reviewed", "Approve", "Reopen", "New version" shown by permission and state; Approve shows the blocker list returned by a 409 `estimate_not_ready` and the 5a-style note.

- [ ] **Step 1: Failing tests:** choosing sends `match_suggestion_id`; unit-mismatch candidate needs the tick; invalid decimal text sends nothing; exclude without reason sends nothing; a 409 `stale_match` rolls the row back and reloads candidates; Approve hidden for estimator, Reopen hidden for project manager; blockers listed on `estimate_not_ready`; "New version" appears only when no draft exists and calls create.
- [ ] **Step 2:** run, expect FAIL. **Step 3:** implement. **Step 4:** vitest, lint, typecheck, build, PASS. **Step 5: Commit** `feat: estimate line controls and status actions`.

### Task 13: Real-stack gate and docs (Sonnet drives; Haiku edits docs; Opus whole-branch review)

**Files:**
- Modify: `docs/plan.md` (Slice 5 status, 5b result), `docs/known-limitations.md` (spec section 11 items), `docs/spikes/` (a short `slice-5b-gate.md` with the journey result)

- [ ] **Step 1:** rebuild the Docker stack (`docker compose up --build`), set pricing defaults as admin, drive the spec section 1 exit-gate journey (steps 1 to 6) in a real browser through Caddy; record each step's result and anything that failed in `slice-5b-gate.md`; fix defects with tests first.
- [ ] **Step 2:** run the full backend suite, `lint-imports`, ruff, frontend lint, typecheck, build, vitest; record counts.
- [ ] **Step 3 (Haiku):** update the three docs with the exact outcome; do not claim anything not run.
- [ ] **Step 4:** Opus reviews the whole branch against the spec; fix findings by the same test-first rule.
- [ ] **Step 5: Commit** `docs: slice 5b gate result and known limitations`.

---

## Self-review

- **Spec coverage:** calculation and rounding (T1); data model, no FKs, one draft index (T2); permissions (T3); pricing defaults and markup basis option (T4, T10); create, lines, live change detection, incomplete label, provisional-sum exclusion via `exclude_reason` (T5, T6, T11); labour (T1, T6, T12); VAT conversion, blocked currency/VAT lines (T5, T6); unreviewed inputs block (T5, T7); status flow, reopen rules, highest approved (T7); concurrency (T7); F1/F3, openapi, architecture docs (T2, T8); UI (T9 to T12); gate and docs (T13).
- **Deliberate deviation from spec section 4:** the spec said `estimates` reads BoQ lines and matches through `estimating.public` and `suppliers.public`; this plan keeps the module free of those imports and has the router map the DTOs to plain inputs, which also avoids any cycle. Flag for the reviewer.
- **Type consistency:** `LiveInputs`, `BoqInput`, `CandidateInput`, `LinePut`, `EstimatePatch`, `Blocker` are defined once (T5, T6, T7) and reused by name; hook and helper names are defined in T9 and used in T10 to T12.
