"""Job handlers: the glue between the queue and the modules."""

from __future__ import annotations

import time
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


def _cap(rows: list[dict[str, Any]], warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    limit = get_settings().extract_max_rows_per_run
    if len(rows) > limit:
        warnings.append({"code": "ROW_CAP_REACHED", "count": len(rows) - limit})
        return rows[:limit]
    return rows


def _replace_warning(duplicates: int) -> list[dict[str, Any]]:
    return [{"code": "DUPLICATE_OF_REVIEWED", "count": duplicates}] if duplicates else []


def extract_boq(
    session: Session, ctx: OrgContext, job: jobs.ClaimedJob, progress: ProgressFn
) -> list[dict[str, Any]]:
    _guard(session, ctx, job.subject_id)
    result = extraction.parse_boq(_pages(session, ctx, job.subject_id))
    warnings = list(result.warnings)
    rows = _cap([c.as_row() for c in result.items], warnings)
    run = pipeline.run_for_job(session, ctx, job.id, "boq")
    pipeline.lock_runs(session, ctx, job.subject_id, "boq")
    stored = estimating.replace_unreviewed(session, ctx, job.subject_id, run.id, rows)
    warnings += _replace_warning(stored.duplicates_of_reviewed)
    pipeline.finish_run(
        session, ctx, job.id, "boq", warnings,
        {"items": stored.inserted, "pages_with_boq": len(result.boq_pages)},
    )  # fmt: skip
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
    progress(1, 1)
    return warnings


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
