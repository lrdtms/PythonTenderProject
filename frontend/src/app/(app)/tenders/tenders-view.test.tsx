import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";
import { ids, makeTender } from "@/test/fixtures";

import { TendersView } from "./tenders-view";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const WRITE = meWith(["read", "edit_tenders"]);

describe("TendersView", () => {
  it("lists tenders with status and links to each", async () => {
    mockApi({ "GET /api/v1/tenders": () => respond(200, [makeTender(), makeTender({ id: ids.user, title: "Clinic", status: "in_review" })]) });
    renderSignedIn(<TendersView />);
    const link = await screen.findByRole("link", { name: "Hall wiring" });
    expect(link).toHaveAttribute("href", `/tenders/${ids.tender}`);
    expect(screen.getByRole("link", { name: "Clinic" })).toBeInTheDocument();
    expect(screen.getByText("In review")).toBeInTheDocument();
  });

  it("shows an empty state, and an error with a retry that works", async () => {
    let fail = true;
    mockApi({
      "GET /api/v1/tenders": () =>
        fail ? respond(500, errorBody("internal_error", "Server problem.")) : respond(200, []),
    });
    renderSignedIn(<TendersView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Server problem.");
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText(/no tenders yet/i)).toBeInTheDocument();
  });

  it("creates a tender: sends only the filled fields with the CSRF header, then shows the list again", async () => {
    let created = false;
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, created ? [makeTender({ title: "New job" })] : []),
        "POST /api/v1/tenders": () => {
          created = true;
          return respond(201, makeTender({ title: "New job" }));
        },
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.type(await screen.findByLabelText(/title/i), "New job");
    await userEvent.type(screen.getByLabelText(/client/i), "Acme");
    await userEvent.click(screen.getByRole("button", { name: /create tender/i }));
    expect(await screen.findByRole("link", { name: "New job" })).toBeInTheDocument();
    const [, init] = callsTo(fetchMock, "POST", "/api/v1/tenders")[0];
    expect((init as RequestInit & { headers: Record<string, string> }).headers["X-Requested-With"]).toBe("IntelTPS");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ title: "New job", client_name: "Acme" });
    expect(screen.getByLabelText(/title/i)).toHaveValue(""); // the form resets
  });

  it("does not double submit and shows the server's message when creating fails", async () => {
    let finish: (r: Response) => void = () => {};
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, []),
        "POST /api/v1/tenders": () => new Promise<Response>((resolve) => (finish = resolve)),
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.type(await screen.findByLabelText(/title/i), "X");
    const button = screen.getByRole("button", { name: /create tender/i });
    await userEvent.click(button);
    await waitFor(() => expect(button).toBeDisabled());
    await userEvent.click(button);
    expect(callsTo(fetchMock, "POST", "/api/v1/tenders")).toHaveLength(1);
    finish(respond(422, errorBody("validation_error", "The request is not valid.")));
    expect(await screen.findByRole("alert")).toHaveTextContent("The request is not valid.");
  });

  it("archives with an inline two-step confirmation", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/tenders": () => respond(200, [makeTender()]),
        [`POST /api/v1/tenders/${ids.tender}/archive`]: () => respond(200, makeTender({ status: "archived" })),
      },
      WRITE,
    );
    renderSignedIn(<TendersView />);
    await userEvent.click(await screen.findByRole("button", { name: "Archive Hall wiring" }));
    expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/archive`)).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Cancel archiving Hall wiring" }));
    expect(screen.getByRole("button", { name: "Archive Hall wiring" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Archive Hall wiring" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm archive of Hall wiring" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/archive`)).toHaveLength(1));
  });

  it("shows no write controls to a user without edit_tenders", async () => {
    mockApi({ "GET /api/v1/tenders": () => respond(200, [makeTender()]) }, meWith(["read"], "reviewer"));
    renderSignedIn(<TendersView />);
    const row = (await screen.findByRole("link", { name: "Hall wiring" })).closest("li")!;
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/title/i)).not.toBeInTheDocument();
  });

  it("asks for archived tenders only when the box is ticked", async () => {
    const fetchMock = mockApi({ "GET /api/v1/tenders": () => respond(200, []) });
    renderSignedIn(<TendersView />);
    await screen.findByText(/no tenders yet/i);
    await userEvent.click(screen.getByLabelText(/show archived/i));
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([url]) => String(url).includes("include_archived=true"))).toBe(true),
    );
  });

  it("keeps the list and says it may be out of date when a refresh fails", async () => {
    let n = 0;
    let healthy = false;
    mockApi({
      "GET /api/v1/tenders": () => {
        n += 1;
        return n === 1 || healthy ? respond(200, [makeTender()]) : respond(500, errorBody("server_error", "Boom"));
      },
    });
    const { client } = renderSignedIn(<TendersView />);
    await screen.findByText("Hall wiring");
    await client.refetchQueries({ queryKey: ["tenders"] });
    expect(await screen.findByText("Could not refresh the list.")).toBeInTheDocument();
    expect(screen.getByText("Hall wiring")).toBeInTheDocument();
    healthy = true;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(screen.queryByText("Could not refresh the list.")).not.toBeInTheDocument());
  });
});
