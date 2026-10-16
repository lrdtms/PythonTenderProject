import { describe, expect, it } from "vitest";

import { splitSpan } from "./source-span";

describe("splitSpan", () => {
  it("splits a valid span", () => expect(splitSpan("abcdef", 2, 4)).toEqual({ before: "ab", mark: "cd", after: "ef" }));
  it.each([[null, 3], [1, null], [3, 3], [4, 2], [-1, 2], [0, 7], [1.5, 3]])("rejects %j,%j", (s, e) =>
    expect(splitSpan("abcdef", s as number | null, e as number | null)).toBeNull(),
  );
});
