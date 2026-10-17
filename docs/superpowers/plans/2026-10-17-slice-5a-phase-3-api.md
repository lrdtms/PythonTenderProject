# Slice 5a, Phase 3: Suppliers, Quotations and Matching API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The REST API for suppliers, quotations, quotation items and match suggestions: list, edit, review, confirm/reject/reset one match, "confirm all clear" in bulk, re-run matching, merge suppliers; every write safe against concurrent extraction and matching, org-scoped, archived-tender-safe and audited. Closes the Phase 2 hand-offs.

**Architecture:** Thin FastAPI routers (`app/api/routers/suppliers.py`, `quotations.py`, `matches.py`) that orchestrate `documents`/`estimating`/`suppliers`/`jobs` through their `public.py`, following `routers/review.py`. All decision logic and SQL stay in the `suppliers` module (service + repos). One tender-level advisory lock (`MatchRepo.lock_tender`) serialises matching, decisions and extraction handlers; lock order is always **tender advisory lock first, then extraction-run row locks**.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, pytest (backend under `backend/`, `uv run`); openapi export + `openapi-typescript` for the frontend types.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-5a-suppliers-matching-design.md` section 6 (API), section 3 (data rules), section 5 (persistence). Phase 1 and 2 are on this branch (`feat/slice-5a-phase-2-matching`; phases 3 to 5 continue on it). Later phases: 4 comparison UI, 5 suppliers page and gate.

## Global Constraints

- **Permissions:** reads need `read`; every write needs `review_data` (admin and estimator). Unknown or other-organisation ids give **404** (F1). Writes on an archived tender give **409 `tender_archived`**. A write that targets a row a re-run replaced gives **409 `row_replaced`** (same as Slice 4). Match conflicts give **409 `match_conflict`**. Duplicate supplier names give **409 `supplier_exists`**.
- **Locking:** every write that changes match rows or the items they point at takes `MatchRepo.lock_tender(tender_id)` FIRST; item review writes then also take `pipeline.lock_runs(version_id, "quotation")` as the BoQ review routes do. The `extract_boq` and `extract_quotation` handlers take the tender lock first thing (before reading protected ids / storing). Lock order everywhere: tender advisory lock, then run row locks. `match_suppliers` already locks inside `match_tender`; move its input reads inside the lock (see Task 3).
- **Current versions only:** list and bulk operations consider only the tender's current document versions and skip rejected BoQ lines and rejected quotation items; decisions on a suggestion whose items are not current give 409 `stale_match`.
- **No floats for money:** decimals are JSON strings validated by the existing pattern (`^-?\d{1,14}(\.\d{1,4})?$`); the match `score` in DTOs is a JSON number (it is not money). Never expose another organisation's data; DTOs carry names only through the existing reviewer-name join.
- **Audit:** every write records `audit.record(...)` with ids and field names only (never descriptions, supplier names or document text).
- **Lowest price is never selected, highlighted or sorted first:** no endpoint orders or filters by price.
- **Tests:** `cd backend && DB_HOST_PORT=5433 uv run pytest -q` (about 6 minutes now; iterate on single files; never run two full suites at once); `uv run ruff check . && uv run ruff format --check . && uv run lint-imports`. After the API changes: `uv run python -m app.api.export_openapi` (writes `frontend/openapi.json`), then in `frontend/`: `npm run gen:api`, `npm run typecheck`, `npm test`. The F1 sweep must stay green and must exercise every new route with a real foreign row (register ids in its `known` map and add bodies to `REQUESTS`).
- **Shell:** the Bash tool here mishandles long heredocs: create files with the editor tools and run short commands.
- **Branch:** `feat/slice-5a-phase-2-matching` (current). Commit messages end with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. Two requests racing on the same tender (confirm vs confirm for two candidates of one BoQ line and supplier; confirm vs BoQ re-extraction; matching vs decision): never two confirmed rows for one (BoQ line, supplier), never a decided match cascade-deleted by a concurrent extraction (Tasks 1 to 3).
2. Switching a quotation's supplier or merging suppliers must update every `match_suggestions.supplier_id` and must not create a second confirmed pair for one (BoQ line, supplier): 409 `match_conflict`, nothing half-applied (Tasks 1, 2).
3. `confirm-clear` confirms only `clear` + `suggested` rows of current versions, never an ambiguous one, never when a confirmed match for that (BoQ line, supplier) exists, and reports exact counts; calling it twice confirms nothing the second time (Task 3).
4. Archived tender: every write refused (409), reads still work; reviewer and project-manager roles get 403 on every write and 200 on reads (all tasks).
5. A suggestion whose quotation item or BoQ line was replaced, rejected or superseded by a newer version: lists hide it, decisions give 409 `stale_match` or 404, never a 500 (Task 3).

---

### Task 1: Suppliers API and the lock/race foundations

**Files:**
- Modify: `backend/app/modules/suppliers/repo.py`, `service.py`, `schemas.py`, `public.py`; `backend/app/worker/handlers.py` (take the tender lock in `extract_boq` and `extract_quotation`)
- Create: `backend/app/api/routers/suppliers.py`; modify `backend/app/api/main.py` (include router)
- Test: `backend/tests/test_suppliers_api.py`, `backend/tests/test_supplier_races.py`

**Interfaces (Produces):**
- Schemas (`suppliers/schemas.py`): `SupplierDTO(id, name, notes, quotation_count: int, created_at)`, `SupplierCreate(name: str 1-200, notes: str|None <= 2000)`, `SupplierPatch(name: str|None 1-200, notes: str|None <= 2000)` (extra forbidden, at least one field, NUL rejected), `SupplierMerge(into_id: UUID)`.
- Repo: `SupplierRepo.get_or_create(name, name_key) -> tuple[Supplier, bool]` implemented with `INSERT ... ON CONFLICT (organisation_id, name_key) DO NOTHING RETURNING id` followed by a select (race-safe; used by `store_quotation` instead of by_key + add); `SupplierRepo.list_with_counts()`; `SupplierRepo.rename(supplier, name, key)` raising `Conflict(code="supplier_exists")` when another supplier of the organisation has the key.
- Service: `list_suppliers(session, ctx)`, `get_supplier(session, ctx, id)`, `create_supplier(session, ctx, body)`, `update_supplier(session, ctx, id, body)`, `merge_suppliers(session, ctx, source_id, into_id)` and `tenders_of_supplier(session, ctx, supplier_id) -> set[UUID version ids]` (document version ids of its quotations, so the router can resolve and lock tenders). All exported from `suppliers/public.py`. `merge_suppliers` runs with the tender locks already held by the router; it moves `quotations.supplier_id`, updates `match_suggestions.supplier_id` for the moved quotations' items, and raises 409 `match_conflict` (nothing changed) when the move would give one BoQ line two confirmed matches for the target supplier; then deletes the source supplier; audit `supplier_merged` with both ids.
- Routes (`/api/v1`): `GET /suppliers`, `POST /suppliers` (201), `GET /suppliers/{supplier_id}`, `PATCH /suppliers/{supplier_id}`, `POST /suppliers/{supplier_id}/merge` (body `SupplierMerge`, returns the target `SupplierDTO`; 409 `merge_conflict`-style uses `match_conflict`; merging into itself is 422 "Choose a different supplier."; unknown `into_id` of another organisation is 404).
- Router `merge`: resolve the affected tenders (`documents.processing_info(version_id).tender_id` for each version from `tenders_of_supplier`), refuse if ANY is archived (409 `tender_archived`), take `MatchRepo.lock_tender` for each tender id in sorted order, then call the service.
- Handlers: `suppliers.lock_tender(session, ctx, tender_id)` (new public wrapper around `MatchRepo.lock_tender`) is called first in `extract_boq` and `extract_quotation` (tender id from `documents.processing_info(...).tender_id`), before `lock_runs` and before `decided_boq_item_ids`.

- [ ] **Step 1: Write the failing tests**

`test_suppliers_api.py` (use `tests.conftest` helpers `register`, `add_member`, `make_tender`, `upload`, fixtures from `tests/fixtures/packs/pack02`, and `tests.test_extraction_pipeline.drain`): list shows supplier names with quotation counts after uploading two pack02 quotations (counts 1 and 1; Greenvale appears once even after a second Greenvale quotation from pack03 → count 2); create (201) then duplicate name with different case/suffix ("Acme (Pty) Ltd" vs "acme") → 409 `supplier_exists`; patch renames and updates the key (rename into an existing name → 409), notes can be set and cleared; empty patch → 422; NUL → 422; merge moves quotations (counts add up), deletes the source, a confirmed pair collision → 409 `match_conflict` with both suppliers unchanged (build the collision by inserting two confirmed `MatchSuggestion` rows for the same BoQ item via `session_scope`); merge into self → 422; reviewer and project_manager roles: 200 on GETs, 403 on POST/PATCH/merge; archived tender affected by the merge → 409 `tender_archived`; foreign ids → 404 (F1 is also extended in Task 3).
`test_supplier_races.py`: (1) two threads (or two sessions in a barrier) calling `SupplierRepo.get_or_create` with the same new name get the same supplier and exactly one row exists; (2) `store_quotation` for two different versions of one tender whose header names normalise to the same new supplier, run concurrently, both succeed and share one supplier (previously an IntegrityError); (3) a decision-like transaction holding `lock_tender` blocks `extract_boq`'s `suppliers.lock_tender` until it commits (use two connections and `pg_try_advisory_xact_lock` to assert the second cannot take it while the first holds it).

- [ ] **Step 2: Run, see them fail**

Run: `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_suppliers_api.py tests/test_supplier_races.py -q`
Expected: FAIL (routes and functions missing).

- [ ] **Step 3: Implement** repo/service/schemas/public/router/handlers as specified. Router pattern: copy `routers/review.py` (`Ctx`, `DbSession`, `_writable`-style archived checks resolve through `documents.processing_info(session, ctx, version_id).tender_archived`). `name_key` for create/rename is `suppliers.normalise_name(name)` with the same fallbacks as `store_quotation` (empty key → `name.lower().strip()`, never the shared "unknown supplier"); display name is the trimmed given name (no title-casing: the user typed it).

- [ ] **Step 4: Run the new tests and the existing suppliers/pipeline tests** (`tests/test_suppliers_store.py`, `tests/test_quotation_pipeline.py`, `tests/test_matching_pipeline.py`, `tests/test_repository_contract.py`), then lint. Fix regressions (the repository-contract test must be extended with the new repo methods and cross-org assertions for `list_with_counts`, `rename`, `get_or_create`).

- [ ] **Step 5: Commit** `feat: suppliers API, race-safe supplier creation and tender locks in extraction handlers`.

---

### Task 2: Quotations and quotation items

**Files:**
- Modify: `backend/app/modules/suppliers/repo.py`, `service.py`, `schemas.py`, `public.py`
- Create: `backend/app/api/routers/quotations.py`; modify `backend/app/api/main.py`
- Test: `backend/tests/test_quotations_api.py`, `backend/tests/test_quotation_items_review.py`

**Interfaces (Produces):**
- Schemas: `QuotationDTO(id, document_version_id, supplier_id, supplier_name, reference, quote_date, valid_until, currency, prices_include_vat, flags: list[str], item_count: int, created_at)`; `QuotationPatch(supplier_id: UUID|None, reference: str|None <= 100, quote_date: date|None, valid_until: date|None, currency: str|None (3 upper-case letters), prices_include_vat: bool|None)` with `extra="forbid"`, at least one field set; `QuotationItemDTO(id, quotation_id, document_version_id, run_id, position, description, sku, unit, quantity: str|None, unit_price: str|None, raw_unit, raw_quantity, raw_price, flags, page_number, sheet, cell_range, review_status, corrected_value, original_value, reviewed_by, reviewed_by_name, reviewed_at)`; `QuotationItemPatch(description 1-2000, sku <= 100, unit <= 30, quantity DecimalText, unit_price DecimalText)` all optional, nullable except description, `extra="forbid"`, NUL rejected.
- Service: `list_quotations(session, ctx, version_ids) -> list[QuotationDTO]` (ordered by version order given, then created_at), `get_quotation_tender_version(session, ctx, quotation_id) -> UUID` (the document version id, so the router can resolve the tender and lock), `update_quotation(session, ctx, quotation_id, patch) -> QuotationDTO` (switching `supplier_id`: target must exist in the organisation, else 404; updates `match_suggestions.supplier_id` of all matches of the quotation's items in the same transaction; 409 `match_conflict` when the move would create a second confirmed match for one (BoQ line, target supplier); header flags recomputed from the resulting fields with the existing `_header_flags` logic, keeping the supplier-name flag; audit `quotation_updated` with field names), `list_quotation_items(session, ctx, version_id, limit, offset)`, `quotation_item_version(session, ctx, item_id) -> UUID` (version id for `lock_runs`), `review_quotation_item(session, ctx, item_id, action, patch)` with exactly the Slice 4 semantics of `estimating.review_item` (original value immutable, corrections recorded in `corrected_value` as strings, status `confirmed|corrected|rejected`, `reviewer`/time recorded, correcting `quantity`/`unit_price` clears `missing_quantity`/`quantity_unparsed`/`missing_price`/`price_unparsed`/`ambiguous_separator`/`zero_price`/`negative_price`/`zero_quantity` as appropriate, audit ids and field names only, 409 `row_replaced` when the row vanished after the lock).
- Routes: `GET /tenders/{tender_id}/quotations` (current versions of kind `quotation` only; the router resolves them via `documents.list_documents`), `PATCH /quotations/{quotation_id}`, `GET /document-versions/{version_id}/quotation-items` (`limit` 1-1000 default 200, `offset`), `PATCH /quotation-items/{item_id}`, `POST /quotation-items/{item_id}/confirm`, `POST /quotation-items/{item_id}/reject`. Item review writes: archived check, `lock_tender`, `pipeline.lock_runs(version, "quotation")`, then the service; reviewer names via `with_reviewer_names`. A `reject` or a `PATCH` of description/sku/unit/quantity/unit_price enqueues a tender matching job (`jobs.enqueue(session, ctx, documents.MATCH_SUPPLIERS_JOB, "tender", tender_id, {})` through the public APIs) so suggestions follow the edit; `confirm` does not.
- The spec section 6 route `GET /quotations/{id}/items` is NOT built (the version-based list serves the UI); update the spec table accordingly.

- [ ] **Step 1: Write the failing tests**

`test_quotations_api.py`: list shows both pack02 quotations with supplier names, `item_count` 15 and 15, `prices_include_vat` false/null as parsed, flags (the Greenvale xlsx carries `VAT_UNKNOWN`); only current versions: upload a new version of one quotation document and the list shows the new one only; `PATCH` reference/dates/currency (currency "zar" → 422, "ZAR" ok; valid_until before quote_date is allowed but not rejected); setting `currency` removes `NO_CURRENCY` from flags, clearing it adds it; supplier switch to another supplier updates the quotation and every `match_suggestions.supplier_id` of its items (insert suggestions first via `match_tender` or the worker) and leaves counts right; a switch that would create two confirmed matches for one (BoQ line, supplier) → 409 `match_conflict`, nothing changed; unknown supplier id of another organisation → 404; reviewer/project_manager → 403 on PATCH, 200 on GET; archived tender → 409 on PATCH.
`test_quotation_items_review.py`: list paging (`limit`, `offset`, ordered by `source_order, position`); confirm/reject/PATCH transitions and field recording (`original_value` unchanged across edits, `corrected_value` holds only changed fields as strings, `reviewed_by_name` filled); decimal validation (JSON number → 422, `"1,500"` → 422, 5 decimals → 422); correcting `unit_price` clears `price_unparsed`; PATCH enqueues exactly one `match_suppliers` job for the tender (and `confirm` enqueues none); a `row_replaced` race: delete the row between lookup and lock (simulate by re-extracting while holding no lock, or by deleting the row in a second session after `quotation_item_version` is resolved — mirror `tests/test_review_boq.py`'s approach); roles and archived behaviour as for BoQ review (`tests/test_review_boq.py` is the template).

- [ ] **Step 2: Run, see them fail.** `cd backend && DB_HOST_PORT=5433 uv run pytest tests/test_quotations_api.py tests/test_quotation_items_review.py -q`

- [ ] **Step 3: Implement** schemas, repo methods, service, routes. Extend `tests/test_repository_contract.py` for the new repo methods with cross-org assertions.

- [ ] **Step 4: Run the new tests plus** `tests/test_suppliers_api.py tests/test_quotation_pipeline.py tests/test_matching_persistence.py tests/test_repository_contract.py`; lint.

- [ ] **Step 5: Commit** `feat: quotations and quotation item review API`.

---

### Task 3: Match suggestions API, F1 sweep, contract regeneration, hand-offs

**Files:**
- Modify: `backend/app/modules/suppliers/repo.py`, `service.py`, `schemas.py`, `public.py`; `backend/app/worker/handlers.py` (move the match job's reads inside the lock); `backend/app/api/routers/review.py` (re-match trigger on BoQ edit/reject)
- Create: `backend/app/api/routers/matches.py`; modify `backend/app/api/main.py`
- Modify: `backend/tests/test_fitness_functions.py`, `backend/tests/review_helpers.py` (seed helper for suppliers/quotations/matches), `backend/tests/test_openapi_contract.py`
- Modify (generated): `frontend/openapi.json`, `frontend/src/api/schema.d.ts`
- Test: `backend/tests/test_matches_api.py`, `backend/tests/test_match_decisions_concurrency.py`

**Interfaces (Produces):**
- Schemas: `MatchSupplierRef(id, name)`; `MatchBoqRef(id, item_no, section, description, unit, quantity: str|None)`; `MatchQuoteRef(id, quotation_id, description, sku, unit, quantity: str|None, unit_price: str|None, valid_until: date|None)`; `MatchSuggestionDTO(id, status, classification, rank: int, score: float, evidence: dict, supplier: MatchSupplierRef, quotation_item: MatchQuoteRef, decided_by, decided_by_name, decided_at)`; `MatchLineDTO(boq: MatchBoqRef, suggestions: list[MatchSuggestionDTO])`; `ConfirmClearResult(confirmed: int, skipped: int)`.
- Service (`suppliers`): `list_match_lines(...)` is assembled by the router: the router loads the tender's current BoQ lines via `estimating.list_boq_items` (all pages of current `boq`/`tender_document` versions, skipping rejected lines), applies the BoQ-line paging (`limit` 1-500 default 100, `offset` over BoQ lines in document order), and asks `suppliers.suggestions_for(session, ctx, boq_ids, quote_version_ids, status, classification, supplier_id)` which returns suggestions joined with quotation item/quotation/supplier data, restricted to current quotation versions and non-rejected quotation items, ordered by `(boq_item_id order given, supplier name, rank)`. Lines without suggestions are returned with an empty list (so the UI can show "no match"). Query filters on the endpoint: `status`, `classification`, `supplier_id`, `only_with_suggestions` (bool, default false).
- `suppliers.decide(session, ctx, suggestion_id, action: "confirm"|"reject"|"reset", current_quote_version_ids, current_boq_ids)` called with the tender lock held: 404 if unknown; 409 `stale_match` if its quotation item's version or its BoQ item is not in the current sets; `confirm`: 409 `match_conflict` if another confirmed match exists for the same (BoQ line, supplier), else status `confirmed`, `decided_by`, `decided_at`; `reject`: status `rejected`; `reset`: back to `suggested` (clears `decided_*`). Any state to any other except a no-op returns the row unchanged. Audit `match_confirmed|match_rejected|match_reset` with ids only. Returns the same `MatchSuggestionDTO`.
- `suppliers.confirm_clear(session, ctx, current_quote_version_ids, current_boq_ids) -> ConfirmClearResult`: confirms every row with `status == 'suggested'` and `classification == 'clear'` whose BoQ line and quotation item are current, skipping (counted in `skipped`) any whose (BoQ line, supplier) already has a confirmed match or would collide with another row confirmed in the same call; one audit event `match_confirm_clear` with the counts.
- Routes: `GET /tenders/{tender_id}/match-suggestions` (returns `list[MatchLineDTO]`), `POST /match-suggestions/{suggestion_id}/confirm|reject|reset`, `POST /tenders/{tender_id}/match-suggestions/confirm-clear`, `POST /tenders/{tender_id}/match` (202 `JobDTO`, requires `review_data`, 409 `tender_archived`). Decision routes: resolve the tender (`suppliers.suggestion_tender_version(session, ctx, suggestion_id) -> UUID` returns the quotation item's version id → `documents.processing_info(...).tender_id`), archived check, `lock_tender`, then compute the current sets and call the service.
- `review.py`: after `correct_boq_item` and `reject_boq_item` enqueue the tender's matching job (same call as in Task 2).
- Handlers: `match_suppliers` takes `lock_tender` BEFORE `_tender_inputs` (the reads), not only inside `match_tender`; `match_tender` keeps taking it (re-taking within a transaction is harmless).
- Test helpers: `review_helpers.seed_supplier_rows(actor, version_id, job_id) -> dict` returning `{"supplier_id", "quotation_id", "quotation_item_id", "match_suggestion_id"}` for org B (a quotation run, `store_quotation`, one `suggested` `MatchSuggestion` against the BoQ item seeded by `seed_review_rows`); extend the F1 sweep: `known |= seed_supplier_rows(...)`, add `forbidden` markers (the seeded supplier name and quotation item description), request bodies for `PATCH /suppliers/{supplier_id}` (`{"name": "hijacked"}`), `POST /suppliers/{supplier_id}/merge` (`{"into_id": <a random uuid>}` — still 404 because the source is foreign), `PATCH /quotations/{quotation_id}` (`{"reference": "hijack"}`), `PATCH /quotation-items/{quotation_item_id}` (`{"description": "hijacked"}`); extend the needles list with `suppliers`, `quotations`, `quotation-items`, `match-suggestions`.

- [ ] **Step 1: Write the failing tests**

`test_matches_api.py` (worker end to end with pack02: upload BoQ + two quotations, `drain()`): the list returns one `MatchLineDTO` per current BoQ line (20), lines without suggestions have `suggestions == []`; each suggestion carries supplier ref, quotation item ref with `unit_price` as a string, evidence with `warnings`; filters (`classification=clear`, `status`, `supplier_id`, `only_with_suggestions`) and BoQ-line paging (`limit=5&offset=5`); NO endpoint sorts or filters by price (assert the OpenAPI params do not include a price parameter and that two quotes with different prices keep stable order by supplier name then rank); confirm → status `confirmed`, `decided_by_name`; confirming a second candidate for the same (BoQ line, supplier) → 409 `match_conflict`; reject then reset then confirm; confirming an `ambiguous` suggestion one by one works; `confirm-clear` confirms exactly the number of `clear` rows (compare with the list), reports `skipped` for collisions, a second call returns `{"confirmed": 0, ...}`, never touches ambiguous rows; a stale suggestion (replace the quotation document version, then decide on the old suggestion) → 409 `stale_match`; the list hides suggestions of superseded versions (the Phase 2 carry-over (a)); rejecting a BoQ line removes its lines/suggestions from the list; `POST /tenders/{id}/match` → 202 + a job that succeeds after `drain()`, second POST while queued returns the same job; archived tender → 409 on every write, reads fine; reviewer/project_manager 403 on writes, 200 on reads; BoQ `PATCH` and `reject` through `/boq-items/...` enqueue a matching job.
`test_match_decisions_concurrency.py`: (1) two sessions confirm two different candidates of the same (BoQ line, supplier) at the same time (use threads with `TestClient` or two `session_scope` blocks and a barrier): exactly one succeeds, the other gets 409 `match_conflict`, one confirmed row remains; (2) a decision holding the tender lock and an `extract_boq` re-run started at the same time: the re-run waits, and afterwards the decided match and its BoQ item survive with the same ids; (3) `match_suppliers` and `confirm-clear` racing: no duplicate confirmed rows, no exceptions.
Update `test_fitness_functions.py` per the interface notes; the sweep must report every new route swept (`swept == schema_count`).

- [ ] **Step 2: Run, see them fail**, then implement repo/service/schemas/routes/handler change/review hook/test helpers.

- [ ] **Step 3: Regenerate the contract and frontend types**

```bash
cd backend && uv run python -m app.api.export_openapi
cd ../frontend && npm run gen:api && npm run typecheck && npm test
```

Expected: typecheck and tests pass (the new generated types are additive). Add the new paths to `test_openapi_contract.py::test_the_review_routes_are_in_the_contract`.

- [ ] **Step 4: Full backend suite once, lint, import rules**

`cd backend && DB_HOST_PORT=5433 uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run lint-imports`

- [ ] **Step 5: Docs**: `docs/known-limitations.md` (Slice 5a: remove the items now closed — running-job re-trigger via `POST /tenders/{id}/match`, current-version filtering, tender lock in extract handlers, supplier merge/switch — and keep the multi-worker note: a match job running when another trigger arrives is not repeated until the next trigger), spec section 6 table (grouped list response, no `GET /quotations/{id}/items`, `reset` and `confirm-clear` semantics, error codes), `docs/plan.md` Slice 5 row (Phase 3 sentence).

- [ ] **Step 6: Commit** `feat: match suggestions API, decisions with tender locking, contract regeneration`.
