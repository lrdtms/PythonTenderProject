"""The tender's current BoQ lines and confirmed matches, mapped to the plain inputs the
estimates module works on. Shared by the estimates and exports routes; imports only module
publics."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.modules.documents import public as documents
from app.modules.estimates import public as estimates
from app.modules.estimating import public as estimating
from app.modules.suppliers import public as suppliers

PAGE = 1000


def current_boq(session, ctx, tender_id: UUID) -> tuple[list[estimating.BoqItemDTO], list[UUID]]:
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


def boq_inputs(boq: list[estimating.BoqItemDTO]) -> list[estimates.BoqInput]:
    return [
        estimates.BoqInput(
            id=i.id, section=i.section, item_no=i.item_no, description=i.description,
            unit=i.unit, quantity=_decimal(i.quantity), review_status=i.review_status,
        )
        for i in boq
    ]  # fmt: skip


def live_inputs(session, ctx, tender_id: UUID) -> estimates.LiveInputs:
    """The current BoQ lines and the confirmed matches on them, mapped to plain inputs."""
    boq, quote_versions = current_boq(session, ctx, tender_id)
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
    return estimates.LiveInputs({b.id: b for b in boq_inputs(boq)}, candidates)
