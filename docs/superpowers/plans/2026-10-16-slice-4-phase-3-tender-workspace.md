# Slice 4, Phase 3: Tender Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in user can see their tenders, create and archive them, open a tender, upload documents (and new versions) with progress, watch the processing job, retry a failed job, and see and re-run the extraction status of each document version.

**Architecture:** Client-rendered views under `(app)` pages that are thin server components (`export const instant = false` plus the view), TanStack Query hooks per resource in `src/api/`, pure helper modules for plain-words status text and client-side file rules, and a handful of small components. A global 401 hook re-checks the session when any query or mutation is refused. Polling is driven by `refetchInterval` and stops on terminal statuses.

**Tech Stack:** Next.js 16.4.1 (App Router, `cacheComponents`), React 19.3, TypeScript, Tailwind 4, TanStack Query 5, Vitest 5 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-16-slice-4-review-ui-design.md` (section 5, "Tender workspace (phase 3)"). Phases 1 and 2 are merged into `main`; this plan builds on the typed client and auth layer from phase 2.

## Global Constraints

- **Read the bundled Next docs before writing frontend code** (`frontend/AGENTS.md`): this Next differs from older versions. Relevant: `node_modules/next/dist/docs/01-app/02-guides/client-side-data-fetching/tanstack-query.md`, `.../02-guides/instant-navigation.md`, `.../03-api-reference/04-functions/use-params.md`.
- `cacheComponents` and `partialPrefetching` stay ON. Every page under `src/app/(app)/**/page.tsx` is a **server component** that exports `export const instant = false;` (with the explanatory comment used in the existing pages) and renders a client view; a test (`src/app/app-pages.test.ts`) enforces the export. Client views read dynamic route params with `useParams()` (under the root `<Suspense>`). No `cookies()` on the Next server; no `dangerouslySetInnerHTML`; document names and warnings are untrusted text.
- API facts (verified in the backend). Paths are full, e.g. `/api/v1/tenders`. Tenders: `GET /tenders?include_archived=`, `POST /tenders` (`TenderCreate`: `title` 1-300 required; `reference_number` ≤100, `client_name` ≤200, `location` ≤200, `closing_at` ISO datetime, all optional), `GET /tenders/{id}`, `POST /tenders/{id}/archive`; statuses `preparing`, `in_review`, `ready`, `submitted`, `archived`. Documents: `GET /tenders/{id}/documents` (`DocumentDTO[]` each with `current_version: VersionDTO | null`), `POST /tenders/{id}/documents` (multipart `file`, form `kind` in `tender_document|boq|quotation|other`, optional `title`; `201` `UploadResultDTO {document, version, job_id}`), `POST /documents/{id}/versions` (multipart `file`). Upload rules (server messages): file not empty, ≤ 25 MB (`"The file is larger than the 25 MB limit."`), extension `pdf|xlsx|csv|docx` (`"Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file."`), content must match the extension; 422 for these, 403 `limit_exceeded` for plan limits, 409 `tender_archived` for archived tenders. Version `processing_status`: `pending|processing|ready|ready_with_warnings|failed`. Jobs: `GET /jobs/{id}` (`JobDTO`: `status` in `queued|running|succeeded|succeeded_with_warnings|failed|cancelled`, `progress_done`, `progress_total`, `error_code`, `warnings[]`), `POST /jobs/{id}/retry`. Extraction: `POST /document-versions/{id}/extract` body `{deep_scan}` returns `JobDTO[]` (409 codes `not_processed`, `tender_archived`, `extraction_options_conflict`), `GET /document-versions/{id}/extraction` returns `{kinds: [{kind: "boq"|"requirements", job: JobDTO|null, run: RunDTO|null}]}`; run `counts` are `{items, pages_with_boq}` for boq and `{requirements, windows, candidate_sentences, evidence_unverified}` for requirements; `warnings` entries look like `{code, pages?, count?, limit?, candidates?}`.
- Permissions (from `me.permissions`; the API enforces them): create/archive tender = `edit_tenders`; upload, new version, retry job = `upload_documents`; run extraction = `review_data`. Project managers and reviewers therefore see no write controls except what their permissions allow. Archived tenders show an "archived, read-only" note and no write controls.
- Show the **job** status (not the run status) for extraction: a run stays `running` while its job waits for a transient retry (known limitation).
- Polling: `refetchInterval` returns `false` for terminal job statuses; default 2000 ms for jobs and 3000 ms for extraction while any job is active; components accept an optional `pollMs` for tests. Polling must stop when the component unmounts (TanStack does this; a test pins it).
- Controls that submit or mutate are disabled while their request is pending (no double submit). No native `confirm()`/`alert()` dialogs (they block browser automation): archive uses an inline two-step "Archive" then "Confirm archive / Cancel".
- Frontend commands run from `frontend/`; backend commands (only Task 6) from `backend/` with `DB_HOST_PORT=5433`. After each task: `npm run lint`, `npm run typecheck` (which runs `next typegen` first), `npm test` and `npm run build` pass, and `rm -rf .next` afterwards.
- Branch `feat/slice-4-phase-3-tender-workspace`. Every commit message ends with the attribution lines from the session's system reminder (`Co-Authored-By: ...` and `Claude-Session: ...`).

## Review Focus

1. Polling stops on terminal job statuses and when the view unmounts (no request storm after navigating away) (Tasks 3, 5).
2. No double submit: Create tender, Upload, Retry and Run extraction are disabled while pending (Tasks 2-5).
3. Client-side file validation mirrors the server's messages, and a server rejection (422, 403 `limit_exceeded`, 409) is still shown, never swallowed (Task 4).
4. A 401 on any query or mutation (except login/register/logout) re-checks the session so `AuthGate` clears the cache and redirects (Task 1).
5. Read-only users and archived tenders see no write controls and a clear note (Tasks 2-5).

---

### Task 1: Foundation — global 401 hook, types, plain-words helpers, fixtures

**Files:**
- Create: `frontend/src/api/query-client.ts`, `frontend/src/api/query-client.test.ts`
- Modify: `frontend/src/components/providers.tsx`, `frontend/src/api/session.ts`, `frontend/src/api/types.ts`
- Create: `frontend/src/lib/status-text.ts`, `frontend/src/lib/status-text.test.ts`, `frontend/src/lib/file-rules.ts`, `frontend/src/lib/file-rules.test.ts`, `frontend/src/lib/format.ts`
- Create: `frontend/src/components/status-badge.tsx`
- Create: `frontend/src/test/fixtures.ts`, `frontend/src/test/fake-xhr.ts`; Modify: `frontend/src/test/render.tsx`

**Interfaces:**
- Produces:
  - `createQueryClient(): QueryClient` — the app's client (same defaults as today) plus: a 401 `ApiError` from any query, or from any mutation not marked `meta: { skipAuthCheck: true }`, calls `client.invalidateQueries({ queryKey: ["me"] })` (the active `AuthGate` observer then refetches `/me`, gets 401, clears the cache and redirects).
  - `types.ts`: `Tender`, `TenderCreate`, `DocumentItem`, `DocumentVersion`, `UploadResult`, `Job`, `Run`, `KindStatus`, `ExtractionStatus` (aliases of the generated `components["schemas"]` DTOs).
  - `lib/status-text.ts`: `isTerminalJob(status?: string): boolean`; `jobStatusLabel`, `processingStatusLabel`, `tenderStatusLabel`, `documentKindLabel`, `kindLabel` (extraction kinds) `(s: string) => string`; `jobErrorText(code: string | null): string`; `warningText(w: unknown): string`; `type Tone = "neutral" | "info" | "success" | "warning" | "danger"`; `jobTone`, `processingTone`, `tenderTone`.
  - `lib/file-rules.ts`: `MAX_UPLOAD_MB = 25`, `ACCEPT = ".pdf,.xlsx,.csv,.docx"`, `validateFile(file: File): string | null`, `formatBytes(n: number): string`.
  - `lib/format.ts`: `formatDateTime(iso: string | null | undefined): string`.
  - `<StatusBadge tone label />`.
  - Test helpers: `mockApi(routes, me?)`, `meWith(permissions, role?)`, `renderSignedIn(ui, { client? })`, `callsTo(fetchMock, method, path)`, fixtures `makeTender/makeVersion/makeDocument/makeJob/makeRun/makeExtraction`, and `FakeXhr`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/api/query-client.test.ts`:

```ts
import { QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorBody, respond } from "@/test/render";

import { get, post } from "./client";
import { createQueryClient } from "./query-client";
import { meQueryOptions } from "./session";
import { ME } from "@/test/render";

const fetchMock = vi.fn();

function meCalls(): number {
  return fetchMock.mock.calls.filter(([url]) => url === "/api/v1/me").length;
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/v1/me") return respond(200, ME);
    if (url === "/api/v1/tenders") return respond(401, errorBody("unauthorized", "Sign in."));
    if (url === "/api/v1/boom") return respond(500, errorBody("internal_error", "No."));
    if (url === "/api/v1/auth/login") return respond(401, errorBody("unauthorized", "Wrong."));
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

async function withActiveMe() {
  const client = createQueryClient();
  const observer = new QueryObserver(client, meQueryOptions);
  const stop = observer.subscribe(() => {});
  await vi.waitFor(() => expect(meCalls()).toBe(1));
  return { client, stop };
}

describe("global 401 handling", () => {
  it("re-checks the session when any query is refused with 401", async () => {
    const { client, stop } = await withActiveMe();
    await client.fetchQuery({ queryKey: ["tenders"], queryFn: () => get("/api/v1/tenders"), retry: false }).catch(() => {});
    await vi.waitFor(() => expect(meCalls()).toBe(2));
    stop();
  });

  it("re-checks the session when a mutation is refused with 401", async () => {
    const { client, stop } = await withActiveMe();
    await client
      .getMutationCache()
      .build(client, { mutationFn: () => post("/api/v1/tenders", {}) })
      .execute({})
      .catch(() => {});
    await vi.waitFor(() => expect(meCalls()).toBe(2));
    stop();
  });

  it("does not for a mutation marked skipAuthCheck (a wrong password is a 401 too)", async () => {
    const { client, stop } = await withActiveMe();
    await client
      .getMutationCache()
      .build(client, { meta: { skipAuthCheck: true }, mutationFn: () => post("/api/v1/auth/login", {}) })
      .execute({})
      .catch(() => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(meCalls()).toBe(1);
    stop();
  });

  it("does not for other errors, and not when the failing query is /me itself", async () => {
    const { client, stop } = await withActiveMe();
    await client.fetchQuery({ queryKey: ["boom"], queryFn: () => get("/api/v1/boom"), retry: false }).catch(() => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(meCalls()).toBe(1);
    stop();
  });
});
```

Create `frontend/src/lib/status-text.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import {
  documentKindLabel,
  isTerminalJob,
  jobErrorText,
  jobStatusLabel,
  jobTone,
  kindLabel,
  processingStatusLabel,
  tenderStatusLabel,
  warningText,
} from "./status-text";

describe("status text", () => {
  it("knows the terminal job statuses", () => {
    for (const s of ["succeeded", "succeeded_with_warnings", "failed", "cancelled"]) {
      expect(isTerminalJob(s)).toBe(true);
    }
    for (const s of ["queued", "running", undefined, ""]) expect(isTerminalJob(s)).toBe(false);
  });

  it("labels every known status in plain words and never shows a raw code for an unknown one", () => {
    expect(jobStatusLabel("running")).toBe("Processing");
    expect(jobStatusLabel("succeeded_with_warnings")).toBe("Done, with warnings");
    expect(processingStatusLabel("ready_with_warnings")).toBe("Ready, with warnings");
    expect(tenderStatusLabel("in_review")).toBe("In review");
    expect(documentKindLabel("boq")).toBe("Bill of quantities");
    expect(kindLabel("requirements")).toBe("Requirements");
    expect(jobStatusLabel("weird_new_status")).toBe("Unknown status");
    expect(jobTone("failed")).toBe("danger");
    expect(jobTone("succeeded")).toBe("success");
  });

  it("explains job failures in plain words", () => {
    expect(jobErrorText("PDF_ENCRYPTED")).toMatch(/password/i);
    expect(jobErrorText("FILE_CORRUPT")).toMatch(/damaged|cannot be read/i);
    expect(jobErrorText("LLM_UNAVAILABLE")).toMatch(/AI/);
    expect(jobErrorText("TENDER_ARCHIVED")).toMatch(/archived/i);
    expect(jobErrorText("SOMETHING_NEW")).toBe("Processing failed. Try again, or upload the file again.");
    expect(jobErrorText(null)).toBe("Processing failed. Try again, or upload the file again.");
  });

  it("explains warnings, including page lists and counts, and survives odd input", () => {
    expect(warningText({ code: "OCR_FAILED", pages: [12, 13, 14] })).toBe(
      "Pages 12, 13, 14 could not be read.",
    );
    expect(warningText({ code: "OCR_FAILED", pages: [2] })).toBe("Page 2 could not be read.");
    expect(warningText({ code: "OCR_LOW_CONFIDENCE", pages: [3] })).toMatch(/page 3/i);
    expect(warningText({ code: "EVIDENCE_UNVERIFIED", count: 2 })).toMatch(/2 requirements/);
    expect(warningText({ code: "FILTER_LOW_YIELD" })).toMatch(/deep scan/i);
    expect(warningText({ code: "BOQ_NEEDS_MANUAL_ENTRY", pages: [4] })).toMatch(/manually/i);
    expect(warningText({ code: "DUPLICATE_OF_REVIEWED", count: 1 })).toMatch(/1 /);
    expect(warningText({ code: "NOT_A_KNOWN_CODE" })).toBe("Warning: NOT_A_KNOWN_CODE");
    expect(warningText(null)).toBe("Warning");
    expect(warningText("text")).toBe("Warning");
  });
});
```

Create `frontend/src/lib/file-rules.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ACCEPT, MAX_UPLOAD_MB, formatBytes, validateFile } from "./file-rules";

function fileOf(name: string, size: number): File {
  const file = new File(["x"], name);
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("validateFile (mirrors the server's messages)", () => {
  it("accepts supported types within the limit, in any case", () => {
    for (const name of ["a.pdf", "b.XLSX", "c.csv", "d.DocX"]) expect(validateFile(fileOf(name, 10))).toBeNull();
    expect(validateFile(fileOf("a.pdf", MAX_UPLOAD_MB * 1024 * 1024))).toBeNull();
  });

  it("rejects an empty file, an oversize file and an unsupported extension", () => {
    expect(validateFile(fileOf("a.pdf", 0))).toBe("The file is empty.");
    expect(validateFile(fileOf("a.pdf", MAX_UPLOAD_MB * 1024 * 1024 + 1))).toBe(
      "The file is larger than the 25 MB limit.",
    );
    expect(validateFile(fileOf("a.exe", 10))).toBe("Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.");
    expect(validateFile(fileOf("noextension", 10))).toBe(
      "Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.",
    );
  });

  it("formats sizes and exposes the accept list", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(ACCEPT).toBe(".pdf,.xlsx,.csv,.docx");
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- src/api/query-client.test.ts src/lib`
Expected: FAIL (modules do not exist).

- [ ] **Step 3: Implement**

Create `frontend/src/api/query-client.ts`:

```ts
import { MutationCache, QueryCache, QueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";

function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.isUnauthorized;
}

/** The app's query client. A 401 anywhere means the session ended (or was revoked): re-check it.
 * The mounted AuthGate observes ["me"], refetches, gets 401, clears the cache and redirects. */
export function createQueryClient(): QueryClient {
  const recheckSession = () => {
    void client.invalidateQueries({ queryKey: ["me"] });
  };
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError: (error, query) => {
        if (isUnauthorized(error) && query.queryKey[0] !== "me") recheckSession();
      },
    }),
    mutationCache: new MutationCache({
      onError: (error, _variables, _context, mutation) => {
        // Login, register and logout answer 401 for ordinary reasons (wrong password, no session).
        if (isUnauthorized(error) && !mutation.meta?.skipAuthCheck) recheckSession();
      },
    }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (count, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
      },
    },
  });
  return client;
}
```

In `frontend/src/components/providers.tsx` replace the `QueryClient` construction with `useState(createQueryClient)` (import `createQueryClient` from `@/api/query-client`; drop the now unused `QueryClient`/`ApiError` imports; keep `QueryClientProvider` and the root `Suspense`).

In `frontend/src/api/session.ts` add `meta: { skipAuthCheck: true }` to the `useMutation` options of `useLogin`, `useRegister` and `useLogout`.

Append to `frontend/src/api/types.ts`:

```ts
export type Tender = components["schemas"]["TenderDTO"];
export type TenderCreate = components["schemas"]["TenderCreate"];
export type DocumentItem = components["schemas"]["DocumentDTO"];
export type DocumentVersion = components["schemas"]["VersionDTO"];
export type UploadResult = components["schemas"]["UploadResultDTO"];
export type Job = components["schemas"]["JobDTO"];
export type Run = components["schemas"]["RunDTO"];
export type KindStatus = components["schemas"]["KindStatusDTO"];
export type ExtractionStatus = components["schemas"]["ExtractionStatusDTO"];
```

Create `frontend/src/lib/status-text.ts`:

```ts
export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const JOB_TERMINAL = new Set(["succeeded", "succeeded_with_warnings", "failed", "cancelled"]);
export const isTerminalJob = (status?: string): boolean => !!status && JOB_TERMINAL.has(status);

const JOB_LABELS: Record<string, string> = {
  queued: "Waiting",
  running: "Processing",
  succeeded: "Done",
  succeeded_with_warnings: "Done, with warnings",
  failed: "Failed",
  cancelled: "Cancelled",
};
const PROCESSING_LABELS: Record<string, string> = {
  pending: "Waiting to process",
  processing: "Processing",
  ready: "Ready",
  ready_with_warnings: "Ready, with warnings",
  failed: "Failed",
};
const TENDER_LABELS: Record<string, string> = {
  preparing: "Preparing",
  in_review: "In review",
  ready: "Ready",
  submitted: "Submitted",
  archived: "Archived",
};
const KIND_LABELS: Record<string, string> = {
  tender_document: "Tender document",
  boq: "Bill of quantities",
  quotation: "Quotation",
  other: "Other",
};
const EXTRACTION_LABELS: Record<string, string> = { boq: "Bill of quantities", requirements: "Requirements" };

export const jobStatusLabel = (s: string): string => JOB_LABELS[s] ?? "Unknown status";
export const processingStatusLabel = (s: string): string => PROCESSING_LABELS[s] ?? "Unknown status";
export const tenderStatusLabel = (s: string): string => TENDER_LABELS[s] ?? "Unknown status";
export const documentKindLabel = (s: string): string => KIND_LABELS[s] ?? "Other";
export const kindLabel = (s: string): string => EXTRACTION_LABELS[s] ?? s;

const JOB_TONES: Record<string, Tone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  succeeded_with_warnings: "warning",
  failed: "danger",
  cancelled: "neutral",
};
const PROCESSING_TONES: Record<string, Tone> = {
  pending: "neutral",
  processing: "info",
  ready: "success",
  ready_with_warnings: "warning",
  failed: "danger",
};
export const jobTone = (s: string): Tone => JOB_TONES[s] ?? "neutral";
export const processingTone = (s: string): Tone => PROCESSING_TONES[s] ?? "neutral";
export const tenderTone = (s: string): Tone => (s === "archived" ? "neutral" : s === "ready" ? "success" : "info");

const GENERIC_FAILURE = "Processing failed. Try again, or upload the file again.";
const JOB_ERRORS: Record<string, string> = {
  FILE_CORRUPT: "The file is damaged or cannot be read. Upload a fresh copy.",
  PDF_ENCRYPTED: "The PDF is password protected. Upload an unlocked copy.",
  UNSUPPORTED_FORMAT: "This file type is not supported.",
  SHEET_TOO_LARGE: "The spreadsheet is too large to process.",
  TENDER_ARCHIVED: "The tender is archived, so nothing can be processed.",
  LLM_UNAVAILABLE: "The AI step is not available right now. Try again in a few minutes.",
  INFRASTRUCTURE: "A temporary problem stopped processing. Try again.",
  LEASE_EXPIRED: "Processing was interrupted. Try again.",
};
export const jobErrorText = (code: string | null): string => (code && JOB_ERRORS[code]) || GENERIC_FAILURE;

function pagesText(pages: unknown): string {
  const list = Array.isArray(pages) ? pages.filter((p): p is number => typeof p === "number") : [];
  return list.length === 1 ? `Page ${list[0]}` : `Pages ${list.join(", ")}`;
}

/** Warnings carry ids, page numbers and counts only (never document text). */
export function warningText(w: unknown): string {
  if (typeof w !== "object" || w === null) return "Warning";
  const { code, pages, count } = w as { code?: unknown; pages?: unknown; count?: unknown };
  const n = typeof count === "number" ? count : 0;
  const plural = (word: string) => (n === 1 ? word : `${word}s`);
  switch (code) {
    case "OCR_FAILED":
      return `${pagesText(pages)} could not be read.`;
    case "OCR_LOW_CONFIDENCE":
      return `${pagesText(pages)} was read with low confidence. Check the values from it.`;
    case "OCR_UNAVAILABLE":
      return "Text recognition was not available for scanned pages.";
    case "BOQ_NEEDS_MANUAL_ENTRY":
      return `${pagesText(pages)} look like a scanned bill of quantities. Enter its lines manually.`;
    case "NO_BOQ_FOUND":
      return "No bill of quantities table was found.";
    case "FILTER_LOW_YIELD":
      return "Few requirement candidates were found. Try a deep scan.";
    case "WINDOW_CAP_REACHED":
      return "The document is long, so only the first part was analysed. Try a deep scan or split it.";
    case "ROW_CAP_REACHED":
      return `${n} ${plural("row")} beyond the limit were not stored.`;
    case "EVIDENCE_UNVERIFIED":
      return `${n} ${plural("requirement")} could not be matched to the page text. Check them against the source.`;
    case "DUPLICATE_OF_REVIEWED":
      return `${n} ${plural("item")} matched ones you already reviewed and were kept as reviewed.`;
    case "WINDOW_TIMEOUT":
    case "WINDOW_INVALID_OUTPUT":
      return "Some sections could not be analysed. Run the extraction again.";
    default:
      return typeof code === "string" ? `Warning: ${code}` : "Warning";
  }
}
```

Create `frontend/src/lib/file-rules.ts`:

```ts
export const MAX_UPLOAD_MB = 25;
export const ACCEPT = ".pdf,.xlsx,.csv,.docx";
const EXTENSIONS = new Set(["pdf", "xlsx", "csv", "docx"]);

/** The same checks and wording as the server, so most mistakes are caught before the upload. The
 * server still decides (it also checks that the content matches the extension). */
export function validateFile(file: File): string | null {
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `The file is larger than the ${MAX_UPLOAD_MB} MB limit.`;
  const dot = file.name.lastIndexOf(".");
  const extension = dot >= 0 ? file.name.slice(dot + 1).toLowerCase() : "";
  if (!EXTENSIONS.has(extension)) return "Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.";
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
```

Create `frontend/src/lib/format.ts`:

```ts
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("en-ZA", { dateStyle: "medium", timeStyle: "short" });
}
```

Create `frontend/src/components/status-badge.tsx`:

```tsx
import type { Tone } from "@/lib/status-text";

const TONES: Record<Tone, string> = {
  neutral: "border-zinc-400 text-zinc-700 dark:text-zinc-300",
  info: "border-blue-500 text-blue-700 dark:text-blue-300",
  success: "border-green-600 text-green-700 dark:text-green-300",
  warning: "border-amber-500 text-amber-700 dark:text-amber-300",
  danger: "border-red-600 text-red-700 dark:text-red-300",
};

/** State is always in the text, never conveyed by colour alone. */
export function StatusBadge({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className={`inline-block rounded border px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}>
      {label}
    </span>
  );
}
```

Create `frontend/src/test/fixtures.ts`:

```ts
import type { DocumentItem, DocumentVersion, ExtractionStatus, Job, KindStatus, Run, Tender } from "@/api/types";

const NOW = "2026-10-16T08:00:00Z";
const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const ids = { tender: ID(1), document: ID(2), version: ID(3), job: ID(4), user: ID(5), run: ID(6) };

export function makeTender(over: Partial<Tender> = {}): Tender {
  return {
    id: ids.tender, title: "Hall wiring", reference_number: "T-001", client_name: "Soweto Hall",
    location: "Soweto", closing_at: null, status: "preparing", created_by: ids.user,
    created_at: NOW, updated_at: NOW, archived_at: null, ...over,
  };
}

export function makeVersion(over: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    id: ids.version, document_id: ids.document, version_number: 1, filename: "pack.pdf",
    mime_type: "application/pdf", file_format: "pdf", file_size: 2048, checksum_sha256: "0".repeat(64),
    processing_status: "ready", is_current: true, created_at: NOW, job_id: ids.job, ...over,
  };
}

export function makeDocument(over: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: ids.document, tender_id: ids.tender, kind: "tender_document", title: "Tender pack",
    created_at: NOW, current_version: makeVersion(), ...over,
  };
}

export function makeJob(over: Partial<Job> = {}): Job {
  return {
    id: ids.job, job_type: "ingest", subject_type: "document_version", subject_id: ids.version,
    status: "succeeded", payload: {}, attempt_count: 1, progress_done: 0, progress_total: 0,
    error_code: null, warnings: [], created_at: NOW, started_at: NOW, completed_at: NOW, ...over,
  };
}

export function makeRun(over: Partial<Run> = {}): Run {
  return {
    id: ids.run, document_version_id: ids.version, job_id: ids.job, kind: "boq", status: "succeeded",
    deep_scan: false, prompt_version: null, filter_version: null, schema_version: null, model: null,
    warnings: [], counts: {}, error_code: null, created_at: NOW, started_at: NOW, finished_at: NOW, ...over,
  };
}

export function makeKind(kind: "boq" | "requirements", job: Partial<Job> | null, run: Partial<Run> | null): KindStatus {
  return {
    kind,
    job: job ? makeJob({ job_type: kind === "boq" ? "extract_boq" : "extract_requirements", ...job }) : null,
    run: run ? makeRun({ kind, ...run }) : null,
  };
}

export function makeExtraction(kinds: KindStatus[]): ExtractionStatus {
  return { kinds };
}
```

Create `frontend/src/test/fake-xhr.ts` (a reusable fake for upload tests):

```ts
type ProgressEvent = { lengthComputable: boolean; loaded: number; total: number };

export class FakeXhr {
  static instances: FakeXhr[] = [];
  static get last(): FakeXhr {
    return FakeXhr.instances[FakeXhr.instances.length - 1];
  }
  headers: Record<string, string> = {};
  upload: { onprogress?: (e: ProgressEvent) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  ontimeout?: () => void;
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: unknown;
  constructor() {
    FakeXhr.instances.push(this);
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
  abort() {
    this.onabort?.();
  }
  /** Test helpers */
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  respond(status: number, body: unknown) {
    this.status = status;
    this.responseText = JSON.stringify(body);
    this.onload?.();
  }
}
```

Extend `frontend/src/test/render.tsx` (keep existing exports; add imports `vi` from `vitest`, `AuthGate` from `@/components/auth-gate`):

```tsx
export function meWith(permissions: string[], role: "admin" | "estimator" | "project_manager" | "reviewer" = "estimator") {
  return { ...ME, role, permissions };
}

type Handler = (init?: RequestInit) => Response | Promise<Response>;

/** Route fetch by "METHOD /path" (query string ignored). Adds GET /api/v1/me unless given.
 * Throws on a request nobody expected, so a test cannot pass by accident. */
export function mockApi(routes: Record<string, Handler>, me: ReturnType<typeof meWith> = ME) {
  const all: Record<string, Handler> = { "GET /api/v1/me": () => respond(200, me), ...routes };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? "GET").toUpperCase();
    const handler = all[`${method} ${url.split("?")[0]}`];
    if (!handler) throw new Error(`unexpected request ${method} ${url}`);
    return handler(init);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export function callsTo(fetchMock: ReturnType<typeof vi.fn>, method: string, path: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => String(url).split("?")[0] === path && ((init as RequestInit | undefined)?.method ?? "GET").toUpperCase() === method,
  );
}

/** Render inside AuthGate, so useSession()/useCan() work. Await a findBy... before asserting. */
export function renderSignedIn(ui: ReactElement, client: QueryClient = createTestClient()) {
  return renderWithClient(<AuthGate>{ui}</AuthGate>, client);
}
```
(Tests that render `AuthGate` need `vi.mock("next/navigation", ...)` in their own file because `vi.mock` is hoisted per file.)

- [ ] **Step 4: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: all pass (the existing 64 tests plus the new ones); `rm -rf .next` afterwards.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: global 401 re-check, plain-words status helpers, file rules and test fixtures"
```

---

### Task 2: Tenders list, create and archive

**Files:**
- Create: `frontend/src/api/tenders.ts`, `frontend/src/app/(app)/tenders/tenders-view.tsx`
- Modify: `frontend/src/app/(app)/tenders/page.tsx`
- Test: `frontend/src/app/(app)/tenders/tenders-view.test.tsx`

**Interfaces:**
- Consumes: `get`, `post`, `ApiError`, `Tender`, `TenderCreate`, `useCan`, `StatusBadge`, `tenderStatusLabel`, `tenderTone`, `formatDateTime`, test helpers from Task 1.
- Produces: `tendersQueryOptions(includeArchived?: boolean)` (key `["tenders", { includeArchived }]`), `tenderQueryOptions(id: string)` (key `["tender", id]`), `useCreateTender()`, `useArchiveTender()` (both invalidate `["tenders"]`; archive also `["tender", id]`); `<TendersView />`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/(app)/tenders/tenders-view.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";
import { ids, makeTender } from "@/test/fixtures";

import { TendersView } from "./tenders-view";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const WRITE = meWith(["read", "edit_tenders"]);

describe("TendersView", () => {
  it("lists tenders with status and links to each", async () => {
    mockApi({ "GET /api/v1/tenders": () => respond(200, [makeTender(), makeTender({ id: ids.user, title: "Clinic", status: "in_review" })]) });
    renderSignedIn(<TendersView />);
    const link = await screen.findByRole("link", { name: "Hall wiring" });
    expect(link).toHaveAttribute("href", `/tenders/${ids.tender}`);
    expect(screen.getByRole("link", { name: "Clinic" })).toBeInTheDocument();
    expect(screen.getByText("In review")).toBeInTheDocument();
  });

  it("shows an empty state, and an error with a retry that works", async () => {
    let fail = true;
    mockApi({
      "GET /api/v1/tenders": () =>
        fail ? respond(500, errorBody("internal_error", "Server problem.")) : respond(200, []),
    });
    renderSignedIn(<TendersView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Server problem.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/no tenders yet/i)).toBeInTheDocument();
  });

  it("creates a tender: sends only the filled fields with the CSRF header, then shows the list again", async () => {
    let created = false;
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, created ? [makeTender({ title: "New job" })] : []),
        "POST /api/v1/tenders": () => {
          created = true;
          return respond(201, makeTender({ title: "New job" }));
        },
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.type(await screen.findByLabelText(/title/i), "New job");
    await userEvent.type(screen.getByLabelText(/client/i), "Acme");
    await userEvent.click(screen.getByRole("button", { name: /create tender/i }));
    expect(await screen.findByRole("link", { name: "New job" })).toBeInTheDocument();
    const [, init] = callsTo(fetchMock, "POST", "/api/v1/tenders")[0];
    expect((init as RequestInit & { headers: Record<string, string> }).headers["X-Requested-With"]).toBe("IntelTPS");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ title: "New job", client_name: "Acme" });
    expect(screen.getByLabelText(/title/i)).toHaveValue(""); // the form resets
  });

  it("does not double submit and shows the server's message when creating fails", async () => {
    let finish: (r: Response) => void = () => {};
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, []),
        "POST /api/v1/tenders": () => new Promise<Response>((resolve) => (finish = resolve)),
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.type(await screen.findByLabelText(/title/i), "X");
    const button = screen.getByRole("button", { name: /create tender/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(callsTo(fetchMock, "POST", "/api/v1/tenders")).toHaveLength(1);
    finish(respond(422, errorBody("validation_error", "The request is not valid.")));
    expect(await screen.findByRole("alert")).toHaveTextContent("The request is not valid.");
  });

  it("archives with an inline two-step confirmation", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, [makeTender()]),
        [`POST /api/v1/tenders/${ids.tender}/archive`]: () => respond(200, makeTender({ status: "archived" })),
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.click(await screen.findByRole("button", { name: /^archive$/i }));
    expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/archive`)).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(screen.getByRole("button", { name: /^archive$/i })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /^archive$/i }));
    await userEvent.click(screen.getByRole("button", { name: /confirm archive/i }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/archive`)).toHaveLength(1));
  });

  it("shows no write controls to a user without edit_tenders", async () => {
    mockApi({ "GET /api/v1/tenders": () => respond(200, [makeTender()]) }, meWith(["read"], "reviewer"));
    renderSignedIn(<TendersView />);
    const row = (await screen.findByRole("link", { name: "Hall wiring" })).closest("li")!;
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/title/i)).not.toBeInTheDocument();
  });

  it("asks for archived tenders only when the box is ticked", async () => {
    const fetchMock = mockApi({ "GET /api/v1/tenders": () => respond(200, []) });
    renderSignedIn(<TendersView />);
    await screen.findByText(/no tenders yet/i);
    await userEvent.click(screen.getByLabelText(/show archived/i));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("include_archived=true"))).toBe(true),
    );
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- "src/app/(app)/tenders"`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

Create `frontend/src/api/tenders.ts`:

```ts
import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { get, post } from "./client";
import type { Tender, TenderCreate } from "./types";

export const tendersQueryOptions = (includeArchived = false) =>
  queryOptions({
    queryKey: ["tenders", { includeArchived }] as const,
    queryFn: ({ signal }) => get<Tender[]>("/api/v1/tenders", { include_archived: includeArchived }, signal),
  });

export const tenderQueryOptions = (id: string) =>
  queryOptions({
    queryKey: ["tender", id] as const,
    queryFn: ({ signal }) => get<Tender>(`/api/v1/tenders/${id}`, undefined, signal),
  });

export function useCreateTender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TenderCreate) => post<Tender>("/api/v1/tenders", input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tenders"] }),
  });
}

export function useArchiveTender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => post<Tender>(`/api/v1/tenders/${id}/archive`),
    onSuccess: (_tender, id) => {
      void queryClient.invalidateQueries({ queryKey: ["tenders"] });
      void queryClient.invalidateQueries({ queryKey: ["tender", id] });
    },
  });
}
```

Create `frontend/src/app/(app)/tenders/tenders-view.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { tendersQueryOptions, useArchiveTender, useCreateTender } from "@/api/tenders";
import type { Tender, TenderCreate } from "@/api/types";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { tenderStatusLabel, tenderTone } from "@/lib/status-text";

function messageOf(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

function CreateForm() {
  const create = useCreateTender();
  const [title, setTitle] = useState("");
  const [reference, setReference] = useState("");
  const [client, setClient] = useState("");
  const [location, setLocation] = useState("");
  const [closing, setClosing] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    if (create.isPending) return;
    const input: TenderCreate = { title: title.trim() };
    if (reference.trim()) input.reference_number = reference.trim();
    if (client.trim()) input.client_name = client.trim();
    if (location.trim()) input.location = location.trim();
    if (closing) input.closing_at = new Date(closing).toISOString();
    create.mutate(input, {
      onSuccess: () => {
        setTitle("");
        setReference("");
        setClient("");
        setLocation("");
        setClosing("");
      },
    });
  }

  return (
    <form onSubmit={submit} className="mb-8 grid gap-4 rounded border border-zinc-300 p-4 sm:grid-cols-2 dark:border-zinc-700">
      <h2 className="text-lg font-medium sm:col-span-2">New tender</h2>
      <Field label="Title" required maxLength={300} value={title} onChange={(e) => setTitle(e.target.value)} />
      <Field label="Reference number" maxLength={100} value={reference} onChange={(e) => setReference(e.target.value)} />
      <Field label="Client" maxLength={200} value={client} onChange={(e) => setClient(e.target.value)} />
      <Field label="Location" maxLength={200} value={location} onChange={(e) => setLocation(e.target.value)} />
      <Field label="Closing date" type="datetime-local" value={closing} onChange={(e) => setClosing(e.target.value)} />
      {create.error ? (
        <p role="alert" className="text-sm text-red-600 sm:col-span-2">
          {messageOf(create.error, "Could not create the tender.")}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={create.isPending || !title.trim()}
          className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {create.isPending ? "Creating…" : "Create tender"}
        </button>
      </div>
    </form>
  );
}

function ArchiveControl({ tender }: { tender: Tender }) {
  const archive = useArchiveTender();
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <span className="flex items-center gap-2">
        <button
          type="button"
          disabled={archive.isPending}
          onClick={() => archive.mutate(tender.id, { onSettled: () => setConfirming(false) })}
          className="rounded border border-red-600 px-3 py-1 text-sm text-red-700 disabled:opacity-50 dark:text-red-300"
        >
          Confirm archive
        </button>
        <button type="button" disabled={archive.isPending} onClick={() => setConfirming(false)} className="text-sm underline">
          Cancel
        </button>
      </span>
    );
  }
  return (
    <span>
      <button type="button" onClick={() => setConfirming(true)} className="rounded border border-zinc-300 px-3 py-1 text-sm dark:border-zinc-700">
        Archive
      </button>
      {archive.error ? (
        <span role="alert" className="ml-2 text-sm text-red-600">
          {messageOf(archive.error, "Could not archive.")}
        </span>
      ) : null}
    </span>
  );
}

export function TendersView() {
  const canEdit = useCan("edit_tenders");
  const [showArchived, setShowArchived] = useState(false);
  const { data, error, isPending, refetch } = useQuery(tendersQueryOptions(showArchived));

  return (
    <section>
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Tenders</h1>
      {canEdit ? <CreateForm /> : null}
      <label className="mb-4 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} />
        Show archived
      </label>
      {isPending ? <p role="status" className="text-sm text-zinc-500">Loading tenders…</p> : null}
      {error && !data ? (
        <div role="alert">
          <p className="mb-2">{messageOf(error, "Could not load tenders.")}</p>
          <button type="button" onClick={() => refetch()} className="rounded border px-3 py-1 text-sm">
            Try again
          </button>
        </div>
      ) : null}
      {data && data.length === 0 ? <p className="text-zinc-600 dark:text-zinc-400">No tenders yet.</p> : null}
      {data && data.length > 0 ? (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {data.map((tender) => (
            <li key={tender.id} className="flex flex-wrap items-center justify-between gap-3 py-3">
              <div>
                <Link href={`/tenders/${tender.id}`} className="font-medium underline">
                  {tender.title}
                </Link>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">
                  {[tender.reference_number, tender.client_name, tender.location].filter(Boolean).join(" · ")}
                  {tender.closing_at ? ` · closes ${formatDateTime(tender.closing_at)}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <StatusBadge tone={tenderTone(tender.status)} label={tenderStatusLabel(tender.status)} />
                {canEdit && tender.status !== "archived" ? <ArchiveControl tender={tender} /> : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
```

Replace `frontend/src/app/(app)/tenders/page.tsx` with (keeping the existing comment block above the export):

```tsx
import { TendersView } from "./tenders-view";

// (keep the existing explanatory comment here)
export const instant = false;

export default function TendersPage() {
  return <TendersView />;
}
```

- [ ] **Step 4: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: pass. If a test fails because `next/link` needs a router in jsdom, mock it in the test file the way `src/components/app-shell.test.tsx` handles it.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: tender list with create and archive"
```

---

### Task 3: Tender workspace page, document list, job progress and retry

**Files:**
- Create: `frontend/src/api/documents.ts`, `frontend/src/api/jobs.ts`, `frontend/src/components/job-progress.tsx`, `frontend/src/app/(app)/tenders/[id]/page.tsx`, `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx`, `frontend/src/app/(app)/tenders/[id]/document-card.tsx`
- Test: `frontend/src/components/job-progress.test.tsx`, `frontend/src/app/(app)/tenders/[id]/tender-workspace.test.tsx`

**Interfaces:**
- Consumes: Task 1 helpers/fixtures, Task 2 `tenderQueryOptions`.
- Produces:
  - `documentsQueryOptions(tenderId)` (key `["documents", tenderId]`, `GET /tenders/{id}/documents`).
  - `JOB_POLL_MS = 2000`; `jobQueryOptions(jobId, pollMs?)` (key `["job", jobId]`, `refetchInterval` is `false` once the status is terminal); `useJob(jobId, tenderId, pollMs?)` — also invalidates `["documents", tenderId]` once when the status turns terminal; `useRetryJob(tenderId)` (`POST /jobs/{id}/retry`, writes the returned job into `["job", id]`, invalidates documents).
  - `<JobProgress jobId tenderId pollMs? />`, `<DocumentCard document tenderId archived />` (Task 4 adds the upload control to it; Task 5 adds the extraction panel), `<TenderWorkspace />` (reads the tender id with `useParams()`).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/job-progress.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeJob } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { JobProgress } from "./job-progress";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const JOB_URL = `/api/v1/jobs/${ids.job}`;

describe("JobProgress", () => {
  it("polls while the job runs, shows progress, stops when it finishes and refreshes the documents", async () => {
    let calls = 0;
    const fetchMock = mockApi({
      [`GET ${JOB_URL}`]: () => {
        calls += 1;
        return respond(200, calls < 3 ? makeJob({ status: "running", progress_done: calls, progress_total: 4 }) : makeJob({ status: "succeeded" }));
      },
      [`GET /api/v1/tenders/${ids.tender}/documents`]: () => respond(200, []),
    });
    const { client } = renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    // make the "documents" key active so the invalidation refetches it
    client.setQueryData(["documents", ids.tender], []);
    expect(await screen.findByRole("progressbar")).toHaveAttribute("max", "4");
    expect(await screen.findByText("Done")).toBeInTheDocument();
    const settled = callsTo(fetchMock, "GET", JOB_URL).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(settled); // polling stopped
  });

  it("stops polling when the component unmounts", async () => {
    const fetchMock = mockApi({ [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "running", progress_total: 5 })) });
    const { unmount } = renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    await screen.findByRole("progressbar");
    unmount();
    const before = callsTo(fetchMock, "GET", JOB_URL).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", JOB_URL)).toHaveLength(before);
  });

  it("explains a failure in plain words and offers a retry that posts once", async () => {
    let retried = false;
    const fetchMock = mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, retried ? makeJob({ status: "queued" }) : makeJob({ status: "failed", error_code: "PDF_ENCRYPTED" })),
        [`POST ${JOB_URL}/retry`]: () => {
          retried = true;
          return respond(200, makeJob({ status: "queued" }));
        },
      },
      meWith(["read", "upload_documents"]),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} pollMs={20} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/password protected/i);
    const button = screen.getByRole("button", { name: /retry/i });
    await userEvent.click(button);
    await waitFor(() => expect(screen.getByText("Waiting")).toBeInTheDocument());
    expect(callsTo(fetchMock, "POST", `${JOB_URL}/retry`)).toHaveLength(1);
  });

  it("shows warnings in plain words and no Retry button to a read-only user", async () => {
    mockApi(
      {
        [`GET ${JOB_URL}`]: () =>
          respond(200, makeJob({ status: "succeeded_with_warnings", warnings: [{ code: "OCR_FAILED", pages: [3, 4] }] })),
      },
      meWith(["read"], "reviewer"),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} />);
    expect(await screen.findByText("Pages 3, 4 could not be read.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("shows the server's message when the retry is refused", async () => {
    mockApi(
      {
        [`GET ${JOB_URL}`]: () => respond(200, makeJob({ status: "failed", error_code: "FILE_CORRUPT" })),
        [`POST ${JOB_URL}/retry`]: () => respond(409, errorBody("tender_archived", "This tender is archived.")),
      },
      meWith(["read", "upload_documents"]),
    );
    renderSignedIn(<JobProgress jobId={ids.job} tenderId={ids.tender} />);
    await userEvent.click(await screen.findByRole("button", { name: /retry/i }));
    expect(await screen.findByText("This tender is archived.")).toBeInTheDocument();
  });
});
```

Create `frontend/src/app/(app)/tenders/[id]/tender-workspace.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeDocument, makeJob, makeTender, makeVersion } from "@/test/fixtures";
import { errorBody, mockApi, renderSignedIn, respond } from "@/test/render";

import { TenderWorkspace } from "./tender-workspace";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: "00000000-0000-4000-8000-000000000001" }),
}));
afterEach(() => vi.unstubAllGlobals());

const TENDER = `/api/v1/tenders/${ids.tender}`;

describe("TenderWorkspace", () => {
  it("shows the tender header and its documents with version, kind, status and job progress", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(200, makeTender({ closing_at: "2026-11-01T10:00:00Z" })),
      [`GET ${TENDER}/documents`]: () =>
        respond(200, [
          makeDocument(),
          makeDocument({
            id: ids.user,
            title: "BoQ",
            kind: "boq",
            current_version: makeVersion({ id: ids.run, document_id: ids.user, filename: "boq.xlsx", version_number: 2, processing_status: "processing", job_id: ids.run }),
          }),
        ]),
      [`GET /api/v1/jobs/${ids.job}`]: () => respond(200, makeJob({ status: "succeeded" })),
      [`GET /api/v1/jobs/${ids.run}`]: () => respond(200, makeJob({ id: ids.run, status: "running", progress_done: 1, progress_total: 3 })),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("heading", { name: "Hall wiring" })).toBeInTheDocument();
    const list = await screen.findByRole("list", { name: /documents/i });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText("Tender document")).toBeInTheDocument();
    expect(within(items[0]).getByText(/pack\.pdf/)).toBeInTheDocument();
    expect(within(items[1]).getByText("Bill of quantities")).toBeInTheDocument();
    expect(within(items[1]).getByText(/version 2/i)).toBeInTheDocument();
    expect(await within(items[1]).findByRole("progressbar")).toBeInTheDocument();
  });

  it("explains an empty tender", async () => {
    mockApi({ [`GET ${TENDER}`]: () => respond(200, makeTender()), [`GET ${TENDER}/documents`]: () => respond(200, []) });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
  });

  it("says so for an unknown tender (404) instead of showing an empty page", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(404, errorBody("not_found", "Tender not found")),
      [`GET ${TENDER}/documents`]: () => respond(404, errorBody("not_found", "Tender not found")),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/not found/i);
  });

  it("marks an archived tender read-only", async () => {
    mockApi({
      [`GET ${TENDER}`]: () => respond(200, makeTender({ status: "archived", archived_at: "2026-10-16T08:00:00Z" })),
      [`GET ${TENDER}/documents`]: () => respond(200, []),
    });
    renderSignedIn(<TenderWorkspace />);
    expect(await screen.findByText(/archived.*read-only/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to see them fail**

Run: `npm test -- src/components/job-progress "src/app/(app)/tenders/[id]"`
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement**

Create `frontend/src/api/documents.ts`:

```ts
import { queryOptions } from "@tanstack/react-query";

import { get } from "./client";
import type { DocumentItem } from "./types";

export const documentsQueryOptions = (tenderId: string) =>
  queryOptions({
    queryKey: ["documents", tenderId] as const,
    queryFn: ({ signal }) => get<DocumentItem[]>(`/api/v1/tenders/${tenderId}/documents`, undefined, signal),
  });
```

Create `frontend/src/api/jobs.ts`:

```ts
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { isTerminalJob } from "@/lib/status-text";

import { get, post } from "./client";
import type { Job } from "./types";

export const JOB_POLL_MS = 2000;

export const jobQueryOptions = (jobId: string, pollMs = JOB_POLL_MS) =>
  queryOptions({
    queryKey: ["job", jobId] as const,
    queryFn: ({ signal }) => get<Job>(`/api/v1/jobs/${jobId}`, undefined, signal),
    // Poll until the job is over; a finished job is fetched once and then left alone.
    refetchInterval: (query) => (isTerminalJob(query.state.data?.status) ? false : pollMs),
    staleTime: 0,
  });

/** The job, polled. When it turns terminal the tender's documents are refreshed once, because the
 * version's processing_status (and its extraction jobs) change with it. */
export function useJob(jobId: string, tenderId: string, pollMs?: number) {
  const queryClient = useQueryClient();
  const query = useQuery(jobQueryOptions(jobId, pollMs));
  const terminal = isTerminalJob(query.data?.status);
  useEffect(() => {
    if (terminal) void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
  }, [terminal, tenderId, queryClient]);
  return query;
}

export function useRetryJob(tenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => post<Job>(`/api/v1/jobs/${jobId}/retry`),
    onSuccess: (job) => {
      queryClient.setQueryData(["job", job.id], job);
      void queryClient.invalidateQueries({ queryKey: ["documents", tenderId] });
    },
  });
}
```

Create `frontend/src/components/job-progress.tsx`:

```tsx
"use client";

import { ApiError } from "@/api/errors";
import { useJob, useRetryJob } from "@/api/jobs";
import { isTerminalJob, jobErrorText, jobStatusLabel, jobTone, warningText } from "@/lib/status-text";

import { useCan } from "./auth-gate";
import { StatusBadge } from "./status-badge";

type Props = { jobId: string; tenderId: string; pollMs?: number };

export function JobProgress({ jobId, tenderId, pollMs }: Props) {
  const { data: job, error, isPending } = useJob(jobId, tenderId, pollMs);
  const canRetry = useCan("upload_documents");
  const retry = useRetryJob(tenderId);

  if (isPending) return <p role="status" className="text-sm text-zinc-500">Checking progress…</p>;
  if (!job) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {error instanceof ApiError ? error.message : "Could not load the progress."}
      </p>
    );
  }
  const active = !isTerminalJob(job.status);
  return (
    <div className="space-y-2 text-sm">
      <StatusBadge tone={jobTone(job.status)} label={jobStatusLabel(job.status)} />
      {active ? (
        <progress
          aria-label="Processing progress"
          className="ml-3 align-middle"
          {...(job.progress_total > 0 ? { value: job.progress_done, max: job.progress_total } : {})}
        />
      ) : null}
      {job.status === "failed" ? (
        <div role="alert" className="text-red-700 dark:text-red-300">
          <p>{jobErrorText(job.error_code)}</p>
          {canRetry ? (
            <button
              type="button"
              disabled={retry.isPending}
              onClick={() => retry.mutate(job.id)}
              className="mt-1 rounded border border-red-600 px-3 py-1 disabled:opacity-50"
            >
              {retry.isPending ? "Retrying…" : "Retry"}
            </button>
          ) : null}
        </div>
      ) : null}
      {retry.error ? (
        <p role="alert" className="text-red-600">
          {retry.error instanceof ApiError ? retry.error.message : "Could not retry."}
        </p>
      ) : null}
      {job.warnings.length > 0 ? (
        <ul className="list-disc pl-5 text-amber-800 dark:text-amber-300">
          {job.warnings.map((w, i) => (
            <li key={i}>{warningText(w)}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
```

Create `frontend/src/app/(app)/tenders/[id]/document-card.tsx` (Task 4 and 5 extend it):

```tsx
"use client";

import type { DocumentItem } from "@/api/types";
import { JobProgress } from "@/components/job-progress";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { documentKindLabel, processingStatusLabel, processingTone } from "@/lib/status-text";

type Props = { document: DocumentItem; tenderId: string; archived: boolean };

export function DocumentCard({ document, tenderId }: Props) {
  const version = document.current_version;
  return (
    <li className="space-y-3 py-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">{document.title}</p>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {documentKindLabel(document.kind)}
            {version ? ` · version ${version.version_number} · ${version.filename}` : ""}
            {` · added ${formatDateTime(document.created_at)}`}
          </p>
        </div>
        {version ? (
          <StatusBadge tone={processingTone(version.processing_status)} label={processingStatusLabel(version.processing_status)} />
        ) : null}
      </div>
      {version?.job_id ? <JobProgress jobId={version.job_id} tenderId={tenderId} /> : null}
    </li>
  );
}
```

Create `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { documentsQueryOptions } from "@/api/documents";
import { ApiError } from "@/api/errors";
import { tenderQueryOptions } from "@/api/tenders";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import { tenderStatusLabel, tenderTone } from "@/lib/status-text";

import { DocumentCard } from "./document-card";

export function TenderWorkspace() {
  const { id } = useParams<{ id: string }>();
  const tender = useQuery(tenderQueryOptions(id));
  const documents = useQuery(documentsQueryOptions(id));

  if (tender.isPending) return <p role="status" className="text-sm text-zinc-500">Loading tender…</p>;
  if (!tender.data) {
    const notFound = tender.error instanceof ApiError && tender.error.isNotFound;
    return (
      <div role="alert">
        <p className="mb-2">
          {notFound ? "This tender was not found." : tender.error instanceof ApiError ? tender.error.message : "Could not load the tender."}
        </p>
        <Link href="/tenders" className="underline">
          Back to tenders
        </Link>
      </div>
    );
  }
  const t = tender.data;
  const archived = t.status === "archived";

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link href="/tenders" className="underline">
          ← Tenders
        </Link>
      </p>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t.title}</h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            {[t.reference_number, t.client_name, t.location].filter(Boolean).join(" · ")}
            {t.closing_at ? ` · closes ${formatDateTime(t.closing_at)}` : ""}
          </p>
        </div>
        <StatusBadge tone={tenderTone(t.status)} label={tenderStatusLabel(t.status)} />
      </header>
      {archived ? (
        <p className="mb-4 rounded border border-zinc-400 p-3 text-sm">This tender is archived and read-only.</p>
      ) : null}

      <h2 className="mb-2 text-lg font-medium">Documents</h2>
      {documents.isPending ? <p role="status" className="text-sm text-zinc-500">Loading documents…</p> : null}
      {documents.error && !documents.data ? (
        <p role="alert" className="text-sm text-red-600">
          {documents.error instanceof ApiError ? documents.error.message : "Could not load the documents."}
        </p>
      ) : null}
      {documents.data && documents.data.length === 0 ? (
        <p className="text-zinc-600 dark:text-zinc-400">No documents yet.</p>
      ) : null}
      {documents.data && documents.data.length > 0 ? (
        <ul aria-label="Documents" className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {documents.data.map((d) => (
            <DocumentCard key={d.id} document={d} tenderId={id} archived={archived} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
```

Create `frontend/src/app/(app)/tenders/[id]/page.tsx` (use the same explanatory comment as the other pages):

```tsx
import { TenderWorkspace } from "./tender-workspace";

// This page waits behind the client-side AuthGate (the session cookie is scoped to /api, so the
// Next server cannot see who is signed in), so it is never in the static shell. Opt out of
// instant-navigation validation; revisit if/when auth moves server-side.
export const instant = false;

export default function TenderPage() {
  return <TenderWorkspace />;
}
```

- [ ] **Step 4: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: pass (the `app-pages` test now also covers `tenders/[id]/page.tsx`). Note for the fake-timer-free polling tests: they rely on `pollMs={20}` and real timers; if one is flaky, raise the waits, never remove the "stopped polling" assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: tender workspace with documents, job progress and retry"
```

---

### Task 4: Upload documents and new versions with progress

**Files:**
- Create: `frontend/src/api/uploads.ts`, `frontend/src/app/(app)/tenders/[id]/upload-form.tsx`, `frontend/src/app/(app)/tenders/[id]/new-version.tsx`
- Modify: `frontend/src/app/(app)/tenders/[id]/tender-workspace.tsx`, `frontend/src/app/(app)/tenders/[id]/document-card.tsx`
- Test: `frontend/src/app/(app)/tenders/[id]/upload-form.test.tsx`

**Interfaces:**
- Consumes: `upload` (Task 3 of phase 2: `upload<T>(path, file, fields, onProgress?, signal?)`), `validateFile`, `ACCEPT`, `formatBytes`, `FakeXhr`, test helpers.
- Produces: `useUploadDocument(tenderId)` and `useUploadVersion(tenderId, documentId)` — TanStack mutations taking `{ file, kind?, title?, onProgress? }`, both invalidating `["documents", tenderId]` on success; `<UploadForm tenderId />`, `<NewVersion tenderId documentId />`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/app/(app)/tenders/[id]/upload-form.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ids, makeDocument, makeVersion } from "@/test/fixtures";
import { FakeXhr } from "@/test/fake-xhr";
import { meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { NewVersion } from "./new-version";
import { UploadForm } from "./upload-form";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

const UPLOAD_URL = `/api/v1/tenders/${ids.tender}/documents`;
const WRITE = meWith(["read", "upload_documents"]);

beforeEach(() => {
  FakeXhr.instances = [];
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});
afterEach(() => vi.unstubAllGlobals());

function pdf(name = "pack.pdf", size = 2048): File {
  const file = new File(["%PDF-1.4"], name, { type: "application/pdf" });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

function result() {
  return { document: makeDocument(), version: makeVersion(), job_id: ids.job };
}

describe("UploadForm", () => {
  it("uploads with the kind and optional title, shows progress, then refreshes the documents and resets", async () => {
    let docs = 0;
    mockApi({ [`GET /api/v1/tenders/${ids.tender}/documents`]: () => (docs++, respond(200, [])) }, WRITE);
    const { client } = renderSignedIn(<UploadForm tenderId={ids.tender} />);
    client.setQueryData(["documents", ids.tender], []);
    await userEvent.selectOptions(await screen.findByLabelText(/document type/i), "boq");
    await userEvent.type(screen.getByLabelText(/title/i), "Main BoQ");
    await userEvent.upload(screen.getByLabelText(/file/i), pdf("boq.pdf"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url]).toEqual(["POST", UPLOAD_URL]);
    expect(xhr.headers["X-Requested-With"]).toBe("IntelTPS");
    const form = xhr.body as FormData;
    expect(form.get("kind")).toBe("boq");
    expect(form.get("title")).toBe("Main BoQ");
    expect((form.get("file") as File).name).toBe("boq.pdf");
    xhr.progress(512, 2048);
    expect(await screen.findByRole("progressbar", { name: /upload/i })).toHaveAttribute("value", "0.25");
    xhr.respond(201, result());
    await waitFor(() => expect(docs).toBeGreaterThan(0));
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/title/i)).toHaveValue("");
  });

  it("catches the same mistakes the server would, before any request is sent", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    const input = await screen.findByLabelText(/file/i);
    await userEvent.upload(input, pdf("huge.pdf", 26 * 1024 * 1024));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is larger than the 25 MB limit.");
    // user-event drops files the input's `accept` would reject unless told not to (a browser user can still pick "all files")
    await userEvent.setup({ applyAccept: false }).upload(input, new File(["x"], "virus.exe"));
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.");
    expect(FakeXhr.instances).toHaveLength(0);
  });

  it("requires a file to be chosen", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.click(await screen.findByRole("button", { name: /upload/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/choose a file/i);
    expect(FakeXhr.instances).toHaveLength(0);
  });

  it.each([
    [422, "validation_error", "The file content does not match its extension."],
    [403, "limit_exceeded", "Your plan's upload limit has been reached."],
    [409, "tender_archived", "This tender is archived."],
  ])("shows the server's refusal (%s %s) and lets the user try again", async (status, code, message) => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    await userEvent.click(screen.getByRole("button", { name: /upload/i }));
    FakeXhr.last.respond(status, { error: { code, message } });
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: /upload/i })).toBeEnabled();
  });

  it("disables the button during the upload so it cannot be sent twice", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await userEvent.upload(await screen.findByLabelText(/file/i), pdf());
    const button = screen.getByRole("button", { name: /upload/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(FakeXhr.instances).toHaveLength(1);
  });

  it("renders nothing for a user without upload_documents", async () => {
    mockApi({}, meWith(["read"], "reviewer"));
    renderSignedIn(<UploadForm tenderId={ids.tender} />);
    await waitFor(() => expect(screen.queryByLabelText(/file/i)).not.toBeInTheDocument());
  });
});

describe("NewVersion", () => {
  it("uploads a new version of an existing document to its own endpoint", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    await userEvent.upload(await screen.findByLabelText(/new version/i), pdf("v2.pdf"));
    await waitFor(() => expect(FakeXhr.instances).toHaveLength(1));
    expect([FakeXhr.last.method, FakeXhr.last.url]).toEqual(["POST", `/api/v1/documents/${ids.document}/versions`]);
    expect((FakeXhr.last.body as FormData).get("kind")).toBeNull();
    FakeXhr.last.respond(201, result());
    expect(await screen.findByText(/uploaded/i)).toBeInTheDocument();
  });

  it("validates the file before sending and shows server errors", async () => {
    mockApi({}, WRITE);
    renderSignedIn(<NewVersion tenderId={ids.tender} documentId={ids.document} />);
    await userEvent.setup({ applyAccept: false }).upload(await screen.findByLabelText(/new version/i), new File(["x"], "bad.txt"));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
    expect(FakeXhr.instances).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- "src/app/(app)/tenders/[id]/upload-form"`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/api/uploads.ts`:

```ts
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { upload } from "./client";
import type { UploadResult } from "./types";

type UploadInput = { file: File; kind?: string; title?: string; onProgress?: (fraction: number) => void };

function useUpload(path: string, tenderId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, kind, title, onProgress }: UploadInput) => {
      const fields: Record<string, string> = {};
      if (kind) fields.kind = kind;
      if (title) fields.title = title;
      return upload<UploadResult>(path, file, fields, onProgress);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["documents", tenderId] }),
  });
}

export const useUploadDocument = (tenderId: string) => useUpload(`/api/v1/tenders/${tenderId}/documents`, tenderId);
export const useUploadVersion = (tenderId: string, documentId: string) =>
  useUpload(`/api/v1/documents/${documentId}/versions`, tenderId);
```

Create `frontend/src/app/(app)/tenders/[id]/upload-form.tsx`:

```tsx
"use client";

import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/errors";
import { useUploadDocument } from "@/api/uploads";
import { useCan } from "@/components/auth-gate";
import { Field } from "@/components/field";
import { ACCEPT, MAX_UPLOAD_MB, formatBytes, validateFile } from "@/lib/file-rules";

const KINDS: [string, string][] = [
  ["tender_document", "Tender document"],
  ["boq", "Bill of quantities"],
  ["quotation", "Quotation"],
  ["other", "Other"],
];

export function UploadForm({ tenderId }: { tenderId: string }) {
  const canUpload = useCan("upload_documents");
  const uploadDocument = useUploadDocument(tenderId);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState("tender_document");
  const [title, setTitle] = useState("");
  const [fraction, setFraction] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [inputKey, setInputKey] = useState(0); // remounts the file input to clear it

  if (!canUpload) return null;

  function submit(event: FormEvent) {
    event.preventDefault();
    if (uploadDocument.isPending) return;
    setDone(false);
    if (!file) return setProblem("Choose a file to upload.");
    const invalid = validateFile(file);
    if (invalid) return setProblem(invalid);
    setProblem(null);
    setFraction(0);
    uploadDocument.mutate(
      { file, kind, title: title.trim() || undefined, onProgress: setFraction },
      {
        onSuccess: () => {
          setDone(true);
          setFile(null);
          setTitle("");
          setInputKey((k) => k + 1);
        },
      },
    );
  }

  const shown = problem ?? (uploadDocument.error instanceof ApiError ? uploadDocument.error.message : uploadDocument.error ? "The upload failed. Try again." : null);

  return (
    <form onSubmit={submit} className="mb-8 grid gap-4 rounded border border-zinc-300 p-4 sm:grid-cols-2 dark:border-zinc-700">
      <h2 className="text-lg font-medium sm:col-span-2">Upload a document</h2>
      <div className="flex flex-col gap-1">
        <label htmlFor="doc-kind" className="text-sm font-medium">Document type</label>
        <select id="doc-kind" value={kind} onChange={(e) => setKind(e.target.value)} className="rounded border border-zinc-300 bg-transparent px-3 py-2 dark:border-zinc-700">
          {KINDS.map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </div>
      <Field label="Title (optional)" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
      <div className="flex flex-col gap-1 sm:col-span-2">
        <label htmlFor="doc-file" className="text-sm font-medium">File</label>
        <input
          key={inputKey}
          id="doc-file"
          type="file"
          accept={ACCEPT}
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setProblem(null);
          }}
        />
        <p className="text-xs text-zinc-500">
          PDF, XLSX, CSV or DOCX, up to {MAX_UPLOAD_MB} MB.{file ? ` Selected: ${file.name} (${formatBytes(file.size)}).` : ""}
        </p>
      </div>
      {uploadDocument.isPending ? (
        <progress aria-label="Upload progress" className="sm:col-span-2" value={fraction} max={1} />
      ) : null}
      {shown ? <p role="alert" className="text-sm text-red-600 sm:col-span-2">{shown}</p> : null}
      {done ? <p role="status" className="text-sm text-green-700 sm:col-span-2 dark:text-green-300">Uploaded. Processing has started.</p> : null}
      <div className="sm:col-span-2">
        <button type="submit" disabled={uploadDocument.isPending} className="rounded bg-zinc-900 px-4 py-2 text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900">
          {uploadDocument.isPending ? "Uploading…" : "Upload"}
        </button>
      </div>
    </form>
  );
}
```
(The first test asserts `value="0.25"` on the progress element: React renders `value={fraction}` with `max={1}`.)

Create `frontend/src/app/(app)/tenders/[id]/new-version.tsx`:

```tsx
"use client";

import { useState } from "react";

import { ApiError } from "@/api/errors";
import { useUploadVersion } from "@/api/uploads";
import { useCan } from "@/components/auth-gate";
import { ACCEPT, validateFile } from "@/lib/file-rules";

export function NewVersion({ tenderId, documentId }: { tenderId: string; documentId: string }) {
  const canUpload = useCan("upload_documents");
  const uploadVersion = useUploadVersion(tenderId, documentId);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  if (!canUpload) return null;

  const shown = problem ?? (uploadVersion.error instanceof ApiError ? uploadVersion.error.message : uploadVersion.error ? "The upload failed. Try again." : null);

  return (
    <div className="text-sm">
      <label className="mr-2 font-medium" htmlFor={`new-version-${documentId}`}>
        Upload new version
      </label>
      <input
        key={inputKey}
        id={`new-version-${documentId}`}
        type="file"
        accept={ACCEPT}
        disabled={uploadVersion.isPending}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          setDone(false);
          const invalid = validateFile(file);
          if (invalid) return setProblem(invalid);
          setProblem(null);
          uploadVersion.mutate(
            { file },
            { onSuccess: () => { setDone(true); setInputKey((k) => k + 1); } },
          );
        }}
      />
      {uploadVersion.isPending ? <span role="status" className="ml-2 text-zinc-500">Uploading…</span> : null}
      {shown ? <p role="alert" className="mt-1 text-red-600">{shown}</p> : null}
      {done ? <p role="status" className="mt-1 text-green-700 dark:text-green-300">Uploaded. Processing has started.</p> : null}
    </div>
  );
}
```

In `tender-workspace.tsx`: import `UploadForm` and render `{!archived ? <UploadForm tenderId={id} /> : null}` just above the Documents heading. In `document-card.tsx`: render `{!archived && version ? <NewVersion tenderId={tenderId} documentId={document.id} /> : null}` below the job progress (destructure `archived` from props).

- [ ] **Step 4: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: upload documents and new versions with progress and validation"
```

---

### Task 5: Extraction status and re-run per document version

**Files:**
- Create: `frontend/src/api/extraction.ts`, `frontend/src/components/extraction-panel.tsx`
- Modify: `frontend/src/app/(app)/tenders/[id]/document-card.tsx`
- Test: `frontend/src/components/extraction-panel.test.tsx`

**Interfaces:**
- Consumes: Task 1 helpers/fixtures, `isTerminalJob`, `warningText`, `jobErrorText`, `kindLabel`.
- Produces: `EXTRACTION_POLL_MS = 3000`; `extractionQueryOptions(versionId, pollMs?)` (key `["extraction", versionId]`; polls while any kind's job is active); `useRequestExtraction(versionId)` (`POST /document-versions/{id}/extract` with `{deep_scan}`, invalidates the extraction key); `<ExtractionPanel versionId ready pollMs? />`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/extraction-panel.test.tsx`:

```tsx
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeExtraction, makeJob, makeKind } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { ExtractionPanel } from "./extraction-panel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const STATUS = `/api/v1/document-versions/${ids.version}/extraction`;
const EXTRACT = `/api/v1/document-versions/${ids.version}/extract`;
const REVIEW = meWith(["read", "review_data"]);

describe("ExtractionPanel", () => {
  it("renders nothing until the version has finished processing", async () => {
    const fetchMock = mockApi({});
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready={false} />);
    await new Promise((r) => setTimeout(r, 30));
    expect(callsTo(fetchMock, "GET", STATUS)).toHaveLength(0);
  });

  it("shows each kind's job status and counts, hides kinds that never ran", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([
          makeKind("boq", { status: "succeeded" }, { status: "succeeded", counts: { items: 12, pages_with_boq: 2 } }),
          makeKind("requirements", { status: "succeeded_with_warnings", warnings: [] }, {
            status: "succeeded_with_warnings",
            counts: { requirements: 7 },
            warnings: [{ code: "EVIDENCE_UNVERIFIED", count: 2 }],
          }),
        ])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText(/12 lines/i)).toBeInTheDocument();
    expect(screen.getByText(/7 requirements/i)).toBeInTheDocument();
    expect(screen.getByText(/2 requirements could not be matched/i)).toBeInTheDocument();
  });

  it("polls while a job is active and stops when all are done", async () => {
    let n = 0;
    const fetchMock = mockApi({
      [`GET ${STATUS}`]: () => {
        n += 1;
        const job = n < 3 ? { status: "running", progress_done: 1, progress_total: 2 } : { status: "succeeded" };
        return respond(200, makeExtraction([makeKind("boq", job, n < 3 ? null : { counts: { items: 3 } })]));
      },
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={20} />);
    expect(await screen.findByText(/3 lines/i)).toBeInTheDocument();
    const settled = callsTo(fetchMock, "GET", STATUS).length;
    await new Promise((r) => setTimeout(r, 120));
    expect(callsTo(fetchMock, "GET", STATUS)).toHaveLength(settled);
  });

  it("shows the job's failure in plain words (not the run's status) and that BoQ output is unaffected", async () => {
    mockApi({
      [`GET ${STATUS}`]: () =>
        respond(200, makeExtraction([
          makeKind("boq", { status: "succeeded" }, { counts: { items: 5 } }),
          makeKind("requirements", { status: "failed", error_code: "LLM_UNAVAILABLE" }, { status: "running" }),
        ])),
    });
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    expect(await screen.findByText(/AI step is not available/i)).toBeInTheDocument();
    expect(screen.getByText(/5 lines/i)).toBeInTheDocument();
    expect(screen.queryByText(/^Processing$/)).not.toBeInTheDocument();
  });

  it("re-runs with the deep-scan option, once, and refreshes the status", async () => {
    let started = false;
    const fetchMock = mockApi(
      {
        [`GET ${STATUS}`]: () =>
          respond(200, makeExtraction([makeKind("requirements", { status: started ? "queued" : "succeeded" }, { counts: { requirements: 1 } })])),
        [`POST ${EXTRACT}`]: () => {
          started = true;
          return respond(202, [makeJob({ job_type: "extract_requirements", status: "queued", payload: { deep_scan: true } })]);
        },
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    await userEvent.click(await screen.findByLabelText(/deep scan/i));
    const button = screen.getByRole("button", { name: /run extraction again/i });
    await userEvent.click(button);
    await waitFor(() => expect(screen.getByText("Waiting")).toBeInTheDocument());
    const posts = callsTo(fetchMock, "POST", EXTRACT);
    expect(posts).toHaveLength(1);
    expect(JSON.parse((posts[0][1] as RequestInit).body as string)).toEqual({ deep_scan: true });
  });

  it.each([
    ["extraction_options_conflict", /different options/i],
    ["tender_archived", /archived/i],
    ["not_processed", /not finished processing/i],
  ])("explains the %s refusal in plain words", async (code, pattern) => {
    mockApi(
      {
        [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { counts: { items: 1 } })])),
        [`POST ${EXTRACT}`]: () => respond(409, errorBody(code, "raw server text")),
      },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    await userEvent.click(await screen.findByRole("button", { name: /run extraction again/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent(pattern);
  });

  it("disables the button while a job runs or the request is pending, and hides it from users without review_data", async () => {
    mockApi(
      { [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "running", progress_total: 2 }, null)])) },
      REVIEW,
    );
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready pollMs={1000} />);
    expect(await screen.findByRole("button", { name: /run extraction again/i })).toBeDisabled();
    vi.unstubAllGlobals();

    mockApi({ [`GET ${STATUS}`]: () => respond(200, makeExtraction([makeKind("boq", { status: "succeeded" }, { counts: { items: 1 } })])) }, meWith(["read"], "reviewer"));
    renderSignedIn(<ExtractionPanel versionId={ids.version} ready />);
    await waitFor(() => expect(screen.getAllByText(/1 line/i).length).toBeGreaterThan(0));
    expect(screen.getAllByRole("button", { name: /run extraction again/i })).toHaveLength(1); // only the first render's
  });
});
```
(The last test's second half renders into the same document; if the double render makes the assertion awkward, split it into two tests: one for "disabled while running", one for "hidden for a read-only user". Splitting is allowed; weakening the assertions is not.)

- [ ] **Step 2: Run to see it fail**

Run: `npm test -- src/components/extraction-panel`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/api/extraction.ts`:

```ts
import { queryOptions, useMutation, useQueryClient } from "@tanstack/react-query";

import { isTerminalJob } from "@/lib/status-text";

import { get, post } from "./client";
import type { ExtractionStatus, Job } from "./types";

export const EXTRACTION_POLL_MS = 3000;

export const anyJobActive = (status?: ExtractionStatus): boolean =>
  !!status?.kinds.some((k) => k.job && !isTerminalJob(k.job.status));

export const extractionQueryOptions = (versionId: string, pollMs = EXTRACTION_POLL_MS) =>
  queryOptions({
    queryKey: ["extraction", versionId] as const,
    queryFn: ({ signal }) => get<ExtractionStatus>(`/api/v1/document-versions/${versionId}/extraction`, undefined, signal),
    refetchInterval: (query) => (anyJobActive(query.state.data) ? pollMs : false),
    staleTime: 0,
  });

export function useRequestExtraction(versionId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (deepScan: boolean) =>
      post<Job[]>(`/api/v1/document-versions/${versionId}/extract`, { deep_scan: deepScan }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["extraction", versionId] }),
  });
}
```

Create `frontend/src/components/extraction-panel.tsx`:

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/api/errors";
import { anyJobActive, extractionQueryOptions, useRequestExtraction } from "@/api/extraction";
import type { KindStatus } from "@/api/types";
import { isTerminalJob, jobErrorText, jobStatusLabel, jobTone, kindLabel, warningText } from "@/lib/status-text";

import { useCan } from "./auth-gate";
import { StatusBadge } from "./status-badge";

const REFUSALS: Record<string, string> = {
  extraction_options_conflict: "An extraction with different options is already running. Wait for it to finish.",
  tender_archived: "This tender is archived, so nothing can be extracted.",
  not_processed: "The document has not finished processing yet.",
};

function countText(kind: string, counts: Record<string, unknown>): string | null {
  const n = (key: string) => (typeof counts[key] === "number" ? (counts[key] as number) : null);
  if (kind === "boq") {
    const items = n("items");
    return items === null ? null : `${items} ${items === 1 ? "line" : "lines"}`;
  }
  const count = n("requirements");
  return count === null ? null : `${count} ${count === 1 ? "requirement" : "requirements"}`;
}

function KindRow({ item }: { item: KindStatus }) {
  const job = item.job;
  const counts = item.run?.counts ? countText(item.kind, item.run.counts as Record<string, unknown>) : null;
  const warnings = [...(job?.warnings ?? []), ...(item.run?.warnings ?? [])];
  const seen = new Set<string>();
  const unique = warnings.map(warningText).filter((t) => (seen.has(t) ? false : (seen.add(t), true)));
  return (
    <li className="space-y-1 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-medium">{kindLabel(item.kind)}</span>
        {job ? <StatusBadge tone={jobTone(job.status)} label={jobStatusLabel(job.status)} /> : null}
        {counts ? <span>{counts}</span> : null}
      </div>
      {job?.status === "failed" ? <p className="text-red-700 dark:text-red-300">{jobErrorText(job.error_code)}</p> : null}
      {unique.length > 0 ? (
        <ul className="list-disc pl-5 text-amber-800 dark:text-amber-300">
          {unique.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

type Props = { versionId: string; ready: boolean; pollMs?: number };

export function ExtractionPanel({ versionId, ready, pollMs }: Props) {
  const canRun = useCan("review_data");
  const status = useQuery({ ...extractionQueryOptions(versionId, pollMs), enabled: ready });
  const request = useRequestExtraction(versionId);
  const [deep, setDeep] = useState(false);
  if (!ready) return null;
  if (status.isPending) return <p role="status" className="text-sm text-zinc-500">Checking extraction…</p>;
  if (!status.data) {
    return (
      <p role="alert" className="text-sm text-red-600">
        {status.error instanceof ApiError ? status.error.message : "Could not load the extraction status."}
      </p>
    );
  }
  const kinds = status.data.kinds.filter((k) => k.job || k.run);
  const busy = anyJobActive(status.data) || request.isPending;
  const refusal = request.error instanceof ApiError ? (REFUSALS[request.error.code] ?? request.error.message) : request.error ? "Could not start the extraction." : null;

  return (
    <div className="rounded border border-zinc-200 p-3 dark:border-zinc-800">
      <h3 className="text-sm font-semibold">Extraction</h3>
      {kinds.length === 0 ? <p className="py-2 text-sm text-zinc-600 dark:text-zinc-400">Extraction has not run yet.</p> : null}
      {kinds.length > 0 ? (
        <ul className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {kinds.map((k) => (
            <KindRow key={k.kind} item={k} />
          ))}
        </ul>
      ) : null}
      {refusal ? <p role="alert" className="mt-2 text-sm text-red-600">{refusal}</p> : null}
      {canRun ? (
        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={deep} onChange={(e) => setDeep(e.target.checked)} disabled={busy} />
            Deep scan (slower, reads every section)
          </label>
          <button
            type="button"
            disabled={busy}
            onClick={() => request.mutate(deep)}
            className="rounded border border-zinc-400 px-3 py-1 disabled:opacity-50"
          >
            {request.isPending ? "Starting…" : "Run extraction again"}
          </button>
        </div>
      ) : null}
    </div>
  );
}
```

In `document-card.tsx` add (below `NewVersion` / `JobProgress`): `{version ? <ExtractionPanel versionId={version.id} ready={version.processing_status === "ready" || version.processing_status === "ready_with_warnings"} /> : null}`.

- [ ] **Step 4: Run to verify**

Run: `npm test && npm run typecheck && npm run lint && npm run build`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: extraction status and re-run per document version"
```

---

### Task 6: Real-browser verification with the real worker, and status (controller task)

This task needs a running API, the background worker and a browser, so the controller runs it (not a subagent). It touches only a throwaway database, never the developer's `inteltps` database.

**Files:**
- Modify: `docs/plan.md` (Slice 4 status line), `docs/known-limitations.md` (only if something new is found)

- [ ] **Step 1: Throwaway backend and worker**

From the repo root (Git Bash). Postgres container `inteltps-db-1`, host port 5433:

```bash
docker exec inteltps-db-1 psql -U intel -d postgres -c "CREATE DATABASE inteltps_spike"
cd backend
export DATABASE_URL=postgresql+psycopg://intel:intel@127.0.0.1:5433/inteltps_spike COOKIE_SECURE=false ENVIRONMENT=development LLM_PROVIDER=fake STORAGE_PATH="$TMP/spike-files"
mkdir -p "$TMP/spike-files" && uv run alembic upgrade head
uv run uvicorn app.api.main:app --port 8000      # background
uv run python -m app.worker.main                 # background (find the real worker entry point: backend/app/worker/main.py or the Compose `worker` command)
```
Expected: health at `http://127.0.0.1:8000/api/v1/health`; the worker logs that it is polling.

- [ ] **Step 2: Frontend and test files**

```bash
cd frontend && API_PROXY_TARGET=http://127.0.0.1:8000 npm run dev      # background
cd ../backend && uv run python - <<'PY'
# a 2-page PDF with a BoQ-like table, a scanned-looking blank PDF is not needed; plus a corrupt file and a too-big file
import os, pymupdf
t = os.environ["TMP"]
d = pymupdf.open()
for i in (1, 2):
    p = d.new_page(); p.insert_text((72, 100), f"Tender page {i}. Tenderers must submit a valid tax clearance certificate.", fontsize=11)
d.save(os.path.join(t, "pack.pdf"))
open(os.path.join(t, "corrupt.pdf"), "wb").write(b"%PDF-1.4 this is not a real pdf")
open(os.path.join(t, "huge.pdf"), "wb").write(b"%PDF-" + b"0" * (26 * 1024 * 1024))
PY
```

- [ ] **Step 3: Verify in the browser (use the browser tools; poll for text, do not rely on fixed waits)**

Register a test user (same rule as before: local dev app, fixture password), then:
1. `/tenders` shows "No tenders yet." and the create form; create a tender with only a title; it appears in the list with "Preparing"; create another with all fields (closing date) and see the details line.
2. Open the tender: header, "No documents yet.", the upload form. Upload `pack.pdf` as "Tender document": progress shows, the document appears, the job moves Waiting → Processing → Done within a few polls, `processing_status` becomes Ready, the extraction panel appears and shows requirements/BoQ statuses; with `LLM_PROVIDER=fake` the requirements job finishes with 0 requirements (note it).
3. Upload `corrupt.pdf`: the job fails and the card shows the plain-words failure and a Retry button; Retry re-queues and fails again (expected), no console errors.
4. Choose `huge.pdf`: the client blocks it with "The file is larger than the 25 MB limit." and sends no request (check the API log).
5. "Upload new version" on the first document with a second PDF: version 2 appears as current.
6. "Run extraction again" with "Deep scan" ticked: the button disables while running; status returns to Done.
7. Archive the second tender (two-step), tick "Show archived" and see it; open it: the "archived and read-only" note and no upload form.
8. As a second user with the reviewer role (create via `POST /api/v1/members` with curl as the admin): no create/archive/upload/retry/run controls anywhere, but lists and statuses are visible.
9. Kill the worker mid-job (or upload while it is stopped): the card stays "Waiting" without errors; restart the worker and it completes.
10. Sign out and in again; expire the session (`DELETE` the row in `sessions` or revoke by changing the password through the members API) and trigger any refetch: the app returns to `/login` (global 401 hook), no loop.

- [ ] **Step 4: Record, update docs, clean up**

Write the outcome of each numbered check into the plan's status line and, if anything new was found, a short entry in `docs/known-limitations.md`. Update the `docs/plan.md` Slice 4 status: phase 3 done with the commit range. Then stop all servers, drop `inteltps_spike` (`docker exec inteltps-db-1 psql -U intel -d postgres -c "DROP DATABASE inteltps_spike WITH (FORCE)"`), delete the temp files and `frontend/.next`.

- [ ] **Step 5: Commit**

```bash
git add docs
git commit -m "docs: Slice 4 phase 3 status"
```

---

## Self-Review

**Spec coverage (spec section 5, "Tender workspace (phase 3)" and phase 3 row):** tender list and create (Task 2); archive (Task 2); tender page with documents, versions and `processing_status` (Task 3); upload form with kind selector, API validation messages, 25 MB limit shown (Task 4); job progress via polling with `refetchInterval` that stops on a terminal status (Tasks 3 and 5); retry for failed jobs, shown only with `upload_documents` (Task 3); per-version extraction status with warnings, re-run with deep-scan toggle, 409 codes explained, job status shown instead of run status (Task 5); version DTO `job_id` resumes progress after reload (Task 3: JobProgress starts from the version's `job_id`); read-only roles and archived tenders (Tasks 2-5). The final review's follow-up (global 401 hook for non-`/me` queries) is Task 1. Routes `/tenders/[id]/review/[versionId]` and `/tenders/[id]/checklist` are phases 4 and 5 (no links yet).

**Placeholder scan:** none. Deliberate unknowns resolved by looking at code when executing: the worker entry point command in Task 6 (`backend/app/worker/main.py` or the Compose `worker` command), and whether `next/link` needs mocking in jsdom (Task 2 Step 4 says how).

**Type consistency:** `tendersQueryOptions`/`tenderQueryOptions` (Task 2) are used by `tender-workspace.tsx` (Task 3); `documentsQueryOptions` key `["documents", tenderId]` matches the invalidations in `useJob`, `useRetryJob` (Task 3) and `uploads.ts` (Task 4); `JobProgress` props `{jobId, tenderId, pollMs?}` match `DocumentCard`'s use; `useCan` permission strings (`edit_tenders`, `upload_documents`, `review_data`) match the backend's `Permission` values; the fixtures' ids (`ids.tender`, `ids.version`, `ids.job`, `ids.run`, `ids.document`, `ids.user`) are the same names in every test file; `skipAuthCheck` meta is set in `session.ts` (Task 1) and read in `query-client.ts` (Task 1).

**Known risks for the executor:** the polling tests use real timers with `pollMs={20}` and assert that polling stops (flaky-prone: raise waits, never drop the "stopped" assertions); the unsupported-file tests use `userEvent.setup({ applyAccept: false })` because user-event otherwise drops files that the input's `accept` rejects, so the validation would never run; React Compiler lint rules (`react-hooks/*`) may flag state updates in handlers that return early (`return setProblem(...)`): rewrite as `setProblem(...); return;` rather than disabling the rule.
