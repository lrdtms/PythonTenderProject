import { ApiError } from "@/api/errors";

const BY_CODE: Record<string, string> = {
  supplier_exists: "A supplier with this name already exists. Merge them instead.",
  match_conflict: "These suppliers both have a confirmed match for the same line. Resolve that first.",
  tender_archived: "A tender that uses this supplier is archived.",
  try_again: "Something changed at the same time. Try again.",
};

export function supplierErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (BY_CODE[error.code]) return BY_CODE[error.code];
    if (error.isNotFound) return "This supplier no longer exists. The list was reloaded.";
    if (error.isForbidden) return "You do not have permission to change suppliers.";
    return error.message;
  }
  return "Something went wrong. Try again.";
}
