import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { supplierErrorText } from "./supplier-text";

describe("supplierErrorText", () => {
  it("maps each known code to plain words", () => {
    expect(supplierErrorText(new ApiError(409, "supplier_exists", "dup"))).toBe(
      "A supplier with this name already exists. Merge them instead.",
    );
    expect(supplierErrorText(new ApiError(409, "match_conflict", "x"))).toBe(
      "These suppliers both have a confirmed match for the same line. Resolve that first.",
    );
    expect(supplierErrorText(new ApiError(409, "tender_archived", "x"))).toBe(
      "A tender that uses this supplier is archived.",
    );
    expect(supplierErrorText(new ApiError(409, "try_again", "x"))).toBe(
      "Something changed at the same time. Try again.",
    );
    expect(supplierErrorText(new ApiError(403, "forbidden", "x"))).toBe(
      "You do not have permission to change suppliers.",
    );
  });

  it("uses the API message for an unknown code", () => {
    expect(supplierErrorText(new ApiError(422, "weird", "Odd request."))).toBe("Odd request.");
  });

  it("says a missing supplier no longer exists", () => {
    expect(supplierErrorText(new ApiError(404, "not_found", "No such supplier."))).toBe(
      "This supplier no longer exists. The list was reloaded.",
    );
  });

  it("falls back for a plain Error and for null", () => {
    expect(supplierErrorText(new Error("boom"))).toBe("Something went wrong. Try again.");
    expect(supplierErrorText(null)).toBe("Something went wrong. Try again.");
  });
});
