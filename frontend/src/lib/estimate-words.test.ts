import { describe, expect, it } from "vitest";

import { blockerText, errorText, flagText } from "./estimate-words";

const FLAGS = [
  "currency_differs",
  "currency_missing",
  "vat_basis_unknown",
  "price_missing",
  "quantity_missing",
  "unit_missing",
  "unreviewed_source",
  "source_changed",
];
const BLOCKERS = ["unresolved", "source_changed", "unreviewed_source", "no_lines"];
const ERRORS = [
  "estimate_frozen",
  "estimate_not_ready",
  "estimate_not_reviewed",
  "draft_exists",
  "pricing_defaults_missing",
  "stale_match",
  "currency_locked",
  "tender_archived",
  "quantity_missing",
  "unit_mismatch_unacknowledged",
];

describe("estimate plain words", () => {
  it.each(FLAGS)("gives a plain sentence for the flag %s", (code) => {
    expect(flagText(code)).toMatch(/\S/);
    expect(flagText(code)).not.toBe(code);
    expect(flagText(code)).toMatch(/[.]$/);
  });

  it.each(BLOCKERS)("gives a plain sentence for the blocker %s", (code) => {
    expect(blockerText(code)).toMatch(/\S/);
    expect(blockerText(code)).not.toBe(code);
    expect(blockerText(code)).toMatch(/[.]$/);
  });

  it("uses the agreed wording for unreviewed_source", () => {
    expect(blockerText("unreviewed_source")).toBe(
      "A BoQ line or quotation item behind this price has not been reviewed yet.",
    );
  });

  it.each(ERRORS)("gives a plain sentence for the error %s", (code) => {
    expect(errorText(code)).toMatch(/\S/);
    expect(errorText(code)).not.toBe(code);
    expect(errorText(code)).toMatch(/[.]$/);
  });

  it("falls back to a generic sentence for unknown codes and never echoes the code", () => {
    for (const fn of [flagText, blockerText, errorText]) {
      const text = fn("made_up_code");
      expect(text).toMatch(/\S/);
      expect(text).not.toContain("made_up_code");
    }
  });
});
