# Contributing

- Branch from `main`: `feat/<task-id>-short-name` (task IDs are in docs/plan.md, e.g. `feat/M2-3-job-queue`).
- One pull request per task, at least one reviewer, CI must be green to merge.
- Do not change the frozen contracts (kernel types, ERD, DTOs, OpenAPI) after day 4 without a note in the group channel.
- Modules import other modules only through `public.py` and follow the arrows in `docs/architecture/diagrams/backend-components.md`. `uv run lint-imports` enforces this.
- Money uses `Decimal`, never `float`. Missing values are `NULL` plus a flag, never 0.
- Logs and audit events contain IDs, never document text or secrets.
- Definition of Done: see Appendix B of the base spec (validation, permissions, tests, error handling, docs, limitations noted).
