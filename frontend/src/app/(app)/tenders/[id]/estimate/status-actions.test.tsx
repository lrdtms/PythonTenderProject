import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeEstimate, makeEstimateLine, makeTender } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender }),
}));

import { EstimateView } from "./estimate-view";

afterEach(() => vi.unstubAllGlobals());

const estimator = meWith(["read", "review_data"], "estimator");
const manager = meWith(["read", "approve_estimate"], "project_manager");
const reviewer = meWith(["read"], "reviewer");

const T = `/api/v1/tenders/${ids.tender}`;
const reviewedAt = { reviewed_by: ids.user, reviewed_at: "2026-10-20T08:00:00Z" };
const draft = makeEstimate();
const reviewed = makeEstimate({ status: "reviewed", ...reviewedAt });
const approved = makeEstimate({ status: "approved", ...reviewedAt, approved_by: ids.user, approved_at: "2026-10-21T09:00:00Z" });
const E = (e: { id: string }) => `/api/v1/estimates/${e.id}`;

const summaryOf = (e: ReturnType<typeof makeEstimate>, version = e.version) => ({
  id: e.id, tender_id: e.tender_id, version, status: e.status, currency: e.currency,
  created_at: e.created_at, reviewed_at: e.reviewed_at, approved_at: e.approved_at,
  is_current_approved: e.status === "approved", totals: e.totals,
});

const LINES = [makeEstimateLine({ id: "00000000-0000-4000-8000-000000000601", description: "LED panel" })];

function routes(estimate: ReturnType<typeof makeEstimate>, over: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    [`GET ${T}`]: () => respond(200, makeTender()),
    [`GET ${T}/estimates`]: () => respond(200, [summaryOf(estimate)]),
    [`GET ${E(estimate)}`]: () => respond(200, estimate),
    [`GET ${E(estimate)}/lines`]: () => respond(200, LINES),
    ...over,
  };
}

const button = (name: string) => screen.queryByRole("button", { name });

describe("status actions", () => {
  it("shows Mark reviewed to an estimator on a draft, and posts to review", async () => {
    const fetchMock = mockApi(routes(draft, { [`POST ${E(draft)}/review`]: () => respond(200, reviewed) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(button("Approve")).toBeNull();
    expect(button("Reopen")).toBeNull();
    expect(button("New version")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${E(draft)}/review`)).toHaveLength(1));
  });

  it("lists the blockers in plain words when marking reviewed is refused", async () => {
    const body = { error: { code: "estimate_not_ready", message: "x", details: { blockers: [{ line_id: LINES[0].id, code: "unresolved" }, { line_id: null, code: "no_lines" }] } } };
    mockApi(routes(draft, { [`POST ${E(draft)}/review`]: () => respond(409, body) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    await userEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
    expect(await screen.findByText(/No price has been chosen yet/)).toBeInTheDocument();
    expect(screen.getByText("This estimate has no BoQ lines to price.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to the line/i })).toHaveAttribute("href", `#line-${LINES[0].id}`);
  });

  it("hides Approve from an estimator and Reopen / Mark reviewed from a project manager", async () => {
    mockApi(routes(reviewed), estimator);
    const first = renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(await screen.findByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(button("Approve")).toBeNull();
    first.unmount();
    vi.unstubAllGlobals();

    mockApi(routes(reviewed), manager);
    const second = renderSignedIn(<EstimateView />);
    expect(await screen.findByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(button("Reopen")).toBeNull();
    expect(button("Mark reviewed")).toBeNull();
    second.unmount();
    vi.unstubAllGlobals();

    mockApi(routes(draft), manager);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(button("Mark reviewed")).toBeNull();
  });

  it("gives a reviewer no actions", async () => {
    mockApi(routes(reviewed), reviewer);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    for (const name of ["Mark reviewed", "Approve", "Reopen", "New version"]) expect(button(name)).toBeNull();
  });

  it("asks for confirmation before approving, and posts only after it", async () => {
    const fetchMock = mockApi(routes(reviewed, { [`POST ${E(reviewed)}/approve`]: () => respond(200, approved) }), manager);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    expect(screen.getByText("Approve this estimate? It can no longer be changed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Yes, approve" })).toHaveFocus();
    expect(callsTo(fetchMock, "POST", `${E(reviewed)}/approve`)).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByText(/It can no longer be changed/)).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, approve" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${E(reviewed)}/approve`)).toHaveLength(1));
  });

  it("lists the blockers when approving is refused as not ready", async () => {
    const body = { error: { code: "estimate_not_ready", message: "x", details: { blockers: [{ line_id: null, code: "source_changed" }] } } };
    mockApi(routes(reviewed, { [`POST ${E(reviewed)}/approve`]: () => respond(409, body) }), manager);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));
    await userEvent.click(screen.getByRole("button", { name: "Yes, approve" }));
    expect(await screen.findByText(/Some prices are out of date/)).toBeInTheDocument();
  });

  it("posts to reopen for an estimator on a reviewed estimate", async () => {
    const fetchMock = mockApi(routes(reviewed, { [`POST ${E(reviewed)}/reopen`]: () => respond(200, draft) }), estimator);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "Reopen" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${E(reviewed)}/reopen`)).toHaveLength(1));
  });

  it("offers New version only when no draft exists, and creates one", async () => {
    const fetchMock = mockApi(routes(approved, { [`POST ${T}/estimates`]: () => respond(201, makeEstimate({ id: "00000000-0000-4000-8000-000000000999", version: 2 })) }), estimator);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "New version" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${T}/estimates`)).toHaveLength(1));
  });

  it("does not offer New version while a draft exists, even when an older version is shown", async () => {
    const d2 = makeEstimate({ id: "00000000-0000-4000-8000-000000000998", version: 2 });
    mockApi(
      {
        ...routes(approved),
        [`GET ${E(d2)}`]: () => respond(200, d2),
        [`GET ${E(d2)}/lines`]: () => respond(200, LINES),
        [`GET ${T}/estimates`]: () => respond(200, [summaryOf(d2), summaryOf(approved, 1)]),
      },
      estimator,
    );
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(button("New version")).toBeNull();
  });

  it("explains missing pricing defaults when creating a new version", async () => {
    mockApi(routes(approved, { [`POST ${T}/estimates`]: () => respond(409, errorBody("pricing_defaults_missing", "none")) }), estimator);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "New version" }));
    expect(await screen.findByText(/Save the pricing defaults first/)).toBeInTheDocument();
  });
});
