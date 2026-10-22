import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/errors";
import { ids, makeEstimate, makeEstimateLine, makeTender } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender }),
}));

import { ErrorNotice, EstimateView } from "./estimate-view";

afterEach(() => vi.unstubAllGlobals());

const estimator = meWith(["read", "review_data"], "estimator");
const reviewer = meWith(["read"], "reviewer");
const admin = meWith(["read", "review_data", "manage_pricing"], "admin");

const T = `/api/v1/tenders/${ids.tender}`;
const draft = makeEstimate();
const E = `/api/v1/estimates/${draft.id}`;

const summaryOf = (e: ReturnType<typeof makeEstimate>) => ({
  id: e.id, tender_id: e.tender_id, version: e.version, status: e.status, currency: e.currency,
  created_at: e.created_at, reviewed_at: e.reviewed_at, approved_at: e.approved_at,
  is_current_approved: e.status === "approved", totals: e.totals,
});

const cand = (n: number, name: string, price: string) => ({
  match_id: `00000000-0000-4000-8000-0000000008${n}0`,
  quotation_item_id: `00000000-0000-4000-8000-0000000009${n}0`,
  supplier_id: `00000000-0000-4000-8000-0000000007${n}0`,
  supplier_name: name, unit_price: price, currency: "ZAR", includes_vat: false, warnings: [],
});

const LINES = [
  makeEstimateLine({ id: "00000000-0000-4000-8000-000000000601", section: "Lighting", description: "LED panel", candidates: [cand(1, "Zulu Supplies", "125.5000"), cand(2, "Alpha Traders", "90.0000")] }),
  makeEstimateLine({ id: "00000000-0000-4000-8000-000000000602", section: "Lighting", item_no: "1.2", description: "Downlight" }),
  makeEstimateLine({ id: "00000000-0000-4000-8000-000000000603", section: "Cabling", item_no: "2.1", description: "Cable tray" }),
];

function routes(over: Record<string, () => Response | Promise<Response>> = {}, estimate = draft, lines = LINES) {
  return {
    [`GET ${T}`]: () => respond(200, makeTender()),
    [`GET ${T}/estimates`]: () => respond(200, [summaryOf(estimate)]),
    [`GET /api/v1/estimates/${estimate.id}`]: () => respond(200, estimate),
    [`GET /api/v1/estimates/${estimate.id}/lines`]: () => respond(200, lines),
    ...over,
  };
}

describe("EstimateView", () => {
  it("shows the draft label, status, settings, summary and lines grouped by section in order", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/LED panel/)).toBeInTheDocument();
    expect(screen.getAllByText("Draft").length).toBeGreaterThan(0);
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual(expect.arrayContaining(["Lighting", "Cabling"]));
    expect(headings.indexOf("Lighting")).toBeLessThan(headings.indexOf("Cabling"));
    expect(screen.getByText("Total inc VAT")).toBeInTheDocument();
    expect(screen.getByLabelText("Version")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to the tender/i })).toBeInTheDocument();
  });

  it("pre-selects no candidate, highlights none, and keeps the order sent", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Zulu Supplies")).toBeLessThan(text.indexOf("Alpha Traders"));
    expect(document.querySelector("[aria-label='Supplier prices'] input:checked, [aria-checked=true], [data-best], [data-lowest]")).toBeNull();
    expect(text).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });

  it("labels the total incomplete while lines are open and hides it otherwise", async () => {
    mockApi(routes({}, makeEstimate({ incomplete: true, unresolved: 2, changed: 1 })), estimator);
    const first = renderSignedIn(<EstimateView />);
    expect(await screen.findByText("Incomplete: excludes 3 lines")).toBeInTheDocument();
    first.unmount();
    vi.unstubAllGlobals();
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(screen.queryByText(/incomplete/i)).toBeNull();
  });

  it("renders a frozen estimate read-only with reviewer and approver names and no controls", async () => {
    const frozen = makeEstimate({
      status: "approved", reviewed_by_name: "Esta Mator", approved_by_name: "Esta Mator", reviewed_by: ids.user, reviewed_at: "2026-10-20T08:00:00Z", approved_by: ids.user, approved_at: "2026-10-21T09:00:00Z",
    });
    mockApi(routes({}, frozen), meWith(["read", "review_data", "approve_estimate"], "admin"));
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(await screen.findByText(/Reviewed by Esta Mator/)).toBeInTheDocument();
    expect(screen.getByText(/Approved by Esta Mator/)).toBeInTheDocument();
    const main = document.body;
    expect(main.querySelector("input[type=text], input[type=radio], textarea")).toBeNull();
    expect(within(main).queryByRole("button", { name: /save settings|create estimate/i })).toBeNull();
    expect(screen.queryByText("Draft")).toBeNull();
    expect(screen.queryByText("Not approved")).toBeNull();
  });

  it("falls back to a team member when the name is null, and asks for no members list", async () => {
    const fetchMock = mockApi(
      routes({}, makeEstimate({ status: "reviewed", reviewed_by: ids.user, reviewed_by_name: null, reviewed_at: "2026-10-20T08:00:00Z" })),
      estimator,
    );
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/Reviewed by a team member/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "GET", "/api/v1/members")).toHaveLength(0);
  });

  it("makes no estimate request when the tender has no estimate", async () => {
    const fetchMock = mockApi(routes({ [`GET ${T}/estimates`]: () => respond(200, []) }), reviewer);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/no estimate yet/i);
    const urls = fetchMock.mock.calls.map(([u]) => String(u).split("?")[0]);
    expect(urls.filter((u) => u.startsWith("/api/v1/estimates"))).toEqual([]);
  });

  it("marks a reviewed estimate as not approved, without a Draft label", async () => {
    mockApi(routes({}, makeEstimate({ status: "reviewed", reviewed_by: ids.user, reviewed_at: "2026-10-20T08:00:00Z" })), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(screen.getByText("Reviewed")).toBeInTheDocument();
    expect(screen.getByText("Not approved")).toBeInTheDocument();
    expect(screen.queryByText("Draft")).toBeNull();
    expect(screen.getByRole("group", { name: "Estimate actions" })).toBeInTheDocument();
    expect(document.querySelector("input[type=text]")).toBeNull();
  });

  it("lets an estimator edit the settings of a draft", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeInTheDocument();
  });

  it("shows a reviewer everything and no controls", async () => {
    mockApi(routes(), reviewer);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(screen.getByText("Total inc VAT")).toBeInTheDocument();
    expect(document.querySelector("input, textarea, button[type=submit]")).toBeNull();
    expect(screen.queryByRole("button", { name: /save settings/i })).toBeNull();
  });

  it("shows 0.00 for an estimate with all lines excluded", async () => {
    const zero = { subtotal_cost: "0.00", markup_total: "0.00", subtotal_ex_vat: "0.00", vat_total: "0.00", total_inc_vat: "0.00" };
    const e = makeEstimate({ priced: 0, excluded: 3, totals: zero });
    mockApi(routes({}, e, LINES.map((l) => ({ ...l, status: "excluded" as const }))), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(screen.getAllByText("ZAR 0.00")).toHaveLength(5);
    expect(document.body.textContent).not.toMatch(/NaN/);
  });

  it("shows a plain empty state for an estimate with no lines", async () => {
    const e = makeEstimate({ priced: 0, excluded: 0, unresolved: 0, changed: 0, incomplete: false, totals: null });
    mockApi(routes({}, e, []), estimator);
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/has no BoQ lines/i)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN/);
  });

  it("sends the status filter to the server", async () => {
    const fetchMock = mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    await userEvent.selectOptions(screen.getByLabelText("Show"), "unresolved");
    await waitFor(() => expect(String(callsTo(fetchMock, "GET", `${E}/lines`).at(-1)?.[0])).toContain("status=unresolved"));
  });

  it("loads more lines when a full page came back", async () => {
    const page = Array.from({ length: 100 }, (_, i) =>
      makeEstimateLine({ id: `00000000-0000-4000-8000-${String(1000 + i).padStart(12, "0")}`, description: `Item ${i}`, position: i }),
    );
    const fetchMock = mockApi(routes({}, draft, page), estimator);
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more lines" }));
    await waitFor(() => expect(String(callsTo(fetchMock, "GET", `${E}/lines`).at(-1)?.[0])).toContain("offset=100"));
  });

  it("offers Create estimate when the tender has none", async () => {
    const fetchMock = mockApi(
      routes({
        [`GET ${T}/estimates`]: () => respond(200, []),
        [`GET /api/v1/pricing-defaults`]: () => respond(200, { currency: "ZAR" }),
        [`POST ${T}/estimates`]: () => respond(201, draft),
      }),
      estimator,
    );
    renderSignedIn(<EstimateView />);
    await userEvent.click(await screen.findByRole("button", { name: "Create estimate" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${T}/estimates`)).toHaveLength(1));
  });

  it("gives no create button to a reviewer", async () => {
    mockApi(routes({ [`GET ${T}/estimates`]: () => respond(200, []) }), reviewer);
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/no estimate yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create estimate" })).toBeNull();
  });

  it("explains missing pricing defaults, and links admins to the pricing page", async () => {
    mockApi(
      routes({
        [`GET ${T}/estimates`]: () => respond(200, []),
        [`GET /api/v1/pricing-defaults`]: () => respond(404, errorBody("pricing_defaults_missing", "none")),
        [`POST ${T}/estimates`]: () => respond(409, errorBody("pricing_defaults_missing", "none")),
      }),
      admin,
    );
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/Save the pricing defaults first, then create the estimate\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /pricing defaults/i })).toHaveAttribute("href", "/settings/pricing");
  });

  it("does not link an estimator to the pricing page", async () => {
    mockApi(
      routes({
        [`GET ${T}/estimates`]: () => respond(200, []),
        [`GET /api/v1/pricing-defaults`]: () => respond(404, errorBody("pricing_defaults_missing", "none")),
      }),
      estimator,
    );
    renderSignedIn(<EstimateView />);
    expect(await screen.findByText(/Save the pricing defaults first, then create the estimate\./)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /pricing defaults/i })).toBeNull();
  });
});

describe("ErrorNotice", () => {
  it("shows the plain words of a frozen-estimate conflict", async () => {
    mockApi({}, estimator);
    renderSignedIn(<ErrorNotice error={new ApiError(409, "estimate_frozen", "frozen")} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("This estimate is no longer a draft");
  });

  it("lists the blockers of estimate_not_ready in plain words", async () => {
    const error = new ApiError(409, "estimate_not_ready", "x", {
      blockers: [{ line_id: "a", code: "unresolved" }, { line_id: null, code: "no_lines" }],
    });
    mockApi({}, estimator);
    renderSignedIn(<ErrorNotice error={error} />);
    expect(await screen.findByText("Some lines still have no price.")).toBeInTheDocument();
    expect(screen.getByText("This estimate has no BoQ lines to price.")).toBeInTheDocument();
  });
});
