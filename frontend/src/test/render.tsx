import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { AuthGate } from "@/components/auth-gate";

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

export function createTestClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Render inside a QueryClientProvider. Pass `client` to seed the cache before the first render. */
export function renderWithClient(ui: ReactElement, client: QueryClient = createTestClient()) {
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

export function meWith(permissions: string[], role: "admin" | "estimator" | "project_manager" | "reviewer" = "estimator") {
  return { ...ME, role, permissions };
}

type Handler = (init?: RequestInit) => Response | Promise<Response>;

/** Route fetch by "METHOD /path" (query string ignored). Adds GET /api/v1/me unless given.
 * Throws on a request nobody expected, so a test cannot pass by accident. It stubs the global
 * fetch: each test file must call `afterEach(() => vi.unstubAllGlobals())`. */
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
