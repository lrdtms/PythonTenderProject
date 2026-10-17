"""Suppliers: list, create, rename, annotate and merge (Slice 5a).

A merge moves quotations between suppliers, so it takes the tender lock of every affected tender
(in sorted order, so two merges cannot deadlock) before it changes anything, and refuses when any
of those tenders is archived."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.kernel import Conflict
from app.modules.documents import public as documents
from app.modules.suppliers import public as suppliers

router = APIRouter(prefix="/api/v1/suppliers", tags=["suppliers"])


@router.get("", response_model=list[suppliers.SupplierDTO])
def list_suppliers(ctx: Ctx, session: DbSession):
    return suppliers.list_suppliers(session, ctx)


@router.post("", response_model=suppliers.SupplierDTO, status_code=201)
def create_supplier(body: suppliers.SupplierCreate, ctx: Ctx, session: DbSession):
    return suppliers.create_supplier(session, ctx, body)


@router.get("/{supplier_id}", response_model=suppliers.SupplierDTO)
def get_supplier(supplier_id: UUID, ctx: Ctx, session: DbSession):
    return suppliers.get_supplier(session, ctx, supplier_id)


@router.patch("/{supplier_id}", response_model=suppliers.SupplierDTO)
def update_supplier(supplier_id: UUID, body: suppliers.SupplierPatch, ctx: Ctx, session: DbSession):
    return suppliers.update_supplier(session, ctx, supplier_id, body)


@router.post("/{supplier_id}/merge", response_model=suppliers.SupplierDTO)
def merge_supplier(supplier_id: UUID, body: suppliers.SupplierMerge, ctx: Ctx, session: DbSession):
    """Merge this supplier into `into_id`; the source is deleted. Returns the target."""
    infos = [
        documents.processing_info(session, ctx, version_id)
        for version_id in sorted(suppliers.tenders_of_supplier(session, ctx, supplier_id))
    ]
    if any(info.tender_archived for info in infos):
        raise Conflict(
            "A tender with this supplier's quotations is archived. Re-open it before merging.",
            code="tender_archived",
        )
    for tender_id in sorted({info.tender_id for info in infos}):
        suppliers.lock_tender(session, ctx, tender_id)
    return suppliers.merge_suppliers(session, ctx, supplier_id, body.into_id)
