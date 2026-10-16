"""Requirement use cases: replace-unreviewed (worker) and list (API)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext, Permission

from .models import Requirement
from .repo import RequirementRepo
from .schemas import ReplaceResult, RequirementDTO


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
