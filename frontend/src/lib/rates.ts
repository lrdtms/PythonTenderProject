const DECIMAL = /^\d+(\.\d+)?$/;
const decimals = (v: string) => (v.split(".")[1] ?? "").length;

export type MarkupBasis = "cost" | "selling_price";

/** null = valid. Mirrors the server rules; the server stays the authority. Values are decimal text, never numbers. */
export function vatError(vat: string): string | null {
  if (!DECIMAL.test(vat)) return "Enter the VAT rate as a number, for example 15.";
  if (decimals(vat) > 2) return "VAT rate can have at most 2 decimals.";
  if (Number(vat) > 100) return "VAT rate must be between 0 and 100.";
  return null;
}

export function markupError(markup: string, basis: MarkupBasis): string | null {
  if (!DECIMAL.test(markup)) return "Enter the markup as a number, for example 10.";
  if (decimals(markup) > 2) return "Markup can have at most 2 decimals.";
  if (basis === "selling_price" && Number(markup) >= 100)
    return "On selling price the markup is a margin and must be below 100.";
  if (basis === "cost" && Number(markup) > 1000) return "Markup on cost must be between 0 and 1000.";
  return null;
}
