"""Document use cases: validated upload, versions, file access, processing hand-off."""

from __future__ import annotations

import hashlib
from typing import BinaryIO
from uuid import UUID

from sqlalchemy.orm import Session

from app.config import get_settings
from app.kernel import Conflict, NotFound, OrgContext, Permission, StoragePort, ValidationFailed
from app.modules.audit import public as audit
from app.modules.jobs import public as jobs
from app.modules.tenders import public as tenders

from .models import DOCUMENT_KINDS, Document, DocumentVersion
from .repo import DocumentRepo, VersionRepo
from .schemas import DocumentDTO, ProcessingInfo, UploadResultDTO, VersionDTO
from .sniff import MIME, safe_filename, sniff

INGEST_JOB = "ingest_document"
ALLOWED_EXTENSIONS = {"pdf", "xlsx", "csv", "docx"}


def _version_dto(v: DocumentVersion, job_id: UUID | None = None) -> VersionDTO:
    dto = VersionDTO.model_validate(v, from_attributes=True)
    dto.job_id = job_id
    return dto


def _document_dto(
    d: Document, current: DocumentVersion | None, job_id: UUID | None = None
) -> DocumentDTO:
    dto = DocumentDTO.model_validate(d, from_attributes=True)
    dto.current_version = _version_dto(current, job_id) if current else None
    return dto


def _validate_file(filename: str, data: bytes) -> tuple[str, str]:
    """Return (safe filename, detected format). Rejects anything that is not what it claims."""
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if not data:
        raise ValidationFailed("The file is empty.", {"field": "file"})
    if len(data) > max_bytes:
        raise ValidationFailed(
            f"The file is larger than the {get_settings().max_upload_mb} MB limit.",
            {"field": "file"},
        )
    name = safe_filename(filename)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationFailed(
            "Unsupported file type. Upload a PDF, XLSX, CSV or DOCX file.", {"field": "file"}
        )
    detected = sniff(data)
    if detected != extension:
        raise ValidationFailed("The file content does not match its extension.", {"field": "file"})
    return name, detected


def _store_version(
    session: Session,
    ctx: OrgContext,
    storage: StoragePort,
    document: Document,
    filename: str,
    file_format: str,
    data: bytes,
) -> tuple[DocumentVersion, UUID]:
    versions = VersionRepo(session, ctx)
    versions.clear_current(document.id)
    number = versions.next_number(document.id)
    key = (
        f"org/{ctx.organisation_id}/tenders/{document.tender_id}/{document.id}/v{number}/{filename}"
    )
    storage.put(key, data)  # file first; the database row is committed with the request
    version = versions.add(
        DocumentVersion(
            document_id=document.id,
            version_number=number,
            filename=filename,
            storage_key=key,
            mime_type=MIME[file_format],
            file_format=file_format,
            file_size=len(data),
            checksum_sha256=hashlib.sha256(data).hexdigest(),
            processing_status="pending",
            is_current=True,
            uploaded_by=ctx.user_id,
        )
    )
    job = jobs.enqueue(session, ctx, INGEST_JOB, "document_version", version.id)
    return version, job.id


def upload_document(
    session: Session,
    ctx: OrgContext,
    storage: StoragePort,
    tender_id: UUID,
    kind: str,
    filename: str,
    data: bytes,
    title: str | None = None,
) -> UploadResultDTO:
    ctx.require(Permission.UPLOAD_DOCUMENTS)
    if kind not in DOCUMENT_KINDS:
        raise ValidationFailed(
            f"Kind must be one of: {', '.join(DOCUMENT_KINDS)}.", {"field": "kind"}
        )
    tender = tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    if tender.status == "archived":
        raise Conflict("This tender is archived. Re-open it before uploading documents.")
    name, file_format = _validate_file(filename, data)
    document = DocumentRepo(session, ctx).add(
        Document(
            tender_id=tender_id, kind=kind, title=(title or name)[:300], created_by=ctx.user_id
        )
    )
    version, job_id = _store_version(session, ctx, storage, document, name, file_format, data)
    audit.record(session, ctx, "document", document.id, "uploaded",
                 {"kind": kind, "filename": name})  # fmt: skip
    return UploadResultDTO(
        document=_document_dto(document, version, job_id),
        version=_version_dto(version, job_id),
        job_id=job_id,
    )


def upload_new_version(
    session: Session,
    ctx: OrgContext,
    storage: StoragePort,
    document_id: UUID,
    filename: str,
    data: bytes,
) -> UploadResultDTO:
    ctx.require(Permission.UPLOAD_DOCUMENTS)
    document = DocumentRepo(session, ctx).get(document_id)
    name, file_format = _validate_file(filename, data)
    version, job_id = _store_version(session, ctx, storage, document, name, file_format, data)
    audit.record(session, ctx, "document", document.id, "new_version",
                 {"filename": name, "count": version.version_number})  # fmt: skip
    return UploadResultDTO(
        document=_document_dto(document, version, job_id),
        version=_version_dto(version, job_id),
        job_id=job_id,
    )


def list_documents(session: Session, ctx: OrgContext, tender_id: UUID) -> list[DocumentDTO]:
    ctx.require(Permission.READ)
    tenders.get_tender(session, ctx, tender_id)
    documents = DocumentRepo(session, ctx).for_tender(tender_id)
    current = VersionRepo(session, ctx).current_for_documents([d.id for d in documents])
    out = []
    for d in documents:
        version = current.get(d.id)
        job = jobs.latest_job_for_subject(session, ctx, version.id) if version else None
        out.append(_document_dto(d, version, job.id if job else None))
    return out


def get_document(session: Session, ctx: OrgContext, document_id: UUID) -> DocumentDTO:
    ctx.require(Permission.READ)
    document = DocumentRepo(session, ctx).get(document_id)
    current = VersionRepo(session, ctx).current_for_documents([document.id]).get(document.id)
    job = jobs.latest_job_for_subject(session, ctx, current.id) if current else None
    return _document_dto(document, current, job.id if job else None)


def list_versions(session: Session, ctx: OrgContext, document_id: UUID) -> list[VersionDTO]:
    ctx.require(Permission.READ)
    DocumentRepo(session, ctx).get(document_id)
    out = []
    for v in VersionRepo(session, ctx).for_document(document_id):
        job = jobs.latest_job_for_subject(session, ctx, v.id)
        out.append(_version_dto(v, job.id if job else None))
    return out


def get_version(session: Session, ctx: OrgContext, version_id: UUID) -> VersionDTO:
    ctx.require(Permission.READ)
    v = VersionRepo(session, ctx).get(version_id)
    job = jobs.latest_job_for_subject(session, ctx, v.id)
    return _version_dto(v, job.id if job else None)


def open_version_file(
    session: Session, ctx: OrgContext, storage: StoragePort, version_id: UUID
) -> tuple[VersionDTO, BinaryIO]:
    """The original file of a version. Existence is checked within the organisation first."""
    ctx.require(Permission.READ)
    v = VersionRepo(session, ctx).get(version_id)
    if not storage.exists(v.storage_key):
        raise NotFound("The stored file is missing.")
    return _version_dto(v), storage.open(v.storage_key)


# --- used by the ingest worker -----------------------------------------------------------------


def processing_info(session: Session, ctx: OrgContext, version_id: UUID) -> ProcessingInfo:
    v = VersionRepo(session, ctx).get(version_id)
    document = DocumentRepo(session, ctx).get(v.document_id)
    return ProcessingInfo(
        version_id=v.id,
        document_id=document.id,
        tender_id=document.tender_id,
        storage_key=v.storage_key,
        file_format=v.file_format,
        filename=v.filename,
    )


def set_processing_status(session: Session, ctx: OrgContext, version_id: UUID, status: str) -> None:
    VersionRepo(session, ctx).get(version_id).processing_status = status
    session.flush()
