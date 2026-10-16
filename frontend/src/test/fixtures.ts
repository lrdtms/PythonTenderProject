import type { DocumentItem, DocumentVersion, ExtractionStatus, Job, KindStatus, Run, Tender } from "@/api/types";

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

export function makeKind(kind: "boq" | "requirements", job: Partial<Job> | null, run: Partial<Run> | null): KindStatus {
  return {
    kind,
    job: job ? makeJob({ job_type: kind === "boq" ? "extract_boq" : "extract_requirements", ...job }) : null,
    run: run ? makeRun({ kind, ...run }) : null,
  };
}

export function makeExtraction(kinds: KindStatus[]): ExtractionStatus {
  return { kinds };
}
