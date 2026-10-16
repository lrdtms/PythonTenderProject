import { describe, expect, it } from "vitest";

import { columnLetters, parseCellRange } from "./cell-range";

describe("cell-range", () => {
  it("parses a row range", () => expect(parseCellRange("A12:F12")).toEqual({ firstRow: 12, lastRow: 12, firstCol: 1, lastCol: 6 }));
  it("parses a single cell", () => expect(parseCellRange("B3")).toEqual({ firstRow: 3, lastRow: 3, firstCol: 2, lastCol: 2 }));
  it("parses multi-letter columns", () => expect(parseCellRange("AA1:AB2")).toMatchObject({ firstCol: 27, lastCol: 28 }));
  it.each([null, "", "garbage", "1A"])("rejects %j", (v) => expect(parseCellRange(v)).toBeNull());
  it("names columns", () => {
    expect(columnLetters(1)).toBe("A");
    expect(columnLetters(26)).toBe("Z");
    expect(columnLetters(27)).toBe("AA");
  });
});
