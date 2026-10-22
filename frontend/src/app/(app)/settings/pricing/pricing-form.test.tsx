import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { callsTo, errorBody, meWith, mockApi, renderSignedIn, respond } from "@/test/render";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));

import { PricingForm } from "./pricing-form";

afterEach(() => vi.unstubAllGlobals());

const admin = meWith(["read", "manage_pricing"], "admin");
const estimator = meWith(["read"], "estimator");
const missing = () => respond(404, errorBody("pricing_defaults_missing", "No defaults."));
const SAVED = {
  currency: "ZAR",
  vat_rate: "15.00",
  markup_basis: "cost",
  default_markup_percent: "10.00",
  updated_at: "2026-10-22T10:00:00Z",
};
const PUT = "/api/v1/pricing-defaults";
const bodyOf = (call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string);

async function fillValid() {
  await userEvent.type(screen.getByLabelText("Currency"), "zar");
  await userEvent.type(screen.getByLabelText("VAT rate (%)"), "15");
  await userEvent.type(screen.getByLabelText("Default markup (%)"), "12.5");
}

describe("PricingForm", () => {
  it("renders empty for an admin when nothing is saved, with no prefilled VAT but a text hint", async () => {
    mockApi({ "GET /api/v1/pricing-defaults": missing }, admin);
    renderSignedIn(<PricingForm />);
    const vat = await screen.findByLabelText("VAT rate (%)");
    expect(vat).toHaveValue("");
    expect(vat).toHaveAttribute("type", "text");
    expect(screen.getByText("15 is the usual South African rate")).toBeInTheDocument();
    expect(screen.getByLabelText("Currency")).toHaveValue("");
    expect(screen.getByLabelText("Default markup (%)")).toHaveAttribute("type", "text");
    expect(screen.getByRole("radio", { name: "On cost" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "On selling price" })).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Save pricing defaults" })).toBeInTheDocument();
  });

  it("saves decimal strings in the exact body shape and confirms", async () => {
    const fetchMock = mockApi(
      {
        "GET /api/v1/pricing-defaults": missing,
        "PUT /api/v1/pricing-defaults": () =>
          respond(200, { ...SAVED, vat_rate: "15", default_markup_percent: "12.5", markup_basis: "selling_price" }),
      },
      admin,
    );
    renderSignedIn(<PricingForm />);
    await screen.findByLabelText("Currency");
    await fillValid();
    await userEvent.click(screen.getByRole("radio", { name: "On selling price" }));
    await userEvent.click(screen.getByRole("button", { name: "Save pricing defaults" }));
    await waitFor(() => expect(callsTo(fetchMock, "PUT", PUT)).toHaveLength(1));
    expect(bodyOf(callsTo(fetchMock, "PUT", PUT)[0])).toEqual({
      currency: "ZAR",
      vat_rate: "15",
      markup_basis: "selling_price",
      default_markup_percent: "12.5",
    });
    expect(await screen.findByText("Pricing defaults saved.")).toBeInTheDocument();
  });

  it("shows saved values for editing", async () => {
    mockApi({ "GET /api/v1/pricing-defaults": () => respond(200, SAVED) }, admin);
    renderSignedIn(<PricingForm />);
    expect(await screen.findByLabelText("Currency")).toHaveValue("ZAR");
    expect(screen.getByLabelText("VAT rate (%)")).toHaveValue("15.00");
  });

  it.each([
    ["a VAT rate above 100", "Currency", "ZAR", "101", "5", "cost", "VAT rate must be between 0 and 100."],
    ["a VAT rate with 3 decimals", "Currency", "ZAR", "15.123", "5", "cost", "VAT rate can have at most 2 decimals."],
    ["markup of 100 on selling price", "Currency", "ZAR", "15", "100", "selling_price", "On selling price the markup is a margin and must be below 100."],
    ["markup above 1000 on cost", "Currency", "ZAR", "15", "1000.01", "cost", "Markup on cost must be between 0 and 1000."],
    ["a 2-letter currency", "Currency", "ZA", "15", "5", "cost", "Currency must be 3 letters, for example ZAR."],
  ])("%s shows a message and sends nothing", async (_n, _l, currency, vat, markup, basis, message) => {
    const fetchMock = mockApi({ "GET /api/v1/pricing-defaults": missing }, admin);
    renderSignedIn(<PricingForm />);
    await userEvent.type(await screen.findByLabelText("Currency"), currency);
    await userEvent.type(screen.getByLabelText("VAT rate (%)"), vat);
    await userEvent.type(screen.getByLabelText("Default markup (%)"), markup);
    if (basis === "selling_price") await userEvent.click(screen.getByRole("radio", { name: "On selling price" }));
    await userEvent.click(screen.getByRole("button", { name: "Save pricing defaults" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(callsTo(fetchMock, "PUT", PUT)).toHaveLength(0);
  });

  it("shows read-only values and no save button to a non-admin", async () => {
    mockApi({ "GET /api/v1/pricing-defaults": () => respond(200, SAVED) }, estimator);
    renderSignedIn(<PricingForm />);
    expect(await screen.findByText("Only an administrator can change pricing defaults.")).toBeInTheDocument();
    expect(await screen.findByText("ZAR")).toBeInTheDocument();
    expect(screen.getByText("On cost")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save pricing defaults" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("tells a non-admin when nothing has been set", async () => {
    mockApi({ "GET /api/v1/pricing-defaults": missing }, estimator);
    renderSignedIn(<PricingForm />);
    expect(await screen.findByText("Pricing defaults have not been set yet. Ask an administrator.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save pricing defaults" })).toBeNull();
  });
});
