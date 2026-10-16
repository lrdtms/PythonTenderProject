# Known limitations and deferred items

A running list (plan section 5, working agreements) for the final documentation. Each item says what happens today and when it should be dealt with. Last updated 2026-10-16 after Slice 4 phase 1.

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

## Slice 4 phase 4 (review screen)

- **Quote highlight is on the extracted text, not the PDF image.** The stored `quote_start`/`quote_end` index the page text after whitespace is collapsed and lower-cased (`provenance.py`), so the client maps them back onto the raw text; matching the quote inside the PDF.js text layer is not implemented. Fuzzy matches mark the nearest located span.
- **After a BoQ re-run a reviewed row and its re-extracted twin both appear** (same item code, no visual link between them).
- **"Run extraction again" on a quotation PDF** returns no jobs and shows no feedback (quotations are not extracted in this slice).
- **Field-level 422 messages** are joined into one message at the top of the editor rather than shown beside each input.
- **Tab counts show "200+"** while more pages exist; the real total needs a count endpoint.

- **Checklist mandatory-status filter is client-side** (the API has no such parameter), so it applies to loaded pages only; the page says so while it is active and more pages exist.

## Slice 1 and Slice 2 (deferred review minors)

- CHECK constraints on status and role columns.
- Audit table immutability.
- F3 target-column check.
- The failed-login audit row has a NULL organisation.
- Concurrent demotion beyond the row lock.
- The Dockerfile uses `uv:latest` and unpinned apt packages (not reproducible).
- The SQLAlchemy/Starlette `TestClient` deprecation warning in the test output.
