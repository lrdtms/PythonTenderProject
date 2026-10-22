import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, createTestClient, mockApi, respond } from "@/test/render";

import {
  ESTIMATE_LINE_PAGE_SIZE,
  useApproveEstimate,
  useCreateEstimate,
  useEstimate,
  useEstimateLines,
  useEstimates,
  usePatchEstimate,
  usePriceLine,
  usePricingDefaults,
  useRefreshLine,
  useReopenEstimate,
  useReviewEstimate,
  useSavePricingDefaults,
} from "./estimates";

afterEach(() => vi.unstubAllGlobals());

const TENDER = "00000000-0000-4000-8000-000000000100";
const EST = "00000000-0000-4000-8000-000000000101";
const LINE = "00000000-0000-4000-8000-000000000102";
const LINES = `/api/v1/estimates/${EST}/lines`;
const ONE = `/api/v1/estimates/${EST}`;
const LIST = `/api/v1/tenders/${TENDER}/estimates`;

function wrapper() {
  const client = createTestClient();
  const W = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper: W };
}

const line = (id = LINE) => ({ id, status: "unresolved" }) as never;

describe("pricing defaults", () => {
  it("reads the defaults", async () => {
    const fetchMock = mockApi({
      "GET /api/v1/pricing-defaults": () => respond(200, { currency: "ZAR" }),
    });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => usePricingDefaults(), { wrapper: W });
    await waitFor(() => expect(result.current.data).toEqual({ currency: "ZAR" }));
    expect(callsTo(fetchMock, "GET", "/api/v1/pricing-defaults")).toHaveLength(1);
  });

  it("saves with PUT and the CSRF header", async () => {
    const body = { currency: "ZAR", vat_rate: "15", markup_basis: "cost", default_markup_percent: "10" };
    const fetchMock = mockApi({
      "PUT /api/v1/pricing-defaults": () => respond(200, body),
    });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => useSavePricingDefaults(), { wrapper: W });
    await act(async () => {
      await result.current.mutateAsync(body as never);
    });
    const [, init] = callsTo(fetchMock, "PUT", "/api/v1/pricing-defaults")[0];
    expect(((init as RequestInit).headers as Record<string, string>)["X-Requested-With"]).toBe("IntelTPS");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual(body);
  });
});

describe("estimate lists and reads", () => {
  it("lists the estimates of a tender", async () => {
    mockApi({ [`GET ${LIST}`]: () => respond(200, [{ id: EST }]) });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => useEstimates(TENDER), { wrapper: W });
    await waitFor(() => expect(result.current.data).toEqual([{ id: EST }]));
  });

  it("reads one estimate", async () => {
    mockApi({ [`GET ${ONE}`]: () => respond(200, { id: EST, status: "draft" }) });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => useEstimate(EST), { wrapper: W });
    await waitFor(() => expect(result.current.data).toEqual({ id: EST, status: "draft" }));
  });

  it("pages lines 100 at a time with the status filter and stops on a short page", async () => {
    const full = Array.from({ length: ESTIMATE_LINE_PAGE_SIZE }, (_, i) => line(`l${i}`));
    const fetchMock = mockApi({ [`GET ${LINES}`]: () => respond(200, full) });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => useEstimateLines(EST, { status: "priced" }), { wrapper: W });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    const first = new URL(String(callsTo(fetchMock, "GET", LINES)[0][0]), "http://x").searchParams;
    expect(first.get("limit")).toBe("100");
    expect(first.get("offset")).toBe("0");
    expect(first.get("status")).toBe("priced");
    fetchMock.mockImplementationOnce(async () => respond(200, [line("last")]));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("offset=100");
    expect(result.current.lines).toHaveLength(ESTIMATE_LINE_PAGE_SIZE + 1);
  });
});

describe("estimate mutations", () => {
  it("creates a draft for the tender and then refreshes the estimate list", async () => {
    let created = false;
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, created ? [{ id: EST }] : []),
      [`POST ${LIST}`]: () => ((created = true), respond(201, { id: EST, status: "draft" })),
    });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => ({ list: useEstimates(TENDER), create: useCreateEstimate(TENDER) }), {
      wrapper: W,
    });
    await waitFor(() => expect(result.current.list.data).toEqual([]));
    await act(async () => {
      await result.current.create.mutateAsync();
    });
    await waitFor(() => expect(result.current.list.data).toEqual([{ id: EST }]));
    expect(callsTo(fetchMock, "POST", LIST)).toHaveLength(1);
  });

  it("prices a line and invalidates the estimate, its lines and the list", async () => {
    const fetchMock = mockApi({
      [`GET ${ONE}`]: () => respond(200, { id: EST }),
      [`GET ${LINES}`]: () => respond(200, []),
      [`GET ${LIST}`]: () => respond(200, []),
      [`PUT /api/v1/estimate-lines/${LINE}`]: () => respond(200, line()),
    });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(
      () => ({ one: useEstimate(EST), lines: useEstimateLines(EST, {}), list: useEstimates(TENDER), price: usePriceLine() }),
      { wrapper: W },
    );
    await waitFor(() => expect(callsTo(fetchMock, "GET", ONE)).toHaveLength(1));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LINES)).toHaveLength(1));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(1));
    await act(async () => {
      await result.current.price.mutateAsync({
        lineId: LINE,
        body: { manual_unit_price: "12.50", unit_mismatch_acknowledged: false },
      } as never);
    });
    const [, init] = callsTo(fetchMock, "PUT", `/api/v1/estimate-lines/${LINE}`)[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      manual_unit_price: "12.50",
      unit_mismatch_acknowledged: false,
    });
    await waitFor(() => expect(callsTo(fetchMock, "GET", ONE)).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LINES)).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(2));
  });

  it("refreshes a line through its own path", async () => {
    const fetchMock = mockApi({ [`POST /api/v1/estimate-lines/${LINE}/refresh`]: () => respond(200, line()) });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => useRefreshLine(), { wrapper: W });
    await act(async () => {
      await result.current.mutateAsync(LINE);
    });
    expect(callsTo(fetchMock, "POST", `/api/v1/estimate-lines/${LINE}/refresh`)).toHaveLength(1);
  });

  it("patches the estimate settings", async () => {
    const fetchMock = mockApi({ [`PATCH ${ONE}`]: () => respond(200, { id: EST }) });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(() => usePatchEstimate(), { wrapper: W });
    await act(async () => {
      await result.current.mutateAsync({ id: EST, patch: { vat_rate: "15.00" } });
    });
    const [, init] = callsTo(fetchMock, "PATCH", ONE)[0];
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({ vat_rate: "15.00" });
  });

  it.each([
    ["review", useReviewEstimate],
    ["reopen", useReopenEstimate],
    ["approve", useApproveEstimate],
  ] as const)("%s posts to its own path and refreshes the estimate queries", async (action, hook) => {
    const fetchMock = mockApi({
      [`GET ${ONE}`]: () => respond(200, { id: EST }),
      [`GET ${LINES}`]: () => respond(200, []),
      [`GET ${LIST}`]: () => respond(200, []),
      [`POST ${ONE}/${action}`]: () => respond(200, { id: EST, status: action }),
    });
    const { wrapper: W } = wrapper();
    const { result } = renderHook(
      () => ({ one: useEstimate(EST), lines: useEstimateLines(EST, {}), list: useEstimates(TENDER), act: hook() }),
      { wrapper: W },
    );
    await waitFor(() => expect(callsTo(fetchMock, "GET", ONE)).toHaveLength(1));
    await act(async () => {
      await result.current.act.mutateAsync(EST);
    });
    expect(callsTo(fetchMock, "POST", `${ONE}/${action}`)).toHaveLength(1);
    await waitFor(() => expect(callsTo(fetchMock, "GET", ONE)).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LINES)).toHaveLength(2));
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST)).toHaveLength(2));
  });
});
