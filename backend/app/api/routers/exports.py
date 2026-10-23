"""Exports: the estimate workbook and the checklist report (Slice 6a, ADR-0007).

The router does the orchestration the `reporting` module may not: it reads the estimate, the BoQ
and the checklist through the other modules' public APIs, maps them to the plain renderer inputs
and hands them to `reporting.create_export`."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import BinaryIO
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api import estimate_inputs
from app.api.deps import Ctx, DbSession, Storage
from app.api.ratelimit import limiter
from app.kernel import Conflict, NotFound, OrgContext, Permission
from app.modules.checklist import public as checklist
from app.modules.documents import public as documents
from app.modules.estimates import public as estimates
from app.modules.identity import public as identity
from app.modules.reporting import public as reporting
from app.modules.suppliers import public as suppliers
from app.modules.tenders import public as tenders

router = APIRouter(prefix="/api/v1", tags=["exports"])

PAGE = 1000


def _stream(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(64 * 1024):
            yield chunk
    finally:
        handle.close()


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _user_name(session: Session, ctx: OrgContext) -> str | None:
    return identity.member_names(session, ctx, {ctx.user_id}).get(ctx.user_id)


def _choose_version(
    summaries: list[estimates.EstimateSummaryDTO], estimate_id: UUID | None
) -> estimates.EstimateSummaryDTO:
    """D2: the given version; else the highest approved; else the newest; else 409."""
    if estimate_id is not None:
        chosen = next((e for e in summaries if e.id == estimate_id), None)
        if chosen is None:
            raise NotFound("Estimate not found.")
        return chosen
    if not summaries:
        raise Conflict("This tender has no estimate to export yet.", code="no_estimate")
    approved = [e for e in summaries if e.status == "approved"]
    return max(approved or summaries, key=lambda e: e.version)


def _estimate_payload(
    session: Session, ctx: OrgContext, tender: tenders.TenderDTO, estimate_id: UUID | None
) -> tuple[reporting.EstimateExportInput, UUID, UUID]:
    """The payload, the chosen estimate id and the tender that estimate belongs to."""
    # Deliberate: with no estimate_id the version is chosen before the lock (a later move is
    # caught by the status re-read below).
    chosen = _choose_version(estimates.list_estimates(session, ctx, tender.id), estimate_id)
    live = estimates.LiveInputs()
    if chosen.status != "approved":
        # Draft and reviewed (a reviewed estimate can be reopened) take the tender lock first,
        # then read the status again: a move may have committed while this request waited.
        suppliers.lock_tender(session, ctx, tender.id)
        session.expire_all()  # drop rows read before the lock
        current = next(
            (e for e in estimates.list_estimates(session, ctx, tender.id) if e.id == chosen.id),
            None,
        )
        if current is None:
            raise NotFound("Estimate not found.")
        if current.status == "draft":
            live = estimate_inputs.live_inputs(session, ctx, tender.id)
    dto, lines = estimates.export_snapshot(session, ctx, chosen.id, live)
    ids = {i for i in (dto.reviewed_by, dto.approved_by) if i}
    names = identity.member_names(session, ctx, ids) if ids else {}
    default_markup = Decimal(dto.markup_percent)
    export_lines = tuple(
        reporting.ExportLine(
            position=x.position, section=x.section, item_no=x.item_no,
            description=x.description, unit=x.unit, quantity=_decimal(x.quantity),
            price_source=x.price_source,  # type: ignore[arg-type]
            supplier_name=x.supplier_name,
            quoted_unit_price=_decimal(x.quoted_unit_price),
            quoted_currency=x.quoted_currency,
            quoted_includes_vat=x.quoted_includes_vat,
            unit_price_ex_vat=_decimal(x.unit_price_ex_vat),
            labour_rate=_decimal(x.labour_rate),
            material_cost=_decimal(x.material_cost), labour_cost=_decimal(x.labour_cost),
            cost=_decimal(x.cost),
            markup_percent=(
                default_markup
                if x.markup_override_percent is None
                else Decimal(x.markup_override_percent)
            ) if x.status == "priced" else None,
            markup=_decimal(x.markup), total=_decimal(x.total), status=x.status,
            flags=tuple(x.flags), exclude_reason=x.exclude_reason,
        )
        for x in lines
    )  # fmt: skip
    totals = (
        reporting.ExportTotals(
            subtotal_cost=Decimal(dto.totals.subtotal_cost),
            markup_total=Decimal(dto.totals.markup_total),
            subtotal_ex_vat=Decimal(dto.totals.subtotal_ex_vat),
            vat_total=Decimal(dto.totals.vat_total),
            total_inc_vat=Decimal(dto.totals.total_inc_vat),
        )
        if dto.totals
        else None
    )
    payload = reporting.EstimateExportInput(
        tender_title=tender.title,
        tender_reference=tender.reference_number,
        client_name=tender.client_name,
        version=dto.version,
        status=dto.status,  # type: ignore[arg-type]
        currency=dto.currency,
        vat_rate=Decimal(dto.vat_rate),
        markup_basis=dto.markup_basis,
        markup_percent=default_markup,
        totals=totals,
        priced=dto.priced, excluded=dto.excluded, unresolved=dto.unresolved,
        changed=dto.changed, incomplete=dto.incomplete,
        reviewed_by_name=names.get(dto.reviewed_by) if dto.reviewed_by else None,
        reviewed_at=dto.reviewed_at,
        approved_by_name=names.get(dto.approved_by) if dto.approved_by else None,
        approved_at=dto.approved_at,
        generated_by_name=_user_name(session, ctx),
        lines=export_lines,
    )  # fmt: skip
    return payload, chosen.id, dto.tender_id


def _checklist_payload(
    session: Session, ctx: OrgContext, tender: tenders.TenderDTO
) -> reporting.ChecklistExportInput:
    docs = [d for d in documents.list_documents(session, ctx, tender.id) if d.current_version]
    order: dict[UUID, int] = {}
    titles: dict[UUID, str] = {}
    for i, d in enumerate(docs):
        v = d.current_version
        order[v.id] = i
        titles[v.id] = d.title or v.filename
    rows: list[checklist.RequirementDTO] = []
    rejected = 0
    limit = reporting.max_rows()
    offset = 0
    while order:
        page = checklist.list_for_versions(session, ctx, list(order), None, None, PAGE, offset)
        for r in page:
            if r.review_status == "rejected":
                rejected += 1
            else:
                rows.append(r)
        if len(page) < PAGE or len(rows) > limit:
            break
        offset += PAGE
    # The repository already orders by (source_order, position); a stable sort by document keeps
    # that order inside each document.
    rows.sort(key=lambda r: order[r.document_version_id])
    return reporting.ChecklistExportInput(
        tender_title=tender.title,
        tender_reference=tender.reference_number,
        client_name=tender.client_name,
        closing_at=tender.closing_at,
        generated_by_name=_user_name(session, ctx),
        rows=tuple(
            reporting.ChecklistRow(
                requirement_type=r.requirement_type,
                mandatory_status=r.mandatory_status,
                description=r.description,
                review_status=r.review_status,
                document_title=titles[r.document_version_id],
                page_number=r.page_number,
                evidence_verified=r.evidence_status == "verified",
            )
            for r in rows
        ),
        rejected_count=rejected,
    )


@router.post("/tenders/{tender_id}/exports", response_model=reporting.ExportDTO, status_code=201)
def create_export(
    tender_id: UUID, body: reporting.ExportCreate, ctx: Ctx, session: DbSession, storage: Storage
):
    tender = tenders.get_tender(session, ctx, tender_id)  # NotFound across organisations
    ctx.require(Permission.EXPORT)
    limiter.check(f"export:{ctx.user_id}", 10, 60)
    if body.kind == "estimate_xlsx":
        payload, estimate_id, estimate_tender_id = _estimate_payload(
            session, ctx, tender, body.estimate_id
        )
        return reporting.create_export(
            session, ctx, storage, tender_id, body.kind, payload,
            estimate_id=estimate_id, estimate_tender_id=estimate_tender_id,
        )  # fmt: skip
    return reporting.create_export(
        session, ctx, storage, tender_id, body.kind, _checklist_payload(session, ctx, tender)
    )


@router.get("/exports/{export_id}", response_model=reporting.ExportDTO)
def get_export(export_id: UUID, ctx: Ctx, session: DbSession):
    dto = reporting.get_export(session, ctx, export_id)
    name = identity.member_names(session, ctx, {dto.generated_by}).get(dto.generated_by)
    return dto.model_copy(update={"generated_by_name": name})


@router.get("/exports/{export_id}/download")
def download_export(export_id: UUID, ctx: Ctx, session: DbSession, storage: Storage):
    dto, handle = reporting.open_export_file(session, ctx, storage, export_id)
    return StreamingResponse(
        _stream(handle),
        media_type=dto.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{dto.file_name}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
            "Content-Security-Policy": "sandbox",
            "Content-Length": str(dto.file_size),
        },
    )
