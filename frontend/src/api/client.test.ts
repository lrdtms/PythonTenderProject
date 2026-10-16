import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./errors";
import { api, del, get, patch, post, upload, withQuery } from "./client";

const fetchMock = vi.fn();

function respond(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function lastCall(): { url: string; init: RequestInit & { headers: Record<string, string> } } {
  const [url, init] = fetchMock.mock.calls.at(-1)!;
  return { url, init };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("CSRF header", () => {
  it("is absent on GET and present on every unsafe method", async () => {
    fetchMock.mockResolvedValue(respond(200, {}));
    await get("/api/v1/me");
    expect(lastCall().init.headers["X-Requested-With"]).toBeUndefined();
    for (const call of [
      () => post("/api/v1/auth/logout"),
      () => patch("/api/v1/boq-items/1", { unit: "m" }),
      () => del("/api/v1/x"),
      () => api("/api/v1/x", { method: "PUT", json: {} }),
    ]) {
      fetchMock.mockResolvedValueOnce(respond(200, {}));
      await call();
      expect(lastCall().init.headers["X-Requested-With"]).toBe("IntelTPS");
    }
  });
});

describe("requests", () => {
  it("sends JSON bodies with a content type and same-origin credentials", async () => {
    fetchMock.mockResolvedValue(respond(200, { ok: true }));
    await post("/api/v1/auth/login", { email: "a@b.co", password: "x" });
    const { init } = lastCall();
    expect(init.method).toBe("POST");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ email: "a@b.co", password: "x" });
    expect(init.credentials).toBe("same-origin");
  });

  it("builds query strings and drops undefined and null values", () => {
    expect(withQuery("/a", { limit: 5, q: "x y", skip: undefined, none: null })).toBe(
      "/a?limit=5&q=x+y",
    );
    expect(withQuery("/a")).toBe("/a");
    expect(withQuery("/a", { skip: undefined })).toBe("/a");
  });

  it("returns undefined for 204", async () => {
    fetchMock.mockResolvedValue(respond(204));
    await expect(post<void>("/api/v1/auth/logout")).resolves.toBeUndefined();
  });
});

describe("errors", () => {
  it("maps the API error format, including 422 details", async () => {
    const details = [{ field: "password", message: "Use at least 10 characters." }];
    fetchMock.mockResolvedValue(
      respond(422, { error: { code: "validation_error", message: "Not valid.", details } }),
    );
    const error = await get("/api/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "validation_error", message: "Not valid.", details });
  });

  it("tells csrf_failed from forbidden", async () => {
    fetchMock.mockResolvedValueOnce(respond(403, { error: { code: "csrf_failed", message: "m" } }));
    const csrf = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    fetchMock.mockResolvedValueOnce(respond(403, { error: { code: "forbidden", message: "m" } }));
    const forbidden = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect([csrf.isCsrfFailure, csrf.isForbidden]).toEqual([true, false]);
    expect([forbidden.isCsrfFailure, forbidden.isForbidden]).toEqual([false, true]);
  });

  it("exposes the distinct 409 codes and 401/404", async () => {
    for (const [status, code] of [
      [409, "row_replaced"],
      [409, "tender_archived"],
      [409, "not_processed"],
      [409, "extraction_options_conflict"],
    ] as const) {
      fetchMock.mockResolvedValueOnce(respond(status, { error: { code, message: "m" } }));
      const error = (await post("/api/v1/x").catch((e: unknown) => e)) as ApiError;
      expect(error.isConflict).toBe(true);
      expect(error.code).toBe(code);
      expect(error.isRowReplaced).toBe(code === "row_replaced");
    }
    fetchMock.mockResolvedValueOnce(respond(401, { error: { code: "unauthorized", message: "m" } }));
    expect(((await get("/api/v1/me").catch((e: unknown) => e)) as ApiError).isUnauthorized).toBe(true);
    fetchMock.mockResolvedValueOnce(respond(404, { error: { code: "not_found", message: "m" } }));
    expect(((await get("/api/v1/x").catch((e: unknown) => e)) as ApiError).isNotFound).toBe(true);
  });

  it("falls back to http_error for a non-JSON error body", async () => {
    fetchMock.mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502 }));
    const error = (await get("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 502, code: "http_error" });
  });

  it("reports a network failure as ApiError status 0", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const error = (await get("/api/v1/x").catch((e: unknown) => e)) as ApiError;
    expect(error).toMatchObject({ status: 0, code: "network_error" });
  });
});

class FakeXhr {
  static last: FakeXhr;
  headers: Record<string, string> = {};
  upload: { onprogress?: (e: { lengthComputable: boolean; loaded: number; total: number }) => void } = {};
  onload?: () => void;
  onerror?: () => void;
  status = 0;
  responseText = "";
  method = "";
  url = "";
  body: unknown;
  constructor() {
    FakeXhr.last = this;
  }
  open(method: string, url: string) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    this.body = body;
  }
}

describe("upload", () => {
  beforeEach(() => vi.stubGlobal("XMLHttpRequest", FakeXhr));

  it("posts multipart with the CSRF header and reports progress", async () => {
    const progress: number[] = [];
    const file = new File(["%PDF"], "t.pdf", { type: "application/pdf" });
    const promise = upload<{ ok: boolean }>("/api/v1/tenders/1/documents", file, { kind: "boq" }, (f) =>
      progress.push(f),
    );
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url]).toEqual(["POST", "/api/v1/tenders/1/documents"]);
    expect(xhr.headers["X-Requested-With"]).toBe("IntelTPS");
    const form = xhr.body as FormData;
    expect(form.get("kind")).toBe("boq");
    expect((form.get("file") as File).name).toBe("t.pdf");
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
    xhr.status = 201;
    xhr.responseText = JSON.stringify({ ok: true });
    xhr.onload?.();
    await expect(promise).resolves.toEqual({ ok: true });
    expect(progress).toEqual([0.5]);
  });

  it("rejects with ApiError on an API error and on a network error", async () => {
    const file = new File(["x"], "t.pdf");
    const failing = upload("/api/v1/x", file, {});
    FakeXhr.last.status = 413;
    FakeXhr.last.responseText = JSON.stringify({ error: { code: "limit_exceeded", message: "Too big." } });
    FakeXhr.last.onload?.();
    await expect(failing).rejects.toMatchObject({ status: 413, code: "limit_exceeded" });
    const offline = upload("/api/v1/x", file, {});
    FakeXhr.last.onerror?.();
    await expect(offline).rejects.toMatchObject({ status: 0, code: "network_error" });
  });
});
