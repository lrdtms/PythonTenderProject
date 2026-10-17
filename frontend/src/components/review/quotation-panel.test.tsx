import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { formatDate } from "@/lib/format";
import { ids, makeQuotation, makeSupplier } from "@/test/fixtures";
import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

import { QuotationPanel } from "./quotation-panel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
afterEach(() => vi.unstubAllGlobals());

const reviewer = meWith(["read"], "reviewer");
const QID = makeQuotation().id;
const QPATH = `/api/v1/quotations/${QID}`;
const OTHER = "00000000-0000-4000-8000-000000000031";

function routes(quotation = makeQuotation({ document_version_id: ids.version }), over = {}) {
  return {
    [`GET /api/v1/tenders/${ids.tender}/quotations`]: () => respond(200, [quotation]),
    "GET /api/v1/suppliers": () =>
      respond(200, [makeSupplier(), makeSupplier({ id: OTHER, name: "Volt Traders" })]),
    ...over,
  };
}

function renderPanel(archived = false) {
  return renderSignedIn(<QuotationPanel tenderId={ids.tender} versionId={ids.version} archived={archived} />);
}

const bodyOf = (fetchMock: ReturnType<typeof mockApi>) =>
  JSON.parse((callsTo(fetchMock, "PATCH", QPATH)[0][1] as RequestInit).body as string);

describe("QuotationPanel", () => {
  it("shows the header in plain words", async () => {
    mockApi(routes());
    renderPanel();
    expect(await screen.findByText("Bright Sparks")).toBeInTheDocument();
    expect(screen.getByText(/Q-100/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(formatDate("2026-10-01")))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(formatDate("2026-12-31")))).toBeInTheDocument();
    expect(screen.getByText(/ZAR/)).toBeInTheDocument();
    expect(screen.getByText("Prices exclude VAT")).toBeInTheDocument();
  });

  it("says when VAT is not stated and shows header flags as warnings", async () => {
    mockApi(routes(makeQuotation({ document_version_id: ids.version, prices_include_vat: null, flags: ["NO_CURRENCY", "VAT_UNKNOWN", "NO_VALIDITY"] })));
    renderPanel();
    expect(await screen.findByText("VAT not stated")).toBeInTheDocument();
    expect(screen.getByText(/currency could not be read/)).toBeInTheDocument();
    expect(screen.getByText(/does not say whether prices include VAT/)).toBeInTheDocument();
    expect(screen.getByText(/validity date could not be read/)).toBeInTheDocument();
  });

  it("gives a reviewer no Edit button", async () => {
    mockApi(routes(), reviewer);
    renderPanel();
    await screen.findByText("Bright Sparks");
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
  });

  it("hides Edit when archived", async () => {
    mockApi(routes());
    renderPanel(true);
    await screen.findByText("Bright Sparks");
    expect(screen.queryByRole("button", { name: "Edit details" })).toBeNull();
  });

  it("upper-cases the currency and sends only that field", async () => {
    const fetchMock = mockApi(routes(undefined, { [`PATCH ${QPATH}`]: () => respond(200, makeQuotation({ currency: "USD" })) }));
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    const currency = screen.getByLabelText("Currency");
    await userEvent.clear(currency);
    await userEvent.type(currency, "usd");
    expect(currency).toHaveValue("USD");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", QPATH)).toHaveLength(1));
    expect(bodyOf(fetchMock)).toEqual({ currency: "USD" });
  });

  it("sends supplier_id when the supplier is switched", async () => {
    const fetchMock = mockApi(routes(undefined, { [`PATCH ${QPATH}`]: () => respond(200, makeQuotation()) }));
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    expect(screen.getByText(/moves its matches/)).toBeInTheDocument();
    await userEvent.selectOptions(await screen.findByLabelText("Supplier"), OTHER);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", QPATH)).toHaveLength(1));
    expect(bodyOf(fetchMock)).toEqual({ supplier_id: OTHER });
  });

  it("sends null when VAT is set to not stated", async () => {
    const fetchMock = mockApi(routes(undefined, { [`PATCH ${QPATH}`]: () => respond(200, makeQuotation()) }));
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    await userEvent.click(screen.getByRole("radio", { name: "VAT not stated" }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", QPATH)).toHaveLength(1));
    expect(bodyOf(fetchMock)).toEqual({ prices_include_vat: null });
  });

  it("shows the mapped match_conflict message and keeps the form open", async () => {
    mockApi(routes(undefined, { [`PATCH ${QPATH}`]: () => respond(409, errorBody("match_conflict", "conflict")) }));
    renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Edit details" }));
    await userEvent.selectOptions(await screen.findByLabelText("Supplier"), OTHER);
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/already confirmed for this line/);
    expect(screen.getByLabelText("Supplier")).toBeInTheDocument();
  });
});
