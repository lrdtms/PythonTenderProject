"""Queue the matching job of a tender after an edit that changes its matching inputs."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext
from app.modules.documents import public as documents
from app.modules.jobs import public as jobs


def enqueue_match(session: Session, ctx: OrgContext, tender_id: UUID) -> jobs.JobDTO:
    """`enqueue` returns the active job when one exists, so a burst of edits yields one job."""
    return jobs.enqueue(session, ctx, documents.MATCH_SUPPLIERS_JOB, "tender", tender_id, {})
