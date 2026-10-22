import { describe, expect, it } from "vitest";

import { blockerReasonText, blockerText, errorText, flagText } from "./estimate-words";

const FLAGS = [
  "currency_differs",
  "currency_missing",
  "vat_basis_unknown",
  "price_missing",
  "quantity_missing",
  "amount_too_large",
  "unit_missing",
  "unit_mismatch",
  "unreviewed_source",
  "source_changed",
];
const BLOCKERS = ["unresolved", "source_changed", "unreviewed_source", "no_lines", "boq_lines_missing"];
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

  it.each(ERRORS)("gives a plain sentence for the error %s", (code) => {
    expect(errorText(code)).toMatch(/\S/);
    expect(errorText(code)).not.toBe(code);
    expect(errorText(code)).toMatch(/[.]$/);
  });

  it("uses the agreed wording for the carried-over messages", () => {
    expect(errorText("estimate_frozen")).toBe(
      "This estimate is no longer a draft, so it cannot be changed. Reopen it, or start a new version if it is approved.",
    );
    expect(errorText("estimate_not_reviewed")).toBe("This estimate has to be marked as reviewed first.");
    expect(errorText("quantity_missing")).toMatch(/can only be excluded/);
    expect(errorText("stale_match")).not.toMatch(/reload/i);
    expect(flagText("unreviewed_source")).toMatch(/Review it before approving\.$/);
    expect(blockerText("unreviewed_source")).toMatch(/Review it before approving\.$/);
  });

  it("uses the server's own message for invalid_markup_override and invalid_settings", () => {
    for (const code of ["invalid_markup_override", "invalid_settings"]) {
      expect(errorText(code, "Markup must be below 100.")).toBe("Markup must be below 100.");
      expect(errorText(code)).toMatch(/\S/);
    }
    expect(errorText("estimate_frozen", "ignored")).not.toBe("ignored");
  });

  it("falls back to a generic sentence for unknown codes and never echoes the code", () => {
    for (const fn of [flagText, blockerText, errorText]) {
      const text = fn("made_up_code");
      expect(text).toMatch(/\S/);
      expect(text).not.toContain("made_up_code");
    }
  });

  it("words a blocker's reasons, or says no price was chosen when it has none", () => {
    expect(blockerReasonText("unresolved", [])).toBe("No price has been chosen yet.");
    expect(blockerReasonText("unresolved", ["vat_basis_unknown", "currency_missing"])).toBe(
      `${flagText("vat_basis_unknown")} ${flagText("currency_missing")}`,
    );
    expect(blockerReasonText("source_changed", ["source_changed"])).toBe(flagText("source_changed"));
    expect(blockerReasonText("no_lines", [])).toBe(blockerText("no_lines"));
    expect(blockerReasonText("boq_lines_missing", ["2 new BoQ lines"])).toBe(blockerText("boq_lines_missing"));
    expect(blockerText("boq_lines_missing")).toMatch(/new version/i);
  });
});
