"""Estimate use cases: pricing defaults, create, and read with live change detection."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission, ValidationFailed
from app.modules.audit import public as audit

from . import calc
from .models import Estimate, EstimateLine, PricingDefaults
from .repo import EstimateRepo
from .schemas import (
    Blocker,
    BlockerCode,
    BoqInput,
    CandidateDTO,
    CandidateInput,
    EstimateDTO,
    EstimateLineDTO,
    EstimatePatch,
    EstimateSummaryDTO,
    LinePut,
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


def _holds_currency(rows: Iterable[EstimateLine]) -> bool:
    """Whether any line (blocked ones included) is priced from a supplier or by hand: the one rule
    behind both the `currency_locked` flag and the refusal to change the currency."""
    return any(r.price_source in ("supplier", "manual") for r in rows)


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
        currency_locked=_holds_currency(row for row, _ in lines),
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
    rows = EstimateRepo(session, ctx).for_tender(tender_id)  # newest version first
    current = next((e.id for e in rows if e.status == "approved"), None)
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
            is_current_approved=e.id == current,
        )
        for e in rows
    ]


# --- writes ----------------------------------------------------------------------------------


def line_tender(session: Session, ctx: OrgContext, line_id: UUID) -> UUID:
    """The tender of a line's estimate, so the router can lock it. NotFound across
    organisations."""
    ctx.require(Permission.READ)
    repo = EstimateRepo(session, ctx)
    return repo.get(repo.line(line_id).estimate_id).tender_id


def _lock_draft(
    session: Session, ctx: OrgContext, estimate_id: UUID
) -> tuple[EstimateRepo, Estimate]:
    repo = EstimateRepo(session, ctx)
    est = repo.get_for_update(estimate_id)
    if est.status != "draft":
        raise Conflict("This estimate is no longer a draft.", code="estimate_frozen")
    return repo, est


def _blocked(row: EstimateLine) -> bool:
    return any((row.flags or {}).values())


def _set_amounts(row: EstimateLine, amounts: calc.LineAmounts | None) -> None:
    """All five amounts or none: a line without a total is never counted as priced."""
    row.material_cost = amounts.material_cost if amounts else None
    row.labour_cost = amounts.labour_cost if amounts else None
    row.cost = amounts.cost if amounts else None
    row.markup = amounts.markup if amounts else None
    row.total = amounts.total if amounts else None


def _price(row: EstimateLine, est: Estimate) -> None:
    """Recompute `unit_price_ex_vat` (supplier lines) and the amounts from the line's snapshots.
    A line with a blocker flag, or without a usable quantity or price, gets no amounts."""
    if row.price_source == "supplier":
        if _blocked(row) or row.quoted_unit_price is None or row.quoted_includes_vat is None:
            row.unit_price_ex_vat = None
        else:
            row.unit_price_ex_vat = calc.to_ex_vat(
                row.quoted_unit_price, row.quoted_includes_vat, est.vat_rate
            )
    if _blocked(row) or row.unit_price_ex_vat is None:
        _set_amounts(row, None)
        return
    _set_amounts(
        row,
        calc.line_amounts(
            calc.LineInput(
                row.quantity, row.unit_price_ex_vat, row.labour_rate, row.markup_override_percent
            ),
            _settings(est),
        ),
    )


def _snapshot_boq(row: EstimateLine, boq: BoqInput) -> None:
    row.section, row.item_no, row.description = boq.section, boq.item_no, boq.description
    row.unit, row.quantity = boq.unit, boq.quantity


def _blockers(est: Estimate, boq: BoqInput, cand: CandidateInput | None) -> dict[str, bool]:
    """Stored blocker flags only. `unreviewed_source` and `source_changed` are live-only."""
    flags: dict[str, bool] = {}
    if boq.quantity is None or boq.quantity <= 0:
        flags["quantity_missing"] = True
    if boq.unit is None:
        flags["unit_missing"] = True
    if cand is not None:
        if cand.unit_price is None:
            flags["price_missing"] = True
        if cand.currency is None:
            flags["currency_missing"] = True
        elif cand.currency != est.currency:
            flags["currency_differs"] = True
        if cand.includes_vat is None:
            flags["vat_basis_unknown"] = True
    return flags


def _snapshot_candidate(row: EstimateLine, cand: CandidateInput) -> None:
    row.price_source = "supplier"
    row.match_suggestion_id = cand.match_id
    row.supplier_id, row.supplier_name = cand.supplier_id, cand.supplier_name
    row.quotation_item_id = cand.quotation_item_id
    row.quoted_unit_price = cand.unit_price
    row.quoted_currency = cand.currency
    row.quoted_includes_vat = cand.includes_vat


def _clear_source(row: EstimateLine) -> None:
    row.match_suggestion_id = row.supplier_id = row.supplier_name = row.quotation_item_id = None
    row.quoted_unit_price = row.quoted_currency = row.quoted_includes_vat = None
    row.unit_price_ex_vat = None
    row.exclude_reason = None
    row.unit_mismatch_acknowledged = False


def _check_override(est: Estimate, override: Decimal | None) -> None:
    if override is None:
        return
    try:
        calc.validate_settings(calc.Settings(est.vat_rate, est.markup_basis, override))  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="invalid_markup_override") from exc


def _find_candidate(live: LiveInputs, boq_item_id: UUID, match_id: UUID | None) -> CandidateInput:
    cand = next((c for c in live.candidates.get(boq_item_id, []) if c.match_id == match_id), None)
    if cand is None:
        raise Conflict(
            "That match is not confirmed and current for this line. Reload.", code="stale_match"
        )
    return cand


def price_line(
    session: Session, ctx: OrgContext, line_id: UUID, body: LinePut, live: LiveInputs
) -> EstimateLineDTO:
    """Set a line's source. PUT semantics: an omitted labour rate or markup override is cleared."""
    ctx.require(Permission.REVIEW_DATA)
    estimate_id = EstimateRepo(session, ctx).line(line_id).estimate_id
    repo, est = _lock_draft(session, ctx, estimate_id)
    row = repo.line(line_id, refresh=True)
    override = (
        Decimal(body.markup_override_percent) if body.markup_override_percent is not None else None
    )
    _check_override(est, override)
    boq = live.boq.get(row.boq_item_id)
    row.updated_by = ctx.user_id
    if body.exclude_reason is not None:
        _clear_source(row)
        row.price_source = "excluded"
        row.exclude_reason = body.exclude_reason
        row.labour_rate = row.markup_override_percent = None
        row.flags = {}
        if boq is not None:
            row.input_hash = input_hash(boq, None)
        _set_amounts(row, None)
        audit.record(
            session, ctx, "estimate_line", row.id, "estimate_line_excluded",
            {"estimate_id": str(est.id), "boq_item_id": str(row.boq_item_id)},
        )  # fmt: skip
        session.flush()
        return _line_dto(row, live)
    if boq is None:
        raise Conflict("This BoQ line is no longer current.", code="stale_match")
    if boq.quantity is None or boq.quantity <= 0:
        raise ValidationFailed(
            "A line without a quantity can only be excluded.", code="quantity_missing"
        )
    cand: CandidateInput | None = None
    if body.match_suggestion_id is not None:
        cand = _find_candidate(live, row.boq_item_id, body.match_suggestion_id)
        if cand.unit_mismatch and not body.unit_mismatch_acknowledged:
            raise ValidationFailed(
                "The quoted unit differs from the BoQ unit; acknowledge it to use this price.",
                code="unit_mismatch_unacknowledged",
            )
    _clear_source(row)
    _snapshot_boq(row, boq)
    row.labour_rate = Decimal(body.labour_rate) if body.labour_rate is not None else None
    row.markup_override_percent = override
    if cand is not None:
        _snapshot_candidate(row, cand)
        row.unit_mismatch_acknowledged = cand.unit_mismatch and body.unit_mismatch_acknowledged
    else:
        row.price_source = "manual"
        row.unit_price_ex_vat = Decimal(body.manual_unit_price or "0")
    row.flags = _blockers(est, boq, cand)
    row.input_hash = input_hash(boq, cand)
    _price(row, est)
    audit.record(
        session, ctx, "estimate_line", row.id, "estimate_line_priced",
        {
            "estimate_id": str(est.id),
            "boq_item_id": str(row.boq_item_id),
            "source": row.price_source,
            "match_suggestion_id": str(cand.match_id) if cand else None,
        },
    )  # fmt: skip
    session.flush()
    session.refresh(row)  # column scale (e.g. 10.5 -> 10.5000) as stored
    return _line_dto(row, live)


def refresh_line(
    session: Session, ctx: OrgContext, line_id: UUID, live: LiveInputs
) -> EstimateLineDTO:
    """Re-snapshot the line from the live BoQ line and the chosen quote item."""
    ctx.require(Permission.REVIEW_DATA)
    estimate_id = EstimateRepo(session, ctx).line(line_id).estimate_id
    repo, est = _lock_draft(session, ctx, estimate_id)
    row = repo.line(line_id, refresh=True)
    boq = live.boq.get(row.boq_item_id)
    if boq is None:
        raise Conflict("This BoQ line is no longer current.", code="stale_match")
    cand: CandidateInput | None = None
    if row.price_source == "supplier":
        cand = _find_candidate(live, row.boq_item_id, row.match_suggestion_id)
        if cand.unit_mismatch and not row.unit_mismatch_acknowledged:
            raise ValidationFailed(
                "The quoted unit now differs from the BoQ unit; choose the price again.",
                code="unit_mismatch_unacknowledged",
            )
    row.updated_by = ctx.user_id
    _snapshot_boq(row, boq)
    if cand is not None:
        _snapshot_candidate(row, cand)
    if row.price_source in ("supplier", "manual"):
        row.flags = _blockers(est, boq, cand)
        _price(row, est)
    row.input_hash = input_hash(boq, cand)
    audit.record(
        session, ctx, "estimate_line", row.id, "estimate_line_priced",
        {
            "estimate_id": str(est.id),
            "boq_item_id": str(row.boq_item_id),
            "source": row.price_source,
            "refreshed": True,
        },
    )  # fmt: skip
    session.flush()
    session.refresh(row)  # column scale (e.g. 10.5 -> 10.5000) as stored
    return _line_dto(row, live)


def patch_estimate(
    session: Session, ctx: OrgContext, estimate_id: UUID, body: EstimatePatch, live: LiveInputs
) -> EstimateDTO:
    ctx.require(Permission.REVIEW_DATA)
    repo, est = _lock_draft(session, ctx, estimate_id)
    rows = repo.all_lines(est.id)
    currency = body.currency if body.currency is not None else est.currency
    vat = Decimal(body.vat_rate) if body.vat_rate is not None else est.vat_rate
    basis = body.markup_basis if body.markup_basis is not None else est.markup_basis
    pct = Decimal(body.markup_percent) if body.markup_percent is not None else est.markup_percent
    if currency != est.currency and _holds_currency(rows):
        raise Conflict("The currency cannot change once a line is priced.", code="currency_locked")
    try:
        calc.validate_settings(calc.Settings(vat, basis, pct))  # type: ignore[arg-type]
        for r in rows:
            if r.markup_override_percent is not None:
                calc.validate_settings(calc.Settings(vat, basis, r.markup_override_percent))  # type: ignore[arg-type]
    except ValueError as exc:
        raise ValidationFailed(str(exc), code="invalid_settings") from exc
    changed = [
        name
        for name, old, new in (
            ("currency", est.currency, currency),
            ("vat_rate", est.vat_rate, vat),
            ("markup_basis", est.markup_basis, basis),
            ("markup_percent", est.markup_percent, pct),
        )
        if old != new
    ]
    est.currency, est.vat_rate, est.markup_basis, est.markup_percent = currency, vat, basis, pct
    for r in rows:
        if r.price_source in ("supplier", "manual"):
            _price(r, est)
    if changed:
        audit.record(
            session, ctx, "estimate", est.id, "estimate_settings_changed", {"fields": changed}
        )
    session.flush()
    session.refresh(est)
    for r in rows:
        session.refresh(r)
    return _estimate_dto(est, _lines_of(repo, est, live))


# --- readiness and status moves --------------------------------------------------------------


def readiness(est: Estimate, lines: Sequence[EstimateLine], live: LiveInputs) -> list[Blocker]:
    """Why this estimate cannot be marked reviewed or approved. Every line is judged against the
    live inputs: a priced or excluded line passes, anything else blocks. An estimate with no
    lines at all is blocked."""
    if not lines:
        return [Blocker(line_id=None, code="no_lines")]
    out: list[Blocker] = []
    for row in lines:
        dto = _line_dto(row, live)
        named = {
            "line_id": row.id,
            "item_no": row.item_no,
            "description": None if row.description is None else row.description[:120],
            "reasons": list(dto.flags),
        }
        if dto.status == "changed":
            out.append(Blocker(code="source_changed", **named))
        elif dto.status == "unresolved":
            only_unreviewed = (
                row.price_source != "unresolved"
                and row.total is not None
                and dto.flags == ["unreviewed_source"]
            )
            code: BlockerCode = "unreviewed_source" if only_unreviewed else "unresolved"
            out.append(Blocker(code=code, **named))
    missing = set(live.boq) - {row.boq_item_id for row in lines}
    if missing:  # a BoQ line that arrived after this version was started has no estimate line
        n = len(missing)
        out.append(
            Blocker(
                line_id=None,
                code="boq_lines_missing",
                reasons=[f"{n} new BoQ line{'s' if n != 1 else ''}"],
            )
        )
    return out


def _require_ready(est: Estimate, rows: Sequence[EstimateLine], live: LiveInputs) -> None:
    blockers = readiness(est, rows, live)
    if blockers:
        raise Conflict(
            "Resolve every line before moving this estimate on.",
            {"blockers": [b.model_dump(mode="json") for b in blockers]},
            code="estimate_not_ready",
        )


def _freeze_totals(est: Estimate, rows: Sequence[EstimateLine]) -> None:
    """Store the totals of the priced lines. Called only once readiness passed, so every
    non-excluded line is priced and has its amounts."""
    zero = Decimal("0.00")
    amounts = [
        calc.LineAmounts(
            r.material_cost if r.material_cost is not None else zero,
            r.labour_cost if r.labour_cost is not None else zero,
            r.cost if r.cost is not None else zero,
            r.markup if r.markup is not None else zero,
            r.total,
        )
        for r in rows
        if r.price_source != "excluded" and r.total is not None
    ]
    t = calc.totals(amounts, _settings(est))
    est.subtotal_cost, est.markup_total = t.subtotal_cost, t.markup_total
    est.subtotal_ex_vat, est.vat_total, est.total_inc_vat = (
        t.subtotal_ex_vat,
        t.vat_total,
        t.total_inc_vat,
    )


def _finish(session: Session, repo: EstimateRepo, est: Estimate, live: LiveInputs) -> EstimateDTO:
    session.flush()
    session.refresh(est)
    return _estimate_dto(est, _lines_of(repo, est, live))


def review_estimate(
    session: Session, ctx: OrgContext, estimate_id: UUID, live: LiveInputs
) -> EstimateDTO:
    ctx.require(Permission.REVIEW_DATA)
    repo, est = _lock_draft(session, ctx, estimate_id)
    rows = repo.all_lines(est.id)
    _require_ready(est, rows, live)
    _freeze_totals(est, rows)
    est.status, est.reviewed_by, est.reviewed_at = "reviewed", ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "estimate", est.id, "estimate_reviewed",
        {"version": est.version, "status": "reviewed", "reviewed_by": str(ctx.user_id)},
    )  # fmt: skip
    return _finish(session, repo, est, live)


def approve_estimate(
    session: Session, ctx: OrgContext, estimate_id: UUID, live: LiveInputs
) -> EstimateDTO:
    """reviewed -> approved. The readiness gate runs again against the live inputs, so a BoQ or
    quotation edit since the review blocks approval (reopen, refresh and review again)."""
    ctx.require(Permission.APPROVE_ESTIMATE)
    repo = EstimateRepo(session, ctx)
    est = repo.get_for_update(estimate_id)
    if est.status == "approved":
        raise Conflict("This estimate is already approved.", code="estimate_frozen")
    if est.status != "reviewed":
        raise Conflict(
            "Mark the estimate reviewed before approving it.", code="estimate_not_reviewed"
        )
    _require_ready(est, repo.all_lines(est.id), live)
    est.status, est.approved_by, est.approved_at = "approved", ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "estimate", est.id, "estimate_approved",
        {
            "version": est.version,
            "status": "approved",
            "reviewed_by": str(est.reviewed_by),
            "approved_by": str(ctx.user_id),
        },
    )  # fmt: skip
    return _finish(session, repo, est, live)


def reopen_estimate(
    session: Session, ctx: OrgContext, estimate_id: UUID, live: LiveInputs
) -> EstimateDTO:
    """reviewed -> draft, only while the tender has no other draft."""
    ctx.require(Permission.REVIEW_DATA)
    repo = EstimateRepo(session, ctx)
    est = repo.get_for_update(estimate_id)
    if est.status == "approved":
        raise Conflict("An approved estimate cannot be reopened.", code="estimate_frozen")
    if est.status != "reviewed":
        raise Conflict("Only a reviewed estimate can be reopened.", code="estimate_not_reviewed")
    if repo.draft_for(est.tender_id) is not None:
        raise Conflict("This tender already has a draft estimate.", code="draft_exists")
    try:
        with session.begin_nested():  # the one-draft index lost a race
            est.status, est.reviewed_by, est.reviewed_at = "draft", None, None
            est.subtotal_cost = est.markup_total = est.subtotal_ex_vat = None
            est.vat_total = est.total_inc_vat = None
            session.flush()
    except IntegrityError as exc:
        session.refresh(est)
        raise Conflict("This tender already has a draft estimate.", code="draft_exists") from exc
    audit.record(
        session, ctx, "estimate", est.id, "estimate_reopened",
        {"version": est.version, "status": "draft"},
    )  # fmt: skip
    return _finish(session, repo, est, live)
