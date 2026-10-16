"""Supplier and quotation use cases (worker side in Slice 5a phase 1)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.kernel import OrgContext

from .models import Quotation, Supplier
from .repo import QuotationItemRepo, QuotationRepo, SupplierRepo
from .schemas import StoreResult

_SUFFIXES = re.compile(r"\b(pty|proprietary|ltd|limited|cc|inc|co|company|\(pty\))\b\.?", re.I)


def normalise_name(name: str) -> str:
    """Identity of a supplier name: lower case, company suffixes and punctuation removed."""
    text = _SUFFIXES.sub(" ", name.lower())
    text = re.sub(r"[^\w\s&]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _display(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip()
    return name.title() if name.isupper() or name.islower() else name


def _jsonable(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def _item_key(sku: object, description: object, unit: object) -> str:
    if sku:
        return "sku:" + str(sku).strip().lower()
    return (
        "d:" + re.sub(r"\s+", " ", str(description or "")).strip().lower() + "|" + str(unit or "")
    )


def _date(value: object) -> date | None:
    return date.fromisoformat(value) if isinstance(value, str) and value else None


def store_quotation(
    session: Session,
    ctx: OrgContext,
    version_id: UUID,
    run_id: UUID,
    header: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    fallback_name: str,
) -> StoreResult:
    suppliers_repo = SupplierRepo(session, ctx)
    quotations = QuotationRepo(session, ctx)
    items = QuotationItemRepo(session, ctx)
    flags = list(header.get("flags") or [])
    existing = quotations.for_version(version_id)

    created = False
    if existing is not None:
        supplier_id = existing.supplier_id  # a switch made by the user is never undone
    else:
        name = header.get("supplier_name") or fallback_name or "Unknown supplier"
        key = normalise_name(name) or "unknown supplier"
        supplier = suppliers_repo.by_key(key)
        if supplier is None:
            supplier = suppliers_repo.add(Supplier(name=_display(name)[:200], name_key=key[:200]))
            created = True
        supplier_id = supplier.id

    fields = {
        "reference": header.get("reference"),
        "quote_date": _date(header.get("quote_date")),
        "valid_until": _date(header.get("valid_until")),
        "currency": header.get("currency"),
        "prices_include_vat": header.get("prices_include_vat"),
    }
    if existing is None:
        quotation: Quotation = quotations.add(
            Quotation(document_version_id=version_id, run_id=run_id, supplier_id=supplier_id,
                      flags=flags, **fields)
        )  # fmt: skip
    else:
        quotation = existing
        quotation.run_id = run_id
        quotation.flags = flags
        for name_, value in fields.items():  # fill gaps only; never overwrite what is there
            if getattr(quotation, name_) is None and value is not None:
                setattr(quotation, name_, value)
        session.flush()

    kept = items.reviewed_or_pinned(quotation.id)
    seen = set()
    for item in kept:
        original = item.original_value or {}
        seen.add(
            _item_key(
                original.get("sku", item.sku),
                original.get("description", item.description),
                original.get("unit", item.unit),
            )
        )
    items.delete_replaceable(quotation.id, {i.id for i in kept})

    new_rows: list[dict[str, Any]] = []
    skipped = 0
    for cand in rows:
        key = _item_key(cand.get("sku"), cand.get("description"), cand.get("unit"))
        if key in seen:
            skipped += 1
            continue
        new_rows.append({
            "quotation_id": quotation.id, "document_version_id": version_id, "run_id": run_id,
            "position": len(new_rows), "source_order": int(cand.get("source_order", 0)),
            "description": cand["description"], "sku": cand.get("sku"), "unit": cand.get("unit"),
            "quantity": cand.get("quantity"), "unit_price": cand.get("unit_price"),
            "raw_unit": cand.get("raw_unit"), "raw_quantity": cand.get("raw_quantity"),
            "raw_price": cand.get("raw_price"), "flags": list(cand.get("flags") or []),
            "page_number": cand.get("page_number"), "sheet": cand.get("sheet"),
            "cell_range": cand.get("cell_range"), "original_value": _jsonable(cand),
        })  # fmt: skip
    items.insert_many(new_rows)
    return StoreResult(len(new_rows), skipped, supplier_id, quotation.id, created)
