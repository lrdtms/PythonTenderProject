# Known limitations and deferred items

A running list (plan section 5, working agreements) for the final documentation. Each item says what happens today and when it should be dealt with. Last updated 2026-10-16 after Slice 3.

## Slice 3 (extraction)

Fix before or during Slice 4 (review UI), because review makes them user-visible:

- **Section is lost on a continuation page.** The BoQ parser resets the current section for every table, so items on a later PDF page have no section until the next heading. The re-run duplicate key is (section or sheet, item number); once reviewed rows exist, an item "A" with no section can suppress other section-less "A" items on re-run as `DUPLICATE_OF_REVIEWED`.
- **List ordering after re-runs.** BoQ and requirement lists are ordered by `created_at` then `position`, so reviewed rows from older runs come before new rows and `position` values can collide. Order by document position within the current run, with reviewed rows slotted by position.
- **Review updates must be conditional.** Slice 4 review writes must take the same version+kind lock as extraction and update `WHERE review_status = 'unreviewed'`, returning 409 when the row has been replaced (ADR-0006 addendum).
- **Comma separators are ambiguous.** `1,500` is read as 1500; in South African comma-decimal usage it could be 1.5. A single comma followed by exactly three digits is not flagged.

Documented trade-offs (acceptable for now):

- **One worker processes one job at a time**, across all organisations. A long requirements job (up to about 240 s per window in the worst case, 85-290 s per synthetic pack in practice) delays other organisations' ingest.
- **Concurrent `POST /extract` with different `deep_scan` values** can both return 202; the second receives the first's job (the active-job index guarantees no duplicate work).
- **A run stays `running` while its job waits for a transient retry.** The API also returns the job status (`queued`), which is the one to display.
- **Extraction is allowed on non-current versions.** Results are scoped to the version they were extracted from.
- **Fuzzy provenance** is per page, skipped for quotes over 600 characters (they become `evidence_unverified`), and silently returns no match on very low-entropy pages. The final re-review recommended lowering the 600-character bound to 300 (prompts ask for at most 25 words). The provenance heartbeat runs between candidates, not inside one `locate()` call.
- **Pre-filter `FOOTER` regex** strips the synthetic generator's footer text and any "Page N" in body text.
- **No `raw_rate` column:** a rate that is too large or too precise is flagged `rate_unparsed` but its text is not kept.
- **Extra extraction jobs after a re-claimed ingest:** if an ingest job completes its work but fails to record completion, the re-run enqueues a second set of extract jobs (idempotent, costs one more LLM pass).
- **Extract jobs for archived tenders** are queued and then refused by the worker, leaving `failed` runs.
- **The `evaluation` requirement type** appears in prompt v3's wording but not in the output schema enum, matching the spike that was measured.
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
