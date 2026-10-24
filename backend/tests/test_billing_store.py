"""Plans, month window and the per-module usage counts."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.billing import public as billing
from app.modules.billing.models import Plan
from app.modules.documents import public as documents
from app.modules.identity import public as identity
from app.modules.reporting import public as reporting
from app.modules.tenders import public as tenders
from tests.conftest import Actor, add_member, make_pdf, make_tender, register, upload


def _ctx(actor: Actor) -> OrgContext:
    return OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)


def test_migration_seeds_exactly_the_two_plans() -> None:
    with session_scope() as s:
        rows = {
            p.code: (
                p.max_tenders,
                p.max_uploads_per_month,
                p.max_storage_mb,
                p.max_exports_per_month,
                p.max_members,
            )
            for p in s.scalars(select(Plan))
        }
    assert rows == {"demo": (25, 200, 1024, 200, 10), "starter": (3, 10, 50, 20, 3)}


@pytest.mark.parametrize("column", ["max_tenders", "max_storage_mb", "max_members"])
@pytest.mark.parametrize("value", [0, -1])
def test_plan_limits_must_be_positive(column: str, value: int) -> None:
    with pytest.raises(IntegrityError), session_scope() as s:
        s.execute(
            text(
                "INSERT INTO plans (code, name, max_tenders, max_uploads_per_month, max_storage_mb,"
                " max_exports_per_month, max_members) VALUES ('bad', 'Bad', 1, 1, 1, 1, 1)"
            )
        )
        s.execute(
            text(f"UPDATE plans SET {column} = :v WHERE code = 'bad'"),  # noqa: S608
            {"v": value},
        )


def test_month_start_boundaries() -> None:
    assert billing.month_start(datetime(2026, 10, 31, 23, 59, 59, tzinfo=UTC)) == datetime(
        2026, 10, 1, tzinfo=UTC
    )
    assert billing.month_start(datetime(2026, 11, 1, 0, 0, 0, tzinfo=UTC)) == datetime(
        2026, 11, 1, tzinfo=UTC
    )


def test_no_plan_row_means_demo(admin: Actor) -> None:
    with session_scope() as s:
        usage = billing.usage_for(s, _ctx(admin), billing.Counts(0, 0, 0, 0, 1))
    assert usage.plan_code == "demo"
    assert {i.resource: i.limit for i in usage.items}["tenders"] == 25


def test_count_functions_are_organisation_scoped_and_ignore_archived(admin: Actor) -> None:
    other = register("b@example.com", org="Org B")
    t1 = make_tender(admin)
    make_tender(admin)
    make_tender(other)
    assert admin.client.post(f"/api/v1/tenders/{t1}/archive").status_code == 200
    upload(admin, make_tender(admin), make_pdf(["hello"]), "a.pdf")
    upload(other, make_tender(other), make_pdf(["other"]), "b.pdf")
    add_member(admin, "est@example.com", "estimator")
    since = datetime(2000, 1, 1, tzinfo=UTC)
    with session_scope() as s:
        ctx = _ctx(admin)
        assert tenders.count_active(s, ctx) == 2  # three created, one archived
        assert documents.count_uploads_since(s, ctx, since) == 1
        assert documents.storage_bytes(s, ctx) > 0
        assert reporting.count_exports_since(s, ctx, since) == 0
        assert identity.count_active_members(s, ctx) == 2


def test_uploads_before_the_month_start_do_not_count(admin: Actor) -> None:
    upload(admin, make_tender(admin), make_pdf(["hello"]), "a.pdf")
    with session_scope() as s:
        assert documents.count_uploads_since(s, _ctx(admin), datetime(2100, 1, 1, tzinfo=UTC)) == 0
