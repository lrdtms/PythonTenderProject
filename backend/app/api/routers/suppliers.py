"""Suppliers: list, create, rename, annotate and merge (Slice 5a).

A merge moves quotations between suppliers, so it takes the tender lock of every affected tender
(in sorted order, so two merges cannot deadlock) before it changes anything, and refuses when any
of those tenders is archived."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.api.deps import Ctx, DbSession
from app.db.session import set_org
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


def _affected(session, ctx, supplier_id: UUID) -> dict[UUID, bool]:
    """tender id -> archived, for every tender holding a quotation of the supplier."""
    out: dict[UUID, bool] = {}
    for version_id in suppliers.tenders_of_supplier(session, ctx, supplier_id):
        info = documents.processing_info(session, ctx, version_id)
        out[info.tender_id] = info.tender_archived
    return out


MERGE_ATTEMPTS = 3


@router.post("/{supplier_id}/merge", response_model=suppliers.SupplierDTO)
def merge_supplier(supplier_id: UUID, body: suppliers.SupplierMerge, ctx: Ctx, session: DbSession):
    """Merge this supplier into `into_id`; the source is deleted. Returns the target.

    A concurrent extraction can attach a quotation of another tender to the source while we lock.
    So: lock the tenders read, re-read, and if the set grew release everything (nothing is
    written yet, so a rollback is safe) and start again, up to MERGE_ATTEMPTS times."""
    for _ in range(MERGE_ATTEMPTS):
        wanted = set(_affected(session, ctx, supplier_id))
        for tender_id in sorted(wanted):
            suppliers.lock_tender(session, ctx, tender_id)
        now = _affected(session, ctx, supplier_id)
        if set(now) <= wanted:
            if any(now.values()):
                raise Conflict(
                    "A tender with this supplier's quotations is archived. Re-open it before "
                    "merging.",
                    code="tender_archived",
                )
            return suppliers.merge_suppliers(session, ctx, supplier_id, body.into_id)
        session.rollback()  # releases the advisory transaction locks
        set_org(session, ctx.organisation_id)
    raise Conflict("The suppliers changed while merging. Try again.", code="try_again")
