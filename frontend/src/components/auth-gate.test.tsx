import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, renderWithClient, respond } from "@/test/render";

import { AuthGate, useCan, useSession } from "./auth-gate";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  replace.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function Who() {
  const me = useSession();
  const canReview = useCan("review_data");
  const canManage = useCan("manage_members");
  return <p>{`${me.name}|${canReview}|${canManage}`}</p>;
}

describe("AuthGate", () => {
  it("renders children with the session and permission checks", async () => {
    fetchMock.mockResolvedValue(respond(200, ME));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects to /login on 401 only", async () => {
    fetchMock.mockResolvedValue(respond(401, errorBody("unauthorized", "Sign in.")));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText(/Esta/)).not.toBeInTheDocument();
  });

  it("shows an error with a retry, and does not redirect, on a server or network failure", async () => {
    fetchMock.mockResolvedValueOnce(respond(500, errorBody("internal_error", "Something went wrong.")));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong.");
    expect(replace).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(respond(200, ME));
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();

    fetchMock.mockReset();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect((await screen.findAllByRole("alert")).at(-1)).toHaveTextContent(/could not reach the server/i);
    expect(replace).not.toHaveBeenCalled();
  });

  it("keeps the app mounted when a later refetch fails with a server error", async () => {
    fetchMock.mockResolvedValueOnce(respond(200, ME));
    const { client } = renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();
    fetchMock.mockResolvedValueOnce(respond(500, errorBody("internal_error", "Something went wrong.")));
    await client.invalidateQueries({ queryKey: ["me"] });
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.getByText("Esta Mator|true|false")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects to /login when a later refetch returns 401", async () => {
    fetchMock.mockResolvedValueOnce(respond(200, ME));
    const { client } = renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();
    fetchMock.mockResolvedValueOnce(respond(401, errorBody("unauthorized", "Sign in.")));
    await client.invalidateQueries({ queryKey: ["me"] });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });

  it("clears the whole cache (stale me included) before redirecting when a refetch returns 401", async () => {
    fetchMock.mockResolvedValueOnce(respond(200, ME));
    const { client } = renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByText("Esta Mator|true|false")).toBeInTheDocument();
    client.setQueryData(["tenders", "dummy"], { secret: "tenant row" });
    const cachedAtRedirect: unknown[] = [];
    replace.mockImplementation(() => cachedAtRedirect.push(client.getQueryData(["tenders", "dummy"])));
    fetchMock.mockResolvedValue(respond(401, errorBody("unauthorized", "Sign in.")));
    await client.invalidateQueries({ queryKey: ["me"] });
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(cachedAtRedirect[0]).toBeUndefined(); // cleared before the redirect, not after
    expect(client.getQueryData(["tenders", "dummy"])).toBeUndefined();
    expect(client.getQueryData(["me"])).toBeUndefined();
  });

  it("shows the API's message for an ApiError", async () => {
    fetchMock.mockResolvedValueOnce(respond(500, errorBody("internal_error", "The database is down.")));
    renderWithClient(<AuthGate><Who /></AuthGate>);
    expect(await screen.findByRole("alert")).toHaveTextContent("The database is down.");
  });

  it("never shows raw exception text for a non-API error", async () => {
    // A body-stream failure surfaces as a plain Error, not an ApiError.
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      text: () => Promise.reject(new Error("Cannot read properties of undefined (reading 'x')")),
    });
    renderWithClient(<AuthGate><Who /></AuthGate>);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong. Try again.");
    expect(alert).not.toHaveTextContent(/cannot read properties/i);
  });
});
