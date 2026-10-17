import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ids, makeQuotationItem } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { QuotationRow } from "./quotation-row";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const reviewer = meWith(["read"], "reviewer");
const noop = () => {};
const PATH = "/api/v1/quotation-items/i1";

function renderRow(over = {}, archived = false) {
  const row = makeQuotationItem({ id: "i1", ...over });
  return renderSignedIn(
    <ul>
      <QuotationRow row={row} versionId={ids.version} selected onSelect={noop} archived={archived} />
    </ul>,
  );
}

const bodyOf = (fetchMock: ReturnType<typeof mockApi>) =>
  JSON.parse((callsTo(fetchMock, "PATCH", PATH)[0][1] as RequestInit).body as string);

describe("QuotationRow", () => {
  it("shows state, flags and prices to a reviewer but no buttons", async () => {
    mockApi({}, reviewer);
    renderRow({ flags: ["zero_quantity"], sku: "LP-6060" });
    expect(await screen.findByText("Unreviewed")).toBeInTheDocument();
    expect(screen.getByText("Quantity is zero")).toBeInTheDocument();
    expect(screen.getByText("LP-6060")).toBeInTheDocument();
    expect(screen.getByText(/Price 125\.5000/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("shows Confirm, Edit and Reject to an estimator and confirms", async () => {
    const fetchMock = mockApi({
      [`POST ${PATH}/confirm`]: () => respond(200, makeQuotationItem({ id: "i1", review_status: "confirmed" })),
    });
    renderRow();
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(callsTo(fetchMock, "POST", `${PATH}/confirm`)).toHaveLength(1));
  });

  it("rejects a bad price without sending, then sends only the changed field", async () => {
    const fetchMock = mockApi({
      [`PATCH ${PATH}`]: () => respond(200, makeQuotationItem({ id: "i1", review_status: "corrected", unit_price: "1500.0000" })),
    });
    renderRow();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const price = screen.getByLabelText("Unit price");
    await userEvent.clear(price);
    await userEvent.type(price, "1,500");
    expect(screen.getByRole("alert")).toHaveTextContent(/plain number/);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(0);
    await userEvent.clear(price);
    await userEvent.type(price, "1500");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(1));
    expect(bodyOf(fetchMock)).toEqual({ unit_price: "1500" });
  });

  it("clearing the quantity sends null", async () => {
    const fetchMock = mockApi({
      [`PATCH ${PATH}`]: () => respond(200, makeQuotationItem({ id: "i1", review_status: "corrected", quantity: null })),
    });
    renderRow();
    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.clear(screen.getByLabelText("Quantity"));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(1));
    expect(bodyOf(fetchMock)).toEqual({ quantity: null });
  });

  it("says Price missing for a null price and never shows 0", async () => {
    mockApi({});
    renderRow({ unit_price: null });
    expect(await screen.findByText(/Price missing/)).toBeInTheDocument();
    expect(screen.queryByText(/Price 0/)).toBeNull();
  });

  it("shows the original value of a corrected row", async () => {
    mockApi({});
    renderRow({
      review_status: "corrected",
      unit_price: "130.0000",
      corrected_value: { unit_price: "130.0000" },
      original_value: { unit_price: "125.5000" },
    });
    expect(await screen.findByText(/\(was 125\.5\)/)).toBeInTheDocument();
  });

  it("marks a row replaced by a re-run on 404", async () => {
    mockApi({ [`POST ${PATH}/confirm`]: () => respond(404, errorBody("not_found", "gone")) });
    renderRow();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Replaced by a re-run/);
    expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  });
});
