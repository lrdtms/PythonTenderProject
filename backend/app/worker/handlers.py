"""Job handlers: the glue between the queue and the modules."""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.infrastructure.llm import get_llm
from app.infrastructure.model_registry import import_all_models
from app.infrastructure.storage import get_storage
from app.kernel import LLMUnavailable, OrgContext, ProcessingFailed
from app.modules.checklist import public as checklist
from app.modules.documents import public as documents
from app.modules.estimating import public as estimating
from app.modules.extraction import public as extraction
from app.modules.jobs import public as jobs
from app.modules.knowledge import public as knowledge
from app.modules.pipeline import public as pipeline
from app.modules.suppliers import public as suppliers
from app.modules.tenders import public as tenders
from app.worker.runner import JobHandler, ProgressFn

import_all_models()  # the worker never loads the API, so register every table here

PROVENANCE_HEARTBEAT_S = 15.0  # well inside the job lease


def _ocr() -> knowledge.OcrRunner | None:
    settings = get_settings()
    if not settings.ocr_enabled:
        return None
    return knowledge.TesseractOcr(settings.tesseract_cmd, settings.ocr_page_timeout_s)


def ingest_document(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    result = knowledge.ingest_version(
        session, ctx, get_storage(), job.subject_id, _ocr(), get_settings().ocr_dpi, progress
    )
    # Same transaction as the ingest result: extraction is queued if and only if ingest committed.
    info = documents.processing_info(session, ctx, job.subject_id)
    for job_type in pipeline.job_types_for_kind(info.kind):
        jobs.enqueue(
            session, ctx, job_type, "document_version", job.subject_id, {"deep_scan": False}
        )
    return result.warnings


def ingest_started(session: Session, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
    knowledge.mark_processing(session, ctx, job.subject_id)


def ingest_failed(session: Session, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
    knowledge.mark_failed(session, ctx, job.subject_id)


def _pages(session: Session, ctx: OrgContext, version_id: UUID) -> list[extraction.PageInput]:
    return [
        extraction.PageInput(**p.model_dump())
        for p in knowledge.get_extraction_input(session, ctx, version_id)
    ]


def _guard(session: Session, ctx: OrgContext, version_id: UUID) -> None:
    if documents.processing_info(session, ctx, version_id).tender_archived:
        raise ProcessingFailed("TENDER_ARCHIVED", "The tender is archived.")


def _lock_tender(session: Session, ctx: OrgContext, version_id: UUID) -> None:
    """First lock of an extraction that touches matches: the order is tender, then runs, so a
    match decision or merge (which hold the tender lock) cannot interleave with it."""
    suppliers.lock_tender(
        session, ctx, documents.processing_info(session, ctx, version_id).tender_id
    )


def _cap(rows: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = get_settings().extract_max_rows_per_run
    if len(rows) > limit:
        warnings.append({"code": "ROW_CAP_REACHED", "count": len(rows) - limit})
        return rows[:limit]
    return rows


def _replace_warning(duplicates: int) -> list[dict[str, Any]]:
    return [{"code": "DUPLICATE_OF_REVIEWED", "count": duplicates}] if duplicates else []


def _enqueue_matching(session: Session, ctx: OrgContext, version_id: UUID) -> None:
    """Queue the tender's matching in the transaction that changed its inputs. `enqueue` returns
    the active job when one exists, so a burst of uploads yields one job. Known limit: a job that
    is already running does not see data written after it started; the next trigger does."""
    tender_id = documents.processing_info(session, ctx, version_id).tender_id
    jobs.enqueue(session, ctx, documents.MATCH_SUPPLIERS_JOB, "tender", tender_id, {})


def extract_boq(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    _guard(session, ctx, job.subject_id)
    result = extraction.parse_boq(_pages(session, ctx, job.subject_id))
    warnings = list(result.warnings)
    rows = _cap([c.as_row() for c in result.items], warnings)
    run = pipeline.run_for_job(session, ctx, job.id, "boq")
    _lock_tender(session, ctx, job.subject_id)
    pipeline.lock_runs(session, ctx, job.subject_id, "boq")
    stored = estimating.replace_unreviewed(
        session, ctx, job.subject_id, run.id, rows,
        protected_ids=suppliers.decided_boq_item_ids(session, ctx),
    )  # fmt: skip
    warnings += _replace_warning(stored.duplicates_of_reviewed)
    pipeline.finish_run(
        session, ctx, job.id, "boq", warnings,
        {"items": stored.inserted, "pages_with_boq": len(result.boq_pages)},
    )  # fmt: skip
    _enqueue_matching(session, ctx, job.subject_id)
    progress(1, 1)
    return warnings


def extract_requirements(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    settings = get_settings()
    _guard(session, ctx, job.subject_id)
    pages = _pages(session, ctx, job.subject_id)
    deep = bool(job.payload.get("deep_scan"))
    boq_pages = extraction.parse_boq(pages).boq_pages
    pf = extraction.prefilter(
        pages, boq_pages, deep, settings.extract_max_windows, settings.extract_window_chars
    )
    warnings: list[dict[str, Any]] = []
    if pf.low_yield:
        warnings.append({"code": "FILTER_LOW_YIELD", "candidates": pf.candidate_sentences})
    if pf.capped:
        warnings.append({"code": "WINDOW_CAP_REACHED", "limit": settings.extract_max_windows})
    try:
        outcome = extraction.extract_requirements(
            pf.windows, get_llm(),
            max_items_per_response=settings.extract_max_items_per_response, progress=progress,
        )  # fmt: skip
    except LLMUnavailable:
        raise ProcessingFailed("LLM_UNAVAILABLE", transient=True) from None
    warnings += outcome.warnings
    merged = extraction.merge_requirements(outcome.candidates)
    total = len(pf.windows)
    last = time.monotonic()

    def still_alive(_done: int, _total: int) -> None:  # renew the lease during provenance
        nonlocal last
        if time.monotonic() - last >= PROVENANCE_HEARTBEAT_S:
            progress(total, total)
            last = time.monotonic()

    located = extraction.attach_provenance(merged, pages, still_alive)
    progress(total, total)
    unverified = sum(1 for c in located if c.evidence_status == "evidence_unverified")
    if unverified:
        warnings.append({"code": "EVIDENCE_UNVERIFIED", "count": unverified})
    rows = _cap([c.as_row() for c in located], warnings)
    run = pipeline.run_for_job(session, ctx, job.id, "requirements")
    pipeline.lock_runs(session, ctx, job.subject_id, "requirements")
    stored = checklist.replace_unreviewed(session, ctx, job.subject_id, run.id, rows)
    warnings += _replace_warning(stored.duplicates_of_reviewed)
    pipeline.finish_run(
        session, ctx, job.id, "requirements", warnings,
        {"windows": len(pf.windows), "candidate_sentences": pf.candidate_sentences,
         "requirements": stored.inserted, "evidence_unverified": unverified},
    )  # fmt: skip
    return warnings


def extract_quotation(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    _guard(session, ctx, job.subject_id)
    result = extraction.parse_quotation(_pages(session, ctx, job.subject_id))
    warnings: list[dict[str, Any]] = [{"code": flag} for flag in result.header.flags]
    warnings += result.warnings
    rows = _cap([c.as_row() for c in result.items], warnings)
    run = pipeline.run_for_job(session, ctx, job.id, "quotation")
    _lock_tender(session, ctx, job.subject_id)
    pipeline.lock_runs(session, ctx, job.subject_id, "quotation")
    filename = documents.get_version(session, ctx, job.subject_id).filename
    stored = suppliers.store_quotation(
        session, ctx, job.subject_id, run.id, result.header.as_row(), rows, Path(filename).stem
    )
    warnings += _replace_warning(stored.duplicates_of_reviewed)
    pipeline.finish_run(
        session, ctx, job.id, "quotation", warnings,
        {"items": stored.inserted, "supplier_created": stored.supplier_created},
    )  # fmt: skip
    _enqueue_matching(session, ctx, job.subject_id)
    progress(1, 1)
    return warnings


def _tender_inputs(
    session: Session, ctx: OrgContext, tender_id: UUID
) -> tuple[list[suppliers.BoqInput], list[UUID], date | None]:
    """The current BoQ lines, current quotation versions and closing date of a tender."""
    boq_lines: list[suppliers.BoqInput] = []
    quote_versions: list[UUID] = []
    for d in documents.list_documents(session, ctx, tender_id):
        v = d.current_version
        if v is None:
            continue
        if d.kind == "quotation":
            quote_versions.append(v.id)
        elif d.kind in ("boq", "tender_document"):
            offset = 0
            while True:
                page = estimating.list_boq_items(session, ctx, v.id, 1000, offset)
                boq_lines += [
                    suppliers.BoqInput(i.id, i.item_no, i.description, i.unit)
                    for i in page
                    if i.review_status != "rejected"
                ]
                if len(page) < 1000:
                    break
                offset += 1000
    tender = tenders.get_tender(session, ctx, tender_id)
    return boq_lines, quote_versions, tender.closing_at.date() if tender.closing_at else None


def match_suppliers(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    suppliers.lock_tender(session, ctx, job.subject_id)  # before the reads, so they are current
    if tenders.get_tender(session, ctx, job.subject_id).status == "archived":
        raise ProcessingFailed("TENDER_ARCHIVED", "The tender is archived.")
    boq_lines, quote_versions, closing = _tender_inputs(session, ctx, job.subject_id)
    suppliers.match_tender(session, ctx, job.subject_id, boq_lines, quote_versions, closing)
    progress(1, 1)
    return []


def _starter(kind: str):
    def on_start(session: Session, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
        requirements = kind == "requirements"
        pipeline.start_run(
            session, ctx, job, kind,
            deep_scan=bool(job.payload.get("deep_scan")),
            prompt_version=extraction.PROMPT_VERSION if requirements else None,
            filter_version=extraction.FILTER_VERSION if requirements else None,
            schema_version=extraction.SCHEMA_VERSION if requirements else None,
            model=get_settings().llm_model if requirements else None,
        )  # fmt: skip

    return on_start


def _failer(kind: str):
    def on_failure(session: Session, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
        current = jobs.get_for_worker(session, job.id)
        pipeline.fail_run(session, ctx, job.id, kind, (current and current.error_code) or "FAILED")

    return on_failure


HANDLERS: dict[str, JobHandler] = {
    documents.MATCH_SUPPLIERS_JOB: JobHandler(run=match_suppliers),
    documents.INGEST_JOB: JobHandler(
        run=ingest_document, on_failure=ingest_failed, on_start=ingest_started
    ),
    documents.EXTRACT_BOQ_JOB: JobHandler(
        run=extract_boq, on_failure=_failer("boq"), on_start=_starter("boq")
    ),
    documents.EXTRACT_REQUIREMENTS_JOB: JobHandler(
        run=extract_requirements,
        on_failure=_failer("requirements"),
        on_start=_starter("requirements"),
    ),
    documents.EXTRACT_QUOTATION_JOB: JobHandler(
        run=extract_quotation, on_failure=_failer("quotation"), on_start=_starter("quotation")
    ),
}
