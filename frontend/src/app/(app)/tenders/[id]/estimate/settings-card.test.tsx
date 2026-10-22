import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeEstimate } from "@/test/fixtures";
import { callsTo, errorBody, mockApi, renderWithClient, respond } from "@/test/render";

import { SettingsCard } from "./settings-card";

afterEach(() => vi.unstubAllGlobals());

const est = makeEstimate();
const PATH = `/api/v1/estimates/${est.id}`;

function setup(over = {}, editable = true, routes = {}) {
  const fetchMock = mockApi({ [`PATCH ${PATH}`]: () => respond(200, { ...est, ...over }), ...routes });
  renderWithClient(<SettingsCard estimate={{ ...est, ...over }} editable={editable} />);
  return fetchMock;
}

describe("SettingsCard", () => {
  it("shows the settings read-only when not editable, with no inputs or buttons", () => {
    setup({}, false);
    expect(screen.getByText("ZAR")).toBeInTheDocument();
    expect(screen.getByText("15.00")).toBeInTheDocument();
    expect(screen.getByText("On cost")).toBeInTheDocument();
    expect(screen.getByText("10.00")).toBeInTheDocument();
    expect(document.querySelector("input, button, select, textarea")).toBeNull();
  });

  it("offers the markup basis choice and uses text inputs, never number", () => {
    setup();
    expect(screen.getByRole("radio", { name: "On cost" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "On selling price" })).not.toBeChecked();
    expect(document.querySelector("input[type=number]")).toBeNull();
  });

  it("sends only the changed fields", async () => {
    const fetchMock = setup();
    await userEvent.clear(screen.getByLabelText("VAT rate (%)"));
    await userEvent.type(screen.getByLabelText("VAT rate (%)"), "14");
    await userEvent.click(screen.getByRole("radio", { name: "On selling price" }));
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(1));
    const body = JSON.parse(String((callsTo(fetchMock, "PATCH", PATH)[0][1] as RequestInit).body));
    expect(body).toEqual({ vat_rate: "14", markup_basis: "selling_price" });
  });

  it.each([
    ["VAT rate (%)", "101", /between 0 and 100/],
    ["VAT rate (%)", "15.123", /at most 2 decimals/],
    ["Default markup (%)", "abc", /as a number/],
    ["Default markup (%)", "1001", /between 0 and 1000/],
  ])("sends nothing when %s is %s", async (label, value, message) => {
    const fetchMock = setup();
    await userEvent.clear(screen.getByLabelText(label));
    await userEvent.type(screen.getByLabelText(label), value);
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(0);
  });

  it("refuses a selling-price markup of 100 or more", async () => {
    const fetchMock = setup();
    await userEvent.click(screen.getByRole("radio", { name: "On selling price" }));
    await userEvent.clear(screen.getByLabelText("Default markup (%)"));
    await userEvent.type(screen.getByLabelText("Default markup (%)"), "100");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByText(/markup is a margin and must be below 100/)).toBeInTheDocument();
    expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(0);
  });

  it("disables the currency with an explanation when the server says it is locked", () => {
    setup({ currency_locked: true });
    expect(screen.getByLabelText("Currency")).toBeDisabled();
    expect(screen.getByText(/cannot be changed while a line has a price/i)).toBeInTheDocument();
  });

  it("allows the currency while the server says it is not locked", () => {
    setup({ priced: 2, currency_locked: false });
    expect(screen.getByLabelText("Currency")).toBeEnabled();
  });

  it("disables the currency after the server reports currency_locked", async () => {
    mockApi({ [`PATCH ${PATH}`]: () => respond(409, errorBody("currency_locked", "locked")) });
    renderWithClient(<SettingsCard estimate={{ ...est, priced: 0 }} editable />);
    await userEvent.clear(screen.getByLabelText("Currency"));
    await userEvent.type(screen.getByLabelText("Currency"), "usd");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(screen.getByLabelText("Currency")).toBeDisabled());
    expect(screen.getByLabelText("Currency")).toHaveValue("ZAR");
    expect(screen.getByRole("alert")).toHaveTextContent(/cannot be changed while a line has a price/i);
  });

  it("sends no request when only the spelling of a number changed", async () => {
    const fetchMock = setup();
    await userEvent.clear(screen.getByLabelText("VAT rate (%)"));
    await userEvent.type(screen.getByLabelText("VAT rate (%)"), "15.0");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(callsTo(fetchMock, "PATCH", PATH)).toHaveLength(0);
    expect(screen.getByLabelText("VAT rate (%)")).toHaveValue("15.00");
  });

  it("shows a reviewed estimate's settings read-only", () => {
    setup({ status: "reviewed" }, false);
    expect(screen.getByText("On cost")).toBeInTheDocument();
    expect(document.querySelector("input, button")).toBeNull();
  });

  it("shows the plain-words message for a 409 estimate_frozen", async () => {
    setup({}, true, { [`PATCH ${PATH}`]: () => respond(409, errorBody("estimate_frozen", "frozen")) });
    await userEvent.clear(screen.getByLabelText("VAT rate (%)"));
    await userEvent.type(screen.getByLabelText("VAT rate (%)"), "14");
    await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This estimate is no longer a draft, so it cannot be changed.");
  });
});
