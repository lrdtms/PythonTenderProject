import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StatusView } from "./status-view";

const fetchMock = vi.fn();
beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const ok = (body: object) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

describe("StatusView", () => {
  it("shows the three parts in plain words", async () => {
    fetchMock.mockResolvedValue(ok({ api: "ok", database: "ok", model: "ok" }));
    render(<StatusView />);
    expect(await screen.findByText("Server: working")).toBeInTheDocument();
    expect(screen.getByText("Database: working")).toBeInTheDocument();
    expect(screen.getByText("Language model: working")).toBeInTheDocument();
  });

  it("says when a part is down or not set up", async () => {
    fetchMock.mockResolvedValue(ok({ api: "ok", database: "down", model: "not_configured" }));
    render(<StatusView />);
    expect(await screen.findByText("Database: not working")).toBeInTheDocument();
    expect(screen.getByText("Language model: not set up")).toBeInTheDocument();
  });

  it("asks again every 15 seconds", async () => {
    fetchMock.mockResolvedValue(ok({ api: "ok", database: "ok", model: "ok" }));
    render(<StatusView />);
    await screen.findByText("Server: working");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("says the server cannot be reached when the request fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<StatusView />);
    expect(await screen.findByText("Cannot reach the server.")).toBeInTheDocument();
  });

  it("does not send credentials-dependent headers or need a session", async () => {
    fetchMock.mockResolvedValue(ok({ api: "ok", database: "ok", model: "ok" }));
    render(<StatusView />);
    await screen.findByText("Server: working");
    expect(String(fetchMock.mock.calls[0][0])).toBe("/api/v1/health/status");
  });
});
