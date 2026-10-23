import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { makeEstimate } from "@/test/fixtures";

import { Summary } from "./summary";

describe("Summary", () => {
  it("shows the five amounts and the counts", () => {
    render(<Summary estimate={makeEstimate({ priced: 3, excluded: 1, unresolved: 0, changed: 0 })} />);
    for (const label of ["Subtotal cost", "Markup", "Subtotal ex VAT", "VAT", "Total inc VAT"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(screen.getByText("ZAR 126.50")).toBeInTheDocument();
    expect(screen.getByText(/3 priced/)).toBeInTheDocument();
    expect(screen.getByText(/1 excluded/)).toBeInTheDocument();
    expect(screen.getByText(/0 unresolved/)).toBeInTheDocument();
    expect(screen.getByText(/0 changed/)).toBeInTheDocument();
  });

  it("labels the total incomplete while lines are unresolved or changed", () => {
    render(<Summary estimate={makeEstimate({ incomplete: true, unresolved: 2, changed: 1 })} />);
    expect(screen.getByText("Incomplete: excludes 3 lines")).toBeInTheDocument();
    // every figure is marked, and a caption covers the whole block
    expect(screen.getAllByText("(partial)")).toHaveLength(5);
    expect(screen.getByText(/These figures are partial/)).toBeInTheDocument();
    expect(screen.getByText("ZAR 110.00")).toBeInTheDocument();
  });

  it("hides the incomplete label when nothing is open", () => {
    render(<Summary estimate={makeEstimate()} />);
    expect(screen.queryByText(/incomplete/i)).toBeNull();
    expect(screen.queryByText(/partial/i)).toBeNull();
  });

  it("shows 0.00 for an all-excluded estimate, never NaN or blank", () => {
    const zero = { subtotal_cost: "0.00", markup_total: "0.00", subtotal_ex_vat: "0.00", vat_total: "0.00", total_inc_vat: "0.00" };
    render(<Summary estimate={makeEstimate({ priced: 0, excluded: 4, totals: zero })} />);
    expect(screen.getAllByText("ZAR 0.00")).toHaveLength(5);
    expect(document.body.textContent).not.toMatch(/NaN/);
  });

  it("shows 0.00 when the server sends no totals", () => {
    render(<Summary estimate={makeEstimate({ totals: null, priced: 0 })} />);
    expect(screen.getAllByText("ZAR 0.00")).toHaveLength(5);
  });
});
