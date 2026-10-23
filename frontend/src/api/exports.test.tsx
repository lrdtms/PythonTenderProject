import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, createTestClient, mockApi, respond } from "@/test/render";

import { exportDownloadPath, useCreateExport } from "./exports";

afterEach(() => vi.unstubAllGlobals());

const TENDER = "00000000-0000-4000-8000-000000000100";
const EST = "00000000-0000-4000-8000-000000000101";
const PATH = `/api/v1/tenders/${TENDER}/exports`;

function wrapper() {
  const client = createTestClient();
  const Wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return Wrapper;
}

describe("useCreateExport", () => {
  it("posts the estimate kind and id with the CSRF header", async () => {
    const fetchMock = mockApi({ [`POST ${PATH}`]: () => respond(201, { id: "x" }) });
    const { result } = renderHook(() => useCreateExport(TENDER), { wrapper: wrapper() });
    await act(async () => {
      await result.current.mutateAsync({ kind: "estimate_xlsx", estimateId: EST });
    });
    const [call] = callsTo(fetchMock, "POST", PATH);
    const init = call[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ kind: "estimate_xlsx", estimate_id: EST });
    expect((init.headers as Record<string, string>)["X-Requested-With"]).toBe("IntelTPS");
  });

  it("omits estimate_id for the checklist", async () => {
    const fetchMock = mockApi({ [`POST ${PATH}`]: () => respond(201, { id: "x" }) });
    const { result } = renderHook(() => useCreateExport(TENDER), { wrapper: wrapper() });
    act(() => result.current.mutate({ kind: "checklist_pdf" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const init = callsTo(fetchMock, "POST", PATH)[0][1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ kind: "checklist_pdf" });
  });
});

describe("exportDownloadPath", () => {
  it("is the download route", () => {
    expect(exportDownloadPath("abc")).toBe("/api/v1/exports/abc/download");
  });
});
