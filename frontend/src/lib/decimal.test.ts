import { describe, expect, it } from "vitest";

import { validateDecimal } from "./decimal";

describe("validateDecimal", () => {
  it.each(["10", "10.5", "-3.1234", "", "  "])("accepts %j", (v) => expect(validateDecimal(v)).toBeNull());
  it.each(["1,500", "1e3", ".5", "10.12345", "-", "abc", "1 000"])("rejects %j", (v) =>
    expect(validateDecimal(v)).toEqual(expect.any(String)),
  );
  it("explains too many decimals", () => expect(validateDecimal("1.12345")).toMatch(/4 decimal/));
});
