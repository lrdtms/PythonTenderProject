import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";

import { exportErrorText } from "./export-words";

const err = (status: number, code: string) => new ApiError(status, code, "server words");

describe("exportErrorText", () => {
  it.each([
    [err(409, "no_estimate"), "no_estimate"],
    [err(422, "export_too_large"), "export_too_large"],
    [err(403, "forbidden"), "forbidden"],
    [err(429, "rate_limited"), "rate_limited"],
    [err(404, "not_found"), "not_found"],
    [err(0, "network_error"), "network_error"],
  ])("gives a plain sentence for %#", (error, code) => {
    const text = exportErrorText(error);
    expect(text.length).toBeGreaterThan(10);
    expect(text).not.toContain(code);
    expect(text).not.toMatch(/_/);
  });

  it("maps by status when the code is unfamiliar", () => {
    expect(exportErrorText(err(429, "whatever"))).toBe(exportErrorText(err(429, "rate_limited")));
    expect(exportErrorText(err(404, "whatever"))).toBe(exportErrorText(err(404, "not_found")));
  });

  it("falls back for unknown errors", () => {
    const text = exportErrorText(err(500, "weird_code"));
    expect(text).not.toContain("weird_code");
    expect(exportErrorText(new Error("boom"))).toBe(text);
    expect(exportErrorText(null)).toBe(text);
  });
});
