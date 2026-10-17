"""Fill `reviewed_by_name` on review DTOs (estimators cannot list members, but may see names)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext
from app.modules.identity import public as identity


class _Reviewed(Protocol):
    reviewed_by: UUID | None
    reviewed_by_name: str | None


class _Decided(Protocol):
    decided_by: UUID | None
    decided_by_name: str | None


def with_decider_names[T: _Decided](
    session: Session, ctx: OrgContext, dtos: Sequence[T]
) -> list[T]:
    """Same as `with_reviewer_names`, for match decisions (`decided_by`)."""
    ids = {d.decided_by for d in dtos if d.decided_by}
    names = identity.member_names(session, ctx, ids) if ids else {}
    for dto in dtos:
        if dto.decided_by:
            dto.decided_by_name = names.get(dto.decided_by)
    return list(dtos)


def with_reviewer_names[T: _Reviewed](
    session: Session, ctx: OrgContext, dtos: Sequence[T]
) -> list[T]:
    ids = {d.reviewed_by for d in dtos if d.reviewed_by}
    names = identity.member_names(session, ctx, ids) if ids else {}
    for dto in dtos:
        if dto.reviewed_by:
            dto.reviewed_by_name = names.get(dto.reviewed_by)
    return list(dtos)
