# IntelTPS: Intelligent Tender Preparation System

AI-assisted tender preparation for South African construction subcontractors. Group project, 16 Oct to 16 Nov 2026.

- Requirements: [docs/prd.md](docs/prd.md) (base spec: `Python_Project.pdf`, kept outside the repo)
- Delivery plan: [docs/plan.md](docs/plan.md)
- Architecture, ADRs, diagrams: [docs/architecture/](docs/architecture/architecture.md)

## Layout

```
backend/    FastAPI modular monolith + worker (uv, pytest, ruff, import-linter)
frontend/   Next.js + TypeScript + Tailwind
infra/      Caddy single-origin config
docs/       PRD, plan, architecture
```

## Prerequisites

Docker Desktop (running), Node 24, Python 3.12 with [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com) installed natively on the host (not in Docker).

## Run the stack

```bash
cp .env.example .env
docker compose up --build
```

- App (through Caddy): http://127.0.0.1:8080 (Caddy is published on loopback only; the api and web ports are not published)
- API health: http://127.0.0.1:8080/api/v1/health (and `/api/v1/health/db`)
- Public link: run the Cloudflare tunnel (`cloudflared`) on the same machine pointing at `http://127.0.0.1:8080`. Cloudflare sets `CF-Connecting-IP`; Caddy turns it (or the TCP peer when absent) into `X-Client-IP`, overwriting anything the client sent, and the API rate-limits on it (`CLIENT_IP_HEADER=X-Client-IP`). For the tunnel (HTTPS) set `ENVIRONMENT=production`, a real `SECRET_KEY` and `COOKIE_SECURE=true` in `.env`; `COOKIE_SECURE=false` is only for local plain http.
- Postgres: 127.0.0.1:${DB_HOST_PORT:-5432} (local only; set `DB_HOST_PORT` in `.env` if 5432 is taken)

Documents are limited to 25 MB per upload (`MAX_UPLOAD_MB`). Scanned PDFs are read with Tesseract OCR, which is installed in the backend image (English model); no host setup is needed for it.

Ollama runs on the host and containers reach it at `host.docker.internal:11434` (`LLM_BASE_URL`). If containers cannot connect, start Ollama with `OLLAMA_HOST=0.0.0.0` and firewall port 11434.

Pull the model once on the host (`ollama pull qwen3:4b`, the `LLM_MODEL` default). Without Docker, set `LLM_BASE_URL=http://127.0.0.1:11434`.

To score extraction on the synthetic packs against the running stack (manual; slow on CPU, a few minutes per pack):

```bash
uv run --project backend python scripts/score_slice3.py --email scorer@example.com     --gen eval/generated --packs pack01 pack02 --out preds_slice3
cd eval && uv run python -m harness score --gen generated --pred ../preds_slice3 --label slice3
```

The script registers (or logs in) one account per run; registration is limited to 5 per hour per IP, so reuse `--email`. Results of the Slice 3 gate: `docs/spikes/slice-3-scores.md`.

## Develop without Docker

```bash
cd backend && uv sync && COOKIE_SECURE=false uv run uvicorn app.api.main:app --reload
cd frontend && npm install && API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
# open http://localhost:3000 (Chrome or Edge: Safari rejects Secure cookies on http)
```

After changing API DTOs run `uv run python -m app.api.export_openapi` in `backend/` and `npm run gen:api` in `frontend/`; CI fails when the generated types are stale.

## Checks (also run in CI)

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run lint-imports      # architecture boundaries (fitness function F2)
# Tests need Postgres with pgvector (docker compose up -d db). They create and migrate a
# throwaway `inteltps_test` database. If Postgres is not on port 5432, set DB_HOST_PORT or
# TEST_DATABASE_URL, e.g. postgresql+psycopg://intel:intel@127.0.0.1:5433/inteltps_test
uv run pytest -q

cd ../frontend
npm run lint && npm run build
```

## Moving to a VM

`docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d` (no exposed DB port, restart policies, 80/443). Publishing Caddy on 80/443 makes `CF-Connecting-IP` client-controlled unless only Cloudflare can reach the VM; read the comment in `docker-compose.vm.yml` first. See docs/prd.md section 21.

## Rules for real documents

Never commit real tender documents. Keep them in `local-documents/` (git-ignored) and use synthetic data with the tunnel and any hosted model.
