"""Requirement use cases: replace-unreviewed (worker) and list (API)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission, ValidationFailed
from app.modules.audit import public as audit

from .models import Requirement
from .repo import RequirementRepo
from .schemas import ReplaceResult, RequirementDTO, RequirementPatch


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def replace_unreviewed(
    session: Session,
    ctx: OrgContext,
    version_id: UUID,
    run_id: UUID,
    cands: Sequence[Mapping[str, Any]],
) -> ReplaceResult:
    repo = RequirementRepo(session, ctx)
    seen: set[str] = set()
    for row in repo.reviewed(version_id):
        original = row.original_value or {}
        key = _norm(original.get("evidence_quote", row.evidence_quote))
        if key:
            seen.add(key)
    repo.delete_unreviewed(version_id)
    rows: list[dict[str, Any]] = []
    skipped = 0
    for cand in cands:
        key = _norm(cand.get("evidence_quote"))
        if key and key in seen:
            skipped += 1
            continue
        rows.append(
            {
                "run_id": run_id,
                "document_version_id": version_id,
                "position": len(rows),
                "source_order": int(cand.get("source_order", 0)),
                "description": cand["description"],
                "requirement_type": cand["requirement_type"],
                "mandatory_status": cand["mandatory_status"],
                "evidence_quote": cand["evidence_quote"],
                "evidence_status": cand.get("evidence_status") or "verified",
                "needs_review": bool(cand.get("needs_review", False)),
                "page_number": cand.get("page_number"),
                "quote_start": cand.get("quote_start"),
                "quote_end": cand.get("quote_end"),
                "original_value": dict(cand),
            }
        )
    repo.insert_many(rows)
    return ReplaceResult(inserted=len(rows), duplicates_of_reviewed=skipped)


def _dto(item: Requirement) -> RequirementDTO:
    return RequirementDTO(
        id=item.id,
        run_id=item.run_id,
        document_version_id=item.document_version_id,
        position=item.position,
        description=item.description,
        requirement_type=item.requirement_type,
        mandatory_status=item.mandatory_status,
        evidence_quote=item.evidence_quote,
        evidence_status=item.evidence_status,
        needs_review=item.needs_review,
        page_number=item.page_number,
        quote_start=item.quote_start,
        quote_end=item.quote_end,
        review_status=item.review_status,
        corrected_value=item.corrected_value,
        original_value=dict(item.original_value or {}),
        reviewed_by=item.reviewed_by,
        reviewed_at=item.reviewed_at,
    )


def list_requirements(
    session: Session, ctx: OrgContext, version_id: UUID, limit: int = 200, offset: int = 0
) -> list[RequirementDTO]:
    ctx.require(Permission.READ)
    limit = max(1, min(limit, 1000))
    repo = RequirementRepo(session, ctx)
    return [_dto(i) for i in repo.for_version(version_id, limit, max(0, offset))]


def version_of(session: Session, ctx: OrgContext, item_id: UUID) -> UUID:
    ctx.require(Permission.REVIEW_DATA)
    return RequirementRepo(session, ctx).version_id_of(item_id)


def review_item(
    session: Session,
    ctx: OrgContext,
    item_id: UUID,
    action: Literal["confirm", "reject", "correct"],
    patch: RequirementPatch | None = None,
) -> RequirementDTO:
    """Call with the extraction lock held. A row a re-run deleted since lookup is `row_replaced`."""
    ctx.require(Permission.REVIEW_DATA)
    row = RequirementRepo(session, ctx).fresh(item_id)
    if row is None:
        raise Conflict(
            "This requirement was replaced by a newer extraction. Reload the list.",
            code="row_replaced",
        )
    fields: list[str] = []
    if action == "correct":
        if patch is None:
            raise ValidationFailed("No changes were given.")
        changes = {
            name: getattr(patch, name)
            for name in patch.model_fields_set
            if getattr(patch, name) != getattr(row, name)
        }
        if not changes:
            return _dto(row)
        for name, value in changes.items():
            setattr(row, name, value)
        row.corrected_value = {**(row.corrected_value or {}), **changes}
        row.review_status = "corrected"
        fields = sorted(changes)
    else:
        row.review_status = "confirmed" if action == "confirm" else "rejected"
    row.reviewed_by, row.reviewed_at = ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "requirement", row.id, f"review_{row.review_status}",
        {"status": row.review_status, "fields": fields},
    )  # fmt: skip
    session.flush()
    return _dto(row)
