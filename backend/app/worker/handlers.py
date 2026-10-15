"""Job handlers: the glue between the queue and the modules."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.infrastructure.storage import get_storage
from app.kernel import OrgContext
from app.modules.audit import public as _audit  # noqa: F401 - registers the audit models
from app.modules.documents import public as documents
from app.modules.identity import public as _identity  # noqa: F401 - registers the organisation models
from app.modules.jobs import public as jobs
from app.modules.knowledge import public as knowledge
from app.modules.tenders import public as _tenders  # noqa: F401 - registers the tender models
from app.worker.runner import JobHandler, ProgressFn


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
    return result.warnings


def ingest_failed(session: Session, ctx: OrgContext, job: jobs.ClaimedJob) -> None:
    knowledge.mark_failed(session, ctx, job.subject_id)


HANDLERS: dict[str, JobHandler] = {
    documents.INGEST_JOB: JobHandler(run=ingest_document, on_failure=ingest_failed),
}
