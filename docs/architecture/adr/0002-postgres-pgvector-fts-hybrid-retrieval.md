# ADR-0002: PostgreSQL + pgvector + full-text search with RRF (no Chroma / rank_bm25)

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
The RAG proposal used ChromaDB (vectors) and rank_bm25 (in-memory keyword index) next to a relational DB. We need vector + keyword retrieval that is tenant-isolated, shared safely by the API and the worker, backed up with everything else, and updated idempotently.

## Decision Drivers
- Tenant isolation must apply to retrieval exactly as to relational data (FR-58, BR-05)
- Exact matching of clause IDs and reference numbers (e.g. "SANS 10142-1", "B.3.12")
- One store, one backup, transactional idempotency (FR-59)
- RAM budget (16 GB) and scale (tens of tenders, < 100k chunks)

## Considered Options
1. **Postgres: `vector(384)` column (pgvector) + `tsvector` column, fused with Reciprocal Rank Fusion in SQL**
2. ChromaDB + rank_bm25 + Postgres
3. Postgres for data + a dedicated vector DB (Qdrant)

## Decision Outcome
Chosen option: **Option 1**.
- `document_chunks` holds `organisation_id`, `tender_id`, `document_version_id`, location, text, `text_hash`, `embedding vector(384)`, `tsv tsvector`, `embedding_model`.
- Retrieval is one SQL function in `knowledge.search()`: two CTEs (vector top-20, keyword top-20), each filtered by `organisation_id`, `tender_id` and current document version, fused with RRF (k = 60), top 4-6 returned.
- **No ANN index at first.** Exact (sequential) cosine distance over a tender's chunks is milliseconds at our scale and has perfect recall. An HNSW index combined with a tenant `WHERE` filter post-filters and can silently return fewer than k rows. Add HNSW only if a measured query exceeds 200 ms, and then use pgvector iterative index scans.
- Text search config: index with `simple` (no stemming) so codes and numbers survive tokenisation, optionally plus an `english` column for prose. Query with `websearch_to_tsquery`.

### Consequences
- Positive: tenant filter, version filter and joins in one query; ACID updates (replace a version's chunks in one transaction); one backup/restore covers vectors.
- Negative / Tradeoff: Postgres FTS ranking (`ts_rank`) is not true BM25, so keyword relevance is somewhat weaker; we accept it because RRF only uses rank order and exact-term matching is the main need. The embedding dimension is fixed in the schema; changing the embedding model means a migration plus re-index job.
- Follow-ups: record `embedding_model` per chunk; the retrieval hit-rate metric (PRD §13) validates the choice.

## Pros and Cons of the Options

### Option 1
- Good: isolation, consistency, simplicity, low RAM.
- Bad: weaker lexical ranking; ANN plus filters needs care at larger scale.

### Option 2
- Good: matches the original proposal; real BM25.
- Bad: three stores to keep consistent; rank_bm25 is in-process memory, rebuilt per process, so API and worker indexes diverge; no tenant filter at the storage layer; extra backups.

### Option 3
- Good: strong ANN with payload filters.
- Bad: another container and RAM, dual writes without transactions, no need at our scale.

## Links / References
- PRD FR-51, FR-52, FR-58, FR-59; Kleppmann, *DDIA* ch. 3 (indexes), ch. 7 (transactions)
- Cormack et al., "Reciprocal Rank Fusion" (SIGIR 2009); pgvector README (filtering, iterative scans)
