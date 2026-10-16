# Slice 4, Phase 2: Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Next.js app a typed API client, cookie-session auth (login, register, sign out, route guard), an app shell, a frontend test setup wired into CI, and a proven PDF.js page renderer, ready for the tender workspace (phase 3) and the review screen (phase 4).

**Architecture:** Client-rendered pages under one root `<Suspense>` with TanStack Query (the Next server never sees the `/api`-scoped session cookie). Types are generated from a committed `frontend/openapi.json` that a backend test keeps equal to the live FastAPI schema. A thin `fetch` wrapper adds the CSRF header, maps the API error format to `ApiError`, and an XHR path gives upload progress. PDF.js loads through a dynamic import inside a client component.

**Tech Stack:** Next.js 16.4.1 (App Router, `cacheComponents`), React 19.3, TypeScript, Tailwind 4, TanStack Query 5, openapi-typescript 7, Vitest 5 + Testing Library, pdfjs-dist 6.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-4-review-ui-design.md` (section 4 and the phase 2 row of section 1). Phase 1 (backend review API) is already merged into `main`.

## Global Constraints

- **Read the bundled Next docs before writing frontend code** (`frontend/AGENTS.md`): this Next differs from older versions. Relevant ones: `node_modules/next/dist/docs/01-app/02-guides/client-side-data-fetching/tanstack-query.md`, `.../lazy-loading.md`, `.../03-api-reference/04-functions/use-params.md`, `.../testing/vitest.md`.
- `cacheComponents` and `partialPrefetching` are enabled in `next.config.ts` and stay on. Any client component that reads a query on first render, or calls `useParams` / `useSearchParams` / `usePathname`, must sit under a `<Suspense>` boundary (the root layout provides one); no server-side `dehydrate()`; the Next server never calls `cookies()`.
- API facts (verified in the backend): CSRF header is exactly `X-Requested-With: IntelTPS`, required on **every** POST, PUT, PATCH and DELETE under `/api/` with no exemptions (login, register, logout included); a missing header is `403` with code `csrf_failed`. Error body is `{"error": {"code", "message", "details"?}}`; 422 `details` is `[{field, message}]`. Session cookie is `intel_session`, `HttpOnly`, path `/api`. `GET /api/v1/me` returns `{user_id, name, email, organisation_id, organisation_name, role, permissions[]}`; register is `201` with the same body and sets the cookie; login is `200`; logout is `204`. Password policy is min 10 characters (server enforces; the UI shows the server message).
- Roles: `admin`, `estimator`, `project_manager`, `reviewer`. Hide controls using `me.permissions`; the API enforces authorisation.
- No tokens or session data in `localStorage`. No `dangerouslySetInnerHTML`. Document text is untrusted: render as text.
- Dev without Docker: the browser origin is Next on `:3000`; `/api/*` is proxied to the local API through an **env-gated** rewrite (`API_PROXY_TARGET`) so the standalone production build contains no rewrite. The API cookie is `Secure` by default; local plain-http dev needs `COOKIE_SECURE=false` in the backend env (Safari rejects Secure cookies on http://localhost: use Chrome or Edge).
- Branch `feat/slice-4-phase-2-frontend-foundation`. Frontend commands run from `frontend/`; backend commands from `backend/` with `DB_HOST_PORT=5433` (this project's Postgres is on 5433).
- After each task: `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` pass from `frontend/` (where the task touches the frontend); backend `ruff check`, `ruff format --check`, `lint-imports`, `pytest` pass where it touches the backend.
- Every commit message ends with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. A network failure or 500 on `/me` must show an error with a retry, **not** bounce the user to `/login`; only a `401` redirects (Task 4).
2. The CSRF header is on every unsafe method and absent on GET; a `403 csrf_failed` is distinguishable from a `403 forbidden` (Task 3).
3. A double click on Sign in / Create account must not submit twice: the button is disabled while the request is pending (Task 4).
4. A signed-in user who opens `/login` or `/register` is sent to `/tenders` (Task 4).
5. A PDF that fails to load (401, 404, corrupt, page out of range) shows an error message, never a blank canvas; a page number outside `1..numPages` is clamped, not an exception (Task 5).

---

### Task 1: Committed OpenAPI contract and its backend test

**Files:**
- Create: `backend/app/api/export_openapi.py`
- Create: `frontend/openapi.json` (generated)
- Test: `backend/tests/test_openapi_contract.py` (create)

**Interfaces:**
- Produces: `app.api.export_openapi.render() -> str` (stable JSON text of `app.openapi()`), `TARGET: Path` (= `frontend/openapi.json`); command `uv run python -m app.api.export_openapi` (from `backend/`) rewrites the file.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_openapi_contract.py`:

```python
"""The frontend's generated types come from frontend/openapi.json; it must match the live API."""

from __future__ import annotations

import json

from app.api.export_openapi import TARGET, render


def test_committed_openapi_matches_the_running_api() -> None:
    committed = json.loads(TARGET.read_text(encoding="utf-8"))
    assert committed == json.loads(render()), (
        "frontend/openapi.json is stale. From backend/ run "
        "`uv run python -m app.api.export_openapi`, then `npm run gen:api` in frontend/, "
        "and commit both files."
    )


def test_the_review_routes_are_in_the_contract() -> None:
    paths = json.loads(render())["paths"]
    for path in (
        "/api/v1/me",
        "/api/v1/auth/login",
        "/api/v1/boq-items/{boq_item_id}",
        "/api/v1/requirements/{requirement_id}/confirm",
        "/api/v1/tenders/{tender_id}/requirements",
    ):
        assert path in paths, path
```

- [ ] **Step 2: Run it to see it fail**

Run (from `backend/`): `DB_HOST_PORT=5433 uv run pytest tests/test_openapi_contract.py -v`
Expected: FAIL (`ModuleNotFoundError: app.api.export_openapi`).

- [ ] **Step 3: Implement the exporter**

Create `backend/app/api/export_openapi.py`:

```python
"""Write the API's OpenAPI document to frontend/openapi.json.

The frontend generates its TypeScript types from that file (`npm run gen:api`), and a test keeps
it equal to the live schema, so a changed DTO breaks the frontend build instead of the browser.

Run from backend/:  uv run python -m app.api.export_openapi
"""

from __future__ import annotations

import json
from pathlib import Path

from app.api.main import app

TARGET = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def render() -> str:
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET}")
```

Run (from `backend/`): `uv run python -m app.api.export_openapi`
Expected output: `wrote ...\frontend\openapi.json`. (If `parents[3]` is wrong for this layout, `app/api/export_openapi.py` is `backend/app/api/…`, so `parents[0]=api`, `[1]=app`, `[2]=backend`, `[3]=repo root`: the path above is correct; verify the printed path ends in `frontend\openapi.json`.)

- [ ] **Step 4: Run to verify it passes, plus lint**

Run: `DB_HOST_PORT=5433 uv run pytest tests/test_openapi_contract.py -v && uv run ruff check . && uv run ruff format --check . && uv run lint-imports`
Expected: 2 passed; ruff and import-linter clean (`app.api` may import `app.api.main`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/export_openapi.py backend/tests/test_openapi_contract.py frontend/openapi.json
git commit -m "feat: commit the OpenAPI contract with a test that keeps it in sync"
```

---

### Task 2: Frontend tooling, generated types, CI

**Files:**
- Modify: `frontend/package.json` (via npm), `frontend/package-lock.json`
- Create: `frontend/vitest.config.mts`, `frontend/vitest.setup.ts`, `frontend/src/api/schema.d.ts` (generated), `frontend/src/api/schema.test.ts`
- Modify: `frontend/eslint.config.mjs`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `frontend/openapi.json` (Task 1).
- Produces: npm scripts `typecheck`, `test`, `test:watch`, `gen:api`; `src/api/schema.d.ts` exporting `paths` and `components` (openapi-typescript v7 shape: `components["schemas"]["MeDTO"]`).

- [ ] **Step 1: Install dependencies (exact versions)**

Run (from `frontend/`):

```bash
npm install --save-exact @tanstack/react-query@5.104.3
npm install --save-dev --save-exact openapi-typescript@7.13.0 vitest@5.0.5 @vitejs/plugin-react@6.1.2 jsdom@30.1.3 @testing-library/react@16.3.3 @testing-library/user-event@14.6.8 @testing-library/jest-dom@7.0.1 vite-tsconfig-paths@6.1.1
```
Expected: installs without peer-dependency errors. If a peer conflict appears (Vitest 5 vs plugin versions), resolve by choosing the nearest compatible published version, record the chosen versions in the commit message, and do not use `--force`.

- [ ] **Step 2: Add scripts and config**

In `frontend/package.json` `"scripts"` add:

```json
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "gen:api": "openapi-typescript openapi.json -o src/api/schema.d.ts"
```

Create `frontend/vitest.config.mts`:

```ts
import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
```

Create `frontend/vitest.setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
```

In `frontend/eslint.config.mjs` add `"src/api/schema.d.ts",` to the `globalIgnores([...])` list.

- [ ] **Step 3: Write the failing smoke test, generate the types, see it pass**

Create `frontend/src/api/schema.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import openapi from "../../openapi.json";
import type { components, paths } from "./schema";

describe("generated API types", () => {
  it("cover the review routes and DTOs", () => {
    const route: keyof paths = "/api/v1/boq-items/{boq_item_id}";
    expect(Object.keys(openapi.paths)).toContain(route);
    const status: components["schemas"]["BoqItemDTO"]["review_status"] = "unreviewed";
    expect(status).toBe("unreviewed");
  });
});
```

Run: `npm test` → FAIL (cannot resolve `./schema`). Then `npm run gen:api` (expected: writes `src/api/schema.d.ts`), then `npm test` → PASS, then `npm run typecheck` → clean.

- [ ] **Step 4: CI**

In `.github/workflows/ci.yml`, in the `frontend` job, after `- run: npm ci` and before `- run: npm run lint`, keep lint, and replace the steps after lint so the job reads:

```yaml
      - run: npm ci
      - run: npm run lint
      - run: npm run typecheck
      - run: npm test
      - name: Generated API types are up to date
        run: |
          npm run gen:api
          git diff --exit-code src/api/schema.d.ts
      - run: npm run build
      - name: Dependency audit (runtime)
        run: npm audit --omit=dev --audit-level=high
```

- [ ] **Step 5: Verify and commit**

Run: `npm run lint && npm run typecheck && npm test && npm run build`
Expected: all pass (the build still renders the existing stub page).

```bash
git add frontend .github/workflows/ci.yml
git commit -m "feat: frontend test tooling, generated API types and CI checks"
```

---

### Task 3: API errors and the typed fetch client

**Files:**
- Create: `frontend/src/api/errors.ts`, `frontend/src/api/client.ts`, `frontend/src/api/types.ts`
- Test: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces:
  - `class ApiError extends Error { status: number; code: string; details?: unknown; isUnauthorized; isForbidden; isCsrfFailure; isConflict; isNotFound; isRowReplaced }` (getters; `isRowReplaced` = `code === "row_replaced"`; `isForbidden` = status 403 and code not `csrf_failed`).
  - `api<T>(path, options?: { method?, json?, query?, signal? }): Promise<T>`; `get<T>(path, query?, signal?)`, `post<T>(path, json?)`, `patch<T>(path, json?)`, `del<T>(path)`; `withQuery(path, query?)`.
  - `upload<T>(path, file: File, fields: Record<string,string>, onProgress?: (fraction: number) => void): Promise<T>` (XHR, multipart field `file`).
  - Types in `types.ts`: `Me`, `Role`, `LoginInput`, `RegisterInput`.
- All paths passed to these functions are full API paths such as `/api/v1/me`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/api/client.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./errors";
import { api, del, get, patch, post, upload, withQuery } from "./client";

const fetchMock = vi.fn();

function respond(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function lastCall(): { url: string; init: RequestInit & { headers: Record<string, string> } } {
  const [url, init] = fetchMock.mock.calls.at(-1)!;
  return { url, init };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("CSRF header", () => {
  it("is absent on GET and present on every unsafe method", async () => {
    fetchMock.mockResolvedValue(respond(200, {}));
    await get("/api/v1/me");
    expect(lastCall().init.headers["X-Requested-With"]).toBeUndefined();
    for (const call of [
      () => post("/api/v1/auth/logout"),
      () => patch("/api/v1/boq-items/1", { unit: "m" }),
      () => del("/api/v1/x"),
      () => api("/api/v1/x", { method: "PUT", json: {} }),
    ]) {
      fetchMock.mockResolvedValueOnce(respond(200, {}));
      await call();
      expect(lastCall().init.headers["X-Requested-With"]).toBe("IntelTPS");
    }
  });
});

describe("requests", () => {
  it("sends JSON bodies with a content type and same-origin credentials", async () => {
    fetchMock.mockResolvedValue(respond(200, { ok: true }));
    await post("/api/v1/auth/login", { email: "a@b.co", password: "x" });
    const { init } = lastCall();
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.co", password: "x" });
    expect(init.credentials).toBe("same-origin");
  });

  it("builds query strings and drops undefined and null values", () => {
    expect(withQuery("/a", { limit: 5, q: "x y", skip: undefined, none: null })).toBe(
      "/a?limit=5&q=x+y",
    );
    expect(withQuery("/a")).toBe("/a");
    expect(withQuery("/a", { skip: undefined })).toBe("/a");
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(respond(204));
    await expect(post<void>("/api/v1/auth/logout")).resolves.toBeUndefined();
  });
});

describe("errors", () => {
  it("maps the API error format, including 422 details", async () => {
    const details = [{ field: "password", message: "Use at least 10 characters." }];
    fetchMock.mockResolvedValue(
      respond(422, { error: { code: "validation_error", message: "Not valid.", details } }),
    );
    const error = await get("/api/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "validation_error", message: "Not valid.", details });
  });

  it("tells csrf_failed from forbidden", async () => {
    fetchMock.mockResolvedValueOnce(respond(403, { error: { code: "csrf_failed", message: "m" } }));
    const csrf = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    fetchMock.mockResolvedValueOnce(respond(403, { error: { code: "forbidden", message: "m" } }));
    const forbidden = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect([csrf.isCsrfFailure, csrf.isForbidden]).toEqual([true, false]);
    expect([forbidden.isCsrfFailure, forbidden.isForbidden]).toEqual([false, true]);
  });

  it("exposes the distinct 409 codes and 401/404", async () => {
    for (const [status, code] of [
      [409, "row_replaced"],
      [409, "tender_archived"],
      [409, "not_processed"],
      [409, "extraction_options_conflict"],
    ] as const) {
      fetchMock.mockResolvedValueOnce(respond(status, { error: { code, message: "m" } }));
      const error = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
      expect(error.isConflict).toBe(true);
      expect(error.code).toBe(code);
      expect(error.isRowReplaced).toBe(code === "row_replaced");
    }
    fetchMock.mockResolvedValueOnce(respond(401, { error: { code: "unauthorized", message: "m" } }));
    expect(((await get("/api/v1/me").catch((e: unknown) => e)) as ApiError).isUnauthorized).toBe(true);
    fetchMock.mockResolvedValueOnce(respond(404, { error: { code: "not_found", message: "m" } }));
    expect(((await get("/api/v1/x").catch((e: unknown) => e)) as ApiError).isNotFound).toBe(true);
  });

  it("falls back to http_error for a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await get("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 502, code: "http_error" });
  });

  it("reports a network failure as ApiError status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = (await get("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 0, code: "network_error" });
  });
});

class FakeXhr {
  static last: FakeXhr;
  headers: Record<string, string> = {};
  upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: unknown;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
}

describe("upload", () => {
  beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));

  it("posts multipart with the CSRF header and reports progress", async () => {
    const progress: number[] = [];
    const file = new File(["%PDF"], "t.pdf", { type: "application/pdf" });
    const promise = upload<{ ok: boolean }>("/api/v1/tenders/1/documents", file, { kind: "boq" }, (f) =>
      progress.push(f),
    );
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url]).toEqual(["POST", "/api/v1/tenders/1/documents"]);
    expect(xhr.headers["X-Requested-With"]).toBe("IntelTPS");
    const form = xhr.body as FormData;
    expect(form.get("kind")).toBe("boq");
    expect((form.get("file") as File).name).toBe("t.pdf");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    xhr.status = 201;
    xhr.responseText = JSON.stringify({ ok: true });
    xhr.onload?.();
    await expect(promise).resolves.toEqual({ ok: true });
    expect(progress).toEqual([0.5]);
  });

  it("rejects with ApiError on an API error and on a network error", async () => {
    const file = new File(["x"], "t.pdf");
    const failing = upload("/api/v1/x", file, {});
    FakeXhr.last.status = 413;
    FakeXhr.last.responseText = JSON.stringify({ error: { code: "limit_exceeded", message: "Too big." } });
    FakeXhr.last.onload?.();
    await expect(failing).rejects.toMatchObject({ status: 413, code: "limit_exceeded" });
    const offline = upload("/api/v1/x", file, {});
    FakeXhr.last.onerror?.();
    await expect(offline).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- src/api/client.test.ts`
Expected: FAIL (cannot resolve `./errors`, `./client`).

- [ ] **Step 3: Implement**

Create `frontend/src/api/errors.ts`:

```ts
/** The API's consistent error body: {"error": {"code", "message", "details"?}}. */
export type ErrorBody = { error: { code: string; message: string; details?: unknown } };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  /** 403 from a permission check (not a missing CSRF header). */
  get isForbidden(): boolean {
    return this.status === 403 && this.code !== "csrf_failed";
  }
  get isCsrfFailure(): boolean {
    return this.status === 403 && this.code === "csrf_failed";
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
  /** A re-run replaced the row between lookup and write: reload the list. */
  get isRowReplaced(): boolean {
    return this.code === "row_replaced";
  }
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", "Could not reach the server. Check your connection and try again.");
}
```

Create `frontend/src/api/client.ts`:

```ts
import { ApiError, type ErrorBody, networkError } from "./errors";

const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "IntelTPS";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type Query = Record<string, string | number | boolean | null | undefined>;
export type RequestOptions = { method?: string; json?: unknown; query?: Query; signal?: AbortSignal };

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

function toApiError(status: number, statusText: string, parsed: unknown): ApiError {
  const error = (parsed as Partial<ErrorBody> | null)?.error;
  return new ApiError(
    status,
    error?.code ?? "http_error",
    error?.message ?? (statusText || "The request failed."),
    error?.details,
  );
}

/** A JSON request to the same-origin API. Full paths, e.g. `/api/v1/me`. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (UNSAFE_METHODS.has(method)) headers[CSRF_HEADER] = CSRF_VALUE;
  let body: string | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  let response: Response;
  try {
    response = await fetch(withQuery(path, options.query), {
      method,
      headers,
      body,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw networkError();
  }
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    throw toApiError(response.status, response.statusText, parsed);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
  api<T>(path, { query, signal });
export const post = <T>(path: string, json?: unknown) => api<T>(path, { method: "POST", json });
export const patch = <T>(path: string, json?: unknown) => api<T>(path, { method: "PATCH", json });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Multipart upload with progress (fetch has no upload progress). */
export function upload<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
  onProgress?: (fraction: number) => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onerror = () => reject(networkError());
    xhr.onload = () => {
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        parsed = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(parsed as T);
      else reject(toApiError(xhr.status, "", parsed));
    };
    xhr.send(form);
  });
}
```

Create `frontend/src/api/types.ts`:

```ts
import type { components } from "./schema";

export type Me = components["schemas"]["MeDTO"];
export type Role = Me["role"];
export type LoginInput = components["schemas"]["LoginRequest"];
export type RegisterInput = components["schemas"]["RegisterRequest"];
```

- [ ] **Step 4: Run to verify they pass**

Run: `npm test -- src/api && npm run typecheck && npm run lint`
Expected: PASS. (If `typecheck` flags `lastCall()`'s tuple typing, loosen the helper's return type to `any`-free equivalents; do not use `// @ts-ignore`.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api
git commit -m "feat: typed API client with CSRF header, error mapping and upload progress"
```

---

### Task 4: Providers, session, route guard, app shell, login and register

**Files:**
- Create: `frontend/src/components/providers.tsx`, `frontend/src/components/field.tsx`, `frontend/src/components/auth-gate.tsx`, `frontend/src/components/app-shell.tsx`, `frontend/src/api/session.ts`, `frontend/src/test/render.tsx`
- Create: `frontend/src/app/(auth)/layout.tsx`, `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(auth)/register/page.tsx`, `frontend/src/app/(app)/layout.tsx`, `frontend/src/app/(app)/tenders/page.tsx`, `frontend/.env.example`
- Modify: `frontend/src/app/layout.tsx`, `frontend/src/app/page.tsx`, `frontend/next.config.ts`, `README.md` (dev section)
- Test: `frontend/src/components/auth-gate.test.tsx`, `frontend/src/app/(auth)/auth-pages.test.tsx`

**Interfaces:**
- Consumes: `get`, `post`, `ApiError`, `Me`, `LoginInput`, `RegisterInput` (Task 3).
- Produces: `meQueryOptions` (key `["me"]`); `useLogin()`, `useRegister()`, `useLogout()` (TanStack mutations; success sets/clears the `["me"]` cache); `AuthGate` (client; 401 → `router.replace("/login")`; other errors show a retry); `useSession(): Me`, `useCan(permission: string): boolean` (only inside `AuthGate`); `Providers`; `AppShell`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/test/render.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

export const ME = {
  user_id: "11111111-1111-1111-1111-111111111111",
  name: "Esta Mator",
  email: "esta@example.com",
  organisation_id: "22222222-2222-2222-2222-222222222222",
  organisation_name: "Acme Electrical",
  role: "estimator" as const,
  permissions: ["read", "edit_tenders", "upload_documents", "review_data"],
};

export function respond(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function errorBody(code: string, message: string) {
  return { error: { code, message } };
}

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
```

Create `frontend/src/components/auth-gate.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, renderWithClient, respond } from "@/test/render";

import { AuthGate, useCan, useSession } from "./auth-gate";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  replace.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function Who() {
  const me = useSession();
  const canReview = useCan("review_data");
  const canManage = useCan("manage_members");
  return <p>{`${me.name}|${canReview}|${canManage}`}</p>;
}

describe("AuthGate", () => {
  it("renders children with the session and permission checks", async () => {
    fetchMock.mockResolvedValue(respond(200, ME));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects to /login on 401 only", async () => {
    fetchMock.mockResolvedValue(respond(401, errorBody("unauthorized", "Sign in.")));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText(/Esta/)).not.toBeInTheDocument();
  });

  it("shows an error with a retry, and does not redirect, on a server or network failure", async () => {
    fetchMock.mockResolvedValueOnce(respond(500, errorBody("internal_error", "Something went wrong.")));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(replace).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(respond(200, ME));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();

    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect((await screen.findAllByRole("alert")).at(-1)).toHaveTextContent(/could not reach the server/i);
    expect(replace).not.toHaveBeenCalled();
  });
});
```

Create `frontend/src/app/(auth)/auth-pages.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, renderWithClient, respond } from "@/test/render";

import LoginPage from "./login/page";
import RegisterPage from "./register/page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  replace.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function signedOut(extra: (url: string, init?: RequestInit) => Response | undefined) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/me") return respond(401, errorBody("unauthorized", "Sign in."));
    const handled = extra(url, init);
    if (handled) return handled;
    throw new Error(`unexpected request ${url}`);
  });
}

describe("login page", () => {
  it("posts the credentials with the CSRF header and goes to /tenders", async () => {
    signedOut((url) => (url === "/api/v1/auth/login" ? respond(200, ME) : undefined));
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/v1/auth/login")!;
    expect(call[1].headers["X-Requested-With"]).toBe("IntelTPS");
    expect(JSON.parse(call[1].body)).toEqual({
      email: "esta@example.com",
      password: "correct-horse-battery",
    });
  });

  it("shows the server's message for a wrong password and stays on the page", async () => {
    signedOut((url) =>
      url === "/api/v1/auth/login"
        ? respond(401, errorBody("unauthorized", "Invalid email or password."))
        : undefined,
    );
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password-1");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(replace).not.toHaveBeenCalled();
  });

  it("disables the button while the request is pending (no double submit)", async () => {
    let finish: (r: Response) => void = () => {};
    signedOut((url) => {
      if (url !== "/api/v1/auth/login") return undefined;
      return new Promise<Response>((resolve) => (finish = resolve)) as unknown as Response;
    });
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    const button = screen.getByRole("button", { name: /sign in/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/auth/login")).toHaveLength(1);
    finish(respond(200, ME));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
  });

  it("sends an already signed-in user straight to /tenders", async () => {
    fetchMock.mockResolvedValue(respond(200, ME));
    renderWithClient(<LoginPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
  });
});

describe("register page", () => {
  it("creates the account, then goes to /tenders", async () => {
    signedOut((url) => (url === "/api/v1/auth/register" ? respond(201, ME) : undefined));
    renderWithClient(<RegisterPage />);
    await userEvent.type(await screen.findByLabelText(/organisation/i), "Acme Electrical");
    await userEvent.type(screen.getByLabelText(/your name/i), "Esta Mator");
    await userEvent.type(screen.getByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/v1/auth/register")!;
    expect(JSON.parse(call[1].body)).toEqual({
      organisation_name: "Acme Electrical",
      name: "Esta Mator",
      email: "esta@example.com",
      password: "correct-horse-battery",
    });
  });

  it("shows the password policy message from the API", async () => {
    signedOut((url) =>
      url === "/api/v1/auth/register"
        ? respond(422, errorBody("validation_error", "Use at least 10 characters."))
        : undefined,
    );
    renderWithClient(<RegisterPage />);
    await userEvent.type(await screen.findByLabelText(/organisation/i), "Acme");
    await userEvent.type(screen.getByLabelText(/your name/i), "Esta");
    await userEvent.type(screen.getByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "short");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Use at least 10 characters.");
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- src/components src/app`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Implement the session layer and components**

Create `frontend/src/api/session.ts`:

```ts
import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import type { LoginInput, Me, RegisterInput } from "./types";

export const meQueryOptions = queryOptions({
  queryKey: ["me"] as const,
  queryFn: ({ signal }) => get<Me>("/api/v1/me", undefined, signal),
  retry: false,
  staleTime: 30_000,
});

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: LoginInput) => post<Me>("/api/v1/auth/login", input),
    onSuccess: (me) => queryClient.setQueryData(meQueryOptions.queryKey, me),
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RegisterInput) => post<Me>("/api/v1/auth/register", input),
    onSuccess: (me) => queryClient.setQueryData(meQueryOptions.queryKey, me),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => post<void>("/api/v1/auth/logout"),
    onSettled: () => queryClient.clear(), // drop every cached tenant row, signed in or not
  });
}
```

Create `frontend/src/components/providers.tsx`:

```tsx
"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useState, type ReactNode } from "react";

import { ApiError } from "@/api/errors";

/** One query client per browser tab. The Suspense boundary is required by Cache Components for
 * anything that reads a query, `useParams` or `useSearchParams` during the first render. */
export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (count, error) =>
              !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Suspense fallback={<p role="status" className="p-8 text-sm text-zinc-500">Loading…</p>}>
        {children}
      </Suspense>
    </QueryClientProvider>
  );
}
```

Create `frontend/src/components/auth-gate.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions } from "@/api/session";
import type { Me } from "@/api/types";

const SessionContext = createContext<Me | null>(null);

/** The signed-in user. Only valid inside <AuthGate>. */
export function useSession(): Me {
  const me = useContext(SessionContext);
  if (!me) throw new Error("useSession must be used inside <AuthGate>");
  return me;
}

/** UI convenience only: the API enforces permissions on every request. */
export function useCan(permission: string): boolean {
  return useSession().permissions.includes(permission);
}

export function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { data: me, error, isPending, refetch } = useQuery(meQueryOptions);
  const unauthorized = error instanceof ApiError && error.isUnauthorized;

  useEffect(() => {
    if (unauthorized) router.replace("/login");
  }, [unauthorized, router]);

  if (isPending || unauthorized) {
    return <p role="status" className="p-8 text-sm text-zinc-500">Loading…</p>;
  }
  if (error || !me) {
    return (
      <div role="alert" className="mx-auto max-w-md p-8">
        <p className="mb-4">{error instanceof Error ? error.message : "Something went wrong."}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="rounded bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          Try again
        </button>
      </div>
    );
  }
  return <SessionContext value={me}>{children}</SessionContext>;
}
```

Create `frontend/src/components/field.tsx`:

```tsx
import { useId, type InputHTMLAttributes } from "react";

type Props = { label: string } & InputHTMLAttributes<HTMLInputElement>;

export function Field({ label, ...input }: Props) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        {...input}
        className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700"
      />
    </div>
  );
}
```

Create `frontend/src/components/app-shell.tsx`:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { useLogout } from "@/api/session";
import type { Role } from "@/api/types";

import { useSession } from "./auth-gate";

const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  estimator: "Estimator",
  project_manager: "Project manager",
  reviewer: "Reviewer",
};

export function AppShell({ children }: { children: ReactNode }) {
  const me = useSession();
  const router = useRouter();
  const logout = useLogout();
  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:bg-white focus:p-2 focus:text-black"
      >
        Skip to content
      </a>
      <header className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <nav aria-label="Main" className="flex items-center gap-6">
          <Link href="/tenders" className="text-lg font-semibold tracking-tight">
            IntelTPS
          </Link>
          <Link href="/tenders" className="text-sm hover:underline">
            Tenders
          </Link>
        </nav>
        <div className="flex items-center gap-4 text-sm">
          <span>{me.organisation_name}</span>
          <span>
            {me.name} ({ROLE_LABELS[me.role]})
          </span>
          <button
            type="button"
            disabled={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSettled: () => router.replace("/login") })}
            className="rounded border border-zinc-300 px-3 py-1 hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            Sign out
          </button>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 p-4 sm:p-8">
        {children}
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Implement the pages, layouts and config**

Create `frontend/src/app/(auth)/layout.tsx`:

```tsx
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">IntelTPS</h1>
      {children}
    </main>
  );
}
```

Create `frontend/src/app/(auth)/login/page.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions, useLogin } from "@/api/session";
import { Field } from "@/components/field";

export default function LoginPage() {
  const router = useRouter();
  const login = useLogin();
  const { data: me } = useQuery(meQueryOptions);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (me) router.replace("/tenders");
  }, [me, router]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (login.isPending) return;
    login.mutate({ email, password }, { onSuccess: () => router.replace("/tenders") });
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">Sign in</h2>
      <Field label="Email" type="email" autoComplete="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="current-password" required
        value={password} onChange={(e) => setPassword(e.target.value)} />
      {login.error ? (
        <p role="alert" className="text-sm text-red-600">
          {login.error instanceof ApiError ? login.error.message : "Could not sign in."}
        </p>
      ) : null}
      <button type="submit" disabled={login.isPending}
        className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
        {login.isPending ? "Signing in…" : "Sign in"}
      </button>
      <p className="text-sm">
        New here? <Link href="/register" className="underline">Create an account</Link>
      </p>
    </form>
  );
}
```

Create `frontend/src/app/(auth)/register/page.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { meQueryOptions, useRegister } from "@/api/session";
import { Field } from "@/components/field";

export default function RegisterPage() {
  const router = useRouter();
  const register = useRegister();
  const { data: me } = useQuery(meQueryOptions);
  const [organisationName, setOrganisationName] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  useEffect(() => {
    if (me) router.replace("/tenders");
  }, [me, router]);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (register.isPending) return;
    register.mutate(
      { organisation_name: organisationName, name, email, password },
      { onSuccess: () => router.replace("/tenders") },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4">
      <h2 className="text-xl font-medium">Create your organisation</h2>
      <Field label="Organisation name" required minLength={2} value={organisationName}
        onChange={(e) => setOrganisationName(e.target.value)} />
      <Field label="Your name" autoComplete="name" required value={name}
        onChange={(e) => setName(e.target.value)} />
      <Field label="Email" type="email" autoComplete="email" required value={email}
        onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="new-password" required
        value={password} onChange={(e) => setPassword(e.target.value)} />
      <p className="text-xs text-zinc-500">At least 10 characters.</p>
      {register.error ? (
        <p role="alert" className="text-sm text-red-600">
          {register.error instanceof ApiError ? register.error.message : "Could not create the account."}
        </p>
      ) : null}
      <button type="submit" disabled={register.isPending}
        className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
        {register.isPending ? "Creating…" : "Create account"}
      </button>
      <p className="text-sm">
        Already registered? <Link href="/login" className="underline">Sign in</Link>
      </p>
    </form>
  );
}
```

Create `frontend/src/app/(app)/layout.tsx`:

```tsx
import type { ReactNode } from "react";

import { AppShell } from "@/components/app-shell";
import { AuthGate } from "@/components/auth-gate";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
  );
}
```

Create `frontend/src/app/(app)/tenders/page.tsx`:

```tsx
export default function TendersPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold tracking-tight">Tenders</h1>
      <p className="mt-2 text-zinc-600 dark:text-zinc-400">
        The tender list arrives with the tender workspace (Slice 4, phase 3).
      </p>
    </section>
  );
}
```

Replace `frontend/src/app/page.tsx` with:

```tsx
import { redirect } from "next/navigation";

export default function Home() {
  redirect("/tenders");
}
```

In `frontend/src/app/layout.tsx`: import `Providers` from `@/components/providers`, change `metadata` to `title: "IntelTPS"` / `description: "Intelligent Tender Preparation System"`, and wrap `{children}` in `<Providers>…</Providers>` inside `<body>` (keep the fonts and the `LayoutProps<"/">` signature).

Replace `frontend/next.config.ts` with:

```ts
import type { NextConfig } from "next";

// `npm run dev` without Docker: set API_PROXY_TARGET=http://127.0.0.1:8000 so /api/* reaches the
// API on the same origin (the session cookie is scoped to /api). Unset in Compose and in
// production builds: Caddy does the routing there (ADR-0009).
const apiProxyTarget = process.env.API_PROXY_TARGET;

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return apiProxyTarget
      ? [{ source: "/api/:path*", destination: `${apiProxyTarget}/api/:path*` }]
      : [];
  },
};

export default nextConfig;
```

Create `frontend/.env.example`:

```
# Only for `npm run dev` without Docker: proxy /api/* to the local API (same origin, so the
# /api-scoped session cookie works). Also set COOKIE_SECURE=false in the backend env.
API_PROXY_TARGET=http://127.0.0.1:8000
```

In `README.md`, under "Develop without Docker", replace the two code lines with:

```bash
cd backend && uv sync && COOKIE_SECURE=false uv run uvicorn app.api.main:app --reload
cd frontend && npm install && API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
# open http://localhost:3000 (Chrome or Edge: Safari rejects Secure cookies on http)
```
and add one sentence: "After changing API DTOs run `uv run python -m app.api.export_openapi` in `backend/` and `npm run gen:api` in `frontend/`; CI fails when the generated types are stale."

- [ ] **Step 5: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: all tests pass; build succeeds (this proves the Suspense/Cache Components rules hold for the new pages). If the build reports "blocking prerender" or "URL data in a Client Component outside Suspense", move the offending hook under the root `Providers` Suspense (already wrapping every page) or add a local `<Suspense>`; do not disable `cacheComponents`.

- [ ] **Step 6: Commit**

```bash
git add frontend README.md
git commit -m "feat: auth pages, session route guard and app shell"
```

---

### Task 5: PDF.js page renderer (the Next 16 spike)

**Files:**
- Modify: `frontend/package.json`, `frontend/package-lock.json` (via npm)
- Create: `frontend/src/components/pdf/pdf-page.tsx`, `frontend/src/components/pdf/clamp-page.ts`, `frontend/src/app/(app)/dev/pdf-spike/page.tsx`
- Test: `frontend/src/components/pdf/clamp-page.test.ts`, `frontend/src/components/pdf/pdf-page.test.tsx`

**Interfaces:**
- Produces: `clampPage(requested: number, numPages: number): number` (integer within `1..numPages`; non-finite or `< 1` → 1); `<PdfPage url pageNumber scale? />` (client component: loads `pdfjs-dist` with a dynamic import, renders one page to a canvas, shows `role="status"` while loading and `role="alert"` with a message on any failure); route `/dev/pdf-spike?version=<id>&page=<n>` (developer spike, removed when phase 4 replaces it).

- [ ] **Step 1: Install pdfjs-dist**

Run (from `frontend/`): `npm install --save-exact pdfjs-dist@6.4.299`
Then read the shipped types before coding: `node_modules/pdfjs-dist/types/src/display/api.d.ts` — find `getDocument` parameters (`url`, `withCredentials`), `PDFDocumentLoadingTask` (`promise`, `destroy`), and `RenderParameters` (v5+ takes `canvas` + `viewport`; older versions take `canvasContext`). Use whichever the shipped types require. Also confirm the worker file name in `node_modules/pdfjs-dist/build/` (expected `pdf.worker.min.mjs`).

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/components/pdf/clamp-page.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { clampPage } from "./clamp-page";

describe("clampPage", () => {
  it.each([
    [1, 5, 1],
    [3, 5, 3],
    [5, 5, 5],
    [6, 5, 5],
    [99, 5, 5],
    [0, 5, 1],
    [-4, 5, 1],
    [2.7, 5, 2],
    [Number.NaN, 5, 1],
    [Number.POSITIVE_INFINITY, 5, 5],
    [3, 0, 1],
  ])("clampPage(%s, %s) = %s", (requested, numPages, expected) => {
    expect(clampPage(requested, numPages)).toBe(expected);
  });
});
```

Create `frontend/src/components/pdf/pdf-page.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const getDocument = vi.fn();
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: {},
  getDocument: (...args: unknown[]) => getDocument(...args),
}));

import { PdfPage } from "./pdf-page";

afterEach(() => getDocument.mockReset());

function fakeDocument(numPages: number) {
  const render = vi.fn(() => ({ promise: Promise.resolve() }));
  const getPage = vi.fn(async () => ({
    getViewport: () => ({ width: 100, height: 140 }),
    render,
  }));
  return { numPages, getPage, destroy: vi.fn() };
}

describe("PdfPage", () => {
  it("shows an error, not a blank canvas, when the file cannot be loaded", async () => {
    getDocument.mockReturnValue({
      promise: Promise.reject(new Error("Unexpected server response (401)")),
      destroy: vi.fn(),
    });
    render(<PdfPage url="/api/v1/document-versions/x/file" pageNumber={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not display/i);
  });

  it("clamps an out-of-range page number to the last page", async () => {
    const doc = fakeDocument(3);
    getDocument.mockReturnValue({ promise: Promise.resolve(doc), destroy: vi.fn() });
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({})) as never;
    render(<PdfPage url="/api/v1/document-versions/x/file" pageNumber={99} />);
    await waitFor(() => expect(doc.getPage).toHaveBeenCalledWith(3));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to see them fail**

Run: `npm test -- src/components/pdf`
Expected: FAIL (modules do not exist).

- [ ] **Step 4: Implement**

Create `frontend/src/components/pdf/clamp-page.ts`:

```ts
/** A page number inside 1..numPages. Non-finite or below 1 becomes 1; above the end becomes the
 * last page. PDF.js throws for an out-of-range page, so every caller goes through this. */
export function clampPage(requested: number, numPages: number): number {
  const last = Math.max(1, Math.floor(numPages));
  if (Number.isNaN(requested) || requested < 1) return 1;
  if (!Number.isFinite(requested)) return last;
  return Math.min(Math.floor(requested), last);
}
```

Create `frontend/src/components/pdf/pdf-page.tsx` (adapt the `getDocument` / `render` calls to the shipped types you read in Step 1; the structure below is fixed):

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

import { clampPage } from "./clamp-page";

type State =
  | { status: "loading" }
  | { status: "ready"; numPages: number; shown: number }
  | { status: "error"; message: string };

type Props = { url: string; pageNumber: number; scale?: number };

/** Renders one page of a same-origin PDF to a canvas. pdfjs-dist is imported dynamically inside
 * the effect, so it never loads on the server and only loads when a PDF is shown. */
export function PdfPage({ url, pageNumber, scale = 1.25 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [state, setState] = useState<State>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    let loadingTask: { destroy: () => Promise<void> | void } | undefined;
    setState({ status: "loading" });

    (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        const task = pdfjs.getDocument({ url, withCredentials: true });
        loadingTask = task;
        const pdf = await task.promise;
        const shown = clampPage(pageNumber, pdf.numPages);
        const page = await pdf.getPage(shown);
        const canvas = canvasRef.current;
        if (cancelled || !canvas) return;
        const viewport = page.getViewport({ scale });
        canvas.width = viewport.width;
        canvas.height = viewport.height;
        await page.render({ canvas, viewport }).promise;
        if (!cancelled) setState({ status: "ready", numPages: pdf.numPages, shown });
      } catch {
        if (!cancelled) {
          setState({
            status: "error",
            message: "Could not display this document page. Reload, or download the original file.",
          });
        }
      }
    })();

    return () => {
      cancelled = true;
      void loadingTask?.destroy();
    };
  }, [url, pageNumber, scale]);

  return (
    <div>
      {state.status === "loading" ? (
        <p role="status" className="text-sm text-zinc-500">Loading page…</p>
      ) : null}
      {state.status === "error" ? (
        <p role="alert" className="text-sm text-red-600">{state.message}</p>
      ) : null}
      {state.status === "ready" ? (
        <p className="mb-1 text-xs text-zinc-500">
          Page {state.shown} of {state.numPages}
        </p>
      ) : null}
      <canvas ref={canvasRef} className={state.status === "error" ? "hidden" : "max-w-full border"} />
    </div>
  );
}
```

Create `frontend/src/app/(app)/dev/pdf-spike/page.tsx`:

```tsx
"use client";

import { useSearchParams } from "next/navigation";

import { PdfPage } from "@/components/pdf/pdf-page";

/** Developer spike (Slice 4 phase 2): proves PDF.js renders inside this Next build. Replaced by
 * the review screen's source viewer in phase 4, then deleted. */
export default function PdfSpikePage() {
  const params = useSearchParams();
  const version = params.get("version");
  const page = Number(params.get("page") ?? "1");
  if (!version) {
    return <p>Add ?version=&lt;document version id&gt;&amp;page=&lt;n&gt; to the address.</p>;
  }
  return (
    <section>
      <h1 className="mb-4 text-xl font-semibold">PDF.js spike</h1>
      <PdfPage url={`/api/v1/document-versions/${encodeURIComponent(version)}/file`} pageNumber={page} />
    </section>
  );
}
```

- [ ] **Step 5: Run to verify, including the production build**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: tests pass and the build succeeds. The build is the real proof for this task: it shows `pdfjs-dist` and its worker bundle under Turbopack with `cacheComponents` on. If the build fails on the worker URL, try (in this order, recording what worked): (a) `import.meta.url` variant as written; (b) copy `pdf.worker.min.mjs` into `public/pdfjs/` at install time with a `postinstall`-free explicit script and set `workerSrc = "/pdfjs/pdf.worker.min.mjs"`; (c) if neither works, STOP and report BLOCKED with the exact error, because phase 4's viewer depends on this.

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: PDF.js page renderer (clamped page, error state) and dev spike route"
```

---

### Task 6: Real-browser verification, spike result and status (controller task)

This task needs a running API and a browser, so the controller runs it (not a subagent). It touches only a throwaway database, never the developer's `inteltps` database.

**Files:**
- Create: `docs/spikes/slice-4-pdfjs.md`
- Modify: `docs/plan.md` (Slice 4 status line), `docs/known-limitations.md` (only if something new was found)

- [ ] **Step 1: Throwaway backend**

From the repo root (Git Bash). The Postgres container is `inteltps-db-1` on host port 5433:

```bash
docker exec inteltps-db-1 psql -U intel -d postgres -c "CREATE DATABASE inteltps_spike"
cd backend
export DATABASE_URL=postgresql+psycopg://intel:intel@127.0.0.1:5433/inteltps_spike COOKIE_SECURE=false ENVIRONMENT=development LLM_PROVIDER=fake STORAGE_PATH="$TMP/spike-files"
uv run alembic upgrade head
uv run uvicorn app.api.main:app --port 8000
```
(second terminal / background). Expected: `Uvicorn running on http://127.0.0.1:8000`; `curl -s http://127.0.0.1:8000/api/v1/health` → `{"status":"ok"}`.

- [ ] **Step 2: Frontend dev server and an uploaded PDF**

```bash
cd frontend && API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```
In a browser (Chrome/Edge via the browser tools) open `http://localhost:3000` → redirected to `/login`. Click "Create an account", register `spike@example.com` / password `correct-horse-battery` / organisation `Spike Org` → lands on `/tenders` with the shell (org name, user name and role, Sign out).

Create a multi-page PDF and upload it as the same user with curl (cookie jar):

```bash
cd backend && uv run python -c "import pymupdf; d=pymupdf.open(); [d.new_page().insert_text((72,72), f'Spike page {i}') for i in (1,2,3)]; d.save('$TMP/spike.pdf')"
H='X-Requested-With: IntelTPS'
curl -s -c "$TMP/jar" -H "$H" -H 'Content-Type: application/json' -d '{"email":"spike@example.com","password":"correct-horse-battery"}' http://127.0.0.1:8000/api/v1/auth/login
TID=$(curl -s -b "$TMP/jar" -H "$H" -H 'Content-Type: application/json' -d '{"title":"Spike"}' http://127.0.0.1:8000/api/v1/tenders | python -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -b "$TMP/jar" -H "$H" -F "file=@$TMP/spike.pdf;type=application/pdf" -F kind=tender_document http://127.0.0.1:8000/api/v1/tenders/$TID/documents
```
Take `version.id` from the upload response.

- [ ] **Step 3: Verify in the browser and record what you saw**

1. `http://localhost:3000/dev/pdf-spike?version=<id>&page=2` shows a canvas with "Spike page 2" and "Page 2 of 3". `page=99` shows page 3 of 3; `page=0` shows page 1. A random UUID shows the red "Could not display" alert, not a blank canvas. Check the browser console for errors (worker load, CSP).
2. Sign out → `/login`; reload `/tenders` while signed out → redirected to `/login`; sign in again → `/tenders`; open `/login` while signed in → redirected to `/tenders`.
3. A wrong password shows the server message; stop the API and reload `/tenders` while signed in → error with "Try again" (not a redirect to `/login`); restart the API and click "Try again" → recovers.

- [ ] **Step 4: Production-mode check**

```bash
cd frontend && npm run build && API_PROXY_TARGET=http://127.0.0.1:8000 npm start
```
Repeat Step 3 item 1 on `http://localhost:3000` (the production server serves the prerendered shell with Cache Components; this is what the demo runs). Note: `API_PROXY_TARGET` must be set at **build** time for the rewrite to be baked into `next build`; if the proxy does not work in `next start`, run `API_PROXY_TARGET=… npm run build` first and record it.

- [ ] **Step 5: Write the result and clean up**

Create `docs/spikes/slice-4-pdfjs.md` with the actual outcome: pdfjs-dist version, which worker setup worked (`import.meta.url` or the `public/` copy), dev and production results for each check above, console errors (or none), bundle observations if any, and the decision for phase 4 (reuse `PdfPage`; what it still lacks: text-layer highlight, zoom, page controls). Update the `docs/plan.md` Slice 4 status line to "phase 2 (frontend foundation) done" with the commit range. Then stop the servers and drop the throwaway database:

```bash
docker exec inteltps-db-1 psql -U intel -d postgres -c "DROP DATABASE inteltps_spike WITH (FORCE)"
```
Remove `$TMP/spike-files`, `$TMP/spike.pdf`, `$TMP/jar`.

- [ ] **Step 6: Commit**

```bash
git add docs
git commit -m "docs: PDF.js spike result and Slice 4 phase 2 status"
```

---

## Self-Review

**Spec coverage (spec section 4 and the phase 2 row of section 1):** typed client generated from a committed `openapi.json` with a backend equality test and CI regenerate-and-diff (Tasks 1-2); wrapper with CSRF header on every unsafe method, error mapping, `csrf_failed` vs `forbidden`, distinct 409 codes (Task 3); XHR upload with progress (Task 3); Suspense/Cache Components constraints and no server prefetch (Global Constraints, Task 4 `Providers`, build check); `/me` guard, 401-only redirect, signed-in redirect, no `proxy.ts` (Task 4); routes `(auth)/login`, `(auth)/register`, `(app)/tenders` placeholder (Task 4) - the other routes in the spec arrive in phases 3-6; env-gated dev rewrite and the Secure-cookie/Safari note (Task 4, README); `tsc --noEmit` + Vitest in CI (Task 2); PDF.js spike with named fallback (Task 5) and real-browser verification (Task 6).

**Placeholder scan:** none. Two places defer to facts that cannot be known until install: Task 2 Step 1 (peer-version resolution) and Task 5 Steps 1/4 (pdfjs `render`/`getDocument` parameter names are read from the shipped types); both say exactly what to read and what to do.

**Type consistency:** `ApiError` getters (`isUnauthorized`, `isForbidden`, `isCsrfFailure`, `isNotFound`, `isConflict`, `isRowReplaced`) are used with the same names in `client.test.ts` and `auth-gate.tsx`; `meQueryOptions.queryKey` is `["me"]` in `session.ts` and every `setQueryData`; `useSession`/`useCan` live in `auth-gate.tsx` and are imported from there by `app-shell.tsx` and the tests; `Me`/`Role`/`LoginInput`/`RegisterInput` come from `types.ts` which reads `components["schemas"]` names that exist in the current OpenAPI (`MeDTO`, `LoginRequest`, `RegisterRequest`).

**Known risks for the executor:** Vitest 5 / plugin-react 6 / jsdom 30 are recent majors (resolve peers, do not force); the production `rewrites` needs `API_PROXY_TARGET` at build time only for the no-Docker demo; `cacheComponents` prerender can reject a hook outside Suspense (the root `Providers` boundary is the fix).
