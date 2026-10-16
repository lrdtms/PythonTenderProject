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

export function createTestClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Render inside a QueryClientProvider. Pass `client` to seed the cache before the first render. */
export function renderWithClient(ui: ReactElement, client: QueryClient = createTestClient()) {
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}
