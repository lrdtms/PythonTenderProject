# ADR-0009: Single origin behind Caddy and Cloudflare Tunnel; Q&A streams over fetch (stretch)

- **Status:** Accepted (Q&A part is stretch, behind feature flag `FEATURE_QA`)
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team

## Context and Problem Statement
The marking link is a Cloudflare quick tunnel whose URL changes on each restart. The frontend and API need cookies, CORS and streaming to work regardless of that URL. Q&A (US-06, FR-53) is a stretch goal that streams slow CPU generation; `EventSource` only supports GET, and proxies may buffer streams.

## Decision Drivers
- Changing tunnel hostname; cookie and CSRF simplicity (ADR-0008)
- Perceived latency at 5-15 tokens/s
- Q&A is not in the rubric; must not threaten the core

## Considered Options
1. **Caddy as the only tunnelled service: `/api/*` -> FastAPI, `/*` -> Next.js (production build). Q&A = `POST /api/tenders/{id}/ask` returning a `text/event-stream`-formatted body read with `fetch` + `ReadableStream`**
2. Tunnel Next.js only, proxy API through Next.js rewrites; Q&A via Next.js route
3. Two hostnames (web and API) with CORS; Q&A via `EventSource` GET with a short-lived query token
4. WebSockets

## Decision Outcome
Chosen option: **Option 1**.
- One origin means no CORS, `SameSite=Lax` cookies just work, and the random tunnel URL needs no config change (the browser calls relative `/api`). Server-side Next.js calls, if any, use `API_INTERNAL_URL=http://api:8000`.
- Caddy `reverse_proxy` with `flush_interval -1` on `/api/tenders/*/ask`; FastAPI `StreamingResponse` with `Cache-Control: no-cache` and `X-Accel-Buffering: no`. Events: `meta` (retrieved chunk list with document/page), `token`, `citations` (validated by code), `done`, `error`.
- Q&A pipeline (if built): `knowledge.search` (tenant + tender scoped) -> prompt with numbered chunks -> stream -> code maps `[n]` markers to chunk IDs from the retrieved set only -> if no chunk passes a relevance floor, answer "not found in this pack" without calling the LLM. Store `chat_queries` with cited chunk IDs only.
- Go/no-go for Q&A on **day 25**: build only if upload-to-export works end to end and the cross-tenant suite is green.

### Consequences
- Positive: one URL to post, no CORS bugs, works unchanged on a VM behind Caddy with real TLS.
- Negative / Tradeoff: one more container (~30 MB RAM); POST streaming needs a hand-written stream parser on the client instead of `EventSource` (no auto-reconnect; acceptable for one-shot answers). Q&A requests go to the same single Ollama instance as the worker, so a question asked during extraction waits behind it.
- Follow-ups: during demos, pause the worker or pre-process documents before asking questions. Verify early that Cloudflare does not buffer `text/event-stream` (it normally streams it).

## Pros and Cons of the Options

### Option 1
- Good: simplest browser story, VM-ready.
- Bad: extra proxy to configure.

### Option 2
- Good: no extra container.
- Bad: Next.js rewrites/dev server can buffer streams; ties the API to the frontend runtime.

### Option 3
- Good: `EventSource` reconnection.
- Bad: CORS plus cross-site cookies (`SameSite=None`) on a changing hostname; token in URL ends up in logs.

### Option 4
- Good: bidirectional.
- Bad: unnecessary for one-way token streams; more state.

## Links / References
- PRD §9 streaming note, §21 tunnel and exposure rules, US-06, FR-53, FR-54; Caddy `reverse_proxy` docs (`flush_interval`)
