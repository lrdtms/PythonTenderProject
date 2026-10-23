# C4 Level 3: Backend Components and Allowed Dependencies

An arrow `A --> B` means "A may import B's public facade (`modules/b/public.py`)". Anything not drawn is forbidden and is checked in CI by import-linter (ADR-0001). The graph is acyclic.

```mermaid
flowchart TB
    subgraph entry["Entrypoints (outermost ring)"]
        API["api/<br/>FastAPI routers, auth deps,<br/>error mapping, OpenAPI"]
        WRK["worker/<br/>job loop + pipeline<br/>orchestration (stages)"]
    end

    subgraph mods["modules/ (each: public.py, domain/, service.py, repo.py)"]
        IDN["identity<br/>users, orgs, memberships, RBAC"]
        BIL["billing<br/>plans, usage limits (mocked)"]
        TEN["tenders<br/>tender workspace"]
        DOC["documents<br/>uploads, versions, file links"]
        KNW["knowledge<br/>parse, OCR, chunk, embed,<br/>hybrid search (only path)"]
        EXT["extraction<br/>BoQ table parser, LLM prompts,<br/>schemas, validators (pure core)"]
        EST["estimating<br/>BoQ items and review"]
        EST2["estimates<br/>pricing, estimates, pure calc.py"]
        SUP["suppliers<br/>quotations, matching, decisions"]
        CHK["checklist<br/>requirements, tasks, deadlines"]
        REP["reporting<br/>Excel/PDF exports"]
        QA["qa (stretch)<br/>grounded answers"]
        AUD["audit<br/>append-only events"]
    end

    subgraph kernel["kernel/ (shared kernel, no I/O)"]
        K["OrgContext, Role, IDs, Money/Decimal,<br/>SourceRef, error types,<br/>Ports: LLMPort, EmbeddingPort,<br/>StoragePort, JobQueuePort, Clock"]
    end

    subgraph infra["infrastructure/ (adapters, implement ports)"]
        DB["db: engine, tenant-scoped<br/>session/repository base"]
        JQ["jobs: Postgres queue<br/>(SKIP LOCKED, leases)"]
        LLM["llm: OllamaAdapter,<br/>OpenAICompatibleAdapter"]
        EMB["embeddings: FastEmbedAdapter"]
        STO["storage: LocalVolume,<br/>(later) Blob/S3"]
    end

    API --> IDN & BIL & TEN & DOC & EST & EST2 & SUP & CHK & REP & QA & AUD & KNW
    WRK --> DOC & KNW & EXT & EST & SUP & CHK & REP & AUD

    DOC --> TEN & BIL & AUD
    KNW --> DOC
    EST --> TEN & AUD
    EST2 --> AUD
    SUP --> EST & DOC & AUD
    CHK --> TEN & IDN & AUD
    REP --> AUD
    QA --> KNW
    IDN --> AUD
    TEN --> AUD

    mods --> kernel
    infra -. implements ports .-> kernel
    mods -. repos use .-> DB
```

## Rules this diagram encodes

1. **Dependency Rule (Clean Architecture).** Entrypoints depend on modules; modules depend on `kernel`; adapters implement `kernel` ports. Modules never import `api/`, `worker/` or a concrete adapter (LLM, embeddings, storage, queue). Adapters are wired at startup in `api/main.py` and `worker/main.py`.
2. **Facade-only cross-module access.** A module imports only `other_module.public`. It never imports another module's ORM models or repositories and never queries another module's tables.
3. **Pure cores.** `extraction/` (whole module) and every `modules/*/domain/` package import neither `fastapi` nor `sqlalchemy`. They take DTOs in and return DTOs out, so they are unit-testable without a DB or a model.
4. **Worker orchestrates, extraction computes.** `extraction` never writes BoQ items or requirements. The worker passes chunks/tables in, gets validated candidates out, and hands them to `estimating.public` / `checklist.public` / `suppliers.public`, which persist them.
5. **Pragmatic exception.** Module repositories use SQLAlchemy directly through the tenant-scoped base in `infrastructure/db` (Repository pattern, PoEAA). We do not abstract the ORM. Tradeoff: a DB swap would touch every repo, which we accept.
