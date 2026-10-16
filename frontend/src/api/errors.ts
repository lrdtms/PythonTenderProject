/** The API's consistent error body: {"error": {"code", "message", "details"?}}. */
export type ErrorBody = { error: { code: string; message: string; details?: unknown } };

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
  /** 403 from a permission check (not a missing CSRF header). */
  get isForbidden(): boolean {
    return this.status === 403 && this.code !== "csrf_failed";
  }
  get isCsrfFailure(): boolean {
    return this.status === 403 && this.code === "csrf_failed";
  }
  get isNotFound(): boolean {
    return this.status === 404;
  }
  get isConflict(): boolean {
    return this.status === 409;
  }
  /** A re-run replaced the row between lookup and write: reload the list. */
  get isRowReplaced(): boolean {
    return this.code === "row_replaced";
  }
}

export function networkError(): ApiError {
  return new ApiError(0, "network_error", "Could not reach the server. Check your connection and try again.");
}
