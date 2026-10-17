"""Audit trail: append-only events with an allowlist of safe metadata keys."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext

from .models import AuditEvent

# Metadata keys that may be stored. Anything else is dropped so document text and secrets
# can never reach the audit trail by accident.
SAFE_METADATA_KEYS = frozenset(
    {"reason", "role", "old_role", "new_role", "status", "old_status", "new_status", "fields",
     "target_user_id", "count", "kind", "filename", "source_id", "into_id"}
)  # fmt: skip


def _safe(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (metadata or {}).items() if k in SAFE_METADATA_KEYS}


def record(
    session: Session,
    ctx: OrgContext | None,
    entity_type: str,
    entity_id: UUID | None,
    action: str,
    metadata: dict[str, Any] | None = None,
    *,
    user_id: UUID | None = None,
    organisation_id: UUID | None = None,
) -> None:
    """Add an audit event in the caller's transaction. Pass `ctx` inside an organisation, or
    explicit ids for events that happen outside one (for example a failed login)."""
    session.add(
        AuditEvent(
            organisation_id=ctx.organisation_id if ctx else organisation_id,
            user_id=ctx.user_id if ctx else user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            event_metadata=_safe(metadata),
        )
    )
