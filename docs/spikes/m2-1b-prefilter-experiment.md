# M2-1b spike: deterministic pre-filter before the LLM (15 Oct 2026)

Script: `spikes/prefilter_experiment.py`. Model: `qwen3:4b` (think off, `num_ctx 4096`, JSON-schema output), same laptop as M2-1 (GTX 1650 Max-Q, i7-8565U).
Data: native-PDF packs from the synthetic generator (`eval/`), requirement extraction only (cover and BoQ pages excluded from both methods). The packs include **distractors**: obligation-, date-, amount- and time-worded sentences that are not tenderer requirements (employer duties, payment terms, history), added to the generator for this experiment.

## Methods

- **Baseline:** all text split into ~1,350-token sections; every section goes to the LLM.
- **Pre-filter:** sentences matching obligation words (must, shall, required, no later than, ...), dates, times, CIDB-style grades, amounts, standards (SANS, B-BBEE, ...), periods; plus one sentence of context either side; windows batched into ~1,350-token calls. Page provenance is found by code from the evidence quote.

## Results (prompt v2, one run each)

| Pack | Pages | LLM calls (pre / base) | Time pre-filter | Time baseline | Recall pre-filter | Recall baseline | False positives (pre / base) |
|---|---|---|---|---|---|---|---|
| pack08 (adversarial) | 7 | 1 / 5 | 62 s | 161 s | 8/8 | 7/8 | 0 / 8 |
| pack01 (clean) | 8 | 1 / 5 | 74 s | 118 s | 9/9 | 9/9 | 0 / 1 |
| pack03 (dense, messy) | 13 | 1 / 8 | 75 s | 260 s | 9/9 | 9/9 | 0 / 16 |
| pack07 (long, boilerplate) | 26 | 2 / 19 | 95 s | ~1,116 s (extrapolated from 10 of 19 calls) | 9/10 | not measured | 1 / not measured (71 items in 10 calls) |
| pack09_xl (stress) | 96 | 3 / 78 | 179 s | ~5,981 s, about 100 min (extrapolated from 10 of 78 calls) | 11/12 | not measured | 10 / not measured (99 items in 10 calls) |

- **Filter alone:** it kept 3-15% of the text and caught every labelled requirement sentence on every pack (100% sentence-level recall). It also triggers on distractors (e.g. 34 of 46 triggered sentences on the 96-page pack).
- **Page references** were correct in every case except one of nine on pack07.
- **Prompt injection** (pack08) was never followed. No evidence quote was unverifiable (not found verbatim in the document).

## Findings

1. **The pre-filter makes the 45-minute target easy for sparse documents:** 3 minutes for a 96-page pack versus about 100 minutes for the baseline (3% of the time), with equal or better recall on the four packs where both were measured.
2. **LLM time is driven by output, not input.** Roughly 8 s per output item. The baseline is slow because it also outputs many false positives, not because it reads more text.
3. **The prompt matters more than the filter for precision.** Prompt v1 ("list every requirement") on pack08 returned 115 items (107 false positives) and took 927 s for 7 pages. Prompt v2 (defines what a tenderer requirement is, and what to ignore) returned 15 items with the baseline and 8 with the filter, in 161 s and 62 s.
4. **Remaining LLM misses are loosely worded requirements:** "written queries should reach..." (informational, 'should') and "defects liability period of N months" (technical). The filter did select them. Prompt v2 does not cover 'should' statements well.
5. **Distractors cause false positives:** on the 96-page pack, 8 of the 10 false positives were boilerplate sentences extracted as requirements. More boilerplate means more review work for users.

## Caveats

- **The filter's 100% recall is optimistic.** Every synthetic requirement contains an obligation word, date or similar trigger by construction, and the distractors were written knowing the triggers. Real tenders contain requirements without trigger words and much more obligation-worded boilerplate. Real recall is unknown until tested on permissioned real documents (PRD section 20).
- One run per configuration at temperature 0; Qwen3 is not deterministic (M2-1). The baseline on the two long packs is extrapolated from 10 calls.
- Scanned packs were not tested (needs OCR). The synthetic text is cleaner than real documents.

## Recommendation

1. **Adopt pre-filter + context windows + prompt v2** as the default requirement-extraction path, and revise FR-61 accordingly: "every section is screened deterministically; candidate windows go to the LLM". The 45-minute target stays.
2. **Keep a manual "deep scan"** (baseline over all sections) for documents where the filter looks suspiciously quiet, and for evaluation. Trigger it automatically or suggest it when fewer than a configured number of candidates are found per 10 pages.
3. **Make the trigger vocabulary configurable** and tune it on real documents. Report filter recall (sentence-level) as its own metric in the evaluation, separate from LLM recall.
4. **Reduce false positives and misses next:** prompt v3 (include 'should' statements as informational; reject employer duties more firmly), and consider a cheap yes/no verification pass per extracted item.
5. Update `docs/architecture/architecture.md` section 5 (throughput) and PRD FR-61 and section 6 with these numbers.
