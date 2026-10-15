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

- App (through Caddy): http://localhost:8080
- API health: http://localhost:8080/api/v1/health (and `/api/v1/health/db`)
- Postgres: 127.0.0.1:${DB_HOST_PORT:-5432} (local only; set `DB_HOST_PORT` in `.env` if 5432 is taken)

Ollama runs on the host and containers reach it at `host.docker.internal:11434` (`LLM_BASE_URL`). If containers cannot connect, start Ollama with `OLLAMA_HOST=0.0.0.0` and firewall port 11434.

## Develop without Docker

```bash
cd backend && uv sync && uv run uvicorn app.api.main:app --reload
cd frontend && npm install && npm run dev
```

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

`docker compose -f docker-compose.yml -f docker-compose.vm.yml up -d` (no exposed DB port, restart policies, 80/443). See docs/prd.md section 21.

## Rules for real documents

Never commit real tender documents. Keep them in `local-documents/` (git-ignored) and use synthetic data with the tunnel and any hosted model.
