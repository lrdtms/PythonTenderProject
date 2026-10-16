import { describe, expect, it } from "vitest";

import { ApiError } from "./errors";
import { MAX_POLL_FAILURES, shouldPoll } from "./jobs";

type Data = { status: string };
const isDone = (d: Data | undefined) => d?.status === "succeeded";

function fakeQuery() {
  const state = {
    data: undefined as Data | undefined,
    error: null as unknown,
    errorUpdateCount: 0,
    dataUpdatedAt: 0,
  };
  return {
    query: { state },
    succeed(status = "running") {
      state.data = { status };
      state.error = null;
      state.dataUpdatedAt += 1;
    },
    fail(error: unknown = new ApiError(503, "unavailable", "down")) {
      state.error = error;
      state.errorUpdateCount += 1;
    },
  };
}

describe("shouldPoll", () => {
  it("keeps polling a running job and stops on a terminal one", () => {
    const q = fakeQuery();
    q.succeed();
    expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    q.succeed("succeeded");
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("stops immediately on a 4xx", () => {
    const q = fakeQuery();
    q.succeed();
    q.fail(new ApiError(404, "not_found", "gone"));
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("never stops for scattered errors separated by successes", () => {
    const q = fakeQuery();
    q.succeed();
    for (let i = 0; i < MAX_POLL_FAILURES * 2; i += 1) {
      q.fail();
      expect(shouldPoll(q.query, 50, isDone)).toBe(50);
      q.succeed();
      expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    }
    q.succeed("succeeded");
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("stops after the maximum number of consecutive failures", () => {
    const q = fakeQuery();
    q.succeed();
    shouldPoll(q.query, 50, isDone);
    for (let i = 1; i < MAX_POLL_FAILURES; i += 1) {
      q.fail();
      expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    }
    q.fail();
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("stops after consecutive failures even when it never succeeded", () => {
    const q = fakeQuery();
    for (let i = 0; i < MAX_POLL_FAILURES; i += 1) q.fail();
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("resets the count when a success follows four failures", () => {
    const q = fakeQuery();
    q.succeed();
    shouldPoll(q.query, 50, isDone);
    for (let i = 0; i < MAX_POLL_FAILURES - 1; i += 1) q.fail();
    expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    q.succeed();
    expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    for (let i = 0; i < MAX_POLL_FAILURES - 1; i += 1) q.fail();
    expect(shouldPoll(q.query, 50, isDone)).toBe(50);
    q.fail();
    expect(shouldPoll(q.query, 50, isDone)).toBe(false);
  });

  it("keeps polling through 408 and 429 (transient), counting them as failures", () => {
    for (const status of [408, 429]) {
      const q = fakeQuery();
      q.succeed();
      q.fail(new ApiError(status, "transient", "later"));
      expect(shouldPoll(q.query, 50, isDone)).toBe(50);
      for (let i = 0; i < MAX_POLL_FAILURES; i++) q.fail(new ApiError(status, "transient", "later"));
      expect(shouldPoll(q.query, 50, isDone)).toBe(false);
    }
  });
});
