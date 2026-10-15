"""Ingestion (parse, OCR, chunk, store) and search."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import NotFound, OrgContext, Permission, StoragePort, ValidationFailed
from app.modules.documents import public as documents

from .chunking import chunk_document
from .ocr import OcrRunner
from .parsers import Progress, parse_document
from .repo import ChunkRepo, PageRepo
from .schemas import IngestResult, PageDetailDTO, PageDTO, SearchHitDTO

PAGE_WARNINGS = {
    "ocr_failed": "OCR_FAILED",
    "low_confidence": "OCR_LOW_CONFIDENCE",
    "ocr_unavailable": "OCR_UNAVAILABLE",
}
MAX_QUERY_CHARS = 200
READY_STATUSES = ("ready", "ready_with_warnings")


def ingest_version(
    session: Session,
    ctx: OrgContext,
    storage: StoragePort,
    version_id: UUID,
    ocr: OcrRunner | None = None,
    ocr_dpi: int = 300,
    progress: Progress | None = None,
) -> IngestResult:
    """Parse a stored file and replace its pages and chunks. Safe to run again (idempotent):
    the original file is never touched, and a failure leaves the previous results in place."""
    info = documents.processing_info(session, ctx, version_id)
    with storage.open(info.storage_key) as fh:
        data = fh.read()
    parsed = parse_document(info.file_format, data, ocr, ocr_dpi, progress)

    page_rows: list[dict[str, Any]] = [
        {
            "page_number": p.page_number,
            "label": p.label,
            "text": p.text,
            "text_source": p.text_source,
            "ocr_confidence": p.ocr_confidence,
            "status": p.status,
            "tables": p.tables,
        }
        for p in parsed
    ]
    PageRepo(session, ctx).replace_for_version(version_id, page_rows)
    drafts = chunk_document([(p.page_number, p.text) for p in parsed])
    ChunkRepo(session, ctx).replace_for_version(
        version_id,
        [
            {"ordinal": i, "page_number": c.page_number, "section": c.section, "text": c.text}
            for i, c in enumerate(drafts)
        ],
    )

    warnings: list[dict[str, Any]] = []
    for status, code in PAGE_WARNINGS.items():
        pages = [p.page_number for p in parsed if p.status == status]
        if pages:
            warnings.append({"code": code, "pages": pages})
    final = "ready_with_warnings" if warnings else "ready"
    documents.set_processing_status(session, ctx, version_id, final)
    return IngestResult(pages=len(parsed), chunks=len(drafts), warnings=warnings)


def mark_processing(session: Session, ctx: OrgContext, version_id: UUID) -> None:
    """Committed on its own by the worker before ingest starts, so clients can see it."""
    documents.set_processing_status(session, ctx, version_id, "processing")


def mark_failed(session: Session, ctx: OrgContext, version_id: UUID) -> None:
    """A ready version was ingested and committed (its job's completion record failed): keep it.
    Every attempt starts by setting `processing`, so a real failure never finds it ready."""
    if documents.get_version(session, ctx, version_id).processing_status in READY_STATUSES:
        return
    documents.set_processing_status(session, ctx, version_id, "failed")


def _page_dto(p: Any) -> PageDTO:
    return PageDTO(
        page_number=p.page_number,
        label=p.label,
        status=p.status,
        text_source=p.text_source,
        ocr_confidence=p.ocr_confidence,
        char_count=len(p.text),
        table_count=len(p.tables),
    )


def list_pages(session: Session, ctx: OrgContext, version_id: UUID) -> list[PageDTO]:
    ctx.require(Permission.READ)
    documents.get_version(session, ctx, version_id)  # NotFound for another organisation
    return [_page_dto(p) for p in PageRepo(session, ctx).for_version(version_id)]


def get_page(
    session: Session, ctx: OrgContext, version_id: UUID, page_number: int
) -> PageDetailDTO:
    ctx.require(Permission.READ)
    documents.get_version(session, ctx, version_id)
    page = PageRepo(session, ctx).one(version_id, page_number)
    if page is None:
        raise NotFound("Page not found")
    return PageDetailDTO(**_page_dto(page).model_dump(), text=page.text, tables=page.tables)


def search_tender(
    session: Session, ctx: OrgContext, tender_id: UUID, query: str, limit: int = 20
) -> list[SearchHitDTO]:
    ctx.require(Permission.READ)
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValidationFailed(
            f"Enter a search of 1 to {MAX_QUERY_CHARS} characters.", {"field": "q"}
        )
    documents.list_documents(session, ctx, tender_id)  # NotFound for another organisation
    hits = ChunkRepo(session, ctx).search(tender_id, query, max(1, min(limit, 50)))
    return [SearchHitDTO(**h) for h in hits]
