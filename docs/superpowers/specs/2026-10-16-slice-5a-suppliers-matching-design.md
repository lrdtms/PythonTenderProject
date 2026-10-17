# Slice 5a: Suppliers, quotations and matching (design)

**Date:** 2026-10-16 · **Branch:** `feat/slice-5a-suppliers-matching` (to be created) · **Status:** draft for owner review
**Authority:** `docs/plan.md` section 3 (Slice 5), `docs/prd.md` FR-34 to FR-37, FR-58, FR-62, FR-63, section 10 (last paragraphs), section 8 (Match Suggestions), `docs/architecture/architecture.md` (modules `suppliers`, `extraction`, `pipeline`; ADR-0006 stages; fitness functions F1, F3, F7), the Slice 4 spec for review semantics. Frontend rules: `frontend/AGENTS.md`.

Slice 5 is split in two. **5a (this spec)** gets quotation items out of supplier quotations, links them to suppliers and suggests which quotation item prices which BoQ line, with a human deciding every match. **5b (a later spec)** builds the Decimal estimate (markup, VAT, versions, draft/reviewed/approved) on top of confirmed matches. 5a is demoable and valuable without 5b.

## 1. Goal and scope

An estimator uploads supplier quotations (PDF or XLSX). Each is read into quotation items with unit prices, attached to a supplier, and compared with the tender's BoQ. For every BoQ line the system lists ranked candidate items from each supplier with the evidence for the match. The estimator confirms or rejects. The AI suggests and a human decides (BR-01); the lowest price is never auto-selected (FR-37).

**Exit gate (real Docker stack through Caddy, synthetic pack with two quotations):**

1. Upload the two quotations of a pack; their items appear with header details and a supplier created from the header name.
2. Run matching; the comparison page lists each BoQ line with candidates per supplier, prices side by side, no cheapest highlight and nothing pre-selected.
3. Ambiguous and unit-mismatch suggestions show why and can only be confirmed one at a time; "confirm all clear matches" skips them.
4. Confirm, reject and reload; decisions persist. Re-run matching and extraction: decided pairs and reviewed items survive.
5. Reviewer and project-manager roles see everything and no controls (API 403 on writes).
6. The scoring script reports top-suggestion accuracy of at least 80% among suggested, every ambiguous or unit-mismatch case flagged, and zero conflicting pairs shown as clear.
7. F1 green for every new route; F3/F2 still green; backend and frontend CI green.

**Out of scope:** totals, markup, VAT, choosing a winning supplier (5b); manual entry of quotation items for scanned quotations (`QUOTE_NEEDS_MANUAL_ENTRY`, listed as a known limitation like scanned BoQs); unit conversion (roll to metres); any LLM in matching or quotation parsing; supplier contact management beyond name and notes; Excel/PDF exports (Slice 6).

## 2. Decisions taken

| Decision | Choice |
|---|---|
| Split | Two specs: 5a suppliers, quotations, matching; 5b estimate |
| Supplier link | Parsed from the quotation header: find by normalised name or create; fixable in review (rename, switch, merge) |
| Parsing and matching | Deterministic (FR-63 and FR-55): reuse the BoQ table machinery; no LLM, no embeddings |
| Permissions | `review_data` (admin and estimator) for every write; `read` for the rest. No new permission |
| Decisions | Every match is a human decision; bulk confirm only for clear matches, never ambiguous ones |

## 3. Data model

All tables carry `organisation_id` with composite foreign keys, like `boq_items` (migration 0005; F3 target-column check applies).

- `suppliers`: id, organisation_id, name, `name_key` (normalised: lower-case, punctuation and legal suffixes such as "pty", "ltd", "(pty) ltd" stripped), notes, created_at. Unique on (organisation_id, name_key).
- `quotations`: id, organisation_id, `document_version_id`, `run_id`, supplier_id, reference, quote_date, valid_until, currency (default none; missing is flagged, never assumed), `prices_include_vat` (true, false or unknown), flags, created_at. One quotation per document version in 5a (a document with several quotations is a known limitation).
- `quotation_items`: id, organisation_id, quotation_id, position, `source_order`, description, `sku`, unit, quantity, `unit_price` (Numeric(18,4), NULL when unreadable, never 0), raw_unit, raw_quantity, raw_price, flags, page_number, sheet, cell_range, review_status, original_value, corrected_value, reviewed_by, reviewed_at. Same review semantics as `boq_items` (original snapshot immutable, corrections recorded, confirm/reject, any state to any other).
- `match_suggestions`: id, organisation_id, boq_item_id, quotation_item_id, score (Numeric(5,4)), `classification` (`clear` or `ambiguous`), `evidence` JSONB (signals, scores, warnings; ids and numbers only, no document text beyond what the rows hold), status (`suggested`, `confirmed`, `rejected`), decided_by, decided_at, created_at. Also `supplier_id` (denormalised from the quotation so the rule below is a real constraint; updated in the same transaction when a quotation's supplier is switched or suppliers are merged). Unique on (boq_item_id, quotation_item_id). Partial unique index on (boq_item_id, supplier_id) WHERE status = 'confirmed': at most one confirmed candidate per BoQ line and supplier, enforced by the database (the service also takes the tender lock so the client gets 409 `match_conflict` rather than an integrity error).
- Extraction runs gain kind `quotation`; `ROUTING["quotation"] = (EXTRACT_QUOTATION_JOB,)`, and a new `match_suppliers` job type.

## 4. Quotation extraction

`extraction.parse_quotation(pages, tables) -> QuotationResult` (pure, no I/O), reusing the table finder, header detection, number parsing and unit normalisation of `parse_boq`:

- **Header block** (page 1 text, or the first rows of the first sheet): supplier name, quotation reference, date, valid until, currency, and the VAT note ("Prices exclude value-added tax unless stated"). Each field that is absent is `None` with a flag (`NO_REFERENCE`, `NO_VALIDITY`, `NO_CURRENCY`, `VAT_UNKNOWN`), never a guess.
- **Item table:** columns for description, unit, quantity and unit price found by header-word synonyms ("unit price", "rate", "price each"; "qty", "quantity"). A trailing `[SKU-1234]` or "Code:"/"Ref:" token is lifted out of the description into `sku`. Wrapped description lines (the code sitting on the next row) are joined. Money uses the same comma and separator rules as quantities, including the `ambiguous_separator` flag. Unreadable price gives `unit_price = NULL` and `price_unparsed`.
- **Scanned PDFs** follow BoQ: `QUOTE_NEEDS_MANUAL_ENTRY` warning, no auto-extraction (OCR numbers are not trusted for money).
- **Pipeline:** `extract_quotation` job (stage after `ingest`, ADR-0006), a run record like the other kinds, `replace_unreviewed` for items (never touches reviewed items; duplicate-of-reviewed warning), supplier find-or-create in the same transaction, then `match_suppliers` enqueued for the tender. Item counts and warnings appear in the existing extraction status panel as a third kind.

## 5. Matching

Deterministic and pure: `suppliers.matching.suggest(boq_items, quotation_items) -> list[Suggestion]` with no database access; the service loads rows and persists results.

**Signals per pair, each recorded in `evidence`:**

- **Spec tokens:** extracted from both descriptions as normalised (number, unit) pairs and structural tokens (`400 A`, `2.5 mm2`, `3C+E`, `IP65`, `100 W`, `1200 mm`, `6 kA`, `3-pole`, `12-way`). Agreement raises the score. A **conflict** (same quantity kind with different values, e.g. `1.5 mm2` against `2.5 mm2`) marks the pair `spec_conflict`; a conflicting pair is never `clear` and is dropped when its score is below the ambiguity floor.
- **Text similarity:** tokens lower-cased, punctuation and stopwords removed, then a sequence ratio over sorted tokens (stdlib `difflib`). Candidate pairs are narrowed first with a token index so cost stays roughly linear.
- **Codes:** a shared SKU, model or standard code (e.g. "SANS 10142") adds a bonus when both sides carry one. Tender BoQ lines seldom have supplier SKUs; absence is neutral.
- **Unit:** normalised units; equal is positive; different is `unit_mismatch` and forces `ambiguous`. No conversion.
- **Price and date are context only:** the evidence carries unit price, quote date and validity; a quote that expires before the tender closes gets `quote_expires_before_closing`. Price never changes a score.

**Scoring and classification.** `score = 0.5*spec + 0.4*text + 0.1*unit`, plus a capped code bonus (weights and thresholds live in `suppliers/matching_config.py`, tuned against the ground truth and documented in the scoring report). The top three candidates per BoQ line per supplier are kept, with their `rank` stored in `evidence`. A suggestion is `clear` when all of these hold:

- score >= `SUGGEST_MIN`, no `spec_conflict`, no `unit_mismatch`;
- **`clear_text_min`:** text similarity >= 0.5, so a pair is never clear on spec agreement alone;
- **`spec_multi_value`:** neither side lists several values of one spec kind (a multi-value description is ambiguous, not clear);
- it beats the runner-up for that line and supplier by >= `MARGIN`, where the margin is **unit-neutral** (the unit signal is ignored, so the same item offered in two units is still a rival);
- **`quote_shared` competition:** the quote item does not score as well as, or within the margin of better for, another BoQ line (neither line is then clear).

Otherwise, with score >= `AMBIGUOUS_MIN`, it is `ambiguous`. Below that it is not stored. `needs_confirmation` is true for ambiguous; in 5a the API still requires an explicit decision for clear ones too, bulk or single.

**Clear vetoes.** A pair that passes the score and margin tests is still not `clear` when any of these evidence warnings is raised (it stays `ambiguous`): `text_differs` (wording differs on both sides), `spec_one_sided` (only one side gives a specification), `accessory_word` (the description may be an accessory, not the item), `negation` (one side excludes something), `number_differs` (the sorted multisets of numeric literals differ, notation-insensitive, with `sku/part/code/pn` references removed first), `defining_word_missing` (a word from the defining vocabulary, after alias expansion and stemming, appears on one side only) and `spec_multi_value`. The strict switch `MatchConfig.one_sided_word_veto` (off by default) turns any one-sided word into a `word_one_sided` veto; it lowers the clear counts from 43 to 23 (committed packs) and 89 to 52 (hold-out) and is not exposed to users. The vetoes are measured to cost no clear in default mode. Rematching is queued after a supplier merge and after a quotation supplier switch.

**Qualifier vocabulary.** Groups of words (`single/double/triple`, `steel/pvc/aluminium/copper/brass`, `surface/flush/recessed`, `indoor/outdoor`) are read from the whole description. Both sides naming a word from one group with no overlap is a spec conflict; a one-sided or overlapping qualifier never conflicts.

**Core notation.** `N-core` / `N core` and `NC+E` are read as the same `core` kind (a convention assumption; the BoQ writes `3-core`, quotations `3C+E`). When the two sides used different spellings the evidence carries the warning `core_notation_differs`; it does not block clear.

**Persistence rules.** Matching replaces `suggested` rows for the tender and leaves `confirmed` and `rejected` rows (and the items they reference) untouched; a rejected pair is not re-suggested. A quotation item that any `confirmed` or `rejected` match refers to counts as reviewed for `replace_unreviewed`: re-extraction never deletes it, so a decision is never silently lost (the existing duplicate-of-reviewed warning applies). Matches of items that were replaced while only `suggested` are deleted with them and regenerated by the next match run. The worker handler for `extract_boq` passes the ids of BoQ items referenced by a `confirmed` or `rejected` match to `estimating.replace_unreviewed` as protected ids (they count as reviewed), mirroring the quotation-item rule; this wiring is built in Phase 2 together with matching. A BoQ line with no candidate above the floor for a supplier is reported as "no match", not as a low-confidence guess.

**Stale confirmed matches.** A `confirmed` match whose quotation item is superseded or rejected is not shown and is not deleted. It is released (set back so a live candidate can take the slot) only when a live suggestion needs that (BoQ line, supplier) slot and the pair is not already decided; the release is audited as `match_released_stale` with the match ids and the user gets no notice.

**Job.** Matching runs as a tender-level `match_suppliers` job, enqueued after `extract_quotation` and `extract_boq`. It takes a per-tender Postgres advisory transaction lock (`pg_advisory_xact_lock`) so concurrent runs for one tender serialise; a run already in progress is not repeated until the next trigger.

## 6. API

Flat under `/api/v1`, org-scoped (unknown or other-organisation id gives 404, which F1 requires), locks via `pipeline.lock_runs` for item writes as in Slice 4, audit with ids and field names only.

| Endpoint | Does |
|---|---|
| `GET /suppliers`, `GET`/`PATCH /suppliers/{id}`, `POST /suppliers`, `POST /suppliers/{id}/merge` | List, rename and annotate, create by hand, merge a duplicate into another (moves its quotations; re-keys `name_key`) |
| `GET /tenders/{id}/quotations` | Quotations of the tender's current document versions with supplier and header |
| `PATCH /quotations/{id}` | Supplier (switch to an existing one), reference, dates, currency, `prices_include_vat` |
| `GET /document-versions/{id}/quotation-items` | Paged list (`limit`/`offset`, `source_order`). There is no `GET /quotations/{id}/items`: the version route covers it |
| `PATCH`, `POST confirm`, `POST reject` on `/quotation-items/{id}` | Review writes; `unit_price` and `quantity` are decimal strings like BoQ |
| `GET /tenders/{id}/match-suggestions` | A list grouped by BoQ line: one entry per current, non-rejected BoQ line with its `suggestions` (empty when none), each with supplier, quotation item (current versions, non-rejected items only) and evidence. Filters `status`, `classification`, `supplier_id`, `only_with_suggestions`; `limit` (1-500, default 100) and `offset` page the BoQ lines. Order is BoQ order, supplier name, rank; there is no price sort or filter by design |
| `POST /match-suggestions/{id}/confirm`, `/reject` | Records reviewer (`decided_by`, with `decided_by_name`) and time; 409 `match_conflict` if another candidate from the same supplier is already confirmed for that BoQ line (reject or reset it first); 409 `stale_match` if the suggestion's quotation version or BoQ line is no longer current. Repeating the current state changes nothing. Takes the tender lock |
| `POST /match-suggestions/{id}/reset` | Back to `suggested` and clears the decider and time (a reviewer may change their mind); 409 `stale_match` as above |
| `POST /tenders/{id}/match-suggestions/confirm-clear` | Confirms only `suggested`, `clear` rows of current BoQ lines and quotation items; a row whose (BoQ line, supplier) already has a confirmed match, or that collides with a row confirmed in the same call, is counted in `skipped`. Also skips rival clear rows (more than one clear row for the same BoQ line and supplier), rows whose quotation item or BoQ line was corrected after the match row was made, rows with `quote_expires_before_closing` and rows with `core_notation_differs`. Returns `{confirmed, skipped}`; ambiguous rows are never touched. The audit row is written only when something was confirmed or skipped |
| `POST /tenders/{id}/match` | Enqueue matching (202 + job; the active job is returned when one is queued or running); needs `review_data`; 409 `tender_archived`. A BoQ line edit or rejection and a quotation item edit or rejection queue it too |

Archived tenders refuse every write with 409 `tender_archived`, as in Slice 4. Decide, confirm-clear, the match trigger, quotation writes and merge check this again after taking the tender lock, so archiving takes the same lock and cannot be overtaken by a write that checked earlier.

**Candidate prices** carry `currency` and `prices_include_vat` from the quotation (`MatchQuoteRef`, both optional).

## 7. Frontend

- **Review screen** serves quotation versions: source viewer on the left (unchanged), quotation header card and items on the right with the same row component states, flags (`price_unparsed`, `ambiguous_separator`, ...), editing of description, unit, quantity and unit price (decimal text inputs, never `number`).
- **Supplier comparison** (`/tenders/[id]/suppliers`): one section per BoQ line (grouped by BoQ section), a column or card per supplier, each candidate showing description, unit, quantity, unit price, spec chips (matched, missing), warnings in words (unit mismatch, spec conflict, quote expired before closing), classification badge and Confirm/Reject. Ambiguous candidates show the reason and have no bulk action. A header action "Confirm all clear matches" reports how many it confirmed and skipped. Prices sit side by side; there is no highlight on the lowest and no default selection. Filters: classification, status, supplier. Paged by BoQ line. The summary line reads "Loaded: N lines · A awaiting a decision · C with a confirmed match · M with no supplier match" (loaded lines only; "with a confirmed match" counts lines, not suggestions). While a classification, status or supplier filter is active the API still returns every line with its suggestions filtered, so a line with none shows "No suggestions match these filters." and is not counted as "no supplier match". After "Confirm all clear matches" a note explains that skipped rows need an individual decision (rival matches, edited items, quotes expiring before closing, or cable notation differences). Prices are shown as sent, as `ZAR 125.5000 · excl. VAT` (or `incl. VAT`, `VAT not stated`; `Currency not stated` when there is no code; `Price missing`), never formatted, ordered or highlighted. Warning chips are shown for every warning; the one-sentence reason appears only when there are no warnings. The extraction panel adds rows kept as reviewed back into its totals ("15 items (12 kept as reviewed)").
- **Suppliers** list (`/suppliers`): rename, notes, merge with a two-step confirm. A whitespace-only name is refused on the page without a request; the merge confirm sends one request however often it is clicked; the "Merged A into B." message belongs to the page, is cleared when another action starts, and survives the source row disappearing; a merge that finds the supplier gone or the list stale reloads the list.
- Navigation: "Suppliers" in the header; a "Compare suppliers" link on the tender page. State is never colour alone; keyboard operable; same optimistic-update and "replaced by a re-run" handling as the review screen.
- Frontend types come from the regenerated `openapi.json` (backend equality test stays).

## 8. Testing and evaluation

- **Backend:** parser tests on both synthetic quotation formats plus messy variants (wrapped lines, comma prices, missing header fields, no table); matcher unit tests per signal and per classification rule; Hypothesis properties (score deterministic, independent of input order, a spec conflict never `clear`, price changes never change the score); API tests per endpoint and role; extended F1 sweep (register `quotation_id`, `quotation_item_id`, `supplier_id`, `match_suggestion_id` in `known`, and extraction plus matching for org B so B owns rows); decided matches survive re-runs; the one-confirmed-per-supplier rule under concurrent requests; F3 for the new tables.
- **Evaluation:** `scripts/score_slice5a.py` runs the real pipeline on the committed packs and compares with `ground_truth.json` (`expected_match`, `unit_mismatch`, `ambiguous`, `confusable_with`). Reports top-suggestion accuracy among suggested, flagged share of ambiguous and unit-mismatch items, and conflicting-clear count (target zero). Thresholds are tuned on seed 42 and checked on seed 43; the report goes in `docs/spikes/slice-5a-scores.md`.
- **Frontend:** Vitest for the comparison page (no auto-selection, no cheapest highlight, bulk confirm skips ambiguous, read-only roles, conflict message, replaced-by-re-run), quotation row editing and decimal validation, suppliers merge two-step confirm.
- **Real stack:** browser journey from the exit gate, driven and recorded in the plan status line.

## 9. Phases (each ends committed and working)

| Phase | Content |
|---|---|
| 1 Data and extraction | Migration 0005, models and repos, `parse_quotation`, job routing, supplier find-or-create, extraction status kind, tests |
| 2 Matching | `matching` core with config, persistence rules, `match_suppliers` job, scoring script and report |
| 3 API | Supplier, quotation, item and suggestion routes, F1 sweep, `openapi.json` regeneration |
| 4 Comparison UI | Quotation review rows, comparison page, bulk confirm |
| 5 Suppliers page and gate | Suppliers list/merge, navigation, real-stack gate run, docs |

Cut order if time runs short: 5 (merge can be an API-only feature), then bulk confirm, then quotation item editing polish. Phases 1 to 4 are the minimum credible demo.

## 10. Risks

- **Parser variance:** real quotations vary more than two synthetic formats. Mitigation: header-synonym tables, flags instead of guesses, scanned PDFs deferred, and the Slice 7 real-document check.
- **Threshold tuning on small data:** 30 items. Mitigation: tune on seed 42, confirm on seed 43, report the margins; thresholds are config, not code scattered in logic.
- **Wrong-but-confident matches:** the worst failure for a pricing tool. Mitigation: spec conflicts can never be `clear`, every decision is human, evidence is shown, and the zero-conflicting-clear counter is a gate item.
- **Concurrency on confirm:** two confirms for one BoQ line and supplier. Mitigation: service-level lock plus a database check; 409 `match_conflict`.
- **Scope:** five phases; the cut order above applies.
- **Known limitations added by this slice:** scanned quotations need manual entry (not yet possible), one quotation per document, no unit conversion, merged suppliers cannot be split, prices in a currency other than the first quote's are shown but not converted.
