import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Usage } from "@/api/usage";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { UsageView } from "./usage-view";

afterEach(() => vi.unstubAllGlobals());

const admin = meWith(["read", "manage_members"], "admin");
const reader = meWith(["read"], "reviewer");

const usage = (over: Partial<Usage> = {}): Usage => ({
  plan_code: "starter",
  plan_name: "Starter",
  items: [
    { resource: "tenders", label: "Active tenders", used: 2, limit: 3, period: "current" },
    { resource: "uploads", label: "Uploads this month", used: 10, limit: 10, period: "month" },
    { resource: "storage_mb", label: "Storage", used: 4, limit: 50, period: "current" },
    { resource: "exports", label: "Exports this month", used: 0, limit: 20, period: "month" },
    { resource: "members", label: "Members", used: 1, limit: 3, period: "current" },
  ],
  available_plans: [
    { code: "demo", name: "Demo" },
    { code: "starter", name: "Starter" },
  ],
  ...over,
});

describe("UsageView", () => {
  it("shows used of limit as text and as a progressbar for every resource", async () => {
    mockApi({ "GET /api/v1/usage": () => respond(200, usage()) }, reader);
    renderSignedIn(<UsageView />);
    expect(await screen.findByText("2 of 3")).toBeInTheDocument();
    const bars = screen.getAllByRole("progressbar");
    expect(bars).toHaveLength(5);
    expect(bars[0]).toHaveAttribute("aria-valuenow", "2");
    expect(bars[0]).toHaveAttribute("aria-valuemax", "3");
    expect(bars[0]).toHaveAccessibleName("Active tenders");
    expect(screen.getByText("4 of 50 MB")).toBeInTheDocument();
    expect(screen.getByText(/Starter plan/)).toBeInTheDocument();
  });

  it("labels monthly resources and says Limit reached in words at the limit", async () => {
    mockApi({ "GET /api/v1/usage": () => respond(200, usage()) }, reader);
    renderSignedIn(<UsageView />);
    const uploads = (await screen.findByText("Uploads this month")).closest("li") as HTMLElement;
    expect(within(uploads).getByText("per month")).toBeInTheDocument();
    expect(within(uploads).getByText("Limit reached")).toBeInTheDocument();
    const tenders = screen.getByText("Active tenders").closest("li") as HTMLElement;
    expect(within(tenders).queryByText("Limit reached")).not.toBeInTheDocument();
  });

  it("hides the plan switch from non-admins", async () => {
    mockApi({ "GET /api/v1/usage": () => respond(200, usage()) }, reader);
    renderSignedIn(<UsageView />);
    await screen.findByText("2 of 3");
    expect(screen.queryByRole("button", { name: "Switch plan" })).not.toBeInTheDocument();
  });

  it("lets an admin switch plan, says no payment is taken, and shows the new limits", async () => {
    let current = usage();
    const fetchMock = mockApi(
      {
        "GET /api/v1/usage": () => respond(200, current),
        "PUT /api/v1/usage/plan": () => {
          current = usage({ plan_code: "demo", plan_name: "Demo" });
          return respond(200, current);
        },
      },
      admin,
    );
    renderSignedIn(<UsageView />);
    await screen.findByText("2 of 3");
    expect(screen.getByText("This is a demo plan switch. No payment is taken.")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Plan"), "demo");
    await userEvent.click(screen.getByRole("button", { name: "Switch plan" }));
    expect(await screen.findByText(/Demo plan/)).toBeInTheDocument();
    const put = callsTo(fetchMock, "PUT", "/api/v1/usage/plan")[0];
    expect(JSON.parse((put[1] as RequestInit).body as string)).toEqual({ plan_code: "demo" });
  });

  it("shows a refusal from the server in words", async () => {
    mockApi(
      {
        "GET /api/v1/usage": () => respond(200, usage()),
        "PUT /api/v1/usage/plan": () => respond(404, errorBody("not_found", "Plan not found")),
      },
      admin,
    );
    renderSignedIn(<UsageView />);
    await screen.findByText("2 of 3");
    await userEvent.selectOptions(screen.getByLabelText("Plan"), "demo");
    await userEvent.click(screen.getByRole("button", { name: "Switch plan" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Plan not found");
  });

  it("shows a load error", async () => {
    mockApi({ "GET /api/v1/usage": () => respond(500, errorBody("internal_error", "Broke.")) }, reader);
    renderSignedIn(<UsageView />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Broke.");
  });
});
