# C4 Level 2: Containers (IntelTPS)

```mermaid
C4Container
    title Containers: IntelTPS on one machine (Docker Compose + native Ollama)

    Person(user, "Tenant user", "Any organisation role")
    System_Ext(cf, "Cloudflare edge", "Public HTTPS")

    System_Boundary(host, "Developer laptop (later: one VM)") {
        Container(tunnel, "cloudflared", "Host process, outside Compose", "Outbound tunnel run on the host; only target is Caddy on 127.0.0.1:8080")
        Container(edge, "Reverse proxy", "Caddy", "Single origin: / -> web, /api -> api. No response buffering for streams")
        Container(web, "Web app", "Next.js (production build), TS, Tailwind, PDF.js", "UI, review beside source, BoQ editor, comparison")
        Container(api, "API", "FastAPI, Pydantic, SQLAlchemy", "Auth, RBAC, tenant scoping, business rules, enqueue jobs, signed file links, (stretch) Q&A stream")
        Container(worker, "Worker", "Same Python image, different entrypoint", "Claims jobs; parse, OCR, chunk, embed, extract, validate. Concurrency 1")
        ContainerDb(db, "Database", "PostgreSQL 16 + pgvector", "Relational state of record, jobs, chunks, vectors, tsvector, audit")
        ContainerDb(files, "File store", "Named Docker volume (StoragePort)", "Original uploads (all versions) and generated exports")
        Container(ollama, "LLM runtime", "Ollama, native on host (GPU/CPU)", "Small instruct model; JSON-schema constrained output")
        Container(mail, "Mailpit", "Container", "Dev SMTP sink")
    }

    Rel(user, cf, "Uses", "HTTPS")
    Rel(cf, tunnel, "Tunnel", "QUIC/HTTP2")
    Rel(tunnel, edge, "Forwards", "HTTP")
    Rel(edge, web, "Routes /", "HTTP")
    Rel(edge, api, "Routes /api", "HTTP")
    Rel(api, db, "Reads/writes (tenant-scoped)", "SQL")
    Rel(worker, db, "Claims jobs, writes results", "SQL")
    Rel(api, files, "Stores uploads, streams downloads", "StoragePort")
    Rel(worker, files, "Reads originals, writes exports", "StoragePort")
    Rel(worker, ollama, "Structured extraction", "HTTP via LLM_BASE_URL")
    Rel(api, ollama, "Q&A generation (stretch)", "HTTP via LLM_BASE_URL")
    Rel(api, mail, "Reminders", "SMTP")
```

Rules
- `cloudflared` is not part of the Compose stack: it runs on the host and connects to Caddy, which is published on `127.0.0.1:8080` only. Caddy is the only thing the tunnel can reach.
- Only Caddy is reachable from the tunnel. Postgres, Ollama, worker and Mailpit publish no ports to the public interface.
- API and worker are one codebase, one image, two entrypoints (`api`, `worker`). They share modules, not a network API.
- Embeddings (bge-small, CPU, ONNX) run in-process in the worker (indexing) and the API (query embedding for Q&A).
- `LLM_BASE_URL` points at `host.docker.internal:11434` locally; on a VM it points at a sidecar or same-host Ollama. Nothing else changes.
