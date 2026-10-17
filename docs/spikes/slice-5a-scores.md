# Slice 5a phase 2: supplier matching scores

Date: 2026-10-17. Offline run of `scripts/score_slice5a.py` (no Docker, no Ollama): the deterministic matcher (`app/modules/suppliers/matching.py`) over the BoQ lines and quotation items that the Slice 3 and 5a parsers read from the synthetic packs, scored against each pack's `ground_truth.json`. Synthetic, templated data only. Exact counts (quote items / scored expected matches / trap items = quote items with no expected match or labelled ambiguous): pack01 13 / 9 / 4, pack02 30 / 22 / 8, pack03 16 / 12 / 4, pack04 11 / 7 / 4, so 70 / 50 / 20 on the four committed packs; hold-out seed 43 (seven readable packs): pack01 13 / 9 / 4, pack02 30 / 22 / 8, pack03 11 / 7 / 4, pack04 15 / 11 / 4, pack06 12 / 8 / 4, pack07 34 / 26 / 8, pack08 32 / 18 / 14, so 147 / 101 / 46.

Reproduce:

    cd backend && uv run python ../scripts/score_slice5a.py
    cd backend && uv run python ../scripts/score_slice5a.py --packs ../eval/generated_s43/pack01 ...

## Final configuration (`matching_config.py`)

| Name | Value |
|---|---|
| w_spec / w_text / w_unit | 0.5 / 0.4 / 0.1 |
| no_spec_factor | 0.9 |
| code_bonus | 0.1 |
| conflict_penalty | 0.25 |
| suggest_min | 0.70 |
| ambiguous_min | 0.45 |
| margin | 0.08 |
| clear_text_min | 0.5 |
| top_n | 3 |

No weight or threshold was changed in this task. All tuning was structural and general (below).

## Results

Metrics: `top_accuracy` is the share of non-ambiguous items with an expected BoQ match whose best suggestion is that line; `wrong_clear` counts clear suggestions that are not the expected line (any clear for an item with no expected match counts) and `ambiguous_cases_clear` counts ambiguous-labelled items offered clear, both excluding the excused pairs below; `unit_mismatch_unflagged` as in the plan. `exact_spec_on_trap_items` counts the excused pairs.

### Committed packs (pack01-pack04)

| Pack | Scored | Top correct | Accuracy | wrong_clear | unit unflagged | ambiguous clear | excused |
|---|---|---|---|---|---|---|---|
| pack01 | 9 | 9 | 1.000 | 0 | 0 | 0 | 0 |
| pack02 | 22 | 22 | 1.000 | 0 | 0 | 0 | 1 |
| pack03 | 12 | 12 | 1.000 | 0 | 0 | 0 | 1 |
| pack04 | 7 | 7 | 1.000 | 0 | 0 | 0 | 0 |
| overall | 50 | 50 | 1.000 | 0 | 0 | 0 | 2 |

Before tuning (the Task 1 matcher as committed), per pack top correct: pack01 7/9, pack02 16/22, pack03 9/12, pack04 5/7 (0.740 overall, 37/50); wrong_clear 0, unit unflagged 0, ambiguous clear 0.

### Hold-out: seed 43 (`eval/generated_s43`, git-ignored)

| Pack | Scored | Top correct | Accuracy | wrong_clear | unit unflagged | ambiguous clear | excused |
|---|---|---|---|---|---|---|---|
| pack01 | 9 | 9 | 1.000 | 0 | 0 | 0 | 1 |
| pack02 | 22 | 22 | 1.000 | 0 | 0 | 0 | 0 |
| pack03 | 7 | 7 | 1.000 | 0 | 0 | 0 | 1 |
| pack04 | 11 | 11 | 1.000 | 0 | 0 | 0 | 0 |
| pack06 | 8 | 8 | 1.000 | 0 | 0 | 0 | 1 |
| pack07 | 26 | 26 | 1.000 | 0 | 0 | 0 | 1 |
| pack08 | 18 | 18 | 1.000 | 0 | 0 | 0 | 0 |
| overall | 101 | 101 | 1.000 | 0 | 0 | 0 | 4 |

pack05 is skipped: its tender document is a scanned PDF, so there are no BoQ lines to match against (Slice 3 routes scanned BoQs to manual entry). Before tuning, on the other seven packs: 0.798 accuracy (top correct per pack: pack01 9/9, pack02 18/22, pack03 5/7, pack04 9/11, pack06 7/8, pack07 22/26, pack08 17/18), wrong_clear 5, ambiguous clear 2.

## Excused pairs (labelling artefacts)

Committed: `pack02/SKU-4876` (suggested C6), `pack03/SKU-3650` (4.6). Hold-out: `pack01/SKU-9244` (D4), `pack03/SKU-3182` (2.1), `pack06/SKU-4756` (4.5), `pack07/SKU-6319` (4.2).

The generator builds each "ambiguous" trap by changing one spec value of a real BoQ line (`confusable_with`) and labels it `expected_match: null`. In these six, the changed value happens to equal a different real BoQ line, so the quote is spec-exact against that line (every spec kind agrees, no one-sided kinds, enough word overlap), and the quoting supplier has no rival offer for it (checked in the ground truth, e.g. pack02 Greenvale offers a single `3C+E 4 mm2` cable against BoQ C6 `3-core 4 mm2`; pack03 Greenvale offers a single `MCB, 1-pole, 20 A, 6 kA` against BoQ 2.1 `Miniature circuit breaker, 1-pole, 20 A, 6 kA`). The excusal holds only under the `3-core` = `3C+E` convention (both of the committed excused pairs carry `core_notation_differs`) and their wording also differs (`PVC/PVC` vs `PVC insulated`, `for conduit installation` vs `installed in conduit`); it is not an identity of words. After the final-review vetoes these pairs are still clear (the wording differences are one-sided extras on the BoQ line, which `text_differs` allows). A clear match to the equivalent line is a reasonable reading, and the matcher must not refuse such matches, so the evaluation excuses exactly these pairs: a clear suggestion on a trap item (expected null or ambiguous) whose evidence has matched spec kinds, no conflicts, no boq_only/quote_only kinds, no multi_value, and text >= `clear_text_min`. Any other clear on a trap item still counts as wrong_clear / ambiguous clear and fails the test; the committed-pack test also asserts at most 1 excused pair per pack, so a regression that makes more traps clear is noticed. `render()` lists the excused pairs by pack and id.

## Final-review vetoes (clear-only) and their cost

The first review showed that the synthetic evaluation could not see one class of error: two products that differ in a word the spec parser does not read (Type B vs Type C, 20 A SP vs TP, 30 mA vs 300 mA, 4000K vs 6500K, single vs three phase board, 2 x 58 W vs 1 x 58 W, Class 1 vs Class 2, light vs heavy duty, earth rod 1.5 m vs 2.4 m, a tray vs its lid, a floodlight vs its bracket, a socket vs its cover plate, an isolator vs its enclosure, a conduit vs its coupler, `lamp ... excluding fitting` vs `fitting ... excluding lamp`) share every parsed spec, and with one quote per supplier nothing separates them, so they came back `clear`. Scores and ranking are unchanged by the vetoes (they act only on the clear decision; `MatchConfig.clear_vetoes=False` switches them off for comparison and a Hypothesis test asserts identical scores and ranks and clear set only shrinking). A vetoed pair stays `ambiguous` with one of these warnings:

- `text_differs`: after alias expansion, stemming and removal of stopwords and spec spans, both sides have a word or number the other lacks (one-sided extras are allowed).
- `spec_one_sided`: a spec kind on only one side (`boq_only` or `quote_only`).
- `accessory_word`: a word from `ACCESSORY_WORDS` (lid, cover, plate, bracket, enclosure, coupler, gland, adaptor, ...) on one side only.
- `negation`: either description contains excluding / excl / without / except / not included / less as a whole word.

Parsing improvements (these do change scores slightly, by correcting misreads): a spec value glued to a preceding word is not read (`mcb20a`), space-grouped thousands before a unit are joined (`1 500 W` is 1500 W), `NxS mm2` (`4x16mm2`) reads as N cores and S mm2. Aliases added: `luminaire` -> `light fitting`, `galv` -> `galvanised` (a `luminaire` vs `light fitting` pair rose from 0.82-0.90 to 1.00, no ranking changed).

Re-measurement (`cd backend && uv run python ../scripts/score_slice5a.py`, plus `--packs ../eval/generated_s43/pack0*`):

| Set | clear before | clear after | top_accuracy before / after | wrong_clear | ambiguous clear |
|---|---|---|---|---|---|
| Committed packs | 43 | 43 | 1.000 / 1.000 | 0 / 0 | 0 / 0 |
| Hold-out seed 43 | 89 | 89 | 1.000 / 1.000 | 0 / 0 | 0 / 0 |

No clear suggestion was lost on either set, so no veto costs a genuine synthetic match here; the same pairs are clear before and after (only the scores of the `luminaire`/`galv` alias pairs moved). That is a statement about this templated data, where quotations are mostly the BoQ wording with word-level synonyms; real quotations will lose more clears to `text_differs` and `spec_one_sided`, which is the intended trade (a buyer confirms an ambiguous pair, a wrong clear is silent). The vetoes themselves are tested on the substitution strings above, not on the synthetic packs.

## What was tuned and what it traded off

1. Core count (`spec_tokens`): `N-core` / `N core` now read as the same `core` kind as `NC+E`. The BoQ writes `3-core`, the quotations `3C+E`; before, they were different kinds, so core count never separated `2C+E`, `3C+E` and `4C+E` cables and 13 of the 50 top suggestions were ties resolved arbitrarily (committed packs 0.740 to 1.000). Trade-off: a genuine `3-core` (L, N, E) versus `3C+E` convention difference is ignored; evidence now carries the warning `core_notation_differs` when the two sides used different spellings (it does not block clear).
2. Margin ignores the unit signal (`unit_neutral`): a same-supplier runner-up differing from the top only by unit (`roll` vs `m` offers of the same cable) is still a rival, so the top is not clear. Trade-off: a supplier offering the same item in two units never gets an automatic clear.
3. Quote competition (`quote_shared`): a quote that scores as well as, or within the margin of better for, another BoQ line is not clear for either. Trade-off: duplicated identical BoQ lines never auto-match (correct).
4. Qualifier conflicts (`single/double/triple`, `steel/pvc/aluminium/copper/brass`, `surface/flush/recessed`, `indoor/outdoor`): both sides naming a word from one group with no overlap counts as a spec conflict. One-sided or overlapping qualifiers never conflict. Found on the hold-out (a `Double` socket clear against a `Single` BoQ line, `Steel` against `PVC` conduit). Trade-off: a fixed short vocabulary.

No weight or threshold was changed.

## Caveats

The `3-core` = `3C+E` equivalence is a convention assumption that holds in this synthetic data and may not on real quotations (it is disclosed per pair by `core_notation_differs`). The data is synthetic, templated and small (50 scored quote items on the committed packs, 101 on the hold-out), drawn from a small set of product families (cables, MCBs, sockets, conduit, boards, lighting). 100 percent top accuracy here says the rules handle these families, not that real quotations will score the same; real descriptions are messier. The hold-out was inspected for failures after the first run, so it informed which general rules were added (item 4); it is a check, not an untouched test set.

Evaluation honesty. The generator makes every trap by changing one value of a kind the parser already reads (a number with a unit, a core count, a pole count, a qualifier word). `wrong_clear = 0` and `ambiguous_cases_clear = 0` therefore confirm that conflicts on PARSED kinds are caught; they say nothing about substitutions in unparsed words, which is what the clear-only vetoes above address (text_differs, spec_one_sided, accessory_word, negation) and which the unit tests, not the packs, cover. `top_accuracy` ranks by score regardless of classification, so it is independent of the vetoes.

Qualifiers are read from the whole description, not from the item noun: `Cable copper 4 mm2 3C+E` against `Cable aluminium 4 mm2 3C+E with copper tinned screen` shares the word `copper`, so no qualifier conflict arises, and the new `text_differs` veto does not block it either (only the quote has extra words), so this pair is still `clear` at 0.81. This is a known remaining gap. The opposite one-sided trade-off also remains: a quote that names a qualifier (`steel`) where the BoQ line names none is not a conflict, so it can still be clear.

Later additions to the vetoes and remaining gaps. Space-grouped values before a unit are ambiguous (`2 100 W` is 2100 W or 2 x 100 W), so both readings are kept as values of that kind: a pair that reads them differently is multi-value and never clear, and the same spelling on both sides still compares equal. A `type` spec kind reads `Type A` / `Type AC` / `Type B` (the word `a` is a stopword, so it needs its own kind); different types conflict and a type on one side only is `spec_one_sided`. `not` and `non` (so `non-dimmable`) are negation words (`no` is deliberately not: it is a unit). Remaining by-design one-sided classes: a feature named on one side only that the parser and vetoes do not read, e.g. `with photocell`, or `20 A SP MCB` against `20 A MCB`, is a one-sided extra and can still be clear when the other side says nothing about it; the vetoes catch differences stated on both sides (or a parsed kind on one side), not omissions. After these additions the clear counts are unchanged (43 committed, 89 hold-out), top_accuracy 1.000, wrong_clear 0.
