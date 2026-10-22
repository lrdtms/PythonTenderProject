"""Estimates: pricing defaults, create, and read (Slice 5b).

The router does the orchestration the `estimates` module may not: it takes the tender lock, then
reads the tender's current BoQ lines and confirmed matches through the other modules' public
APIs and maps them to the plain inputs the estimates module works on."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import Ctx, DbSession
from app.api.tender_guard import refuse_archived
from app.kernel import NotFound, Permission
from app.modules.documents import public as documents
from app.modules.estimates import public as estimates
from app.modules.estimating import public as estimating
from app.modules.suppliers import public as suppliers
from app.modules.tenders import public as tenders

router = APIRouter(prefix="/api/v1", tags=["estimates"])

PAGE = 1000


def _current(session, ctx, tender_id: UUID) -> tuple[list[estimating.BoqItemDTO], list[UUID]]:
    """The tender's current, non-rejected BoQ lines in document order, and the current quotation
    versions."""
    boq: list[estimating.BoqItemDTO] = []
    quote_versions: list[UUID] = []
    for d in documents.list_documents(session, ctx, tender_id):  # NotFound for another org
        v = d.current_version
        if v is None:
            continue
        if d.kind == "quotation":
            quote_versions.append(v.id)
        elif d.kind in ("boq", "tender_document"):
            offset = 0
            while True:
                page = estimating.list_boq_items(session, ctx, v.id, PAGE, offset)
                boq += [i for i in page if i.review_status != "rejected"]
                if len(page) < PAGE:
                    break
                offset += PAGE
    return boq, quote_versions


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _boq_inputs(boq: list[estimating.BoqItemDTO]) -> list[estimates.BoqInput]:
    return [
        estimates.BoqInput(
            id=i.id, section=i.section, item_no=i.item_no, description=i.description,
            unit=i.unit, quantity=_decimal(i.quantity), review_status=i.review_status,
        )
        for i in boq
    ]  # fmt: skip


def _live(session, ctx, tender_id: UUID) -> estimates.LiveInputs:
    """The current BoQ lines and the confirmed matches on them, mapped to plain inputs."""
    boq, quote_versions = _current(session, ctx, tender_id)
    reviewed: dict[UUID, bool] = {}
    for version_id in quote_versions:
        offset = 0
        while True:
            page = suppliers.list_quotation_items(session, ctx, version_id, PAGE, offset)
            reviewed.update({q.id: q.review_status != "unreviewed" for q in page})
            if len(page) < PAGE:
                break
            offset += PAGE
    found = suppliers.suggestions_for(
        session, ctx, [i.id for i in boq], quote_versions, "confirmed", None, None
    )
    candidates: dict[UUID, list[estimates.CandidateInput]] = {}
    for m in found:
        q = m.quotation_item
        candidates.setdefault(m.boq_item_id, []).append(
            estimates.CandidateInput(
                match_id=m.id, boq_item_id=m.boq_item_id, quotation_item_id=q.id,
                supplier_id=m.supplier.id, supplier_name=m.supplier.name,
                unit_price=_decimal(q.unit_price), currency=q.currency,
                includes_vat=q.prices_include_vat,
                unit_mismatch="unit_mismatch" in (m.evidence.get("warnings") or []),
                quote_item_reviewed=reviewed.get(q.id, False),
            )
        )  # fmt: skip
    return estimates.LiveInputs({b.id: b for b in _boq_inputs(boq)}, candidates)


@router.get("/pricing-defaults", response_model=estimates.PricingDefaultsDTO)
def get_pricing_defaults(ctx: Ctx, session: DbSession):
    dto = estimates.get_defaults(session, ctx)
    if dto is None:
        raise NotFound("Pricing defaults have not been set.", code="pricing_defaults_missing")
    return dto


@router.put("/pricing-defaults", response_model=estimates.PricingDefaultsDTO)
def put_pricing_defaults(body: estimates.PricingDefaultsPut, ctx: Ctx, session: DbSession):
    return estimates.save_defaults(session, ctx, body)


@router.get("/tenders/{tender_id}/estimates", response_model=list[estimates.EstimateSummaryDTO])
def list_estimates(tender_id: UUID, ctx: Ctx, session: DbSession):
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    return estimates.list_estimates(session, ctx, tender_id)


@router.post(
    "/tenders/{tender_id}/estimates", response_model=estimates.EstimateDTO, status_code=201
)
def create_estimate(tender_id: UUID, ctx: Ctx, session: DbSession):
    tenders.get_tender(session, ctx, tender_id)  # NotFound for another organisation
    ctx.require(Permission.REVIEW_DATA)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)  # an archive may have committed meanwhile
    boq, _ = _current(session, ctx, tender_id)
    return estimates.create_estimate(session, ctx, tender_id, _boq_inputs(boq))


@router.get("/estimates/{estimate_id}", response_model=estimates.EstimateDTO)
def get_estimate(estimate_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    return estimates.get_estimate(session, ctx, estimate_id, _live(session, ctx, tender_id))


@router.get("/estimates/{estimate_id}/lines", response_model=list[estimates.EstimateLineDTO])
def get_lines(
    estimate_id: UUID,
    ctx: Ctx,
    session: DbSession,
    status: Literal["priced", "excluded", "unresolved", "changed"] | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _live(session, ctx, tender_id)
    return estimates.list_lines(session, ctx, estimate_id, live, status, limit, offset)


def _locked_live(session, ctx, tender_id: UUID) -> estimates.LiveInputs:
    """Authorise, refuse an archived tender, take the tender lock, then read the live inputs.
    The estimate row lock is taken afterwards, in the service."""
    ctx.require(Permission.REVIEW_DATA)
    refuse_archived(session, ctx, tender_id)
    suppliers.lock_tender(session, ctx, tender_id)
    refuse_archived(session, ctx, tender_id, fresh=True)  # an archive may have committed meanwhile
    return _live(session, ctx, tender_id)


@router.patch("/estimates/{estimate_id}", response_model=estimates.EstimateDTO)
def patch_estimate(estimate_id: UUID, body: estimates.EstimatePatch, ctx: Ctx, session: DbSession):
    tender_id = estimates.tender_of(session, ctx, estimate_id)
    live = _locked_live(session, ctx, tender_id)
    return estimates.patch_estimate(session, ctx, estimate_id, body, live)


@router.put("/estimate-lines/{line_id}", response_model=estimates.EstimateLineDTO)
def put_line(line_id: UUID, body: estimates.LinePut, ctx: Ctx, session: DbSession):
    tender_id = estimates.line_tender(session, ctx, line_id)
    live = _locked_live(session, ctx, tender_id)
    return estimates.price_line(session, ctx, line_id, body, live)


@router.post("/estimate-lines/{line_id}/refresh", response_model=estimates.EstimateLineDTO)
def refresh_line(line_id: UUID, ctx: Ctx, session: DbSession):
    tender_id = estimates.line_tender(session, ctx, line_id)
    live = _locked_live(session, ctx, tender_id)
    return estimates.refresh_line(session, ctx, line_id, live)
