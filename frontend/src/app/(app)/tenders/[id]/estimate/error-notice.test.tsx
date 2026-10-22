import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { ErrorNotice } from "./error-notice";

const blocker = (n: number, extra: Record<string, unknown> = {}) => ({
  line_id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
  code: "unresolved",
  item_no: `A${n}`,
  description: `Cable ${n}`,
  reasons: [],
  ...extra,
});
const notReady = (blockers: unknown[]) => new ApiError(409, "estimate_not_ready", "x", { blockers });

describe("ErrorNotice blockers", () => {
  it("names each line and its own reason", () => {
    render(
      <ErrorNotice
        error={notReady([blocker(1), blocker(2, { reasons: ["vat_basis_unknown"] }), blocker(3, { code: "source_changed", reasons: ["source_changed"] })])}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("A1 Cable 1: No price has been chosen yet.");
    expect(items[1]).toHaveTextContent("A2 Cable 2: It is not clear whether the quoted prices include VAT.");
    expect(items[2]).toHaveTextContent("A3 Cable 3: The BoQ or quotation behind this price has changed");
    expect(within(items[0]).getByRole("link", { name: "Go to the line" })).toHaveAttribute("href", `#line-${blocker(1).line_id}`);
  });

  it("shows the first 10 with the total count and 'and N more'", () => {
    render(<ErrorNotice error={notReady(Array.from({ length: 14 }, (_, i) => blocker(i + 1)))} />);
    expect(screen.getByText("14 lines need attention.")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(10);
    expect(screen.getByText("and 4 more")).toBeInTheDocument();
    expect(screen.queryByText(/A11 /)).not.toBeInTheDocument();
  });

  it("still words a blocker without a line", () => {
    render(<ErrorNotice error={notReady([{ line_id: null, code: "no_lines", item_no: null, description: null, reasons: [] }])} />);
    expect(screen.getByRole("listitem")).toHaveTextContent("This estimate has no BoQ lines to price.");
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
