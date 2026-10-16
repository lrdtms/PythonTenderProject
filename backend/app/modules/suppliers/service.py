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

from . import matching
from .models import Quotation, Supplier
from .repo import MatchRepo, QuotationItemRepo, QuotationRepo, SupplierRepo
from .schemas import MatchResult, StoreResult

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


def _header_flags(name_missing: bool, fields: Mapping[str, Any]) -> list[str]:
    """Header warnings derived from the stored values (the name flag comes from the parse)."""
    flags = ["NO_SUPPLIER_NAME"] if name_missing else []
    for field, flag in (
        ("reference", "NO_REFERENCE"), ("quote_date", "NO_QUOTE_DATE"),
        ("valid_until", "NO_VALIDITY"), ("currency", "NO_CURRENCY"),
        ("prices_include_vat", "VAT_UNKNOWN"),
    ):  # fmt: skip
        if fields.get(field) is None:
            flags.append(flag)
    return flags


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
    name_missing = "NO_SUPPLIER_NAME" in (header.get("flags") or [])
    existing = quotations.for_version(version_id)

    created = False
    if existing is not None:
        supplier_id = existing.supplier_id  # a switch made by the user is never undone
    else:
        header_name = header.get("supplier_name")
        name = header_name or fallback_name or "Unknown supplier"
        if header_name:
            key = normalise_name(name) or name.lower().strip() or f"unknown supplier {version_id}"
            supplier = suppliers_repo.by_key(key)
        else:  # a file name says nothing about identity: never merge on it
            key, supplier = f"file:{version_id}", None
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
                      flags=_header_flags(name_missing, fields), **fields)
        )  # fmt: skip
    else:
        quotation = existing
        quotation.run_id = run_id
        for name_, value in fields.items():  # fill gaps only; never overwrite what is there
            if getattr(quotation, name_) is None and value is not None:
                setattr(quotation, name_, value)
        quotation.flags = _header_flags(
            name_missing, {k: getattr(quotation, k) for k in fields}
        )  # flags always agree with the stored fields
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


def match_tender(
    session: Session,
    ctx: OrgContext,
    tender_id: UUID,
    boq_lines: Sequence[matching.BoqLine],
    quote_version_ids: Sequence[UUID],
    closing_date: date | None,
) -> MatchResult:
    """Replace the undecided suggestions of the given BoQ lines and quotation versions.

    Decided matches (confirmed or rejected) are kept; a decided pair is not suggested again, and a
    BoQ line already confirmed for a supplier gets no further suggestion for that supplier."""
    matches = MatchRepo(session, ctx)
    matches.lock_tender(tender_id)
    pairs = QuotationItemRepo(session, ctx).for_versions(quote_version_ids)
    quote_lines = [
        matching.QuoteLine(
            i.id, q.supplier_id, q.id, i.description, i.sku, i.unit, i.unit_price, q.valid_until
        )
        for i, q in pairs
    ]
    existing = matches.for_items({b.id for b in boq_lines}, {q.id for q in quote_lines})
    decided = [m for m in existing if m.status != "suggested"]
    removed = matches.delete_suggested([m.id for m in existing if m.status == "suggested"])
    decided_pairs = {(m.boq_item_id, m.quotation_item_id) for m in decided}
    confirmed_slots = {(m.boq_item_id, m.supplier_id) for m in decided if m.status == "confirmed"}
    rows: list[dict[str, Any]] = []
    for s in matching.suggest(boq_lines, quote_lines, closing_date):
        if (s.boq_id, s.quote_id) in decided_pairs or (s.boq_id, s.supplier_id) in confirmed_slots:
            continue
        rows.append({
            "boq_item_id": s.boq_id, "quotation_item_id": s.quote_id,
            "supplier_id": s.supplier_id, "score": s.score,
            "classification": s.classification, "evidence": s.evidence,
        })  # fmt: skip
    matches.insert_many(rows)
    return MatchResult(suggested=len(rows), kept_decided=len(decided), removed_suggested=removed)


def decided_boq_item_ids(session: Session, ctx: OrgContext) -> set[UUID]:
    """BoQ lines that a person has confirmed or rejected a match for."""
    return MatchRepo(session, ctx).decided_boq_item_ids()
