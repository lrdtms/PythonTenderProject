"""Export use cases: render a file, store it, record it, and hand it back (ADR-0007).

The file is written before its row is committed; `delete_on_rollback` removes it when the
transaction fails. Audit metadata carries only ids, counts, the status label and the kind.
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.db.stored_files import delete_on_rollback
from app.kernel import NotFound, OrgContext, Permission, StoragePort, ValidationFailed
from app.modules.audit import public as audit
from app.modules.identity import public as identity

from .models import Export
from .pdf import checklist_label, render_checklist_pdf
from .repo import ExportRepo
from .safe_text import export_filename
from .schemas import (
    ChecklistExportInput,
    EstimateExportInput,
    ExportDTO,
    ExportKind,
)
from .xlsx import is_draft, render_estimate_xlsx

MAX_ROWS = 5_000  # rejected requirements are never in `rows`, so they do not count

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_TYPE = "application/pdf"


def max_rows() -> int:
    """Read at call time so a test (or a later setting) that patches `MAX_ROWS` is honoured."""
    return MAX_ROWS


def _dto(row: Export, names: dict[UUID, str]) -> ExportDTO:
    return ExportDTO(
        id=row.id,
        tender_id=row.tender_id,
        kind=row.kind,  # type: ignore[arg-type]
        estimate_id=row.estimate_id,
        estimate_version=row.estimate_version,
        label=row.label,  # type: ignore[arg-type]
        file_name=row.file_name,
        content_type=row.content_type,
        file_size=row.file_size,
        row_count=row.row_count,
        generated_by=row.generated_by,
        generated_by_name=names.get(row.generated_by),
        generated_at=row.generated_at,
    )


def _dto_for(session: Session, ctx: OrgContext, row: Export) -> ExportDTO:
    return _dto(row, identity.member_names(session, ctx, {row.generated_by}))


def create_export(
    session: Session,
    ctx: OrgContext,
    storage: StoragePort,
    tender_id: UUID,
    kind: ExportKind,
    payload: EstimateExportInput | ChecklistExportInput,
    estimate_id: UUID | None = None,
    estimate_tender_id: UUID | None = None,
) -> ExportDTO:
    """Render `payload`, store the file and record it. `estimate_tender_id` is the tender the
    estimate really belongs to, looked up by the router; it must equal `tender_id`."""
    ctx.require(Permission.EXPORT)
    export_id, generated_at = uuid4(), datetime.now(UTC)
    metadata_version: int | None = None
    if kind == "estimate_xlsx":
        if not isinstance(payload, EstimateExportInput):
            raise ValidationFailed("The data does not match this kind of export.")
        if estimate_id is None or estimate_tender_id != tender_id:
            raise ValidationFailed("The estimate does not belong to this tender.")
        rows = len(payload.lines)
    elif kind == "checklist_pdf":
        if not isinstance(payload, ChecklistExportInput):
            raise ValidationFailed("The data does not match this kind of export.")
        if estimate_id is not None:
            raise ValidationFailed("A checklist export has no estimate.")
        rows = len(payload.rows)
    else:
        raise ValidationFailed("Unknown export kind.")
    if rows > max_rows():
        raise ValidationFailed(
            f"This export has more than {max_rows():,} rows. Narrow it down and try again.",
            code="export_too_large",
        )
    payload = replace(payload, generated_at=generated_at, export_id=export_id)

    if isinstance(payload, EstimateExportInput):
        label: str = payload.status
        metadata_version = payload.version
        data = render_estimate_xlsx(payload)
        file_name = export_filename(
            payload.tender_title, "estimate", payload.version, is_draft(label), generated_at.date()
        )
        ext, content_type = "xlsx", XLSX_TYPE
    else:
        label = checklist_label(payload)
        data = render_checklist_pdf(payload)
        file_name = export_filename(
            payload.tender_title, "checklist", None, label == "draft", generated_at.date()
        )
        ext, content_type = "pdf", PDF_TYPE

    key = f"org/{ctx.organisation_id}/tenders/{tender_id}/exports/{export_id}.{ext}"
    storage.put(key, data)  # file first; the row is committed with the request
    delete_on_rollback(session, storage, key)
    row = ExportRepo(session, ctx).add(
        Export(
            id=export_id,
            tender_id=tender_id,
            kind=kind,
            estimate_id=estimate_id,
            estimate_version=metadata_version,
            label=label,
            file_key=key,
            file_name=file_name,
            content_type=content_type,
            file_size=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            row_count=rows,
            generated_by=ctx.user_id,
            generated_at=generated_at,
        )
    )
    audit.record(
        session,
        ctx,
        "export",
        export_id,
        "export_created",
        {
            "kind": kind,
            "estimate_id": str(estimate_id) if estimate_id else None,  # JSONB cannot hold a UUID
            "version": metadata_version,
            "status": label,
            "count": rows,
        },
    )
    session.flush()
    return _dto_for(session, ctx, row)


def get_export(session: Session, ctx: OrgContext, export_id: UUID) -> ExportDTO:
    ctx.require(Permission.READ)
    return _dto_for(session, ctx, ExportRepo(session, ctx).get(export_id))


def open_export_file(
    session: Session, ctx: OrgContext, storage: StoragePort, export_id: UUID
) -> tuple[ExportDTO, BinaryIO]:
    """The stored file of an export. Existence is checked within the organisation first."""
    ctx.require(Permission.EXPORT)
    row = ExportRepo(session, ctx).get(export_id)
    if not storage.exists(row.file_key):
        raise NotFound("The stored file is missing.")
    audit.record(session, ctx, "export", row.id, "export_downloaded", {"kind": row.kind})
    return _dto_for(session, ctx, row), storage.open(row.file_key)
