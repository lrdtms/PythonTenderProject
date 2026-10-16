import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, createTestClient, respond } from "@/test/render";

import { useLogin, useRegister } from "./session";

const OTHER_USER = { ...ME, user_id: "33333333-3333-3333-3333-333333333333", name: "New User" };

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function setup<T>(hook: () => T) {
  const client = createTestClient();
  client.setQueryData(["me"], ME);
  client.setQueryData(["tenders", "dummy"], { secret: "previous user's tenant row" });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, ...renderHook(hook, { wrapper }) };
}

describe("a new session drops the previous user's cache", () => {
  it("login clears every cached query, then stores the new me", async () => {
    fetchMock.mockResolvedValue(respond(200, OTHER_USER));
    const { client, result } = setup(useLogin);
    await act(() => result.current.mutateAsync({ email: "new@example.com", password: "correct-horse-battery" }));
    expect(client.getQueryData(["tenders", "dummy"])).toBeUndefined();
    expect(client.getQueryData(["me"])).toEqual(OTHER_USER);
  });

  it("register clears every cached query, then stores the new me", async () => {
    fetchMock.mockResolvedValue(respond(201, OTHER_USER));
    const { client, result } = setup(useRegister);
    await act(() =>
      result.current.mutateAsync({
        organisation_name: "New Org",
        name: "New User",
        email: "new@example.com",
        password: "correct-horse-battery",
      }),
    );
    expect(client.getQueryData(["tenders", "dummy"])).toBeUndefined();
    expect(client.getQueryData(["me"])).toEqual(OTHER_USER);
  });
});
