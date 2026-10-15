"""Documents: upload, versions, file download, extracted pages, search."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, BinaryIO
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import Ctx, DbSession, Storage
from app.config import get_settings
from app.modules.documents import public as documents
from app.modules.knowledge import public as knowledge

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _read_upload(file: UploadFile) -> bytes:
    """Read at most the limit plus one byte, so oversize files are rejected without loading them."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    return file.file.read(limit + 1)


def _stream(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(64 * 1024):
            yield chunk
    finally:
        handle.close()


@router.post(
    "/tenders/{tender_id}/documents", response_model=documents.UploadResultDTO, status_code=201
)
def upload_document(
    tender_id: UUID,
    ctx: Ctx,
    session: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form()] = "tender_document",
    title: Annotated[str | None, Form()] = None,
):
    return documents.upload_document(
        session,
        ctx,
        storage,
        tender_id,
        kind,
        file.filename or "document",
        _read_upload(file),
        title,
    )


@router.post(
    "/documents/{document_id}/versions", response_model=documents.UploadResultDTO, status_code=201
)
def upload_version(
    document_id: UUID,
    ctx: Ctx,
    session: DbSession,
    storage: Storage,
    file: Annotated[UploadFile, File()],
):
    return documents.upload_new_version(
        session, ctx, storage, document_id, file.filename or "document", _read_upload(file)
    )


@router.get("/tenders/{tender_id}/documents", response_model=list[documents.DocumentDTO])
def list_documents(tender_id: UUID, ctx: Ctx, session: DbSession):
    return documents.list_documents(session, ctx, tender_id)


@router.get("/documents/{document_id}", response_model=documents.DocumentDTO)
def get_document(document_id: UUID, ctx: Ctx, session: DbSession):
    return documents.get_document(session, ctx, document_id)


@router.get("/documents/{document_id}/versions", response_model=list[documents.VersionDTO])
def list_versions(document_id: UUID, ctx: Ctx, session: DbSession):
    return documents.list_versions(session, ctx, document_id)


@router.get("/document-versions/{version_id}/file")
def download_file(version_id: UUID, ctx: Ctx, session: DbSession, storage: Storage):
    """The original file. Only PDFs are shown inline (for the viewer); the rest download."""
    version, handle = documents.open_version_file(session, ctx, storage, version_id)
    disposition = "inline" if version.file_format == "pdf" else "attachment"
    return StreamingResponse(
        _stream(handle),
        media_type=version.mime_type,
        headers={
            "Content-Disposition": f'{disposition}; filename="{version.filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Length": str(version.file_size),
        },
    )


@router.get("/document-versions/{version_id}/pages", response_model=list[knowledge.PageDTO])
def list_pages(version_id: UUID, ctx: Ctx, session: DbSession):
    return knowledge.list_pages(session, ctx, version_id)


@router.get(
    "/document-versions/{version_id}/pages/{page_number}", response_model=knowledge.PageDetailDTO
)
def get_page(version_id: UUID, page_number: int, ctx: Ctx, session: DbSession):
    return knowledge.get_page(session, ctx, version_id, page_number)


@router.get("/tenders/{tender_id}/search", response_model=list[knowledge.SearchHitDTO])
def search(
    tender_id: UUID,
    ctx: Ctx,
    session: DbSession,
    q: Annotated[str, Query(max_length=200)],
    limit: int = 20,
):
    return knowledge.search_tender(session, ctx, tender_id, q, limit)
