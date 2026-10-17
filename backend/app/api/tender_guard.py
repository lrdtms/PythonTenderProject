"""The archived-tender refusal shared by every route that writes under the tender lock."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext
from app.modules.tenders import public as tenders


def refuse_archived(
    session: Session, ctx: OrgContext, tender_id: UUID, fresh: bool = False
) -> None:
    """409 `tender_archived`. Call once to refuse early (after authorising, before the lock) and
    again with `fresh=True` right after taking the lock: an archive that committed while the
    request waited must not be overtaken by a decision."""
    if tenders.is_archived(session, ctx, tender_id, fresh=fresh):
        raise Conflict(
            "This tender is archived. Re-open it before reviewing.", code="tender_archived"
        )
