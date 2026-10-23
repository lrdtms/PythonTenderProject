"""Exports table: CHECK constraints, composite foreign keys and tenant scoping."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.session import session_scope
from app.kernel import NotFound, OrgContext, Role
from app.modules.estimates.models import Estimate
from app.modules.estimates.repo import EstimateRepo
from app.modules.reporting.models import Export
from app.modules.reporting.repo import ExportRepo
from tests.conftest import make_tender, register

ESTIMATE_COLS = "ck_exports_ck_exports_estimate_cols"


def _ctx(actor) -> OrgContext:
    return OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)


def _estimate(ctx: OrgContext, tender_id: str) -> Estimate:
    return Estimate(
        organisation_id=ctx.organisation_id,
        tender_id=UUID(tender_id),
        version=1,
        status="approved",
        currency="ZAR",
        vat_rate=Decimal("15.00"),
        markup_basis="cost",
        markup_percent=Decimal("10.00"),
        created_by=ctx.user_id,
    )


def _export(ctx: OrgContext, tender_id: str, **over) -> Export:
    values = {
        "organisation_id": ctx.organisation_id,
        "tender_id": UUID(tender_id),
        "kind": "checklist_pdf",
        "label": "draft",
        "file_key": f"org/{ctx.organisation_id}/tenders/{tender_id}/exports/{uuid4()}.pdf",
        "file_name": "hall-checklist-DRAFT-20261023.pdf",
        "content_type": "application/pdf",
        "file_size": 1234,
        "sha256": "a" * 64,
        "row_count": 3,
        "generated_by": ctx.user_id,
        "generated_at": datetime(2026, 10, 23, 8, 30, tzinfo=UTC),
    }
    return Export(**{**values, **over})


def _refused(ctx: OrgContext, entity: Export, constraint: str) -> None:
    with session_scope() as session:
        repo = ExportRepo(session, ctx)
        with pytest.raises(IntegrityError) as exc, session.begin_nested():
            repo.add(entity)
        assert exc.value.orig.diag.constraint_name == constraint  # type: ignore[union-attr]


def test_valid_estimate_and_checklist_exports_are_stored() -> None:
    actor = register("exp1@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    stamp = datetime(2026, 10, 23, 8, 30, 15, 123456, tzinfo=UTC)
    with session_scope() as session:
        estimate = EstimateRepo(session, ctx).add(_estimate(ctx, tender_id))
        repo = ExportRepo(session, ctx)
        xlsx = repo.add(
            _export(
                ctx,
                tender_id,
                kind="estimate_xlsx",
                label="approved",
                estimate_id=estimate.id,
                estimate_version=1,
                generated_at=stamp,
            )
        )
        pdf = repo.add(_export(ctx, tender_id, label="approved"))
        session.expire_all()
        assert repo.get(xlsx.id).generated_at == stamp
        assert repo.get(pdf.id).estimate_id is None


@pytest.mark.parametrize("which", ["id_only", "version_only"])
def test_checklist_with_one_estimate_column_is_refused(which: str) -> None:
    actor = register(f"exp2{which[:2]}@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        estimate = EstimateRepo(session, ctx).add(_estimate(ctx, tender_id))
        session.commit()
        est_id = estimate.id
    extra = {"estimate_id": est_id} if which == "id_only" else {"estimate_version": 1}
    _refused(ctx, _export(ctx, tender_id, **extra), ESTIMATE_COLS)


@pytest.mark.parametrize("which", ["id_only", "version_only", "neither"])
def test_estimate_export_needs_both_estimate_columns(which: str) -> None:
    actor = register(f"exp3{which[:2]}@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        estimate = EstimateRepo(session, ctx).add(_estimate(ctx, tender_id))
        session.commit()
        est_id = estimate.id
    extra = {
        "id_only": {"estimate_id": est_id},
        "version_only": {"estimate_version": 1},
        "neither": {},
    }[which]
    _refused(
        ctx,
        _export(ctx, tender_id, kind="estimate_xlsx", label="approved", **extra),
        ESTIMATE_COLS,
    )


@pytest.mark.parametrize(
    ("over", "constraint"),
    [
        ({"label": "reviewed"}, "ck_exports_ck_exports_checklist_label"),  # draft or approved
        ({"label": "final"}, "ck_exports_ck_exports_checklist_label"),
        ({"kind": "checklist_docx"}, "ck_exports_ck_exports_estimate_cols"),
    ],
)
def test_bad_kind_or_label_is_refused(over: dict, constraint: str) -> None:
    actor = register(f"exp4{uuid4().hex[:8]}@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    _refused(ctx, _export(ctx, tender_id, **over), constraint)


def test_unknown_label_on_an_estimate_export_is_refused() -> None:
    actor = register("exp5@example.com")
    ctx, tender_id = _ctx(actor), make_tender(actor)
    with session_scope() as session:
        estimate = EstimateRepo(session, ctx).add(_estimate(ctx, tender_id))
        session.commit()
        est_id = estimate.id
    _refused(
        ctx,
        _export(
            ctx,
            tender_id,
            kind="estimate_xlsx",
            label="final",
            estimate_id=est_id,
            estimate_version=1,
        ),
        "ck_exports_ck_exports_label",
    )


def test_estimate_of_another_organisation_is_refused() -> None:
    a, b = register("exp6a@example.com", org="Org A"), register("exp6b@example.com", org="Org B")
    ctx_a, ctx_b, tender_a, tender_b = _ctx(a), _ctx(b), make_tender(a), make_tender(b)
    with session_scope() as session:
        estimate_b = EstimateRepo(session, ctx_b).add(_estimate(ctx_b, tender_b))
        session.commit()
        est_b = estimate_b.id
    _refused(
        ctx_a,
        _export(
            ctx_a,
            tender_a,
            kind="estimate_xlsx",
            label="approved",
            estimate_id=est_b,
            estimate_version=1,
        ),
        "fk_exports_estimate",
    )


def test_tender_of_another_organisation_is_refused() -> None:
    a, b = register("exp6c@example.com", org="Org A"), register("exp6d@example.com", org="Org B")
    ctx_a, tender_b = _ctx(a), make_tender(b)
    _refused(ctx_a, _export(ctx_a, tender_b), "fk_exports_tender")


def test_generator_must_be_a_member_of_the_organisation() -> None:
    a, b = register("exp7a@example.com", org="Org A"), register("exp7b@example.com", org="Org B")
    ctx_a, tender_a = _ctx(a), make_tender(a)
    _refused(
        ctx_a,
        _export(ctx_a, tender_a, generated_by=UUID(b.me["user_id"])),
        "fk_exports_generator_membership",
    )


def test_another_organisation_cannot_read_the_export() -> None:
    a, b = register("exp8a@example.com", org="Org A"), register("exp8b@example.com", org="Org B")
    ctx_a, ctx_b, tender_a = _ctx(a), _ctx(b), make_tender(a)
    with session_scope() as session:
        row = ExportRepo(session, ctx_a).add(_export(ctx_a, tender_a))
        assert ExportRepo(session, ctx_a).get(row.id).id == row.id
        with pytest.raises(NotFound):
            ExportRepo(session, ctx_b).get(row.id)
