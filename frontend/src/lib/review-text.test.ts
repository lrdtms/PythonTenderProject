import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { flagLabel, reviewStatusLabel, writeErrorText } from "./review-text";

describe("review-text", () => {
  it("treats 404 and row_replaced as replaced", () => {
    expect(writeErrorText(new ApiError(404, "not_found", "x")).replaced).toBe(true);
    expect(writeErrorText(new ApiError(409, "row_replaced", "x")).replaced).toBe(true);
  });
  it("explains 403 and archived", () => {
    expect(writeErrorText(new ApiError(403, "forbidden", "x")).text).toMatch(/permission/);
    expect(writeErrorText(new ApiError(409, "tender_archived", "x")).text).toMatch(/archived/);
  });
  it("passes other messages through", () => {
    expect(writeErrorText(new ApiError(422, "validation_error", "Bad value"))).toEqual({ text: "Bad value", replaced: false });
  });
  it("uses 422 detail messages", () => {
    const e = new ApiError(422, "validation_error", "The request is not valid.", [{ field: "quantity", message: "Quantity is too large." }]);
    expect(writeErrorText(e).text).toBe("Quantity is too large.");
  });
  it("labels", () => {
    expect(reviewStatusLabel("corrected")).toBe("Corrected");
    expect(flagLabel("missing_quantity")).toBe("Quantity missing");
    expect(flagLabel("weird")).toBe("weird");
  });
});
