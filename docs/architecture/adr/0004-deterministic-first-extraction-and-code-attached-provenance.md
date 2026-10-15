# ADR-0004: Deterministic-first extraction; provenance and numbers owned by code

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
A 1.5-4B model on a GTX 1050 will make mistakes. Quantities, units and source references are critical fields (PRD §13 target >= 95%). Schema-constrained output guarantees valid JSON, not correct values. Where does the LLM sit, and how do we stop it inventing values or sources?

## Decision Drivers
- BR-02 provenance, BR-03 deterministic financial maths, FR-55, FR-56
- Evaluation targets on critical fields
- Prompt-injection resistance (document text is untrusted, FR-17)
- CPU inference cost: every LLM call is 10-60 s

## Considered Options
1. **Deterministic parsers first; LLM only classifies/cleans/suggests; code attaches provenance and verifies evidence**
2. LLM extracts everything from page text, including provenance
3. Deterministic only (no LLM)

## Decision Outcome
Chosen option: **Option 1**.
- **BoQ:** pdfplumber (native PDF tables) / openpyxl (XLSX) / csv produce rows with item number, description, unit, quantity, rate. Numbers parse to `Decimal`; failures become `missing`, never `0`. The LLM may only: classify a row (item / heading / subtotal), normalise a unit to a controlled list, or *suggest* a missing value, stored as `suggested_value` with `ai_suggested = true`, never as `original_value`.
- **Requirements:** map over every chunk with a schema-constrained prompt (FR-61). The schema has **no provenance fields**; it requires an `evidence_quote`. Code checks the quote against the chunk text (normalised fuzzy match >= 0.9). Fail: the candidate is kept but flagged `evidence_unverified`. Code then attaches `SourceRef(document_version_id, page|sheet, cell_range?, chunk_id)` from chunk metadata.
- **Supplier matching:** deterministic multi-signal score (normalised text similarity, product-code regex, unit compatibility, size/spec tokens, manufacturer, price/date sanity). No LLM in MVP. Ambiguity (top-2 gap < threshold) forces `needs_confirmation`; nothing is auto-confirmed (BR-04, FR-37).
- **All money maths** in `estimating/domain` with `Decimal` and explicit rounding; the LLM never computes a total.

### Consequences
- Positive: critical fields stay testable and reproducible; hallucinated sources are impossible by construction; injection can at worst produce a wrong *candidate*, which a human reviews (BR-01).
- Negative / Tradeoff: messy or scanned BoQ tables that the parser cannot read get no automatic lines (FR-55 known limitation), and evidence verification throws away some correct but paraphrased requirements (lower recall). Rule-based matching needs hand-tuned thresholds.
- Follow-ups: tune the evidence-match threshold against the §13 set; log the share of `evidence_unverified`.

## Pros and Cons of the Options

### Option 1
- Good: accuracy on critical fields, auditability, fewer LLM calls.
- Bad: parser rules per layout; scanned BoQs need manual entry.

### Option 2
- Good: handles odd layouts in theory.
- Bad: small models misread tables and invent page numbers; slow; untestable.

### Option 3
- Good: fully deterministic.
- Bad: requirement extraction from prose is not feasible with rules alone; loses the AI marks.

## Links / References
- PRD FR-55, FR-56, FR-61, §10; base spec BR-01..BR-04; Evans, *DDD* (keeping domain rules in the domain)
