import { describe, expect, it } from "vitest";

import { ApiError } from "@/api/errors";
import { makeMatchSuggestion } from "@/test/fixtures";

import {
  classificationLabel,
  classificationTone,
  evidenceSummary,
  matchErrorText,
  matchStatusLabel,
  matchStatusTone,
  reasonText,
  scoreText,
  warningLabel,
} from "./match-text";

describe("match labels", () => {
  it("labels classifications and statuses", () => {
    expect(classificationLabel("clear")).toBe("Clear match");
    expect(classificationLabel("ambiguous")).toBe("Needs a decision");
    expect(classificationLabel("weird")).toBe("Needs a decision");
    expect(classificationTone("clear")).toBe("success");
    expect(classificationTone("ambiguous")).toBe("warning");
    expect(matchStatusLabel("suggested")).toBe("Suggested");
    expect(matchStatusLabel("confirmed")).toBe("Confirmed");
    expect(matchStatusLabel("rejected")).toBe("Rejected");
    expect(matchStatusLabel("zzz")).toBe("zzz");
    expect(matchStatusTone("suggested")).toBe("info");
    expect(matchStatusTone("confirmed")).toBe("success");
    expect(matchStatusTone("rejected")).toBe("danger");
    expect(matchStatusTone("zzz")).toBe("neutral");
  });

  it("labels every warning code and shows unknown codes", () => {
    expect(warningLabel("spec_conflict")).toBe("Specification differs");
    expect(warningLabel("unit_mismatch")).toBe("Unit differs");
    expect(warningLabel("quote_expires_before_closing")).toBe("Quote expires before the tender closes");
    expect(warningLabel("spec_multi_value")).toBe("Quote lists more than one value");
    expect(warningLabel("quote_shared")).toBe("Fits another line as well");
    expect(warningLabel("core_notation_differs")).toBe("Cable core notation differs (3-core vs 3C+E)");
    expect(warningLabel("text_differs")).toBe("Wording differs on both sides");
    expect(warningLabel("spec_one_sided")).toBe("Only one side gives a specification");
    expect(warningLabel("accessory_word")).toBe("May be an accessory, not the item");
    expect(warningLabel("negation")).toBe("Says something is excluded");
    expect(warningLabel("number_differs")).toBe("Quantities or sizes differ");
    expect(warningLabel("defining_word_missing")).toBe("One side names a feature the other does not");
    expect(warningLabel("brand_new_code")).toBe("brand_new_code");
  });

  // A copy of the backend EVIDENCE_WARNING_CODES (matching.py); keep in step with it.
  const BACKEND_CODES = [
    "spec_conflict", "spec_multi_value", "unit_mismatch", "core_notation_differs", "text_differs",
    "spec_one_sided", "accessory_word", "negation", "number_differs", "defining_word_missing",
    "word_one_sided", "quote_shared", "quote_expires_before_closing",
  ];
  it("has a plain-words label for every backend warning code", () => {
    expect(BACKEND_CODES).toHaveLength(13);
    for (const code of BACKEND_CODES) {
      expect(warningLabel(code), code).not.toBe(code);
      expect(warningLabel(code), code).not.toMatch(/_/);
    }
  });
});

describe("reasonText", () => {
  const withWarnings = (warnings: unknown) => makeMatchSuggestion({ evidence: { warnings } });
  it("handles 0, 1, 2 and 3 warnings", () => {
    expect(reasonText(withWarnings([]))).toBe("Several close candidates from this supplier.");
    expect(reasonText(makeMatchSuggestion({ evidence: {} }))).toBe("Several close candidates from this supplier.");
    expect(reasonText(withWarnings(["unit_mismatch"]))).toBe("Unit differs.");
    expect(reasonText(withWarnings(["unit_mismatch", "spec_conflict"]))).toBe(
      "Unit differs, and specification differs.",
    );
    expect(reasonText(withWarnings(["unit_mismatch", "spec_conflict", "negation"]))).toBe(
      "Unit differs, and specification differs.",
    );
  });
});

describe("matchErrorText", () => {
  it("maps API codes", () => {
    expect(matchErrorText(new ApiError(409, "match_conflict", "x"))).toBe(
      "Another candidate from this supplier is already confirmed for this line. Reject or reset that one first.",
    );
    expect(matchErrorText(new ApiError(409, "stale_match", "x"))).toBe("This quotation was replaced. Reload the list.");
    expect(matchErrorText(new ApiError(403, "forbidden", "x"))).toBe("You do not have permission to review this data.");
    expect(matchErrorText(new ApiError(409, "tender_archived", "x"))).toBe("This tender is archived, so it is read-only.");
    expect(matchErrorText(new ApiError(409, "try_again", "x"))).toBe("Something changed at the same time. Try again.");
    expect(matchErrorText(new ApiError(404, "row_replaced", "x"))).toBe("Replaced by a re-run. The list was reloaded.");
    expect(matchErrorText(new ApiError(500, "boom", "Server said no"))).toBe("Server said no");
    expect(matchErrorText(new Error("plain"))).toBe("Something went wrong. Try again.");
  });
});

describe("scoreText", () => {
  it("shows a whole percent", () => {
    expect(scoreText(0.8143)).toBe("81%");
    expect(scoreText(1)).toBe("100%");
    expect(scoreText(Number.NaN)).toBe("");
  });
});

describe("evidenceSummary", () => {
  const full = {
    signals: { text: 0.9, spec: 0.5, unit: 1, code: false },
    spec: { matched: ["voltage"], conflicts: ["core"], boq_only: ["ip_rating"], quote_only: [], multi_value: [] },
    unit: { boq: "m", quote: "m", state: "equal" },
    price: { unit_price: "12.50" },
    valid_until: "2026-12-31",
    warnings: [],
    rank: 1,
  };
  const value = (rows: { label: string; value: string }[], label: string) => rows.find((r) => r.label === label)?.value;

  it("summarises a full object", () => {
    const rows = evidenceSummary(full);
    expect(value(rows, "Text similarity")).toBe("90%");
    expect(value(rows, "Specification agreement")).toBe("50%");
    expect(value(rows, "Unit")).toBe("Same unit");
    expect(value(rows, "Matching specifications")).toBe("voltage");
    expect(value(rows, "Conflicting specifications")).toBe("core");
    expect(value(rows, "Given on one side only")).toBe("ip rating");
    expect(value(rows, "Valid until")).toBe("2026-12-31");
  });

  it("words the unit states", () => {
    expect(value(evidenceSummary({ unit: { state: "mismatch" } }), "Unit")).toBe("Units differ");
    expect(value(evidenceSummary({ unit: { state: "unknown" } }), "Unit")).toBe("Unit not known");
  });

  it("returns no rows for {} and survives garbage", () => {
    expect(evidenceSummary({})).toEqual([]);
    const garbage = {
      signals: { text: "high", spec: "x" },
      spec: { matched: "voltage", conflicts: [1, null, "core"] },
      unit: "m",
      valid_until: 5,
    };
    expect(() => evidenceSummary(garbage)).not.toThrow();
    expect(evidenceSummary(garbage).find((r) => r.label === "Text similarity")).toBeUndefined();
    expect(() => evidenceSummary(null as unknown as Record<string, unknown>)).not.toThrow();
  });
});
