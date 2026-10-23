import type { QueryClient } from "@tanstack/react-query";
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

/** Render the shell signed in, seed a tenant row, and click Sign out with the given logout result. */
async function clickSignOut(logout: () => Promise<Response>) {
  fetchMock.mockImplementation(async (url: string) => {
    if (url === "/api/v1/me") return respond(200, ME);
    if (url === "/api/v1/auth/logout") return logout();
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
  return client;
}

async function expectSignedOut(client: QueryClient) {
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(client.getQueryData(["tenders", "dummy"])).toBeUndefined();
  expect(client.getQueryData(["me"])).toBeUndefined();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
}

async function expectStillSignedIn(client: QueryClient) {
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not sign out. Try again.");
  expect(replace).not.toHaveBeenCalled();
  expect(client.getQueryData(["tenders", "dummy"])).toEqual({ secret: "tenant row" });
  expect(client.getQueryData(["me"])).toEqual(ME);
  expect(screen.getByText("content")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /sign out/i })).toBeEnabled();
}

describe("AppShell sign out", () => {
  it("clears the cache and goes to /login when the server ends the session (204)", async () => {
    const client = await clickSignOut(async () => new Response(null, { status: 204 }));
    await expectSignedOut(client);
  });

  it("treats a 401 as already signed out: clears the cache and goes to /login", async () => {
    const client = await clickSignOut(async () => respond(401, errorBody("unauthorized", "Sign in.")));
    await expectSignedOut(client);
  });

  it("on a server error, shows an alert, keeps the cache and does not redirect", async () => {
    const client = await clickSignOut(async () =>
      respond(500, errorBody("internal_error", "Something went wrong.")),
    );
    await expectStillSignedIn(client);
  });

  it("on a network failure, shows an alert and lets the user try again", async () => {
    let attempt = 0;
    const client = await clickSignOut(async () => {
      attempt += 1;
      if (attempt === 1) throw new TypeError("Failed to fetch");
      return new Response(null, { status: 204 });
    });
    await expectStillSignedIn(client);
    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    await expectSignedOut(client);
  });
});

describe("AppShell suppliers link", () => {
  it.each([
    ["a reviewer", ["read"]],
    ["an admin", ["read", "manage_members"]],
  ])("shows Suppliers to %s", async (_who, permissions) => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/v1/me") return respond(200, { ...ME, permissions });
      throw new Error(`unexpected request ${url}`);
    });
    renderWithClient(
      <AuthGate>
        <AppShell>content</AppShell>
      </AuthGate>,
    );
    await screen.findByText("content");
    expect(screen.getByRole("link", { name: "Suppliers" })).toHaveAttribute("href", "/suppliers");
  });
});

describe("AppShell members link", () => {
  async function renderWith(permissions: string[]) {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/v1/me") return respond(200, { ...ME, permissions });
      throw new Error(`unexpected request ${url}`);
    });
    renderWithClient(
      <AuthGate>
        <AppShell>content</AppShell>
      </AuthGate>,
    );
    await screen.findByText("content");
  }

  it("shows Members only to someone who can manage members", async () => {
    await renderWith(["read", "manage_members"]);
    expect(screen.getByRole("link", { name: "Members" })).toHaveAttribute("href", "/members");
  });

  it("hides Members from everyone else", async () => {
    await renderWith(["read"]);
    expect(screen.queryByRole("link", { name: "Members" })).toBeNull();
  });
});

describe("AppShell pricing link", () => {
  async function renderWith(permissions: string[]) {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/v1/me") return respond(200, { ...ME, permissions });
      throw new Error(`unexpected request ${url}`);
    });
    renderWithClient(
      <AuthGate>
        <AppShell>content</AppShell>
      </AuthGate>,
    );
    await screen.findByText("content");
  }

  it("shows Pricing only to someone who can manage pricing", async () => {
    await renderWith(["read", "manage_pricing"]);
    expect(screen.getByRole("link", { name: "Pricing" })).toHaveAttribute("href", "/settings/pricing");
  });

  it("hides Pricing from everyone else", async () => {
    await renderWith(["read", "manage_members"]);
    expect(screen.queryByRole("link", { name: "Pricing" })).toBeNull();
  });
});

describe("AppShell audit link", () => {
  async function renderWith(permissions: string[]) {
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/v1/me") return respond(200, { ...ME, permissions });
      throw new Error(`unexpected request ${url}`);
    });
    renderWithClient(
      <AuthGate>
        <AppShell>content</AppShell>
      </AuthGate>,
    );
    await screen.findByText("content");
  }

  it("is shown to someone who may view the audit trail", async () => {
    await renderWith(["read", "view_audit"]);
    expect(screen.getByRole("link", { name: "Audit" })).toHaveAttribute("href", "/audit");
  });

  it("is hidden from everyone else", async () => {
    await renderWith(["read", "manage_members"]);
    expect(screen.queryByRole("link", { name: "Audit" })).toBeNull();
  });
});
