"""Request dependencies: one transaction per request, and the OrgContext from the session cookie."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker, set_org
from app.infrastructure.storage import get_storage
from app.kernel import OrgContext, StoragePort
from app.modules.identity import public as identity

SESSION_COOKIE = "intel_session"


def get_session() -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on any error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


# scope="function": the commit runs when the handler returns, before the response is sent, so a
# failing commit becomes a 500 instead of a 2xx for work that was never saved.
DbSession = Annotated[Session, Depends(get_session, scope="function")]


def get_ctx(request: Request, session: DbSession) -> OrgContext:
    ctx = identity.resolve_context(session, request.cookies.get(SESSION_COOKIE))
    set_org(session, ctx.organisation_id)
    return ctx


Ctx = Annotated[OrgContext, Depends(get_ctx)]


Storage = Annotated[StoragePort, Depends(get_storage)]
