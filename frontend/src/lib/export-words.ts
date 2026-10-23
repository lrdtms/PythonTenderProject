import { ApiError } from "@/api/errors";

const GENERIC = "The file could not be prepared. Try again in a moment.";

const BY_CODE: Record<string, string> = {
  no_estimate: "This tender has no estimate yet. Create an estimate first, then download it.",
  export_too_large: "This file would be too large to prepare. Contact support if you need it.",
  forbidden: "You do not have permission to download files.",
  rate_limited: "You have asked for several files in a short time. Wait a minute, then try again.",
  not_found: "That tender or estimate could not be found. Refresh the page and try again.",
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
