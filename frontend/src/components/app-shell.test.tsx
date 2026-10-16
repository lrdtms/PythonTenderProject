import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, renderWithClient, respond } from "@/test/render";

import { AppShell } from "./app-shell";
import { AuthGate } from "./auth-gate";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  replace.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

async function signOut(logoutResponse: Response) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/v1/me") return respond(200, ME);
    if (url === "/api/v1/auth/logout") return logoutResponse;
    throw new Error(`unexpected request ${url}`);
  });
  const { client } = renderWithClient(
    <AuthGate>
      <AppShell>content</AppShell>
    </AuthGate>,
  );
  await screen.findByText("content");
  client.setQueryData(["tenders", "dummy"], { secret: "tenant row" });
  expect(client.getQueryCache().getAll().length).toBeGreaterThan(1);
  await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  await waitFor(() => expect(client.getQueryData(["tenders", "dummy"])).toBeUndefined());
  expect(client.getQueryData(["me"])).toBeUndefined();
}

describe("AppShell sign out", () => {
  it("clears the cache and goes to /login", async () => {
    await signOut(new Response(null, { status: 204 }));
  });

  it("still clears the cache and redirects when the logout request fails", async () => {
    await signOut(respond(500, errorBody("internal_error", "Something went wrong.")));
  });
});
