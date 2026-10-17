import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeMatchLine, makeMatchSuggestion, makeQuotation, makeTender } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useParams: () => ({ id: ids.tender }),
}));

import { ComparisonView } from "./comparison-view";

afterEach(() => vi.unstubAllGlobals());

const LIST = `/api/v1/tenders/${ids.tender}/match-suggestions`;
const CONFIRM_CLEAR = `/api/v1/tenders/${ids.tender}/match-suggestions/confirm-clear`;
const estimator = meWith(["read", "review_data"], "estimator");
const reviewer = meWith(["read"], "reviewer");

const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const sug = (n: number, over = {}) => makeMatchSuggestion({ id: ID(100 + n), ...over });
const line = (n: number, section: string | null, suggestions = [sug(n)]) =>
  makeMatchLine({
    boq: { id: ID(200 + n), item_no: `${n}.1`, section, description: `Item ${n}`, unit: "no", quantity: "1.0000" },
    suggestions,
  });

function routes(over: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    [`GET /api/v1/tenders/${ids.tender}`]: () => respond(200, makeTender()),
    [`GET /api/v1/tenders/${ids.tender}/quotations`]: () =>
      respond(200, [makeQuotation(), makeQuotation({ id: ID(41), supplier_id: ID(31), supplier_name: "Volt Traders" })]),
    [`GET ${LIST}`]: () =>
      respond(200, [
        line(1, "Lighting", [
          sug(1, { supplier: { id: ID(30), name: "Bright Sparks" } }),
          sug(2, {
            supplier: { id: ID(31), name: "Volt Traders" },
            quotation_item: { ...makeMatchSuggestion().quotation_item, unit_price: "90.0000" },
          }),
        ]),
        line(2, "Lighting", []),
        line(3, "Cabling", [sug(3, { classification: "ambiguous" })]),
      ]),
    ...over,
  };
}

describe("ComparisonView", () => {
  it("groups lines under section headings in API order, with an empty sentence", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ComparisonView />);
    const headings = await screen.findAllByRole("heading", { level: 2 });
    expect(headings.map((h) => h.textContent)).toEqual(["Lighting", "Cabling"]);
    expect(screen.getByText("No supplier quote matches this line.")).toBeInTheDocument();
  });

  it("lists suppliers in API order with no price highlight or wording", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ComparisonView />);
    await screen.findByText("Unit price: 90.0000");
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Unit price: 125.5000")).toBeLessThan(text.indexOf("Unit price: 90.0000"));
    expect(document.querySelector("[data-best], [data-lowest], [data-cheapest]")).toBeNull();
    expect(text).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });

  it("sends each filter to the server, restarting from offset 0", async () => {
    const fetchMock = mockApi(routes(), estimator);
    renderSignedIn(<ComparisonView />);
    await screen.findByText("Unit price: 90.0000");
    const last = () => String(callsTo(fetchMock, "GET", LIST).at(-1)?.[0]);
    await userEvent.selectOptions(screen.getByLabelText("Classification"), "clear");
    await waitFor(() => expect(last()).toContain("classification=clear"));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "suggested");
    await waitFor(() => expect(last()).toContain("status=suggested"));
    await userEvent.selectOptions(screen.getByLabelText("Supplier"), ID(31));
    await waitFor(() => expect(last()).toContain(`supplier_id=${ID(31)}`));
    await userEvent.click(screen.getByLabelText("Only lines with a suggestion"));
    await waitFor(() => expect(last()).toContain("only_with_suggestions=true"));
    expect(last()).toContain("offset=0");
  });

  it("offers Load more only after a full page and asks for offset=100", async () => {
    const full = Array.from({ length: 100 }, (_, i) => line(i + 1, "Lighting", []));
    const fetchMock = mockApi(routes({ [`GET ${LIST}`]: () => respond(200, full) }), estimator);
    renderSignedIn(<ComparisonView />);
    await userEvent.click(await screen.findByRole("button", { name: "Load more lines" }));
    await waitFor(() => expect(String(callsTo(fetchMock, "GET", LIST).at(-1)?.[0])).toContain("offset=100"));
  });

  it("has no Load more after a short page", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ComparisonView />);
    await screen.findByText("Unit price: 90.0000");
    expect(screen.queryByRole("button", { name: "Load more lines" })).toBeNull();
  });

  it("confirms all clear matches, counting only clear suggested ones, and reports the server counts", async () => {
    const fetchMock = mockApi(
      routes({ [`POST ${CONFIRM_CLEAR}`]: () => respond(200, { confirmed: 2, skipped: 0 }) }),
      estimator,
    );
    renderSignedIn(<ComparisonView />);
    const button = await screen.findByRole("button", { name: "Confirm all clear matches (2)" });
    await userEvent.click(button);
    expect(await screen.findByText("Confirmed 2, skipped 0")).toBeInTheDocument();
    expect(callsTo(fetchMock, "POST", CONFIRM_CLEAR)).toHaveLength(1);
  });

  it("disables confirm-all when nothing is clear and open", async () => {
    mockApi(routes({ [`GET ${LIST}`]: () => respond(200, [line(1, "A", [sug(1, { classification: "ambiguous" })])]) }), estimator);
    renderSignedIn(<ComparisonView />);
    expect(await screen.findByRole("button", { name: "Confirm all clear matches (0)" })).toBeDisabled();
  });

  it("disables confirm-all while it runs", async () => {
    let release: (r: Response) => void = () => {};
    mockApi(routes({ [`POST ${CONFIRM_CLEAR}`]: () => new Promise<Response>((r) => (release = r)) }), estimator);
    renderSignedIn(<ComparisonView />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm all clear matches (2)" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Confirm all clear matches/ })).toBeDisabled());
    release(respond(200, { confirmed: 2, skipped: 0 }));
    await screen.findByText("Confirmed 2, skipped 0");
  });

  it("shows a refusal from confirm-all", async () => {
    mockApi(routes({ [`POST ${CONFIRM_CLEAR}`]: () => respond(409, errorBody("tender_archived", "archived")) }), estimator);
    renderSignedIn(<ComparisonView />);
    await userEvent.click(await screen.findByRole("button", { name: "Confirm all clear matches (2)" }));
    expect(await screen.findByText("This tender is archived, so it is read-only.")).toBeInTheDocument();
  });

  it("starts matching again", async () => {
    const fetchMock = mockApi(
      routes({ [`POST /api/v1/tenders/${ids.tender}/match`]: () => respond(202, { id: ids.job }) }),
      estimator,
    );
    renderSignedIn(<ComparisonView />);
    await userEvent.click(await screen.findByRole("button", { name: "Run matching again" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `/api/v1/tenders/${ids.tender}/match`)).toHaveLength(1));
  });

  it("shows no controls to a reviewer but still lists the lines", async () => {
    mockApi(routes(), reviewer);
    renderSignedIn(<ComparisonView />);
    await screen.findByText("Unit price: 90.0000");
    expect(screen.queryByRole("button", { name: /Confirm all/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run matching again" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("is read-only for an archived tender", async () => {
    mockApi(routes({ [`GET /api/v1/tenders/${ids.tender}`]: () => respond(200, makeTender({ status: "archived" })) }), estimator);
    renderSignedIn(<ComparisonView />);
    await screen.findByText("Unit price: 90.0000");
    expect(screen.queryByRole("button", { name: /Confirm all/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Run matching again" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("says the tender was not found on a 404", async () => {
    mockApi(routes({ [`GET /api/v1/tenders/${ids.tender}`]: () => respond(404, errorBody("not_found", "no")) }), estimator);
    renderSignedIn(<ComparisonView />);
    expect(await screen.findByText("This tender was not found.")).toBeInTheDocument();
  });

  it("summarises the loaded lines only, and says so", async () => {
    mockApi(routes(), estimator);
    renderSignedIn(<ComparisonView />);
    const summary = await screen.findByText(/Loaded: 3 lines/);
    expect(summary).toHaveTextContent("1 with a clear match");
    expect(summary).toHaveTextContent("1 needing a decision");
    expect(summary).toHaveTextContent("0 confirmed");
  });
});
