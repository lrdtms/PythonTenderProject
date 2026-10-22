"""Estimate use cases: pricing defaults, create, and read with live change detection."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission
from app.modules.audit import public as audit

from . import calc
from .models import Estimate, EstimateLine, PricingDefaults
from .repo import EstimateRepo
from .schemas import (
    BoqInput,
    CandidateDTO,
    CandidateInput,
    EstimateDTO,
    EstimateLineDTO,
    EstimateSummaryDTO,
    LineStatus,
    LiveInputs,
    PricingDefaultsDTO,
    PricingDefaultsPut,
    TotalsDTO,
)


def _defaults_dto(row: PricingDefaults) -> PricingDefaultsDTO:
    return PricingDefaultsDTO(
        currency=row.currency,
        vat_rate=str(row.vat_rate),
        markup_basis=row.markup_basis,  # type: ignore[arg-type]
        default_markup_percent=str(row.default_markup_percent),
        updated_at=row.updated_at,
    )


def get_defaults(session: Session, ctx: OrgContext) -> PricingDefaultsDTO | None:
    ctx.require(Permission.READ)
    row = EstimateRepo(session, ctx).defaults()
    return _defaults_dto(row) if row is not None else None


def save_defaults(
    session: Session, ctx: OrgContext, body: PricingDefaultsPut
) -> PricingDefaultsDTO:
    ctx.require(Permission.MANAGE_PRICING)
    row = EstimateRepo(session, ctx).save_defaults(
        body.currency,
        Decimal(body.vat_rate),
        body.markup_basis,
        Decimal(body.default_markup_percent),
        ctx.user_id,
    )
    audit.record(
        session,
        ctx,
        "pricing_defaults",
        ctx.organisation_id,
        "pricing_defaults_changed",
        {"fields": ["currency", "vat_rate", "markup_basis", "default_markup_percent"]},
    )
    return _defaults_dto(row)


# --- hashing and change detection ------------------------------------------------------------


def _text(value: Decimal | bool | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return str(value)


def input_hash(boq: BoqInput, candidate: CandidateInput | None) -> str:
    """Hash of what a priced line depends on: quantity, unit and, for a supplier price, the
    quoted unit price, VAT basis and currency."""
    parts = [_text(boq.quantity), _text(boq.unit)]
    if candidate is not None:
        parts += [
            _text(candidate.supplier_id),
            _text(candidate.unit_price),
            _text(candidate.includes_vat),
            _text(candidate.currency),
        ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _warnings(c: CandidateInput) -> list[str]:
    out = []
    if c.includes_vat is None:
        out.append("vat_basis_unknown")
    if c.currency is None:
        out.append("currency_missing")
    if c.unit_mismatch:
        out.append("unit_mismatch")
    if not c.quote_item_reviewed:
        out.append("unreviewed_source")
    return out


def _candidate_dto(c: CandidateInput) -> CandidateDTO:
    return CandidateDTO(
        match_id=c.match_id,
        supplier_id=c.supplier_id,
        supplier_name=c.supplier_name,
        quotation_item_id=c.quotation_item_id,
        unit_price=_dec(c.unit_price),
        currency=c.currency,
        includes_vat=c.includes_vat,
        warnings=_warnings(c),
    )


def _dec(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _line_dto(row: EstimateLine, live: LiveInputs | None) -> EstimateLineDTO:
    """One line, with its status and flags computed against the live inputs. `live` is None for
    a frozen estimate, which never looks at them."""
    flags = sorted(k for k, v in (row.flags or {}).items() if v)
    candidates: list[CandidateInput] = []
    chosen: CandidateInput | None = None
    changed = False
    if live is not None:
        candidates = sorted(
            live.candidates.get(row.boq_item_id, []), key=lambda c: c.supplier_name.lower()
        )  # stable: the router's rank order is kept within one supplier
        boq = live.boq.get(row.boq_item_id)
        if row.price_source == "supplier":
            chosen = next((c for c in candidates if c.match_id == row.match_suggestion_id), None)
        if row.price_source in ("supplier", "manual"):
            changed = (
                boq is None
                or (row.price_source == "supplier" and chosen is None)
                or input_hash(boq, chosen) != row.input_hash
            )
        if row.price_source != "excluded" and (
            (boq is not None and boq.review_status == "unreviewed")
            or (chosen is not None and not chosen.quote_item_reviewed)
        ):
            flags.append("unreviewed_source")
    status: LineStatus
    if row.price_source == "excluded":
        status = "excluded"
    elif changed:
        status = "changed"
    elif row.price_source == "unresolved" or flags or row.total is None:
        status = "unresolved"  # a line without amounts is never counted as priced
    else:
        status = "priced"
    if changed:
        flags.append("source_changed")
    return EstimateLineDTO(
        id=row.id,
        boq_item_id=row.boq_item_id,
        position=row.position,
        section=row.section,
        item_no=row.item_no,
        description=row.description,
        unit=row.unit,
        quantity=_dec(row.quantity),
        status=status,
        price_source=row.price_source,
        match_suggestion_id=row.match_suggestion_id,
        supplier_id=row.supplier_id,
        supplier_name=row.supplier_name,
        quoted_unit_price=_dec(row.quoted_unit_price),
        quoted_currency=row.quoted_currency,
        quoted_includes_vat=row.quoted_includes_vat,
        unit_price_ex_vat=_dec(row.unit_price_ex_vat),
        labour_rate=_dec(row.labour_rate),
        markup_override_percent=_dec(row.markup_override_percent),
        exclude_reason=row.exclude_reason,
        unit_mismatch_acknowledged=row.unit_mismatch_acknowledged,
        material_cost=_dec(row.material_cost),
        labour_cost=_dec(row.labour_cost),
        cost=_dec(row.cost),
        markup=_dec(row.markup),
        total=_dec(row.total),
        flags=flags,
        candidates=[_candidate_dto(c) for c in candidates],
    )


def _totals_dto(t: calc.Totals) -> TotalsDTO:
    return TotalsDTO(
        subtotal_cost=str(t.subtotal_cost),
        markup_total=str(t.markup_total),
        subtotal_ex_vat=str(t.subtotal_ex_vat),
        vat_total=str(t.vat_total),
        total_inc_vat=str(t.total_inc_vat),
    )


def _stored_totals(est: Estimate) -> TotalsDTO | None:
    if est.total_inc_vat is None:
        return None
    return TotalsDTO(
        subtotal_cost=str(est.subtotal_cost),
        markup_total=str(est.markup_total),
        subtotal_ex_vat=str(est.subtotal_ex_vat),
        vat_total=str(est.vat_total),
        total_inc_vat=str(est.total_inc_vat),
    )


def _settings(est: Estimate) -> calc.Settings:
    return calc.Settings(est.vat_rate, est.markup_basis, est.markup_percent)  # type: ignore[arg-type]


def _lines_of(
    repo: EstimateRepo, est: Estimate, live: LiveInputs
) -> list[tuple[EstimateLine, EstimateLineDTO]]:
    use = live if est.status == "draft" else None  # a frozen estimate ignores live inputs
    return [(row, _line_dto(row, use)) for row in repo.all_lines(est.id)]


def _estimate_dto(
    est: Estimate, lines: Sequence[tuple[EstimateLine, EstimateLineDTO]]
) -> EstimateDTO:
    counts = {"priced": 0, "excluded": 0, "unresolved": 0, "changed": 0}
    amounts: list[calc.LineAmounts] = []
    zero = Decimal("0.00")
    for row, dto in lines:
        counts[dto.status] += 1
        if dto.status == "priced" and row.total is not None:  # priced implies amounts
            amounts.append(
                calc.LineAmounts(
                    row.material_cost if row.material_cost is not None else zero,
                    row.labour_cost if row.labour_cost is not None else zero,
                    row.cost if row.cost is not None else zero,
                    row.markup if row.markup is not None else zero,
                    row.total,
                )
            )
    totals = (
        _totals_dto(calc.totals(amounts, _settings(est)))
        if est.status == "draft"
        else _stored_totals(est)
    )
    return EstimateDTO(
        id=est.id,
        tender_id=est.tender_id,
        version=est.version,
        status=est.status,
        currency=est.currency,
        vat_rate=str(est.vat_rate),
        markup_basis=est.markup_basis,  # type: ignore[arg-type]
        markup_percent=str(est.markup_percent),
        based_on_version=est.based_on_version,
        totals=totals,
        incomplete=counts["unresolved"] + counts["changed"] > 0,
        created_by=est.created_by,
        created_at=est.created_at,
        reviewed_by=est.reviewed_by,
        reviewed_at=est.reviewed_at,
        approved_by=est.approved_by,
        approved_at=est.approved_at,
        **counts,
    )


# --- use cases -------------------------------------------------------------------------------


def create_estimate(
    session: Session, ctx: OrgContext, tender_id: UUID, boq: Sequence[BoqInput]
) -> EstimateDTO:
    """A new draft: one `unresolved` line per BoQ line, in the order given, nothing chosen."""
    ctx.require(Permission.REVIEW_DATA)
    repo = EstimateRepo(session, ctx)
    defaults = repo.defaults()
    if defaults is None:
        raise Conflict("Set the pricing defaults first.", code="pricing_defaults_missing")
    if repo.draft_for(tender_id) is not None:
        raise Conflict("This tender already has a draft estimate.", code="draft_exists")
    latest = repo.latest_version(tender_id)
    est = Estimate(
        tender_id=tender_id,
        version=latest + 1,
        status="draft",
        currency=defaults.currency,
        vat_rate=defaults.vat_rate,
        markup_basis=defaults.markup_basis,
        markup_percent=defaults.default_markup_percent,
        based_on_version=latest or None,
        created_by=ctx.user_id,
    )
    try:
        with session.begin_nested():  # the one-draft index or the version key lost a race
            repo.add(est)
    except IntegrityError as exc:
        raise Conflict("This tender already has a draft estimate.", code="draft_exists") from exc
    repo.add_lines(
        [
            EstimateLine(
                estimate_id=est.id,
                boq_item_id=b.id,
                position=n,
                section=b.section,
                item_no=b.item_no,
                description=b.description,
                unit=b.unit,
                quantity=b.quantity,
                price_source="unresolved",
                flags={},
                input_hash=input_hash(b, None),
                updated_by=ctx.user_id,
            )
            for n, b in enumerate(boq)
        ]
    )
    audit.record(
        session, ctx, "estimate", est.id, "estimate_created",
        {"tender_id": str(tender_id), "version": est.version, "lines": len(boq)},
    )  # fmt: skip
    if est.version > 1:
        audit.record(
            session, ctx, "estimate", est.id, "estimate_version_created",
            {"version": est.version, "based_on_version": latest},
        )  # fmt: skip
    return _estimate_dto(est, _lines_of(repo, est, LiveInputs({b.id: b for b in boq})))


def tender_of(session: Session, ctx: OrgContext, estimate_id: UUID) -> UUID:
    """The estimate's tender, so the router can read the live inputs. NotFound across
    organisations."""
    ctx.require(Permission.READ)
    return EstimateRepo(session, ctx).get(estimate_id).tender_id


def get_estimate(
    session: Session, ctx: OrgContext, estimate_id: UUID, live: LiveInputs
) -> EstimateDTO:
    ctx.require(Permission.READ)
    repo = EstimateRepo(session, ctx)
    est = repo.get(estimate_id)
    return _estimate_dto(est, _lines_of(repo, est, live))


def list_lines(
    session: Session,
    ctx: OrgContext,
    estimate_id: UUID,
    live: LiveInputs,
    status: LineStatus | None,
    limit: int,
    offset: int,
) -> list[EstimateLineDTO]:
    """Lines in BoQ order. The status filter is applied to the computed status, then the page is
    cut, so a page never comes back short because of the filter."""
    ctx.require(Permission.READ)
    repo = EstimateRepo(session, ctx)
    est = repo.get(estimate_id)
    dtos = [dto for _, dto in _lines_of(repo, est, live)]
    if status is not None:
        dtos = [d for d in dtos if d.status == status]
    return dtos[offset : offset + limit]


def list_estimates(session: Session, ctx: OrgContext, tender_id: UUID) -> list[EstimateSummaryDTO]:
    ctx.require(Permission.READ)
    return [
        EstimateSummaryDTO(
            id=e.id,
            tender_id=e.tender_id,
            version=e.version,
            status=e.status,
            currency=e.currency,
            totals=_stored_totals(e),
            created_at=e.created_at,
            reviewed_at=e.reviewed_at,
            approved_at=e.approved_at,
        )
        for e in EstimateRepo(session, ctx).for_tender(tender_id)
    ]
