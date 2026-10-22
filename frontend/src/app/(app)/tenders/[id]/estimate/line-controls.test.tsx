import { screen, waitFor, within } from "@testing-library/react";
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
const reviewer = meWith(["read"], "reviewer");

const T = `/api/v1/tenders/${ids.tender}`;
const draft = makeEstimate();
const E = `/api/v1/estimates/${draft.id}`;
const L1 = "00000000-0000-4000-8000-000000000601";
const L2 = "00000000-0000-4000-8000-000000000602";
const L3 = "00000000-0000-4000-8000-000000000603";

const summaryOf = (e: ReturnType<typeof makeEstimate>) => ({
  id: e.id, tender_id: e.tender_id, version: e.version, status: e.status, currency: e.currency,
  created_at: e.created_at, reviewed_at: e.reviewed_at, approved_at: e.approved_at,
  is_current_approved: e.status === "approved", totals: e.totals,
});

const cand = (n: number, name: string, price: string, warnings: string[] = []) => ({
  match_id: `00000000-0000-4000-8000-0000000008${n}0`,
  quotation_item_id: `00000000-0000-4000-8000-0000000009${n}0`,
  supplier_id: `00000000-0000-4000-8000-0000000007${n}0`,
  supplier_name: name, unit_price: price, currency: "ZAR", includes_vat: false, warnings,
});
const ZULU = cand(1, "Zulu Supplies", "125.5000");
const ALPHA = cand(2, "Alpha Traders", "90.0000", ["unit_mismatch"]);

const LINES = [
  makeEstimateLine({ id: L1, description: "LED panel", candidates: [ZULU, ALPHA], labour_rate: "12.5000", markup_override_percent: "7.50" }),
  makeEstimateLine({ id: L2, item_no: "1.2", description: "Provisional sum", quantity: null, flags: ["quantity_missing"] }),
  makeEstimateLine({ id: L3, item_no: "2.1", description: "Cable tray", status: "changed", flags: ["source_changed"], price_source: "supplier" }),
];

function routes(over: Record<string, () => Response | Promise<Response>> = {}, lines = LINES, estimate = draft) {
  return {
    [`GET ${T}`]: () => respond(200, makeTender()),
    [`GET ${T}/estimates`]: () => respond(200, [summaryOf(estimate)]),
    [`GET /api/v1/estimates/${estimate.id}`]: () => respond(200, estimate),
    [`GET /api/v1/estimates/${estimate.id}/lines`]: () => respond(200, lines),
    ...over,
  };
}

const rowOf = (text: string) => screen.getByText(new RegExp(text)).closest("li") as HTMLElement;
const bodyOf = (call: unknown[] | undefined) => JSON.parse(String((call?.[1] as RequestInit).body));
const PUT = (id: string) => `/api/v1/estimate-lines/${id}`;

describe("line controls", () => {
  it("sends match_suggestion_id when a candidate is chosen, with the current rates, and nothing is pre-selected", async () => {
    const fetchMock = mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(200, LINES[0]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    expect(row.querySelectorAll("input[type=radio]:checked")).toHaveLength(0);
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "PUT", PUT(L1))[0])).toEqual({
      match_suggestion_id: ZULU.match_id,
      labour_rate: "12.5000",
      markup_override_percent: "7.50",
      unit_mismatch_acknowledged: false,
    });
  });

  it("keeps the candidate order as sent and marks none as cheapest", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const names = within(rowOf("LED panel")).getAllByRole("radio").map((r) => r.closest("label")?.textContent ?? "");
    expect(names[0]).toMatch(/Zulu/);
    expect(names[1]).toMatch(/Alpha/);
    expect(document.body.textContent).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });

  it("needs the acknowledge tick before a unit-mismatch candidate can be chosen", async () => {
    const fetchMock = mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(200, LINES[0]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    const radio = within(row).getByRole("radio", { name: /Alpha Traders/ });
    expect(radio).toBeDisabled();
    await userEvent.click(within(row).getByRole("checkbox", { name: /different unit/i }));
    expect(radio).toBeEnabled();
    await userEvent.click(radio);
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "PUT", PUT(L1))[0])).toMatchObject({
      match_suggestion_id: ALPHA.match_id,
      unit_mismatch_acknowledged: true,
      labour_rate: "12.5000",
      markup_override_percent: "7.50",
    });
  });

  it("sends the manual price as a string from a text input", async () => {
    const fetchMock = mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(200, LINES[0]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    const input = within(row).getByLabelText("Manual unit price");
    expect(input).toHaveAttribute("type", "text");
    await userEvent.type(input, "99.5");
    await userEvent.click(within(row).getByRole("button", { name: "Use manual price" }));
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(1));
    const body = bodyOf(callsTo(fetchMock, "PUT", PUT(L1))[0]);
    expect(body.manual_unit_price).toBe("99.5");
    expect(body.labour_rate).toBe("12.5000");
    expect(body.markup_override_percent).toBe("7.50");
  });

  it.each(["abc", "0", "-3", "1.23456", ""])("sends nothing for the invalid manual price %j", async (text) => {
    const fetchMock = mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    if (text) await userEvent.type(within(row).getByLabelText("Manual unit price"), text);
    await userEvent.click(within(row).getByRole("button", { name: "Use manual price" }));
    expect(await within(row).findByRole("alert")).toBeInTheDocument();
    expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(0);
  });

  it("sends nothing when excluding without a reason, and the reason when given", async () => {
    const fetchMock = mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(200, LINES[0]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    await userEvent.click(within(row).getByRole("button", { name: "Exclude" }));
    expect(await within(row).findByRole("alert")).toHaveTextContent(/reason/i);
    expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(0);
    await userEvent.type(within(row).getByLabelText("Reason for excluding"), "Client supplies it");
    await userEvent.click(within(row).getByRole("button", { name: "Exclude" }));
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "PUT", PUT(L1))[0])).toMatchObject({
      exclude_reason: "Client supplies it",
      labour_rate: "12.5000",
      markup_override_percent: "7.50",
    });
  });

  it("sends nothing for invalid labour or markup text", async () => {
    const fetchMock = mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    const labour = within(row).getByLabelText("Labour rate");
    await userEvent.clear(labour);
    await userEvent.type(labour, "1.23456");
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    expect(await within(row).findByRole("alert")).toHaveTextContent(/labour rate/i);
    await userEvent.clear(labour);
    await userEvent.type(labour, "5");
    const markup = within(row).getByLabelText("Markup override %");
    await userEvent.clear(markup);
    await userEvent.type(markup, "1001");
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    expect(await within(row).findByRole("alert")).toHaveTextContent(/markup/i);
    expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(0);
  });

  it("clears the rates by sending null for emptied fields", async () => {
    const fetchMock = mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(200, LINES[0]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    await userEvent.clear(within(row).getByLabelText("Labour rate"));
    await userEvent.clear(within(row).getByLabelText("Markup override %"));
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT(L1))).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "PUT", PUT(L1))[0])).toMatchObject({ labour_rate: null, markup_override_percent: null });
  });

  it("offers only Exclude on a line without a quantity", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/Provisional sum/);
    const row = rowOf("Provisional sum");
    expect(within(row).getByRole("button", { name: "Exclude" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Use manual price" })).toBeNull();
    expect(within(row).queryByLabelText("Manual unit price")).toBeNull();
    expect(within(row).queryByLabelText("Labour rate")).toBeNull();
    expect(within(row).queryByRole("radio")).toBeNull();
  });

  it("offers Refresh only on a line whose source changed, and posts to refresh", async () => {
    const fetchMock = mockApi(routes({ [`POST ${PUT(L3)}/refresh`]: () => respond(200, LINES[2]) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/Cable tray/);
    expect(within(rowOf("LED panel")).queryByRole("button", { name: "Refresh" })).toBeNull();
    await userEvent.click(within(rowOf("Cable tray")).getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${PUT(L3)}/refresh`)).toHaveLength(1));
  });

  it("rolls back and reloads the lines on a stale_match", async () => {
    const fetchMock = mockApi(
      routes({ [`PUT ${PUT(L1)}`]: () => respond(409, errorBody("stale_match", "stale")) }),
      estimator,
    );
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    const before = callsTo(fetchMock, "GET", `${E}/lines`).length;
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    expect(await within(row).findByText(/out of date\. Choose it again/)).toBeInTheDocument();
    await waitFor(() => expect(callsTo(fetchMock, "GET", `${E}/lines`).length).toBeGreaterThan(before));
    expect(within(rowOf("LED panel")).getByRole("radio", { name: /Zulu Supplies/ })).not.toBeChecked();
  });

  it("shows the plain frozen message when the estimate is no longer a draft", async () => {
    mockApi(routes({ [`PUT ${PUT(L1)}`]: () => respond(409, errorBody("estimate_frozen", "x")) }), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    const row = rowOf("LED panel");
    await userEvent.click(within(row).getByRole("radio", { name: /Zulu Supplies/ }));
    expect(await within(row).findByText(/no longer a draft/)).toBeInTheDocument();
  });

  it("gives a reviewer no line controls", async () => {
    mockApi(routes(), reviewer);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(document.querySelector("input, textarea")).toBeNull();
    expect(screen.queryByRole("button", { name: /exclude|refresh|use manual/i })).toBeNull();
  });

  it("gives a frozen estimate no line controls", async () => {
    const frozen = makeEstimate({ status: "reviewed", reviewed_by: ids.user, reviewed_at: "2026-10-20T08:00:00Z" });
    mockApi(routes({}, LINES, frozen), estimator);
    renderSignedIn(<EstimateView />);
    await screen.findByText(/LED panel/);
    expect(document.querySelector("input[type=text], input[type=radio]")).toBeNull();
    expect(screen.queryByRole("button", { name: /exclude|refresh|use manual/i })).toBeNull();
  });
});
