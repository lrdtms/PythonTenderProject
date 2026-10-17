import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeMatchLine, makeMatchSuggestion } from "@/test/fixtures";
import { callsTo, createTestClient, errorBody, mockApi, respond } from "@/test/render";

import { ApiError } from "./errors";
import {
  MATCH_PAGE_SIZE,
  type MatchFilters,
  useConfirmClear,
  useDecideMatch,
  useMatchLines,
  useRunMatching,
} from "./matches";

afterEach(() => vi.unstubAllGlobals());

const SUPPLIER = "00000000-0000-4000-8000-000000000030";
const LIST = `/api/v1/tenders/${ids.tender}/match-suggestions`;

function setup() {
  const client = createTestClient();
  const W = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper: W };
}

const urls = (fetchMock: ReturnType<typeof vi.fn>) =>
  callsTo(fetchMock, "GET", LIST).map(([url]) => new URL(String(url), "http://x").searchParams);

describe("useMatchLines", () => {
  it("pages 100 lines at a time and stops on a short page", async () => {
    const full = Array.from({ length: MATCH_PAGE_SIZE }, (_, i) =>
      makeMatchLine({ boq: { ...makeMatchLine().boq, id: `b${i}` } }),
    );
    const fetchMock = mockApi({ [`GET ${LIST}`]: () => respond(200, full) });
    const { wrapper } = setup();
    const { result } = renderHook(() => useMatchLines(ids.tender, {}), { wrapper });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    expect(urls(fetchMock)[0].get("limit")).toBe("100");
    expect(urls(fetchMock)[0].get("offset")).toBe("0");
    fetchMock.mockImplementationOnce(async () => respond(200, [makeMatchLine()]));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("offset=100");
    expect(result.current.lines).toHaveLength(MATCH_PAGE_SIZE + 1);
  });

  it("sends filters and restarts from offset 0 when a filter changes", async () => {
    const fetchMock = mockApi({ [`GET ${LIST}`]: () => respond(200, [makeMatchLine()]) });
    const { wrapper } = setup();
    const { result, rerender } = renderHook(({ f }: { f: MatchFilters }) => useMatchLines(ids.tender, f), {
      wrapper,
      initialProps: { f: {} as MatchFilters },
    });
    await waitFor(() => expect(result.current.lines).toHaveLength(1));
    expect(urls(fetchMock)[0].has("status")).toBe(false);
    rerender({
      f: { status: "confirmed", classification: "clear", supplierId: SUPPLIER, onlyWithSuggestions: true },
    });
    await waitFor(() => expect(urls(fetchMock)).toHaveLength(2));
    const second = urls(fetchMock)[1];
    expect(second.get("status")).toBe("confirmed");
    expect(second.get("classification")).toBe("clear");
    expect(second.get("supplier_id")).toBe(SUPPLIER);
    expect(second.get("only_with_suggestions")).toBe("true");
    expect(second.get("offset")).toBe("0");
  });
});

describe("useDecideMatch", () => {
  const SUGG = "00000000-0000-4000-8000-000000000060";
  function useBoth() {
    return { list: useMatchLines(ids.tender, {}), decide: useDecideMatch(ids.tender) };
  }

  it("confirms with the CSRF header, replaces the suggestion at once, then refreshes in the background", async () => {
    let confirmed = false;
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () =>
        respond(200, [makeMatchLine({ suggestions: [makeMatchSuggestion({ status: confirmed ? "confirmed" : "suggested", decided_by_name: confirmed ? "Esta" : null })] })]),
      [`POST /api/v1/match-suggestions/${SUGG}/confirm`]: () =>
        ((confirmed = true), respond(200, makeMatchSuggestion({ status: "confirmed", decided_by_name: "Esta" }))),
    });
    const { wrapper } = setup();
    const { result } = renderHook(useBoth, { wrapper });
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    await act(async () => {
      await result.current.decide.confirm.mutateAsync(SUGG);
    });
    const [, init] = callsTo(fetchMock, "POST", `/api/v1/match-suggestions/${SUGG}/confirm`)[0];
    expect(((init as RequestInit).headers as Record<string, string>)["X-Requested-With"]).toBe("IntelTPS");
    await waitFor(() => expect(result.current.list.lines[0].suggestions[0].status).toBe("confirmed"));
    await waitFor(() => expect(result.current.list.lines[0].suggestions[0].decided_by_name).toBe("Esta"));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST).length).toBeGreaterThanOrEqual(2));
  });

  it("rejects and resets through their own paths", async () => {
    let server = "suggested";
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeMatchLine({ suggestions: [makeMatchSuggestion({ status: server })] })]),
      [`POST /api/v1/match-suggestions/${SUGG}/reject`]: () =>
        ((server = "rejected"), respond(200, makeMatchSuggestion({ status: "rejected" }))),
      [`POST /api/v1/match-suggestions/${SUGG}/reset`]: () =>
        ((server = "suggested"), respond(200, makeMatchSuggestion({ status: "suggested" }))),
    });
    const { wrapper } = setup();
    const { result } = renderHook(useBoth, { wrapper });
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    await act(async () => {
      await result.current.decide.reject.mutateAsync(SUGG);
    });
    await waitFor(() => expect(result.current.list.lines[0].suggestions[0].status).toBe("rejected"));
    await act(async () => {
      await result.current.decide.reset.mutateAsync(SUGG);
    });
    await waitFor(() => expect(result.current.list.lines[0].suggestions[0].status).toBe("suggested"));
    expect(callsTo(fetchMock, "POST", `/api/v1/match-suggestions/${SUGG}/reset`)).toHaveLength(1);
  });

  it.each(["stale_match", "row_replaced", "try_again"])("reloads the list on %s", async (code) => {
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeMatchLine()]),
      [`POST /api/v1/match-suggestions/${SUGG}/confirm`]: () => respond(409, errorBody(code, "no")),
    });
    const { wrapper } = setup();
    const { result } = renderHook(useBoth, { wrapper });
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    await act(async () => {
      await result.current.decide.confirm.mutateAsync(SUGG).catch(() => {});
    });
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST).length).toBeGreaterThanOrEqual(2));
  });

  it("does not reload the list on 409 match_conflict", async () => {
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeMatchLine()]),
      [`POST /api/v1/match-suggestions/${SUGG}/confirm`]: () => respond(409, errorBody("match_conflict", "no")),
    });
    const { wrapper } = setup();
    const { result } = renderHook(useBoth, { wrapper });
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    await act(async () => {
      await result.current.decide.confirm.mutateAsync(SUGG).catch(() => {});
    });
    await new Promise((r) => setTimeout(r, 50));
    expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(1);
  });

  it("leaves the cache unchanged on 409 match_conflict", async () => {
    mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeMatchLine()]),
      [`POST /api/v1/match-suggestions/${SUGG}/confirm`]: () => respond(409, errorBody("match_conflict", "no")),
    });
    const { wrapper } = setup();
    const { result } = renderHook(useBoth, { wrapper });
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    let caught: unknown;
    await act(async () => {
      caught = await result.current.decide.confirm.mutateAsync(SUGG).catch((e: unknown) => e);
    });
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe("match_conflict");
    await waitFor(() => expect(result.current.list.lines[0].suggestions[0].status).toBe("suggested"));
  });
});

describe("useConfirmClear and useRunMatching", () => {
  it("confirm-clear posts and reloads the lines", async () => {
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeMatchLine()]),
      [`POST ${LIST}/confirm-clear`]: () => respond(200, { confirmed: 3, skipped: 1 }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(
      () => ({ list: useMatchLines(ids.tender, {}), clear: useConfirmClear(ids.tender) }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.list.lines).toHaveLength(1));
    let out: { confirmed: number; skipped: number } | undefined;
    await act(async () => {
      out = await result.current.clear.mutateAsync();
    });
    expect(out).toEqual({ confirmed: 3, skipped: 1 });
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST).length).toBeGreaterThanOrEqual(2));
  });

  it("run matching posts to /match", async () => {
    const fetchMock = mockApi({
      [`POST /api/v1/tenders/${ids.tender}/match`]: () => respond(202, { id: ids.job }),
    });
    const { wrapper } = setup();
    const { result } = renderHook(() => useRunMatching(ids.tender), { wrapper });
    await act(async () => {
      await result.current.mutateAsync();
    });
    expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/match`)).toHaveLength(1);
  });
});
