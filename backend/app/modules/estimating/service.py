"""BoQ item use cases: replace-unreviewed (worker) and list (API)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext, Permission

from .models import BoqItem
from .repo import BoqRepo
from .schemas import BoqItemDTO, ReplaceResult


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _key(section: object, sheet: object, item_no: object) -> tuple[str, str] | None:
    """Identity of a BoQ line: (section or sheet, item number). No number: no identity."""
    if not _norm(item_no):
        return None
    return (_norm(section) or _norm(sheet), _norm(item_no))


def _jsonable(cand: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in cand.items()}


def replace_unreviewed(
    session: Session,
    ctx: OrgContext,
    version_id: UUID,
    run_id: UUID,
    cands: Sequence[Mapping[str, Any]],
) -> ReplaceResult:
    repo = BoqRepo(session, ctx)
    seen: set[tuple[str, str]] = set()
    for row in repo.reviewed(version_id):
        original = row.original_value or {}
        key = _key(
            original.get("section", row.section),
            original.get("sheet", row.sheet),
            original.get("item_no", row.item_no),
        )
        if key:
            seen.add(key)
    repo.delete_unreviewed(version_id)
    rows: list[dict[str, Any]] = []
    skipped = 0
    for cand in cands:
        key = _key(cand.get("section"), cand.get("sheet"), cand.get("item_no"))
        if key and key in seen:
            skipped += 1
            continue
        rows.append(
            {
                "run_id": run_id,
                "document_version_id": version_id,
                "position": len(rows),
                "source_order": int(cand.get("source_order", 0)),
                "section": cand.get("section"),
                "item_no": cand.get("item_no"),
                "description": cand["description"],
                "unit": cand.get("unit"),
                "quantity": cand.get("quantity"),
                "rate": cand.get("rate"),
                "raw_unit": cand.get("raw_unit"),
                "raw_quantity": cand.get("raw_quantity"),
                "flags": list(cand.get("flags") or []),
                "page_number": cand.get("page_number"),
                "sheet": cand.get("sheet"),
                "cell_range": cand.get("cell_range"),
                "original_value": _jsonable(cand),
            }
        )
    repo.insert_many(rows)
    return ReplaceResult(inserted=len(rows), duplicates_of_reviewed=skipped)


def _dto(item: BoqItem) -> BoqItemDTO:
    return BoqItemDTO(
        id=item.id,
        run_id=item.run_id,
        document_version_id=item.document_version_id,
        position=item.position,
        section=item.section,
        item_no=item.item_no,
        description=item.description,
        unit=item.unit,
        quantity=None if item.quantity is None else str(item.quantity),
        rate=None if item.rate is None else str(item.rate),
        raw_unit=item.raw_unit,
        raw_quantity=item.raw_quantity,
        flags=list(item.flags),
        page_number=item.page_number,
        sheet=item.sheet,
        cell_range=item.cell_range,
        review_status=item.review_status,
        corrected_value=item.corrected_value,
    )


def list_boq_items(
    session: Session, ctx: OrgContext, version_id: UUID, limit: int = 200, offset: int = 0
) -> list[BoqItemDTO]:
    ctx.require(Permission.READ)
    limit = max(1, min(limit, 1000))
    return [_dto(i) for i in BoqRepo(session, ctx).for_version(version_id, limit, max(0, offset))]
