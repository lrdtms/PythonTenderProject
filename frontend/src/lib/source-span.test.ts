import { describe, expect, it } from "vitest";

import { splitQuoteSpan, splitSpan } from "./source-span";

describe("splitSpan", () => {
  it("splits a valid span", () => expect(splitSpan("abcdef", 2, 4)).toEqual({ before: "ab", mark: "cd", after: "ef" }));
  it.each([[null, 3], [1, null], [3, 3], [4, 2], [-1, 2], [0, 7], [1.5, 3]])("rejects %j,%j", (s, e) =>
    expect(splitSpan("abcdef", s as number | null, e as number | null)).toBeNull(),
  );
});

describe("splitQuoteSpan", () => {
  it("maps offsets in whitespace-collapsed, lower-cased text back onto the raw text", () => {
    const raw = "  Intro\r\n\r\n   MUST   hold a   Certificate.  ";
    // squashed: "intro must hold a certificate."
    const squashed = "intro must hold a certificate.";
    const start = squashed.indexOf("must");
    const end = squashed.indexOf("certificate") + "certificate".length;
    expect(splitQuoteSpan(raw, start, end)?.mark).toBe("MUST   hold a   Certificate");
  });

  it("counts code points, not UTF-16 units", () => {
    const raw = "😀 pay on time";
    expect(splitQuoteSpan(raw, 2, 13)?.mark).toBe("pay on time");
  });

  it("returns null past the end", () => {
    expect(splitQuoteSpan("short", 2, 40)).toBeNull();
    expect(splitQuoteSpan("short", null, 3)).toBeNull();
  });
});
