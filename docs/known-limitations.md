# Known limitations and deferred items

A running list (plan section 5, working agreements) for the final documentation. Each item says what happens today and when it should be dealt with. Last updated 2026-10-16 after Slice 4 phase 1.

## Slice 3 (extraction) and Slice 4 phase 1 (review API)

Fixed in Slice 4 phase 1: section carry-over, `source_order` list ordering, locked review writes, `ambiguous_separator` flag (the value is still read as thousands).

Slice 4 phase 1 notes (review API), deferred from code review:

- **`_apply` re-adds `missing_quantity` even on rate-only or provisional lines**, and does not clear `ambiguous_separator` when the quantity or rate is corrected. Reviewers may see a stale flag; deal with it when the review UI shows flags.
- **`BoqPatch` text fields are not stripped and `unit` is not canonicalised.** Clearing `item_no` drops the dedupe identity, so a re-run may add an unreviewed duplicate of that line. Deal with it when the BoQ editor lands.
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

## Slice 1 and Slice 2 (deferred review minors)

- CHECK constraints on status and role columns.
- Audit table immutability.
- F3 target-column check.
- The failed-login audit row has a NULL organisation.
- Concurrent demotion beyond the row lock.
- The Dockerfile uses `uv:latest` and unpinned apt packages (not reproducible).
- The SQLAlchemy/Starlette `TestClient` deprecation warning in the test output.
