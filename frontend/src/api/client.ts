import { ApiError, type ErrorBody, networkError } from "./errors";

const CSRF_HEADER = "X-Requested-With";
const CSRF_VALUE = "IntelTPS";
const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export type Query = Record<string, string | number | boolean | null | undefined>;
export type RequestOptions = { method?: string; json?: unknown; query?: Query; signal?: AbortSignal };

export function withQuery(path: string, query?: Query): string {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

function toApiError(status: number, statusText: string, parsed: unknown): ApiError {
  const error = (parsed as Partial<ErrorBody> | null)?.error;
  return new ApiError(
    status,
    error?.code ?? "http_error",
    error?.message ?? (statusText || "The request failed."),
    error?.details,
  );
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && (error as { name?: unknown }).name === "AbortError";
}

function invalidResponse(status: number): ApiError {
  return new ApiError(status, "invalid_response", "The server sent an unexpected response.");
}

/** Parse a successful body: empty -> undefined, non-JSON -> invalid_response ApiError. */
function parseSuccess<T>(status: number, text: string): T {
  if (status === 204 || status === 205 || text === "") return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw invalidResponse(status);
  }
}

/** A JSON request to the same-origin API. Full paths, e.g. `/api/v1/me`. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (UNSAFE_METHODS.has(method)) headers[CSRF_HEADER] = CSRF_VALUE;
  let body: string | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  let response: Response;
  try {
    response = await fetch(withQuery(path, options.query), {
      method,
      headers,
      body,
      credentials: "same-origin",
      signal: options.signal,
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw networkError();
  }
  if (!response.ok) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    throw toApiError(response.status, response.statusText, parsed);
  }
  return parseSuccess<T>(response.status, await response.text());
}

export const get = <T>(path: string, query?: Query, signal?: AbortSignal) =>
  api<T>(path, { query, signal });
export const post = <T>(path: string, json?: unknown) => api<T>(path, { method: "POST", json });
export const patch = <T>(path: string, json?: unknown) => api<T>(path, { method: "PATCH", json });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

/** Multipart upload with progress (fetch has no upload progress). */
export function upload<T>(
  path: string,
  file: File,
  fields: Record<string, string>,
  onProgress?: (fraction: number) => void,
  signal?: AbortSignal,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abortError = new DOMException("Aborted", "AbortError");
    if (signal?.aborted) {
      reject(abortError);
      return;
    }
    const form = new FormData();
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", path);
    xhr.setRequestHeader(CSRF_HEADER, CSRF_VALUE);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(event.loaded / event.total);
    };
    xhr.onerror = () => reject(networkError());
    xhr.ontimeout = () => reject(networkError());
    xhr.onabort = () => reject(abortError);
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(parseSuccess<T>(xhr.status, xhr.responseText));
        } catch (error) {
          reject(error);
        }
        return;
      }
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(xhr.responseText);
      } catch {
        parsed = null;
      }
      reject(toApiError(xhr.status, "", parsed));
    };
    xhr.send(form);
  });
}
