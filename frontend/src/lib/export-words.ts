import { ApiError } from "@/api/errors";

const GENERIC = "The file could not be prepared. Try again in a moment.";

const BY_CODE: Record<string, string> = {
  no_estimate: "This tender has no estimate yet. Create one first.",
  export_too_large: "This is too large to export in one file.",
  forbidden: "Your role cannot export files.",
  rate_limited: "You are exporting too quickly. Wait a minute and try again.",
  not_found: "That tender or estimate could not be found. Refresh the page and try again.",
  csrf_failed: "Your session needs a refresh. Refresh the page and try again.",
  validation_error: "That estimate cannot be exported from this tender. Refresh the page.",
  network_error: "Could not reach the server. Check your connection and try again.",
};

const BY_STATUS: Record<number, string> = {
  403: BY_CODE.forbidden,
  404: BY_CODE.not_found,
  429: BY_CODE.rate_limited,
};

/** Plain sentence for a failed export. Never shows a raw code. */
export function exportErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC;
  if (Object.prototype.hasOwnProperty.call(BY_CODE, error.code)) return BY_CODE[error.code];
  return BY_STATUS[error.status] ?? GENERIC;
}
