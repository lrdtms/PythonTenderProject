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
});
