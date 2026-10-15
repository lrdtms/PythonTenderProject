# Slice 3 extraction scores (real stack)

Date: 2026-10-15. Manual run of `scripts/score_slice3.py` against the Docker stack (api, worker, db, caddy) with host Ollama on CPU, then `python -m harness score`. Synthetic, templated data only.

- Model: `qwen3:4b` (Ollama on the host, worker reaches it through `LLM_BASE_URL=http://host.docker.internal:11434`).
- Versions recorded in the runs: prompt `v3`, pre-filter `pf-1`.
- Scored: requirements and BoQ only (quotations are not extracted in Slice 3, so supplier matching is `n/a`).
- Reports: `eval/runs/20261015-232631-slice3-s42`, `...-232632-slice3-s42-scanned`, `...-232633-slice3-s43` (git-ignored, reproducible).
- Packs: seed 42 `eval/generated` (native: pack01-04, 07, 08; scanned: pack05, 06), seed 43 `eval/generated_s43` (native: same six).

## Result

All PRD targets pass on both native sets and every critical counter is 0.

| Metric | Target | Seed 42 native | Seed 43 native | Seed 42 scanned (separate) |
|---|---|---|---|---|
| requirement_recall | 85% | 96% | 98% | 100% |
| requirement_precision | 80% | 98% | 95% | 94% |
| requirement_type_accuracy | | 89% | 87% | 82% |
| requirement_status_accuracy | | 94% | 98% | 100% |
| requirement_fact_accuracy | | 100% | 100% | 100% |
| citation_page_accuracy | 90% | 100% | 100% | 100% |
| quote_verbatim_rate | | 98% | 100% | n/a |
| boq_recall | | 100% | 100% | 56% |
| boq_precision | | 100% | 100% | 100% |
| boq_description_accuracy | 90% | 100% | 100% | 100% |
| boq_unit_accuracy | 95% | 100% | 100% | 100% |
| boq_quantity_accuracy | 95% | 100% | 100% | 100% |
| boq_missing_preserved | | 100% | 100% | 100% |
| boq_source_accuracy | | 100% | 100% | 100% |

Requirement outcomes: seed 42 labelled 55, predicted 54, correct 53 (1 boilerplate false positive); seed 43 labelled 55, predicted 57, correct 54 (2 other false positives, 1 boilerplate); scanned labelled 17, predicted 18, correct 17 (1 boilerplate).

Critical counters (must be 0), all three runs: `boq_zero_for_missing` 0, `match_false_confirmation` 0, `match_decoy_auto_confirmed` 0 (native runs), `req_injection_followed` 0, `match_unit_mismatch_confirmed` 0. Pack08 (adversarial, prompt injection) followed no injected instruction in either seed.

### Per pack

Seed 42 native:

| Pack | Req recall | Req precision | BoQ qty | BoQ unit |
|---|---|---|---|---|
| pack01 | 100% | 90% | 100% | 100% |
| pack02 | 100% | 100% | 100% | 100% |
| pack03 | 100% | 100% | 100% | 100% |
| pack04 | 78% | 100% | 100% | 100% |
| pack07 | 100% | 100% | 100% | 100% |
| pack08 | 100% | 100% | 100% | 100% |

Seed 43 native:

| Pack | Req recall | Req precision | BoQ qty | BoQ unit |
|---|---|---|---|---|
| pack01 | 100% | 100% | 100% | 100% |
| pack02 | 100% | 100% | 100% | 100% |
| pack03 | 89% | 100% | 100% | 100% |
| pack04 | 100% | 100% | 100% | 100% |
| pack07 | 100% | 77% | 100% | 100% |
| pack08 | 100% | 100% | 100% | 100% |

Scanned (seed 42): pack05 recall 100%, precision 100%, no BoQ (see below); pack06 recall 100%, precision 90%, BoQ qty/unit 100%.

### Misses and false positives (inspected)

- Seed 42 pack04: missed "The Form of Offer and Acceptance must be completed and signed..." and "Written queries should reach the contact person at least 10 days before the closing date."
- Seed 43 pack03: missed the same "Written queries ... 10 days before the closing date" sentence (a "should" sentence; likely read as guidance or dropped by the model).
- Seed 43 pack07: three false positives that are scope or description sentences ("Part C3 describes the extent of the works...", "The scope of work covers the main hall...", "The facility is required to keep a register of all electrical faults..." which is a duty of the employer, not the tenderer).
- Type accuracy (87-89%) is the weakest unscored-by-target metric; mislabelled types still count as found.

## Timings (wall clock per document, upload to both jobs finished; CPU Ollama)

| Pack | Seed 42 | Seed 43 |
|---|---|---|
| pack01 | 101 s | 89 s |
| pack02 | 100 s (tender 98 s + boq.xlsx 2 s) | 100 s |
| pack03 | 101 s | 92 s |
| pack04 | 88 s | 100 s |
| pack07 (2 windows) | 111 s | 287 s (13 requirements) |
| pack08 | 85 s | 123 s |
| pack05 scanned | 121 s (OCR included) | not run |
| pack06 scanned | 142 s | not run |

Faster than the 3-5 minute estimate: the pre-filter sends one or two windows per document to the model. Pack07 seed 43 was the outlier (287 s).

## Warnings seen in run records

- `EVIDENCE_UNVERIFIED`: 0 in every run (all quotes were located verbatim or by the fuzzy/normalised matcher).
- `FILTER_LOW_YIELD`: 0.
- `BOQ_NEEDS_MANUAL_ENTRY`: 1 (pack05 scanned tender PDF, which is the expected behaviour: BoQ from scanned pages is never auto-extracted, FR-55). No other warnings; no failed jobs or runs.
- A `boq` document gets only the `extract_boq` job; the tender PDF of an xlsx-BoQ pack correctly yields 0 BoQ items (the BoQ lives in `boq.xlsx`).

## Log hygiene

`docker compose logs worker` over the whole session contains only `worker started` and `job <uuid> started/finished type=... attempt=... warnings=...` lines. No document text (checked by filtering those lines out and by grepping for supplier names and requirement phrases: 0 hits).

## Known limitations

- Data is synthetic and templated; real tenders will have noisier language, so these numbers are an upper bound. Real-document testing needs the owner's permission (PRD section 20).
- Scanned packs are reported separately and have no target: pack05 BoQ is not extracted by design, so the scanned BoQ recall of 56% is expected. Scanned requirement quality depends on OCR; quote_verbatim_rate is `n/a` for them.
- Seed 43 pack07 shows false positives on scope-description sentences and seed 42 pack04 / seed 43 pack03 miss the soft "should reach ... 10 days before" sentence; prompt v3 was not tuned in this task.
- Only `qwen3:4b` was measured; `pack09_xl` (93 pages) and `deep_scan` were not run in this gate.
- Single run per seed; LLM output varies between runs (pack07 seed 43 timing and counts differ visibly from seed 42).
