"""Plan limits at the API edge: the router knows every module, so it gathers the counts and hands
them to `billing`, which only knows plans."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.kernel import OrgContext
from app.modules.billing import public as billing
from app.modules.documents import public as documents
from app.modules.identity import public as identity
from app.modules.reporting import public as reporting
from app.modules.tenders import public as tenders


def gather_counts(session: Session, ctx: OrgContext) -> billing.Counts:
    since = billing.month_start()
    return billing.Counts(
        tenders=tenders.count_active(session, ctx),
        uploads=documents.count_uploads_since(session, ctx, since),
        storage_bytes=documents.storage_bytes(session, ctx),
        exports=reporting.count_exports_since(session, ctx, since),
        members=identity.count_active_members(session, ctx),
    )


def enforce(session: Session, ctx: OrgContext, resource: billing.Resource, adding: int = 1) -> None:
    """Raise LimitExceeded (403) when creating `adding` more of `resource` would pass the plan."""
    counters = {
        billing.Resource.TENDERS: lambda: tenders.count_active(session, ctx),
        billing.Resource.UPLOADS: lambda: documents.count_uploads_since(
            session, ctx, billing.month_start()
        ),
        billing.Resource.STORAGE_MB: lambda: documents.storage_bytes(session, ctx),
        billing.Resource.EXPORTS: lambda: reporting.count_exports_since(
            session, ctx, billing.month_start()
        ),
        billing.Resource.MEMBERS: lambda: identity.count_active_members(session, ctx),
    }
    billing.check_limit(session, ctx, resource, counters[resource], adding)
