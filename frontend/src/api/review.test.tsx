import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeBoqItem } from "@/test/fixtures";
import { callsTo, createTestClient, errorBody, mockApi, respond } from "@/test/render";

import { REVIEW_PAGE_SIZE, useBoqItems, useReviewMutation } from "./review";

afterEach(() => vi.unstubAllGlobals());

const LIST = `/api/v1/document-versions/${ids.version}/boq-items`;

function wrapper() {
  const client = createTestClient();
  const W = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return W;
}

function useBoth() {
  const list = useBoqItems(ids.version);
  const review = useReviewMutation("boq-item", ids.version);
  return { list, review };
}

describe("review data layer", () => {
  it("pages by offset and stops on a short page", async () => {
    const full = Array.from({ length: REVIEW_PAGE_SIZE }, (_, i) => makeBoqItem({ id: `a${i}` }));
    const fetchMock = mockApi({ [`GET ${LIST}`]: () => respond(200, full) });
    const { result } = renderHook(() => useBoqItems(ids.version), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.hasNextPage).toBe(true));
    fetchMock.mockImplementationOnce(async () => respond(200, [makeBoqItem({ id: "last" })]));
    await act(async () => {
      await result.current.fetchNextPage();
    });
    await waitFor(() => expect(result.current.hasNextPage).toBe(false));
    expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain("offset=200");
    expect(result.current.rows).toHaveLength(REVIEW_PAGE_SIZE + 1);
  });

  it("confirms optimistically and rolls back on 403", async () => {
    let release: () => void = () => {};
    mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeBoqItem({ id: "r1" })]),
      "POST /api/v1/boq-items/r1/confirm": () =>
        new Promise<Response>((res) => {
          release = () => res(respond(403, errorBody("forbidden", "no")));
        }),
    });
    const { result } = renderHook(useBoth, { wrapper: wrapper() });
    await waitFor(() => expect(result.current.list.rows).toHaveLength(1));
    act(() => {
      result.current.review.mutate({ action: "confirm", id: "r1" });
    });
    await waitFor(() => expect(result.current.list.rows[0].review_status).toBe("confirmed"));
    await act(async () => {
      release();
    });
    await waitFor(() => expect(result.current.list.rows[0].review_status).toBe("unreviewed"));
  });

  it("reloads the list when the row was replaced", async () => {
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeBoqItem({ id: "r1" })]),
      "POST /api/v1/boq-items/r1/confirm": () => respond(404, errorBody("not_found", "gone")),
    });
    const { result } = renderHook(useBoth, { wrapper: wrapper() });
    await waitFor(() => expect(result.current.list.rows).toHaveLength(1));
    await act(async () => {
      await result.current.review.mutateAsync({ action: "confirm", id: "r1" }).catch(() => {});
    });
    await waitFor(() => expect(callsTo(fetchMock, "GET", LIST).length).toBeGreaterThanOrEqual(2));
  });

  it("sends exactly the patch body with the CSRF header", async () => {
    const fetchMock = mockApi({
      [`GET ${LIST}`]: () => respond(200, [makeBoqItem({ id: "r1" })]),
      "PATCH /api/v1/boq-items/r1": () => respond(200, makeBoqItem({ id: "r1", review_status: "corrected" })),
    });
    const { result } = renderHook(useBoth, { wrapper: wrapper() });
    await waitFor(() => expect(result.current.list.rows).toHaveLength(1));
    await act(async () => {
      await result.current.review.mutateAsync({ action: "correct", id: "r1", patch: { quantity: "1500" } });
    });
    const [, init] = callsTo(fetchMock, "PATCH", "/api/v1/boq-items/r1")[0];
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ quantity: "1500" });
    expect(((init as RequestInit).headers as Record<string, string>)["X-Requested-With"]).toBe("IntelTPS");
  });
});
