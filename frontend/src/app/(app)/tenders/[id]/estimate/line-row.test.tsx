import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeEstimateLine } from "@/test/fixtures";

import { LineRow } from "./line-row";

const cand = (n: number, name: string, price: string | null, over = {}) => ({
  match_id: `00000000-0000-4000-8000-0000000008${n}0`,
  quotation_item_id: `00000000-0000-4000-8000-0000000009${n}0`,
  supplier_id: `00000000-0000-4000-8000-0000000007${n}0`,
  supplier_name: name,
  unit_price: price,
  currency: "ZAR" as string | null,
  includes_vat: false as boolean | null,
  warnings: [],
  ...over,
});

describe("LineRow", () => {
  it("lists candidates in the order sent, selects none and marks no price", () => {
    const line = makeEstimateLine({ candidates: [cand(1, "Zulu Supplies", "125.5000"), cand(2, "Alpha Traders", "90.0000")] });
    render(<ul><LineRow line={line} currency="ZAR" /></ul>);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("Zulu Supplies")).toBeLessThan(text.indexOf("Alpha Traders"));
    expect(screen.getByText("ZAR 125.5000 · excl. VAT")).toBeInTheDocument();
    expect(document.querySelector("input, button, [aria-checked], [aria-selected], [data-best], [data-lowest], [data-selected]")).toBeNull();
    expect(text).not.toMatch(/cheapest|lowest|\bbest\b/i);
  });

  it("states missing prices, currency and VAT basis in words", () => {
    const line = makeEstimateLine({
      candidates: [cand(1, "A", null), cand(2, "B", "5.0000", { currency: null, includes_vat: null }), cand(3, "C", "6.0000", { includes_vat: true })],
    });
    render(<ul><LineRow line={line} currency="ZAR" /></ul>);
    expect(screen.getByText("Price missing")).toBeInTheDocument();
    expect(screen.getByText("5.0000 · VAT not stated · Currency not stated")).toBeInTheDocument();
    expect(screen.getByText("ZAR 6.0000 · incl. VAT")).toBeInTheDocument();
  });

  it("shows status text, plain-words flags, and the item, unit and quantity", () => {
    const line = makeEstimateLine({ status: "changed", flags: ["source_changed", "made_up"] });
    render(<ul><LineRow line={line} currency="ZAR" /></ul>);
    expect(screen.getByText("Source changed")).toBeInTheDocument();
    expect(screen.getByText(/has changed since it was chosen/)).toBeInTheDocument();
    expect(screen.getByText(/1\.1/)).toBeInTheDocument();
    expect(screen.getByText(/Unit: no/)).toBeInTheDocument();
    expect(screen.getByText(/Quantity: 10\.0000/)).toBeInTheDocument();
  });

  it("shows the chosen source and amounts of a priced line", () => {
    const line = makeEstimateLine({
      status: "priced", price_source: "supplier", supplier_name: "Zulu Supplies", quoted_unit_price: "125.5000",
      quoted_currency: "ZAR", quoted_includes_vat: false, unit_price_ex_vat: "125.5000", material_cost: "1255.00",
      labour_cost: "0.00", markup: "125.50", total: "1380.50", cost: "1255.00",
    });
    render(<ul><LineRow line={line} currency="ZAR" /></ul>);
    const row = screen.getByRole("listitem");
    expect(within(row).getByText(/Price from Zulu Supplies: ZAR 125\.5000 · excl\. VAT/)).toBeInTheDocument();
    expect(within(row).getByText("ZAR 1380.50")).toBeInTheDocument();
    expect(within(row).getByText("Priced")).toBeInTheDocument();
  });

  it("shows an exclusion with its reason and a manual price", () => {
    const { rerender } = render(<ul><LineRow line={makeEstimateLine({ status: "excluded", price_source: "excluded", exclude_reason: "Client supplies it" })} currency="ZAR" /></ul>);
    expect(screen.getByText("Excluded: Client supplies it")).toBeInTheDocument();
    rerender(<ul><LineRow line={makeEstimateLine({ status: "priced", price_source: "manual", quoted_unit_price: "10.0000", quoted_currency: "ZAR", quoted_includes_vat: false })} currency="ZAR" /></ul>);
    expect(screen.getByText(/Manual price: ZAR 10\.0000/)).toBeInTheDocument();
  });

  it("renders a controls slot for later editing", () => {
    render(<ul><LineRow line={makeEstimateLine()} currency="ZAR" controls={<p>slot</p>} /></ul>);
    expect(screen.getByText("slot")).toBeInTheDocument();
  });
});
