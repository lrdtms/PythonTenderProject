# Synthetic tender data and evaluation (M1)

Generates fictional tender packs plus **ground truth**, so extraction accuracy (PRD section 13) can be measured automatically. Everything is invented; every document is stamped "Synthetic test document - fictional data".

## Usage

```bash
cd eval
uv sync
uv run python -m synthgen generate --out generated          # the standard 8 packs
uv run python -m synthgen generate --out generated --stress # plus a ~93-page stress pack
uv run python -m synthgen verify --out generated            # re-check files against ground truth
uv run pytest -q                                            # generator tests
```

Options: `--seed N` (default 42, same seed gives byte-identical ground truth), `--only pack03 pack05`.
Output goes to `eval/generated/` (git-ignored, reproducible from the seed).

## The standard set (PRD section 13 targets: 8 packs, 5+ quotations, ~150 BoQ lines, ~60 requirements)

| Pack | What it exercises |
|---|---|
| pack01 | Clean native PDF, BoQ as a PDF table, one PDF quotation |
| pack02 | Clean native PDF, BoQ in XLSX, PDF + XLSX quotations |
| pack03 | Dense layout (requirements buried in paragraphs), messy PDF BoQ (unit aliases, missing and "rate only" quantities, spaced thousands) |
| pack04 | Dense layout, messy XLSX BoQ (title block, merged cells, comma decimals, subtotals, extra sheet) |
| pack05 | Scanned tender PDF (image only, rotated, blurred, noisy), BoQ table inside it |
| pack06 | Scanned tender + messy XLSX BoQ |
| pack07 | About 25 pages, mostly boilerplate, PDF + XLSX quotations |
| pack08 | Adversarial: a prompt-injection paragraph and 5 near-identical "decoy" quotation items |
| pack09_xl | (`--stress`) About 93 pages, 12 requirements spread thinly, for timing and pre-filter tests |

Current totals (standard 8): 72 requirements, 166 BoQ lines, 11 quotations (162 items), 2 scanned tender documents.

## Ground truth (`ground_truth.json`, schema in `schema/ground_truth.schema.json`)

- **requirements**: id, description, type, mandatory status, `evidence_quote` (verbatim sentence in the source), `keyword` (a correct extraction must contain it), and the source location.
- **boq_items**: canonical `unit`/`quantity` plus the `raw_unit`/`raw_quantity` exactly as printed, flags (`missing_quantity`, `rate_only`, `unit_alias`, `provisional_sum`), and the source location. A missing quantity is `null`, never 0.
- **quotations**: per item `expected_match` (the BoQ item a correct matcher confirms), `confusable_with` (a near-identical BoQ item that must NOT be auto-matched), `unit_mismatch`, `ambiguous`.
- **non_requirements**: text that looks like an instruction but is not a requirement (prompt injection).
- **Locations** use the **physical 1-based page index** (what PDF.js opens), plus the printed page label (which deliberately differs by 1-2), or sheet + cell range for spreadsheets.

## How the labels stay trustworthy

`verify` re-opens every generated file and checks that each quote is on the recorded page, each BoQ row is at the recorded page or cell range, scanned PDFs have no text layer, and page counts match. The generator also checks the native PDF before turning it into a scan. The tests include a tamper test that proves `verify` fails when ground truth is wrong.

## Known limits (v1)

- Scanned packs are not OCR-verified (the quotes were checked on the native PDF before scanning). Add a Tesseract-based check once OCR is wired up.
- Requirements are template-based sentences with varied facts, so the language is cleaner than real tenders. Add real documents later per PRD section 20 (permission required, never commit them).
- Filler text is drawn from a small pool of descriptive sentences, so long packs repeat sentences.
- The catalogue is electrical-only.
