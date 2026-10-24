"""Organisation-scoped audit reads. Events with no organisation are never returned."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.kernel import OrgContext, ValidationFailed

from .models import AuditEvent
from .schemas import AuditFilters


def encode_cursor(created_at: datetime, event_id: UUID) -> str:
    raw = f"{created_at.isoformat()}|{event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        text = base64.urlsafe_b64decode(cursor.encode()).decode()
        stamp, ident = text.split("|")
        return datetime.fromisoformat(stamp), UUID(ident)
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise ValidationFailed("Invalid cursor") from exc


class AuditRepo:
    def __init__(self, session: Session, ctx: OrgContext):
        self.session = session
        self.ctx = ctx

    def _org(self):
        return AuditEvent.organisation_id == self.ctx.organisation_id

    def page(
        self, filters: AuditFilters, cursor: str | None, limit: int
    ) -> tuple[list[AuditEvent], bool]:
        stmt = select(AuditEvent).where(self._org())
        if filters.entity_type:
            stmt = stmt.where(AuditEvent.entity_type == filters.entity_type)
        if filters.action:
            stmt = stmt.where(AuditEvent.action == filters.action)
        if filters.user_id:
            stmt = stmt.where(AuditEvent.user_id == filters.user_id)
        if filters.date_from:
            start = datetime.combine(filters.date_from, time.min, tzinfo=UTC)
            stmt = stmt.where(AuditEvent.created_at >= start)
        if filters.date_to:
            end = datetime.combine(filters.date_to, time.min, tzinfo=UTC) + timedelta(days=1)
            stmt = stmt.where(AuditEvent.created_at < end)
        if cursor:
            at, ident = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    AuditEvent.created_at < at,
                    and_(AuditEvent.created_at == at, AuditEvent.id < ident),
                )
            )
        stmt = stmt.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit + 1)
        rows = list(self.session.scalars(stmt))
        return rows[:limit], len(rows) > limit

    def facets(self) -> tuple[list[str], list[str]]:
        types = self.session.scalars(
            select(AuditEvent.entity_type)
            .where(self._org())
            .distinct()
            .order_by(AuditEvent.entity_type)
        )
        actions = self.session.scalars(
            select(AuditEvent.action).where(self._org()).distinct().order_by(AuditEvent.action)
        )
        return list(types), list(actions)
