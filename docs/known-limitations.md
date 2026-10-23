# Known limitations and deferred items

A running list (plan section 5, working agreements) for the final documentation. Each item says what happens today and when it should be dealt with. Last updated 2026-10-23 after the hosted-model, cancellation and progress work (commits 2037117 to a55f9be).

## Slice 3 (extraction) and Slice 4 phase 1 (review API)

Fixed in Slice 4 phase 1: BoQ section detection (a lone text cell with no figures is a heading in whichever column it sits, with a leading `SECTION:` stripped) and section carry-over across pages, including pages that repeat the same header row (a header with the same column mapping on the next page continues the open section; a different header, a page gap or a narrower table resets it); `source_order` list ordering; locked review writes; review writes refused on an archived tender (409 `tender_archived`); the `ambiguous_separator` flag (the value is still read as thousands; correcting the quantity or rate clears the flag); clearing a quantity no longer adds `missing_quantity` to a rate-only, provisional-sum or unparsed line; NUL characters in review patches are a 422.

Review transitions: any review action (confirm, correct, reject) may be applied from any state, and none returns a row to `unreviewed` (see `docs/architecture/architecture.md` section 5).

Slice 4 phase 1 notes (review API), deferred from code review:

- **`BoqPatch` text fields are not stripped and `unit` is not canonicalised.** Deal with it when the BoQ editor lands. (Clearing `item_no` does not affect re-run dedupe: the dedupe key is read from `original_value`.)
- **A lone `row_from` or `row_to` on page detail is not capped at 5000 rows** (only a full window is). Fine for the sizes seen so far; cap it before large sheets are uploaded.
- **`source_order` saturates past 100 tables on one page**, and legacy rows (extracted before migration 0004) sort by position only until their version is re-extracted.
- **Rows from several documents interleave in the tender-wide requirements list** (`GET /tenders/{id}/requirements`); the checklist page should group or filter by document.

Documented trade-offs (acceptable for now):

- **One worker processes one job at a time**, across all organisations. A long requirements job (up to about 240 s per window in the worst case, 85-290 s per synthetic pack in practice) delays other organisations' ingest.
- **Concurrent `POST /extract` with different `deep_scan` values** can both return 202; the second receives the first's job (the active-job index guarantees no duplicate work).
- **A run stays `running` while its job waits for a transient retry.** The API also returns the job status (`queued`), which is the one to display.
- **Extraction is allowed on non-current versions.** Results are scoped to the version they were extracted from.
- **Fuzzy provenance** is per page, skipped for quotes over 600 characters (they become `evidence_unverified`), and silently returns no match on very low-entropy pages. The final re-review recommended lowering the 600-character bound to 300 (prompts ask for at most 25 words). The provenance heartbeat runs between candidates, not inside one `locate()` call.
- **Pre-filter `FOOTER` regex** strips the synthetic generator's footer text and any "Page N" in body text.
- **No `raw_rate` column:** a rate that is too large or too precise is flagged `rate_unparsed` but its text is not kept.
- **Extra extraction jobs after a re-claimed ingest:** if an ingest job completes its work but fails to record completion, the re-run enqueues a second set of extract jobs (idempotent, costs one more LLM pass).
- **Extract jobs already queued for a tender that is archived later** are refused by the worker, leaving `failed` runs. The extract route itself now returns 409 `tender_archived`.
- **The `evaluation` requirement type** appears in prompt v3's wording but not in the output schema enum, matching the spike that was measured.
- **Concurrent edits of one row are last-write-wins.** The DTO shows who reviewed it and when (`reviewed_by_name`, `reviewed_at`).
- **Scanned BoQs have no manual line entry yet** (`BOQ_NEEDS_MANUAL_ENTRY`).
- **DOCX sources have no rendered viewer.**
- **Unit tests:** the store test reuses one run id; no write-isolation assertions for the new repositories; `ROW_CAP_REACHED` is untested; the `limit=0` API test accepts 200 or 422.
- **Scoring script** silently skips a document if ingest times out or fails and hard-codes its prediction metadata; harness output under `eval/runs/` is git-ignored.

Measurement caveats are in [spikes/slice-3-scores.md](spikes/slice-3-scores.md): synthetic data, one run per seed, scored before the final review fix wave, `pack09_xl` and `deep_scan` not run, only `qwen3:4b` measured.

## Slice 5a (suppliers and quotations)

- **Scanned quotations need manual entry, which is not yet possible.** They get a `QUOTE_NEEDS_MANUAL_ENTRY` warning and no items.
- **One quotation per document.** A document holding several quotations is read as one.
- **A re-run fills only empty header fields** and never undoes a supplier switch made by a user.
- **Prices in other currencies are shown but not converted.**
- **Column heading synonyms are narrow.** "Unit Price (ZAR)" and "Price excl VAT" headings are not recognised, and separate SKU or Code columns are ignored.
- **Dates are read day-first** for dd/mm/yyyy.
- **The header is read only from the page that holds the item table**, so a cover-letter first page is missed.
- **A match job running when another trigger arrives is not repeated** until the next trigger: the new trigger returns the running job, which may have read its inputs already. `POST /tenders/{id}/match` re-runs it on demand; multi-worker deployments need re-enqueue-when-running.
- **Matching ignores quantity and price by design** and does no unit conversion (different units are flagged `unit_mismatch`).
- **The synonym and qualifier vocabulary is small and trade-specific.** Qualifiers are read from the whole description, so a shared incidental material word can hide a conflict, and a quote naming a qualifier that the BoQ line omits is not penalised.
- **`N-core` and `NC+E` are treated as the same cable notation** (a convention); the evidence flags it as `core_notation_differs`.
- **Matching accuracy is measured on synthetic data only** (about 70 quote items on the committed packs; exact counts are in `docs/spikes/slice-5a-scores.md`). Two ground-truth items per pack are generator labelling artefacts, which the evaluation reports separately.
- **Suggested rows of superseded document versions can linger in the database.** Every read path filters to current versions, and a decision on such a row is refused with 409 `stale_match`, but the rows are only removed when the next match job touches the same BoQ lines.
- **Closing-date comparison uses the UTC date of `closing_at`.**
- **"Clear" is conservative, not a guarantee.** A clear match has passed the vetoes (`text_differs`, `spec_one_sided`, `accessory_word`, `negation`, `number_differs`, `defining_word_missing`, `spec_multi_value`), but the defining-word vocabulary is a fixed list and the number check compares multisets of numeric literals. One-sided extras remain possible: a quote that omits a feature word that is not in the vocabulary still reads as clear. A strict switch, `MatchConfig.one_sided_word_veto`, makes any one-sided word a veto (`word_one_sided`); on the committed packs it takes the clear count from 43 to 23, on hold-out seed 43 from 89 to 52, with accuracy and the safety counts unchanged. It is a config switch only; nothing exposes it to an owner yet. Every match still needs a human click.
- **Stale confirmed matches are released lazily.** A confirmation made on a superseded or rejected quotation item is kept (hidden from the comparison page) until a live candidate needs the slot (same BoQ line and supplier). It is then released, with a `match_released_stale` audit entry listing the match ids. The user is not shown a notice.
- **A merge does not survive the next upload.** Merging combines two supplier rows but keeps no alias, so the merged-away name in a later quotation can recreate the duplicate supplier. An alias table is future work.
- **Matched and missing specification kinds are text rows in the "Why this match" disclosure, not chips** (a deviation from spec section 7). Warnings are chips.
- **"Confirm all clear matches" skips** ambiguous rows, rival clear rows (more than one clear row for one BoQ line and supplier), rows whose quotation item or BoQ line was corrected after the match, rows with a quote expiring before the tender closes, and rows where the cable notation differs. Those need an individual decision; the page says so after the run.
- **Price display mixes stored text and fixed decimals.** The original value of a corrected item is shown as stored (for example "was 54917.00") while current values show four decimals. Candidate prices show the currency code and the VAT basis as quoted ("incl. VAT", "excl. VAT", "VAT not stated"); there is no conversion between currencies or VAT bases.
- **One worker means a long requirements job delays matching.**

## Slice 5b (the estimate)

From the spec's known limitations:

- One currency per estimate. There is no conversion of currency, VAT basis or units.
- No preliminaries, contingency or discounts as concepts.
- No per-supplier totals comparison.
- The approver may equal the reviewer.
- A scanned quote needs a manual price typed per line, and manual quotation entry does not exist yet.
- Markup defaults to cost. The selling-price basis is implemented (spec section 12 records the owner's answer that the markup basis is an option) but was not exercised in the browser gate.
- Section subtotals (spec sections 1 and 5) were cut and are not shown.
- BoQ lines added after an estimate was started (a second BoQ or addendum upload, or a BoQ re-run) block review and approval with `boq_lines_missing`; start a new version to include them. Amounts of 1e16 or more are refused with a 422 (`amount_too_large`) instead of being stored.

Observed or deferred during the build and gate:

- **Currency stays locked** until every priced or manual line is excluded.
- **Approve can freeze BoQ inputs edited concurrently.** The spec accepts this window.
- **The estimate page reads all quotation items on each request** to learn review status.
- **No `boq_missing` flag** for a line whose BoQ line has vanished.
- **Digits outside ASCII are accepted.** The `RateText` and `DecimalText` patterns use `\d`, which also matches Unicode digits. They should use `[0-9]`.
- **"Reopen" and "New version" sit side by side** on a reviewed estimate, and their wording can be confused. "New version" is available on a reviewed, not approved, version with no draft, as the spec provides.
- **"Confirm all clear matches" (Slice 5a) skips rows that still show "Clear match"** where a cable-notation warning applies. At the gate these needed individual confirms. This is pre-existing 5a behaviour.

## Hosted model and extraction operations (22-23 Oct 2026)

Details, the benchmark and the remaining necessary changes are in [hosted-llm-and-extraction-ops.md](hosted-llm-and-extraction-ops.md).

- **Large documents can lose windows.** On one 73-window document, 22 windows ended `WINDOW_INVALID_OUTPUT` with the hosted model, and the job still completed. The cause is unverified (most likely the 2048-token output cap). Check the window count before trusting a long run.
- **A capped window costs two billed calls.** The `length` result is retried once with the truncation prompt, and it still fails if the cap is the cause.
- **Post-window provenance is slow and shows no progress.** The progress bar stays at "N of N" while sources are attached, which can take minutes.
- **Cancel can land late.** A cancel that arrives after the last heartbeat check can still store results under a cancelled job. One hosted call already in flight completes and is billed.
- **A crash after cancel can leave a run `running`.** No sweep clears it yet.
- **Ingest jobs cannot be cancelled** (409 `job_not_cancellable`), so a document cannot be stopped mid-ingest.
- **A worker restart mid-extraction restarts the whole job** from window 1, sending the text and billing again, unless the job was cancelled first.
- **The hosted settings are named `kimi`** (`LLM_PROVIDER=kimi`, `LLM_KIMI_*`) but work with any OpenAI-compatible API, such as Mammouth.
- **Hosted use is limited to synthetic data** until the POPIA assessment is done; one real-looking document was processed with a hosted provider during testing (see the privacy item in the ops document).

## Slice 4 phase 4 (review screen)

- **Quote highlight is on the extracted text, not the PDF image.** The stored `quote_start`/`quote_end` index the page text after whitespace is collapsed and lower-cased (`provenance.py`), so the client maps them back onto the raw text; matching the quote inside the PDF.js text layer is not implemented. Fuzzy matches mark the nearest located span.
- **After a BoQ re-run a reviewed row and its re-extracted twin both appear** (same item code, no visual link between them).
- **Field-level 422 messages** are joined into one message at the top of the editor rather than shown beside each input.
- **Tab counts show "200+"** while more pages exist; the real total needs a count endpoint.

- **Checklist mandatory-status filter is client-side** (the API has no such parameter), so it applies to loaded pages only; the page says so while it is active and more pages exist.

- **Comparison page summary counts cover loaded lines only** (the API has no totals), and the list fetches 100 BoQ lines per page; "Load more lines" reads the rest.

- **Members page:** own-row and last-admin protections live on the server only (the UI shows its refusals); resetting your own password ends your own sessions too, and the page warns about it.

## Slice 1 and Slice 2 (deferred review minors)

- CHECK constraints on status and role columns.
- Audit table immutability.
- F3 target-column check.
- The failed-login audit row has a NULL organisation.
- Concurrent demotion beyond the row lock.
- The Dockerfile uses `uv:latest` and unpinned apt packages (not reproducible).
- The SQLAlchemy/Starlette `TestClient` deprecation warning in the test output.
- A merged supplier cannot be split again; a merge is permanent.
