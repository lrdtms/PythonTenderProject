"""Engine and session factory. Sessions run one transaction each (commit on success)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def set_org(session: Session, organisation_id: UUID) -> None:
    """Expose the acting organisation to the database (RLS-ready, ADR-0005). Transaction-local."""
    session.execute(
        text("SELECT set_config('app.org_id', :org, true)"), {"org": str(organisation_id)}
    )


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transaction for scripts, the worker and tests: commit on success, roll back on error."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def ping() -> None:
    """Raise if the database is unreachable (used by the health endpoint)."""
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
