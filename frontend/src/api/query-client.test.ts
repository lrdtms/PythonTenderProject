import { QueryObserver } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, respond } from "@/test/render";

import { get, post } from "./client";
import { createQueryClient } from "./query-client";
import { meQueryOptions } from "./session";

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

  it("does not re-check the session for a non-401 error", async () => {
    const { client, stop } = await withActiveMe();
    await client.fetchQuery({ queryKey: ["boom"], queryFn: () => get("/api/v1/boom"), retry: false }).catch(() => {});
    await new Promise((r) => setTimeout(r, 50));
    expect(meCalls()).toBe(1);
    stop();
  });

  it("does not loop when the /me query itself answers 401", async () => {
    let meRequests = 0;
    fetchMock.mockImplementation(async (url: string) => {
      if (url === "/api/v1/me") {
        meRequests += 1;
        return meRequests === 1 ? respond(200, ME) : respond(401, errorBody("unauthorized", "Sign in."));
      }
      throw new Error(`unexpected ${url}`);
    });
    const { client, stop } = await withActiveMe();
    await vi.waitFor(() => expect(client.getQueryState(["me"])?.status).toBe("success"));
    await client.refetchQueries({ queryKey: ["me"] });
    await new Promise((r) => setTimeout(r, 100));
    expect(meCalls()).toBe(2);
    stop();
  });

  it("shares one re-check between several parallel 401s", async () => {
    const { client, stop } = await withActiveMe();
    await Promise.all(
      ["a", "b", "c"].map((key) =>
        client.fetchQuery({ queryKey: [key], queryFn: () => get("/api/v1/tenders"), retry: false }).catch(() => {}),
      ),
    );
    await new Promise((r) => setTimeout(r, 100));
    expect(meCalls()).toBeLessThanOrEqual(2);
    stop();
  });
});
