import type { BoqItem, DocumentItem, DocumentVersion, ExtractionStatus, Job, KindStatus, MatchLine, MatchSuggestion, PageDetail, PageSummary, Quotation, QuotationItem, Requirement, Run, Supplier, Tender } from "@/api/types";

const NOW = "2026-10-16T08:00:00Z";
const ID = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
export const ids = { tender: ID(1), document: ID(2), version: ID(3), job: ID(4), user: ID(5), run: ID(6) };

export function makeTender(over: Partial<Tender> = {}): Tender {
  return {
    id: ids.tender, title: "Hall wiring", reference_number: "T-001", client_name: "Soweto Hall",
    location: "Soweto", closing_at: null, status: "preparing", created_by: ids.user,
    created_at: NOW, updated_at: NOW, archived_at: null, ...over,
  };
}

export function makeVersion(over: Partial<DocumentVersion> = {}): DocumentVersion {
  return {
    id: ids.version, document_id: ids.document, version_number: 1, filename: "pack.pdf",
    mime_type: "application/pdf", file_format: "pdf", file_size: 2048, checksum_sha256: "0".repeat(64),
    processing_status: "ready", is_current: true, created_at: NOW, job_id: ids.job, ...over,
  };
}

export function makeDocument(over: Partial<DocumentItem> = {}): DocumentItem {
  return {
    id: ids.document, tender_id: ids.tender, kind: "tender_document", title: "Tender pack",
    created_at: NOW, current_version: makeVersion(), ...over,
  };
}

export function makeJob(over: Partial<Job> = {}): Job {
  return {
    id: ids.job, job_type: "ingest", subject_type: "document_version", subject_id: ids.version,
    status: "succeeded", payload: {}, attempt_count: 1, progress_done: 0, progress_total: 0,
    error_code: null, warnings: [], created_at: NOW, started_at: NOW, completed_at: NOW, ...over,
  };
}

export function makeRun(over: Partial<Run> = {}): Run {
  return {
    id: ids.run, document_version_id: ids.version, job_id: ids.job, kind: "boq", status: "succeeded",
    deep_scan: false, prompt_version: null, filter_version: null, schema_version: null, model: null,
    warnings: [], counts: {}, error_code: null, created_at: NOW, started_at: NOW, finished_at: NOW, ...over,
  };
}

export function makeKind(kind: "boq" | "requirements" | "quotation", job: Partial<Job> | null, run: Partial<Run> | null): KindStatus {
  return {
    kind,
    job: job ? makeJob({ job_type: kind === "boq" ? "extract_boq" : kind === "quotation" ? "extract_quotation" : "extract_requirements", ...job }) : null,
    run: run ? makeRun({ kind, ...run }) : null,
  };
}

export function makeExtraction(kinds: KindStatus[]): ExtractionStatus {
  return { kinds };
}

export function makeBoqItem(over: Partial<BoqItem> = {}): BoqItem {
  return {
    id: ID(10), run_id: ids.run, document_version_id: ids.version, position: 1, section: "Lighting",
    item_no: "1.1", description: "LED panel 600x600", unit: "no", quantity: "10.0000", rate: null,
    raw_unit: "no", raw_quantity: "10", flags: [], page_number: 1, sheet: null, cell_range: null,
    review_status: "unreviewed", corrected_value: null, original_value: {}, reviewed_by: null,
    reviewed_by_name: null, reviewed_at: null, ...over,
  };
}

export function makeRequirement(over: Partial<Requirement> = {}): Requirement {
  return {
    id: ID(20), run_id: ids.run, document_version_id: ids.version, position: 1,
    description: "Tenderers must hold a valid tax clearance certificate.",
    requirement_type: "eligibility", mandatory_status: "mandatory",
    evidence_quote: "must hold a valid tax clearance certificate", evidence_status: "verified",
    needs_review: false, page_number: 1, quote_start: 10, quote_end: 52, review_status: "unreviewed",
    corrected_value: null, original_value: {}, reviewed_by: null, reviewed_by_name: null,
    reviewed_at: null, ...over,
  };
}

export function makePage(over: Partial<PageSummary> = {}): PageSummary {
  return {
    page_number: 1, label: null, status: "ok", text_source: "embedded", ocr_confidence: null,
    char_count: 100, table_count: 0, ...over,
  };
}

export function makePageDetail(over: Partial<PageDetail> = {}): PageDetail {
  return { ...makePage(), text: "Note: Tenderers must hold a valid tax clearance certificate.", tables: [], ...over };
}

export function makeSupplier(over: Partial<Supplier> = {}): Supplier {
  return { id: ID(30), name: "Bright Sparks", notes: null, quotation_count: 1, created_at: NOW, ...over };
}

export function makeQuotation(over: Partial<Quotation> = {}): Quotation {
  return {
    id: ID(40), document_version_id: ID(41), supplier_id: ID(30), supplier_name: "Bright Sparks",
    reference: "Q-100", quote_date: "2026-10-01", valid_until: "2026-12-31", currency: "ZAR",
    prices_include_vat: false, flags: [], item_count: 1, created_at: NOW, ...over,
  };
}

export function makeQuotationItem(over: Partial<QuotationItem> = {}): QuotationItem {
  return {
    id: ID(50), run_id: ids.run, quotation_id: ID(40), document_version_id: ID(41), position: 1,
    sku: null, description: "LED panel 600x600 40W", unit: "no", quantity: "10.0000",
    unit_price: "125.5000", raw_unit: "no", raw_quantity: "10", raw_price: "125.50", flags: [],
    page_number: 1, sheet: null, cell_range: null, review_status: "unreviewed", corrected_value: null,
    original_value: {}, reviewed_by: null, reviewed_by_name: null, reviewed_at: null, ...over,
  };
}

export function makeMatchSuggestion(over: Partial<MatchSuggestion> = {}): MatchSuggestion {
  return {
    id: ID(60), boq_item_id: ID(10), supplier: { id: ID(30), name: "Bright Sparks" },
    quotation_item: {
      id: ID(50), quotation_id: ID(40), description: "LED panel 600x600 40W", sku: null,
      unit: "no", quantity: "10.0000", unit_price: "125.5000", valid_until: "2026-12-31",
    },
    score: 0.9, rank: 1, classification: "clear", status: "suggested", evidence: {},
    decided_by: null, decided_by_name: null, decided_at: null, ...over,
  };
}

export function makeMatchLine(over: Partial<MatchLine> = {}): MatchLine {
  return {
    boq: { id: ID(10), item_no: "1.1", section: "Lighting", description: "LED panel 600x600", unit: "no", quantity: "10.0000" },
    suggestions: [makeMatchSuggestion()], ...over,
  };
}
