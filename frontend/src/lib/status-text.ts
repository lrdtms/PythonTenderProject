export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

const JOB_TERMINAL = new Set(["succeeded", "succeeded_with_warnings", "failed", "cancelled"]);
export const isTerminalJob = (status?: string): boolean => !!status && JOB_TERMINAL.has(status);

const JOB_LABELS: Record<string, string> = {
  queued: "Waiting",
  running: "Processing",
  succeeded: "Done",
  succeeded_with_warnings: "Done, with warnings",
  failed: "Failed",
  cancelled: "Cancelled",
};
const PROCESSING_LABELS: Record<string, string> = {
  pending: "Waiting to process",
  processing: "Processing",
  ready: "Ready",
  ready_with_warnings: "Ready, with warnings",
  failed: "Failed",
};
const TENDER_LABELS: Record<string, string> = {
  preparing: "Preparing",
  in_review: "In review",
  ready: "Ready",
  submitted: "Submitted",
  archived: "Archived",
};
const KIND_LABELS: Record<string, string> = {
  tender_document: "Tender document",
  boq: "Bill of quantities",
  quotation: "Quotation",
  other: "Other",
};
const EXTRACTION_LABELS: Record<string, string> = {
  boq: "Bill of quantities",
  requirements: "Requirements",
  quotation: "Quotation",
};

export const jobStatusLabel = (s: string): string => JOB_LABELS[s] ?? "Unknown status";
export const processingStatusLabel = (s: string): string => PROCESSING_LABELS[s] ?? "Unknown status";
export const tenderStatusLabel = (s: string): string => TENDER_LABELS[s] ?? "Unknown status";
export const documentKindLabel = (s: string): string => KIND_LABELS[s] ?? "Other";
export const kindLabel = (s: string): string => EXTRACTION_LABELS[s] ?? s;

const JOB_TONES: Record<string, Tone> = {
  queued: "neutral",
  running: "info",
  succeeded: "success",
  succeeded_with_warnings: "warning",
  failed: "danger",
  cancelled: "neutral",
};
const PROCESSING_TONES: Record<string, Tone> = {
  pending: "neutral",
  processing: "info",
  ready: "success",
  ready_with_warnings: "warning",
  failed: "danger",
};
export const jobTone = (s: string): Tone => JOB_TONES[s] ?? "neutral";
export const processingTone = (s: string): Tone => PROCESSING_TONES[s] ?? "neutral";
export const tenderTone = (s: string): Tone => (s === "archived" ? "neutral" : s === "ready" ? "success" : "info");

const GENERIC_FAILURE = "Processing failed. Try again, or upload the file again.";
const JOB_ERRORS: Record<string, string> = {
  FILE_CORRUPT: "The file is damaged or cannot be read. Upload a fresh copy.",
  PDF_ENCRYPTED: "The PDF is password protected. Upload an unlocked copy.",
  UNSUPPORTED_FORMAT: "This file type is not supported.",
  SHEET_TOO_LARGE: "The spreadsheet is too large to process.",
  TENDER_ARCHIVED: "The tender is archived, so nothing can be processed.",
  LLM_UNAVAILABLE: "The AI step is not available right now. Try again in a few minutes.",
  INFRASTRUCTURE: "A temporary problem stopped processing. Try again.",
  LEASE_EXPIRED: "Processing was interrupted. Try again.",
};
export const jobErrorText = (code: string | null): string => (code && JOB_ERRORS[code]) || GENERIC_FAILURE;

function pageList(pages: unknown): number[] {
  return Array.isArray(pages) ? pages.filter((p): p is number => typeof p === "number") : [];
}

/** Subject and verb agreement for a page list; "Some pages" when there are none. */
function pagesSubject(pages: unknown, one: string, many: string): string {
  const list = pageList(pages);
  if (list.length === 0) return `Some pages ${many}`;
  return list.length === 1 ? `Page ${list[0]} ${one}` : `Pages ${list.join(", ")} ${many}`;
}

/** Warnings carry ids, page numbers and counts only (never document text). */
export function warningText(w: unknown): string {
  if (typeof w !== "object" || w === null) return "Warning";
  const { code, pages, count } = w as { code?: unknown; pages?: unknown; count?: unknown };
  const n = typeof count === "number" && Number.isFinite(count) ? count : null;
  const plural = (word: string) => (n === 1 ? word : `${word}s`);
  switch (code) {
    case "OCR_FAILED":
      return pagesSubject(pages, "could not be read.", "could not be read.");
    case "OCR_LOW_CONFIDENCE":
      {
      const single = pageList(pages).length === 1;
      return pagesSubject(pages, "was read with low confidence.", "were read with low confidence.") +
        (single ? " Check the values from it." : " Check the values from them.");
    }
    case "OCR_UNAVAILABLE":
      return "Text recognition was not available for scanned pages.";
    case "BOQ_NEEDS_MANUAL_ENTRY":
      return (
        pagesSubject(pages, "looks like a scanned bill of quantities.", "look like a scanned bill of quantities.") +
        " Enter its lines manually."
      );
    case "NO_BOQ_FOUND":
      return "No bill of quantities table was found.";
    case "FILTER_LOW_YIELD":
      return "Few requirement candidates were found. Try a deep scan.";
    case "WINDOW_CAP_REACHED":
      return "The document is long, so only the first part was analysed. Try a deep scan or split it.";
    case "ROW_CAP_REACHED":
      return n === null ? "Some rows beyond the limit were not stored." : `${n} ${plural("row")} beyond the limit ${n === 1 ? "was" : "were"} not stored.`;
    case "EVIDENCE_UNVERIFIED":
      return n === null ? "Some requirements could not be matched to the page text. Check them against the source." : `${n} ${plural("requirement")} could not be matched to the page text. Check them against the source.`;
    case "DUPLICATE_OF_REVIEWED":
      return n === null ? "Some items matched ones you already reviewed and were kept as reviewed." : `${n} ${plural("item")} matched ones you already reviewed and were kept as reviewed.`;
    case "NO_SUPPLIER_NAME":
      return "The supplier name could not be read, so the file name was used. Rename the supplier.";
    case "NO_REFERENCE":
      return "The quotation reference could not be read.";
    case "NO_QUOTE_DATE":
      return "The quotation date could not be read.";
    case "NO_VALIDITY":
      return "The quotation's validity date could not be read. Check it is still valid.";
    case "NO_CURRENCY":
      return "The currency could not be read. Check the prices before using them.";
    case "VAT_UNKNOWN":
      return "The quotation does not say whether prices include VAT.";
    case "QUOTE_NEEDS_MANUAL_ENTRY":
      return (
        pagesSubject(pages, "looks like a scanned quotation.", "look like a scanned quotation.") +
        " Its items cannot be read automatically yet."
      );
    case "NO_QUOTATION_FOUND":
      return "No quotation table was found in this document.";
    case "WINDOW_TIMEOUT":
    case "WINDOW_INVALID_OUTPUT":
      return "Some sections could not be analysed. Run the extraction again.";
    default:
      return typeof code === "string" ? `Warning: ${code}` : "Warning";
  }
}
