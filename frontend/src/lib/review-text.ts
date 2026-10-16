import { ApiError } from "@/api/errors";

import type { Tone } from "./status-text";

const STATUS_LABELS: Record<string, string> = {
  unreviewed: "Unreviewed",
  confirmed: "Confirmed",
  corrected: "Corrected",
  rejected: "Rejected",
};
const STATUS_TONES: Record<string, Tone> = {
  unreviewed: "neutral",
  confirmed: "success",
  corrected: "info",
  rejected: "danger",
};
export const reviewStatusLabel = (s: string): string => STATUS_LABELS[s] ?? "Unknown";
export const reviewTone = (s: string): Tone => STATUS_TONES[s] ?? "neutral";

const FLAG_LABELS: Record<string, string> = {
  missing_quantity: "Quantity missing",
  ambiguous_separator: "Check the thousands separator",
  rate_unparsed: "Rate could not be read",
  provisional_sum: "Provisional sum",
  unit_unrecognised: "Unit not recognised",
};
export const flagLabel = (code: string): string => FLAG_LABELS[code] ?? code;

export const REQUIREMENT_TYPES = ["deadline", "meeting", "eligibility", "document", "pricing", "technical", "other"] as const;
export const MANDATORY_STATUSES = ["mandatory", "conditional", "informational"] as const;

const TYPE_LABELS: Record<string, string> = {
  deadline: "Deadline",
  meeting: "Meeting",
  eligibility: "Eligibility",
  document: "Document",
  pricing: "Pricing",
  technical: "Technical",
  other: "Other",
};
const MANDATORY_LABELS: Record<string, string> = {
  mandatory: "Mandatory",
  conditional: "Conditional",
  informational: "Informational",
};
export const requirementTypeLabel = (s: string): string => TYPE_LABELS[s] ?? s;
export const mandatoryLabel = (s: string): string => MANDATORY_LABELS[s] ?? s;

/** What to tell the user when a row write fails. `replaced` = a re-run removed the row. */
export function writeErrorText(error: unknown): { text: string; replaced: boolean } {
  if (error instanceof ApiError) {
    if (error.status === 404 || error.isRowReplaced) {
      return { text: "Replaced by a re-run. The list was reloaded.", replaced: true };
    }
    if (error.isForbidden) return { text: "You do not have permission to review this data.", replaced: false };
    if (error.code === "tender_archived") return { text: "This tender is archived, so it is read-only.", replaced: false };
    return { text: error.message, replaced: false };
  }
  return { text: "Something went wrong. Try again.", replaced: false };
}
