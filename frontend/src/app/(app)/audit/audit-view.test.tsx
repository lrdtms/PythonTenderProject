import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AuditEvent } from "@/api/audit";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { AuditView } from "./audit-view";

afterEach(() => vi.unstubAllGlobals());

const pm = meWith(["read", "view_audit"], "project_manager");
const event = (over: Partial<AuditEvent>): AuditEvent => ({
  id: "e1",
  created_at: "2026-10-23T08:30:00Z",
  user_id: "u1",
  user_name: "Pat Manager",
  entity_type: "estimate",
  entity_id: "x1",
  action: "approved",
  metadata: { version: 2 },
  ...over,
});
const FACETS = { entity_types: ["estimate", "tender"], actions: ["approved", "created"] };
const facets = () => respond(200, FACETS);

describe("AuditView", () => {
  it("tells someone without view_audit they have no access and never asks for events", async () => {
    const fetchMock = mockApi({}, meWith(["read"], "estimator"));
    renderSignedIn(<AuditView />);
    expect(await screen.findByText("You do not have access to the audit trail.")).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/v1/audit")).toHaveLength(0);
  });

  it("shows events in plain words with the person and details as text", async () => {
    mockApi(
      {
        "GET /api/v1/audit": () =>
          respond(200, {
            items: [
              event({}),
              event({ id: "e2", user_name: null, entity_type: "job", action: "retry_requested", metadata: { reason: "<b>x</b>" } }),
            ],
            next_cursor: null,
          }),
        "GET /api/v1/audit/facets": facets,
      },
      pm,
    );
    renderSignedIn(<AuditView />);
    expect(await screen.findByText("Estimate approved")).toBeInTheDocument();
    expect(screen.getByText("Pat Manager")).toBeInTheDocument();
    expect(screen.getByText("version: 2")).toBeInTheDocument();
    expect(screen.getByText("Unknown user")).toBeInTheDocument();
    expect(screen.getByText("Job retry requested")).toBeInTheDocument();
    expect(screen.getByText("reason: <b>x</b>")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    mockApi({ "GET /api/v1/audit": () => respond(200, { items: [], next_cursor: null }), "GET /api/v1/audit/facets": facets }, pm);
    renderSignedIn(<AuditView />);
    expect(await screen.findByText("No events match.")).toBeInTheDocument();
  });

  it("sends the chosen filters", async () => {
    const fetchMock = mockApi(
      { "GET /api/v1/audit": () => respond(200, { items: [], next_cursor: null }), "GET /api/v1/audit/facets": facets },
      pm,
    );
    renderSignedIn(<AuditView />);
    await screen.findByText("No events match.");
    await userEvent.selectOptions(screen.getByLabelText("Action"), "approved");
    await userEvent.selectOptions(screen.getByLabelText("Object"), "estimate");
    await userEvent.type(screen.getByLabelText("From"), "2026-10-01");
    const last = callsTo(fetchMock, "GET", "/api/v1/audit").at(-1)![0] as string;
    expect(last).toContain("action=approved");
    expect(last).toContain("entity_type=estimate");
    expect(last).toContain("from=2026-10-01");
  });

  it("loads more only while a cursor is offered, and appends", async () => {
    mockApi(
      {
        "GET /api/v1/audit": () => respond(200, { items: [event({ id: "e1" })], next_cursor: "c1" }),
        "GET /api/v1/audit/facets": facets,
      },
      pm,
    );
    renderSignedIn(<AuditView />);
    expect(await screen.findByRole("button", { name: "Load more" })).toBeInTheDocument();
  });

  it("appends the next page and hides Load more at the end", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/audit": () => respond(200, { items: [event({ id: "e1" })], next_cursor: null }),
        "GET /api/v1/audit/facets": facets,
      },
      pm,
    );
    renderSignedIn(<AuditView />);
    await screen.findByText("Estimate approved");
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/v1/audit")).toHaveLength(1);
  });

  it("shows a server error in words", async () => {
    mockApi(
      {
        "GET /api/v1/audit": () => respond(403, errorBody("forbidden", "Not allowed.")),
        "GET /api/v1/audit/facets": facets,
      },
      pm,
    );
    renderSignedIn(<AuditView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Not allowed.");
  });

  it("lists rows in a table", async () => {
    mockApi({ "GET /api/v1/audit": () => respond(200, { items: [event({})], next_cursor: null }), "GET /api/v1/audit/facets": facets }, pm);
    renderSignedIn(<AuditView />);
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
  });
});
