import { readdirSync, readFileSync } from "node:fs";
import { basename, join, relative } from "node:path";

import { describe, expect, it } from "vitest";

// Every page behind the client-side AuthGate must opt out of instant-navigation validation
// (see the comment in each page). A layout-level export does not cover child pages.
const APP_DIR = join(import.meta.dirname, "(app)");

function pageFiles(dir: string): string[] {
  return readdirSync(dir, { recursive: true, encoding: "utf8" })
    .filter((entry) => /^page\.(tsx|ts|jsx|js)$/.test(basename(entry)))
    .map((entry) => join(dir, entry));
}

describe("(app) pages", () => {
  const pages = pageFiles(APP_DIR);

  it("finds the pages", () => {
    expect(pages.length).toBeGreaterThan(0);
  });

  it.each(pages.map((file) => [relative(APP_DIR, file), file]))("%s exports instant = false", (_, file) => {
    expect(readFileSync(file, "utf8")).toMatch(/^export const instant = false;?$/m);
  });
});
