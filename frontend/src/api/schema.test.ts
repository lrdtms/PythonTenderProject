import { describe, expect, it } from "vitest";

import openapi from "../../openapi.json";
import type { components, paths } from "./schema";

describe("generated API types", () => {
  it("cover the review routes and DTOs", () => {
    const route: keyof paths = "/api/v1/boq-items/{boq_item_id}";
    expect(Object.keys(openapi.paths)).toContain(route);
    const status: components["schemas"]["BoqItemDTO"]["review_status"] = "unreviewed";
    expect(status).toBe("unreviewed");
  });
});
