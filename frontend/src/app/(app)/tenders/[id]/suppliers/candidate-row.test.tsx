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
    expect(screen.getByText("Unit price: 54917.00")).toBeInTheDocument();
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
    expect(screen.getByText("Unit differs, and specification differs.")).toBeInTheDocument();
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

  it("never uses ranking words", async () => {
    mockApi({}, estimator);
    mount({ status: "confirmed" });
    await screen.findByText("Bright Sparks");
    expect(document.body.textContent).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });
});
