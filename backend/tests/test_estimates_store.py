"""Estimate tables: one draft per tender, tenant scoping, and no foreign keys out of the lines."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import session_scope
from app.kernel import NotFound, OrgContext, Role
from app.modules.estimates.models import Estimate, EstimateLine, PricingDefaults
from app.modules.estimates.repo import EstimateRepo
from tests.conftest import make_tender, register


def _ctx(actor) -> OrgContext:
    return OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)


def _estimate(ctx: OrgContext, tender_id: str, version: int = 1, status: str = "draft") -> Estimate:
    return Estimate(
        organisation_id=ctx.organisation_id,
        tender_id=UUID(tender_id),
        version=version,
        status=status,
        currency="ZAR",
        vat_rate=Decimal("15.00"),
        markup_basis="cost",
        markup_percent=Decimal("10.00"),
        created_by=ctx.user_id,
    )


def _line(ctx: OrgContext, estimate_id: UUID, **over) -> EstimateLine:
    values = {
        "organisation_id": ctx.organisation_id,
        "estimate_id": estimate_id,
        "boq_item_id": uuid4(),
        "position": 0,
        "description": "Cable 2.5mm",
        "price_source": "supplier",
        "match_suggestion_id": uuid4(),
        "supplier_id": uuid4(),
        "quotation_item_id": uuid4(),
        "quantity": Decimal("10.0000"),
        "unit_price_ex_vat": Decimal("5.0000"),
        "updated_by": ctx.user_id,
    }
    return EstimateLine(**{**values, **over})


def test_two_drafts_for_one_tender_are_refused() -> None:
    actor = register("est1@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        repo = EstimateRepo(session, ctx)
        repo.add(_estimate(ctx, tender_id, 1))
        with pytest.raises(IntegrityError), session.begin_nested():
            repo.add(_estimate(ctx, tender_id, 2))


def test_a_reviewed_estimate_and_a_new_draft_can_coexist() -> None:
    actor = register("est2@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        repo = EstimateRepo(session, ctx)
        repo.add(_estimate(ctx, tender_id, 1, status="approved"))
        draft = repo.add(_estimate(ctx, tender_id, 2))
        assert repo.draft_for(UUID(tender_id)).id == draft.id
        assert repo.latest_version(UUID(tender_id)) == 2
        with pytest.raises(IntegrityError), session.begin_nested():  # unique per tender
            repo.add(_estimate(ctx, tender_id, 2, status="reviewed"))


def test_another_organisation_cannot_read_the_estimate() -> None:
    a, b = register("est3a@example.com", org="Org A"), register("est3b@example.com", org="Org B")
    ctx_a, ctx_b, tender_id = _ctx(a), _ctx(b), make_tender(a)
    with session_scope() as session:
        estimate = EstimateRepo(session, ctx_a).add(_estimate(ctx_a, tender_id))
        EstimateRepo(session, ctx_a).add_lines([_line(ctx_a, estimate.id)])
        other = EstimateRepo(session, ctx_b)
        with pytest.raises(NotFound):
            other.get_for_update(estimate.id)
        assert other.draft_for(UUID(tender_id)) is None
        assert other.lines(estimate.id, 10, 0, None) == []
        assert len(EstimateRepo(session, ctx_a).lines(estimate.id, 10, 0, None)) == 1


def test_lines_have_no_foreign_keys_except_to_estimates() -> None:
    targets = {fk.column.table.name for fk in EstimateLine.__table__.foreign_keys}
    assert targets == {"estimates", "organisations", "memberships"}
    keys = {fk.parent.name for fk in EstimateLine.__table__.foreign_keys}
    for loose in ("boq_item_id", "match_suggestion_id", "quotation_item_id", "supplier_id"):
        assert loose not in keys


def test_a_line_pointing_at_rows_that_do_not_exist_inserts_and_is_unique_per_boq_item() -> None:
    actor = register("est4@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        repo = EstimateRepo(session, ctx)
        estimate = repo.add(_estimate(ctx, tender_id))
        boq_id = uuid4()
        repo.add_lines([_line(ctx, estimate.id, boq_item_id=boq_id)])
        with pytest.raises(IntegrityError), session.begin_nested():
            repo.add_lines([_line(ctx, estimate.id, boq_item_id=boq_id)])


def test_pricing_defaults_round_trip() -> None:
    actor = register("est5@example.com")
    ctx = _ctx(actor)
    with session_scope() as session:
        repo = EstimateRepo(session, ctx)
        assert repo.defaults() is None
        repo.save_defaults("ZAR", Decimal("15.00"), "cost", Decimal("12.50"), ctx.user_id)
        repo.save_defaults("ZAR", Decimal("15.00"), "selling_price", Decimal("20.00"), ctx.user_id)
        saved = repo.defaults()
        assert isinstance(saved, PricingDefaults)
        assert (saved.markup_basis, saved.default_markup_percent) == (
            "selling_price",
            Decimal("20.00"),
        )
