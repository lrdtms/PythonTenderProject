import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeMatchSuggestion } from "@/test/fixtures";
import { callsTo, createTestClient, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
}));

import { CandidateRow } from "./candidate-row";

afterEach(() => vi.unstubAllGlobals());

const estimator = meWith(["read", "review_data"], "estimator");
const reviewer = meWith(["read"], "reviewer");
const SID = "00000000-0000-4000-8000-000000000060";

function mount(over: Parameters<typeof makeMatchSuggestion>[0], canReview = true, client = createTestClient()) {
  return renderSignedIn(
    <ul>
      <CandidateRow suggestion={makeMatchSuggestion(over)} tenderId={ids.tender} canReview={canReview} />
    </ul>,
    client,
  );
}

describe("CandidateRow", () => {
  it("shows supplier, description, SKU, unit and the price string exactly", async () => {
    mockApi({}, estimator);
    mount({
      supplier: { id: "s1", name: "Volt Traders" },
      quotation_item: { ...makeMatchSuggestion().quotation_item, sku: "LP-600", unit_price: "54917.00" },
    });
    expect(await screen.findByText("Volt Traders")).toBeInTheDocument();
    expect(screen.getByText("LED panel 600x600 40W")).toBeInTheDocument();
    expect(screen.getByText("SKU LP-600")).toBeInTheDocument();
    expect(screen.getByText(/Unit: no/)).toBeInTheDocument();
    expect(screen.getByText("Unit price: ZAR 54917.00 · excl. VAT")).toBeInTheDocument();
  });

  it("says 'Price missing' when there is no price", async () => {
    mockApi({}, estimator);
    mount({ quotation_item: { ...makeMatchSuggestion().quotation_item, unit_price: null } });
    expect(await screen.findByText("Unit price: Price missing")).toBeInTheDocument();
  });

  it("explains an ambiguous match in words", async () => {
    mockApi({}, estimator);
    mount({ classification: "ambiguous", evidence: { warnings: ["unit_mismatch", "spec_conflict"] } });
    expect(await screen.findByText("Needs a decision")).toBeInTheDocument();
    expect(screen.getAllByText("Unit differs").length).toBeGreaterThan(0);
    expect(screen.getByText("Specification differs")).toBeInTheDocument();
    expect(screen.queryByText("Unit differs, and specification differs.")).not.toBeInTheDocument();
  });

  it("gives the sentence only when there are no warnings", async () => {
    mockApi({}, estimator);
    mount({ classification: "ambiguous", evidence: { warnings: [] } });
    expect(await screen.findByText("Several close candidates from this supplier.")).toBeInTheDocument();
  });

  it("shows currency and VAT basis in words, never formatted", async () => {
    mockApi({}, estimator);
    const base = makeMatchSuggestion().quotation_item;
    const a = mount({ quotation_item: { ...base, unit_price: "125.5000", currency: "ZAR", prices_include_vat: true } });
    expect(await screen.findByText("Unit price: ZAR 125.5000 · incl. VAT")).toBeInTheDocument();
    a.unmount();
    const b = mount({ quotation_item: { ...base, unit_price: "125.5000", currency: "USD", prices_include_vat: null } });
    expect(await screen.findByText("Unit price: USD 125.5000 · VAT not stated")).toBeInTheDocument();
    b.unmount();
    mount({ quotation_item: { ...base, unit_price: "125.5000", currency: null, prices_include_vat: false } });
    expect(await screen.findByText("Unit price: 125.5000 · excl. VAT · Currency not stated")).toBeInTheDocument();
  });

  it("lists the evidence rows under 'Why this match'", async () => {
    mockApi({}, estimator);
    mount({ score: 0.87, evidence: { signals: { text: 0.9, spec: 0.5 }, unit: { state: "equal" } } });
    const details = (await screen.findByText("Why this match")).closest("details") as HTMLElement;
    expect(within(details).getByText("87%")).toBeInTheDocument();
    expect(within(details).getByText("Text similarity")).toBeInTheDocument();
    expect(within(details).getByText("Same unit")).toBeInTheDocument();
  });

  it("offers the right buttons for each status", async () => {
    mockApi({}, estimator);
    const names = () => screen.getAllByRole("button").map((b) => b.textContent);
    const a = mount({ status: "suggested" });
    await screen.findByRole("button", { name: "Confirm" });
    expect(names()).toEqual(["Confirm", "Reject"]);
    a.unmount();
    const b = mount({ status: "confirmed" });
    await screen.findByRole("button", { name: "Reset" });
    expect(names()).toEqual(["Reject", "Reset"]);
    b.unmount();
    mount({ status: "rejected" });
    await screen.findByRole("button", { name: "Confirm" });
    expect(names()).toEqual(["Confirm", "Reset"]);
  });

  it("shows no buttons to a reviewer", async () => {
    mockApi({}, reviewer);
    mount({}, false);
    await screen.findByText("Bright Sparks");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("names who decided and when", async () => {
    mockApi({}, estimator);
    mount({ status: "confirmed", decided_by_name: "Thandi", decided_at: "2026-10-16T08:00:00Z" });
    expect(await screen.findByText(/Decided by Thandi on/)).toBeInTheDocument();
  });

  it("posts the confirmation to the suggestion", async () => {
    const fetchMock = mockApi(
      { [`POST /api/v1/match-suggestions/${SID}/confirm`]: () => respond(200, makeMatchSuggestion({ status: "confirmed" })) },
      estimator,
    );
    mount({});
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `/api/v1/match-suggestions/${SID}/confirm`)).toHaveLength(1));
  });

  it("shows a conflict on that row only", async () => {
    mockApi(
      { [`POST /api/v1/match-suggestions/${SID}/confirm`]: () => respond(409, errorBody("match_conflict", "conflict")) },
      estimator,
    );
    renderSignedIn(
      <ul>
        <CandidateRow suggestion={makeMatchSuggestion()} tenderId={ids.tender} canReview />
        <CandidateRow
          suggestion={makeMatchSuggestion({ id: "00000000-0000-4000-8000-000000000061", supplier: { id: "s2", name: "Other Co" } })}
          tenderId={ids.tender}
          canReview
        />
      </ul>,
    );
    const buttons = await screen.findAllByRole("button", { name: "Confirm" });
    await userEvent.click(buttons[0]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Another candidate from this supplier is already confirmed");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Confirm" })[1]).toBeEnabled();
  });

  it("reloads the list after a stale_match refusal", async () => {
    mockApi(
      { [`POST /api/v1/match-suggestions/${SID}/confirm`]: () => respond(409, errorBody("stale_match", "stale")) },
      estimator,
    );
    const client = createTestClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    mount({}, true, client);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This quotation was replaced");
    expect(spy).toHaveBeenCalledWith({ queryKey: ["matches", ids.tender] });
  });

  it("clears an old error when another action succeeds", async () => {
    mockApi(
      {
        [`POST /api/v1/match-suggestions/${SID}/confirm`]: () => respond(409, errorBody("match_conflict", "conflict")),
        [`POST /api/v1/match-suggestions/${SID}/reject`]: () => respond(200, makeMatchSuggestion({ status: "rejected" })),
      },
      estimator,
    );
    mount({});
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await screen.findByRole("alert");
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("shows the newest error, not the older one", async () => {
    mockApi(
      {
        [`POST /api/v1/match-suggestions/${SID}/confirm`]: () => respond(409, errorBody("match_conflict", "conflict")),
        [`POST /api/v1/match-suggestions/${SID}/reject`]: () => respond(409, errorBody("try_again", "again")),
      },
      estimator,
    );
    mount({});
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    await screen.findByText(/already confirmed/);
    await userEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByText("Something changed at the same time. Try again.")).toBeInTheDocument();
    expect(screen.queryByText(/already confirmed/)).toBeNull();
  });

  it("disables the actions while the page is busy", async () => {
    mockApi({}, estimator);
    renderSignedIn(
      <ul>
        <CandidateRow suggestion={makeMatchSuggestion()} tenderId={ids.tender} canReview busy />
      </ul>,
    );
    expect(await screen.findByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("never uses ranking words", async () => {
    mockApi({}, estimator);
    mount({
      status: "confirmed",
      score: 0.91,
      classification: "ambiguous",
      evidence: {
        warnings: ["unit_mismatch", "quote_shared", "accessory_word"],
        signals: { text: 0.8, spec: 0.6 },
        unit: { state: "mismatch" },
        spec: { matched: ["voltage"], conflicts: ["power"], boq_only: ["colour"], quote_only: ["ip_rating"] },
        valid_until: "2026-12-31",
      },
    });
    await screen.findByText("Bright Sparks");
    expect(document.body.textContent).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });
});
