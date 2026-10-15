# ADR-0001: Modular monolith with one background worker

- **Status:** Accepted
- **Date:** 2026-10-15
- **Deciders:** IntelTPS team (4 members)

## Context and Problem Statement
Four students have 32 days, one laptop to host on, and fewer than 10 concurrent users. The workload has two shapes: fast request/response (CRUD, review, export) and slow, memory-hungry document processing (OCR, embedding, LLM at 5-15 tokens/s). The base spec (§4.7, §5.6) requires a modular monolith and allows a separate worker. How do we structure the backend so four people can work in parallel without stepping on each other?

## Decision Drivers
- Delivery speed and low operational load (one machine, no on-call)
- Parallel work by 4 people (Conway's Law: 4 ownership areas)
- Long jobs must not block HTTP requests; memory must stay within 16 GB
- Maintainability marks: separate business logic, data access, doc processing and AI (base spec §4.6)

## Considered Options
1. **Modular monolith (one codebase/image) + one worker process sharing the modules**
2. Plain layered monolith (routers/services/models folders), FastAPI BackgroundTasks for jobs
3. Microservices (API, ingestion service, AI service)

## Decision Outcome
Chosen option: **Option 1**. One Python package with modules (`identity`, `tenders`, `documents`, `knowledge`, `extraction`, `estimating`, `suppliers`, `checklist`, `reporting`, `billing`, `audit`, `qa`), two entrypoints (`api`, `worker`) built from the same Docker image. Module boundaries are enforced by **import-linter** contracts in CI (see diagrams/backend-components.md).

### Consequences
- Positive: one deploy, one DB transaction scope, no network contracts between our own components; boundaries are real (tested) so a module could later be extracted.
- Negative / Tradeoff: we give up independent scaling and independent deploys; a crash-looping dependency (e.g. a native OCR lib) can affect both entrypoints because they share an image. Facade discipline costs a little extra code (DTOs at module edges).
- Follow-ups: write the import-linter contract on day 2, before modules have code, so it never has to be retrofitted.

## Pros and Cons of the Options

### Option 1
- Good: simple ops, testable seams, matches base spec, maps to team ownership.
- Bad: shared process memory per entrypoint; requires discipline (mitigated by CI).

### Option 2
- Good: fastest to start.
- Bad: "folders by layer" hides the domain (no screaming architecture); BackgroundTasks die with the request process, have no retries, no visibility (violates FR-15/FR-16).

### Option 3
- Good: independent scaling.
- Bad: distributed-systems tax (network failure modes, contracts, deploys) with no scale force to justify it; explicitly a PRD non-goal.

## Links / References
- Base spec §4.6, §4.7, §5.3, §5.6; PRD §7
- Newman, *Building Microservices* ("monolith first"); Martin, *Clean Architecture* (Dependency Rule); import-linter docs
