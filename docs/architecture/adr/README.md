# Architecture Decision Records (IntelTPS)

Format: MADR. New decisions get the next number; superseded ADRs stay, with status updated.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-modular-monolith-with-background-worker.md) | Modular monolith with one background worker | Accepted |
| [0002](0002-postgres-pgvector-fts-hybrid-retrieval.md) | PostgreSQL + pgvector + FTS with RRF (no Chroma / rank_bm25) | Accepted |
| [0003](0003-llm-and-embeddings-behind-ports.md) | LLM and embeddings behind swappable ports, configured by environment | Accepted |
| [0004](0004-deterministic-first-extraction-and-code-attached-provenance.md) | Deterministic-first extraction; provenance and numbers owned by code | Accepted |
| [0005](0005-tenant-isolation-strategy.md) | Tenant isolation: scoped data-access path, organisation_id everywhere, composite FKs; RLS deferred | Accepted |
| [0006](0006-db-backed-job-queue-and-idempotent-stages.md) | Postgres-backed job queue, staged pipeline, idempotent and resumable stages | Accepted |
| [0007](0007-storage-port-local-volume-now-blob-later.md) | File storage behind a port: local volume now, blob/S3 later | Accepted |
| [0008](0008-authentication-and-session-approach.md) | Self-managed auth: short JWT cookie, rotating refresh token, roles from DB | Accepted (session mechanism amended by 0010) |
| [0009](0009-single-origin-edge-and-qa-streaming.md) | Single origin behind Caddy + Cloudflare Tunnel; Q&A streams over fetch (stretch) | Accepted (Q&A stretch) |
| [0010](0010-solo-scope-and-server-side-sessions.md) | Solo build: reduced scope and server-side sessions | Accepted |

Overview and module contracts: [../architecture.md](../architecture.md). Diagrams: [../diagrams/](../diagrams/).
