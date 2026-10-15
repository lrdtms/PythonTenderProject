# M2-1c spike: extraction prompt evaluation with the harness (15 Oct 2026)

Tools: `eval/harness` (scoring), `spikes/prefilter_experiment.py --prompt v2|v3|v4` (pre-filter + `qwen3:4b`), synthetic packs from `eval/synthgen`.
All data is synthetic and the language is templated, so these numbers are optimistic for real tenders.

## Prompts

- **v2:** defines what a tenderer requirement is and what to ignore (background, employer duties, history, payment mechanics).
- **v3:** v2 plus definitions of each `requirement_type` and `mandatory_status`.
- **v4:** v3 plus "do not skip minor requirements; include every should/may instruction, form, declaration, query deadline and defects period".

## Results

Recall is the lenient kind (quote overlap or keyword). "Facts" requires every date, time, number and grade of the labelled sentence to survive. Page, facts and verbatim-quote rates were 100% in every run.

| Dataset | Prompt | Recall | Precision | Type accuracy | Status accuracy |
|---|---|---|---|---|---|
| Packs 01, 03, 08 (tuned against; 26 reqs) | v2 | 100% | 100% | 38% | 88% |
| | v3 | 100% | 100% | 92% | 92% |
| Packs 02, 04, 07 (held out; 29 reqs) | v2 | 97% | 97% | 61% | 96% |
| | v3 | 90% | 100% | 88% | 100% |
| All six, seed 42 (55 reqs) | v2 | 100% | 98% | 47% | 91% |
| | v3 | 95% | 100% | 90% | 96% |
| | v4 | 94% | 89% | 89% | 97% |
| **Fresh packs, seed 43 (55 reqs, not tuned against)** | v2 | 98% | 96% | 61% | 91% |
| | v3 | **95%** | **98%** | **90%** | **98%** |

## Findings

1. **v3 is the best prompt so far.** On every dataset it lifts type accuracy by about 30-45 points and status accuracy by 4-7 points, and slightly improves precision. The gain holds on data it was not tuned on.
2. **v3 costs about 3-5 points of recall.** The misses cluster on informational "written queries should reach..." statements and on one price-validity period ("60 days"). The second is a mandatory pricing requirement, so it matters more.
3. **v4 is worse than v3.** The "don't skip anything" instruction produced no recall gain and cost 11 points of precision (the model started extracting boilerplate such as employer duties). Dropped.
4. **Reruns are deterministic here.** For the same input and prompt, Qwen3-4B at temperature 0 produced byte-identical predictions (v2 and v3, three and two repetitions); v4 varied slightly. Repeating the same documents adds little. What varies is the document, so evaluate on different packs (seeds) instead of rerunning one set. This corrects the earlier note in M2-1 that Qwen3 is non-deterministic: that was observed in a different setup.
5. **Type labels are partly a taxonomy question.** Before v3 the model labelled "tax pin", "registration certificate" and "good standing" as `eligibility` while the ground truth says `document`, and labelled the site meeting and the programme requirement as `deadline`. Definitions fixed most of it, but the taxonomy should be agreed with users (a first-pass choice, easy to change).
6. **Critical errors:** no prompt injection was followed and no quote was unverifiable in any run.

## Recommendation

1. Use **prompt v3** as the extraction prompt, with the pre-filter, and record `prompt_version` and `filter_version` with every result (the harness metadata supports this).
2. Close the recall gap without hurting precision: widen the pre-filter vocabulary for periods ("days", "weeks", "months") and "should" statements; consider a second, cheap pass that re-checks the sentences the filter selected but the LLM skipped ("is this a requirement for the tenderer? yes/no").
3. Treat these numbers as a ceiling until real tenders are tested (PRD section 20). Public tender documents (eTenders, CIDB standard documents) can serve as a realism check set.
4. Evaluate future prompt changes on at least two seeds, tuning on one and judging on the other.
