import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ME, errorBody, renderWithClient, respond } from "@/test/render";

import LoginPage from "./login/page";
import RegisterPage from "./register/page";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const fetchMock = vi.fn();
beforeEach(() => {
  replace.mockReset();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

function signedOut(extra: (url: string, init?: RequestInit) => Response | undefined) {
  fetchMock.mockImplementation(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/me") return respond(401, errorBody("unauthorized", "Sign in."));
    const handled = extra(url, init);
    if (handled) return handled;
    throw new Error(`unexpected request ${url}`);
  });
}

describe("login page", () => {
  it("posts the credentials with the CSRF header and goes to /tenders", async () => {
    signedOut((url) => (url === "/api/v1/auth/login" ? respond(200, ME) : undefined));
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/v1/auth/login")!;
    expect(call[1].headers["X-Requested-With"]).toBe("IntelTPS");
    expect(JSON.parse(call[1].body)).toEqual({
      email: "esta@example.com",
      password: "correct-horse-battery",
    });
  });

  it("shows the server's message for a wrong password and stays on the page", async () => {
    signedOut((url) =>
      url === "/api/v1/auth/login"
        ? respond(401, errorBody("unauthorized", "Invalid email or password."))
        : undefined,
    );
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong-password-1");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password.");
    expect(replace).not.toHaveBeenCalled();
  });

  it("disables the button while the request is pending (no double submit)", async () => {
    let finish: (r: Response) => void = () => {};
    signedOut((url) => {
      if (url !== "/api/v1/auth/login") return undefined;
      return new Promise<Response>((resolve) => (finish = resolve)) as unknown as Response;
    });
    renderWithClient(<LoginPage />);
    await userEvent.type(await screen.findByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    const button = screen.getByRole("button", { name: /sign in/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/v1/auth/login")).toHaveLength(1);
    finish(respond(200, ME));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
  });

  it("sends an already signed-in user straight to /tenders", async () => {
    fetchMock.mockResolvedValue(respond(200, ME));
    renderWithClient(<LoginPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
  });
});

describe("register page", () => {
  it("creates the account, then goes to /tenders", async () => {
    signedOut((url) => (url === "/api/v1/auth/register" ? respond(201, ME) : undefined));
    renderWithClient(<RegisterPage />);
    await userEvent.type(await screen.findByLabelText(/organisation/i), "Acme Electrical");
    await userEvent.type(screen.getByLabelText(/your name/i), "Esta Mator");
    await userEvent.type(screen.getByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "correct-horse-battery");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tenders"));
    const call = fetchMock.mock.calls.find(([url]) => url === "/api/v1/auth/register")!;
    expect(JSON.parse(call[1].body)).toEqual({
      organisation_name: "Acme Electrical",
      name: "Esta Mator",
      email: "esta@example.com",
      password: "correct-horse-battery",
    });
  });

  it("shows the password policy message from the API", async () => {
    signedOut((url) =>
      url === "/api/v1/auth/register"
        ? respond(422, errorBody("validation_error", "Use at least 10 characters."))
        : undefined,
    );
    renderWithClient(<RegisterPage />);
    await userEvent.type(await screen.findByLabelText(/organisation/i), "Acme");
    await userEvent.type(screen.getByLabelText(/your name/i), "Esta");
    await userEvent.type(screen.getByLabelText(/email/i), "esta@example.com");
    await userEvent.type(screen.getByLabelText(/password/i), "short");
    await userEvent.click(screen.getByRole("button", { name: /create account/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Use at least 10 characters.");
  });
});
