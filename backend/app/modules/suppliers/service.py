"""Supplier and quotation use cases (worker side in Slice 5a phase 1)."""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.kernel import Conflict, OrgContext, Permission, ValidationFailed
from app.modules.audit import public as audit

from . import matching
from .models import MatchSuggestion, Quotation, QuotationItem, Supplier
from .repo import MatchRepo, QuotationItemRepo, QuotationRepo, SupplierRepo
from .schemas import (
    ConfirmClearResult,
    MatchQuoteRef,
    MatchResult,
    MatchSuggestionDTO,
    MatchSupplierRef,
    QuotationDTO,
    QuotationItemDTO,
    QuotationItemPatch,
    QuotationPatch,
    StoreResult,
    SupplierCreate,
    SupplierDTO,
    SupplierPatch,
)

_SUFFIXES = re.compile(r"\b(pty|proprietary|ltd|limited|cc|inc|co|company|\(pty\))\b\.?", re.I)


def normalise_name(name: str) -> str:
    """Identity of a supplier name: lower case, company suffixes and punctuation removed."""
    text = _SUFFIXES.sub(" ", name.lower())
    text = re.sub(r"[^\w\s&]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def supplier_key(name: str, empty: str = "") -> str:
    """The one rule for a supplier's identity key: the normalised name, else the lower-cased
    name, else `empty`."""
    return (normalise_name(name) or name.lower().strip() or empty)[:200]


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
            key = supplier_key(name, f"unknown supplier {version_id}")
        else:  # a file name says nothing about identity: never merge on it
            key = f"file:{version_id}"
        supplier, created = suppliers_repo.get_or_create(_display(name)[:200], key[:200])
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


def _dto(supplier: Supplier, count: int) -> SupplierDTO:
    return SupplierDTO(
        id=supplier.id, name=supplier.name, notes=supplier.notes,
        quotation_count=count, created_at=supplier.created_at,
    )  # fmt: skip


def list_suppliers(session: Session, ctx: OrgContext) -> list[SupplierDTO]:
    ctx.require(Permission.READ)
    return [_dto(s, n) for s, n in SupplierRepo(session, ctx).list_with_counts()]


def get_supplier(session: Session, ctx: OrgContext, supplier_id: UUID) -> SupplierDTO:
    ctx.require(Permission.READ)
    repo = SupplierRepo(session, ctx)
    return _dto(repo.get(supplier_id), repo.quotation_count(supplier_id))


def create_supplier(session: Session, ctx: OrgContext, body: SupplierCreate) -> SupplierDTO:
    ctx.require(Permission.REVIEW_DATA)
    supplier, created = SupplierRepo(session, ctx).get_or_create(body.name, supplier_key(body.name))
    if not created:
        raise Conflict("A supplier with this name already exists.", code="supplier_exists")
    supplier.notes = body.notes
    session.flush()
    fields = ["name", "notes"] if body.notes is not None else ["name"]
    audit.record(session, ctx, "supplier", supplier.id, "supplier_created", {"fields": fields})
    return _dto(supplier, 0)


def update_supplier(
    session: Session, ctx: OrgContext, supplier_id: UUID, body: SupplierPatch
) -> SupplierDTO:
    ctx.require(Permission.REVIEW_DATA)
    repo = SupplierRepo(session, ctx)
    supplier = repo.get(supplier_id)
    fields: list[str] = []
    if body.name is not None and "name" in body.model_fields_set and body.name != supplier.name:
        repo.rename(supplier, body.name, supplier_key(body.name))
        fields.append("name")
    if "notes" in body.model_fields_set and body.notes != supplier.notes:
        supplier.notes = body.notes
        fields.append("notes")
    session.flush()
    if fields:
        audit.record(session, ctx, "supplier", supplier.id, "supplier_updated", {"fields": fields})
    return _dto(supplier, repo.quotation_count(supplier_id))


def tenders_of_supplier(session: Session, ctx: OrgContext, supplier_id: UUID) -> set[UUID]:
    """Document version ids of the supplier's quotations, so a caller can resolve and lock the
    affected tenders."""
    ctx.require(Permission.REVIEW_DATA)
    repo = SupplierRepo(session, ctx)
    repo.get(supplier_id)
    return repo.version_ids(supplier_id)


def merge_suppliers(
    session: Session, ctx: OrgContext, source_id: UUID, into_id: UUID
) -> SupplierDTO:
    """Call with the affected tenders' locks held. Moves every quotation and match of the source
    to the target and deletes the source, or changes nothing (409 `match_conflict`) when a BoQ
    line would end up with two confirmed matches for the target."""
    ctx.require(Permission.REVIEW_DATA)
    repo = SupplierRepo(session, ctx)
    source = repo.get(source_id)
    if source_id == into_id:
        raise ValidationFailed("Choose a different supplier.")
    target = repo.get(into_id)
    if repo.confirmed_boq_ids(source_id) & repo.confirmed_boq_ids(into_id):
        raise Conflict(
            "Both suppliers have a confirmed match for the same BoQ line. "
            "Reject one of them before merging.",
            code="match_conflict",
        )
    try:  # the tender locks make a concurrent change impossible; if one still lands, undo
        with session.begin_nested():
            repo.move_to(source_id, into_id)
            repo.remove(source)
    except IntegrityError:
        raise Conflict(
            "The suppliers changed while merging. Try again.", code="try_again"
        ) from None
    audit.record(
        session, ctx, "supplier", into_id, "supplier_merged",
        {"source_id": str(source_id), "into_id": str(into_id)},
    )  # fmt: skip
    return _dto(target, repo.quotation_count(into_id))


def lock_tender(session: Session, ctx: OrgContext, tender_id: UUID) -> None:
    """Serialise matching, match decisions, extraction and merges for one tender."""
    MatchRepo(session, ctx).lock_tender(tender_id)


# --- match suggestions (API side) --------------------------------------------------------------


def _suggestion_dto(
    m: MatchSuggestion, item: QuotationItem, quotation: Quotation, supplier: Supplier
) -> MatchSuggestionDTO:
    return MatchSuggestionDTO(
        id=m.id, status=m.status, classification=m.classification,
        rank=int((m.evidence or {}).get("rank", 0)), score=float(m.score),
        evidence=dict(m.evidence or {}),
        supplier=MatchSupplierRef(id=supplier.id, name=supplier.name),
        quotation_item=MatchQuoteRef(
            id=item.id, quotation_id=quotation.id, description=item.description, sku=item.sku,
            unit=item.unit,
            quantity=None if item.quantity is None else str(item.quantity),
            unit_price=None if item.unit_price is None else str(item.unit_price),
            valid_until=quotation.valid_until,
        ),
        boq_item_id=m.boq_item_id, decided_by=m.decided_by, decided_at=m.decided_at,
    )  # fmt: skip


def suggestions_for(
    session: Session,
    ctx: OrgContext,
    boq_ids: Sequence[UUID],
    quote_version_ids: Sequence[UUID],
    status: str | None = None,
    classification: str | None = None,
    supplier_id: UUID | None = None,
) -> list[MatchSuggestionDTO]:
    """Suggestions for the given BoQ lines (current quotation versions, non-rejected items only),
    ordered by the BoQ order given, then supplier name, then rank. Never ordered by price."""
    ctx.require(Permission.READ)
    rows = MatchRepo(session, ctx).joined(
        boq_ids, quote_version_ids, status, classification, supplier_id
    )
    order = {b: n for n, b in enumerate(boq_ids)}
    dtos = [(order[m.boq_item_id], _suggestion_dto(m, i, q, s)) for m, i, q, s in rows]
    dtos.sort(key=lambda t: (t[0], t[1].supplier.name.lower(), t[1].supplier.id.int,
                             t[1].rank, t[1].id.int))  # fmt: skip
    return [d for _, d in dtos]


def suggestion_tender_version(session: Session, ctx: OrgContext, suggestion_id: UUID) -> UUID:
    """The document version of the suggestion's quotation item, so the router can resolve and
    lock its tender."""
    ctx.require(Permission.REVIEW_DATA)
    return MatchRepo(session, ctx).tender_version_id(suggestion_id)


_TARGET = {"confirm": "confirmed", "reject": "rejected", "reset": "suggested"}
_AUDIT = {"confirm": "match_confirmed", "reject": "match_rejected", "reset": "match_reset"}


def decide(
    session: Session,
    ctx: OrgContext,
    suggestion_id: UUID,
    action: Literal["confirm", "reject", "reset"],
    current_quote_version_ids: Collection[UUID],
    current_boq_ids: Collection[UUID],
) -> MatchSuggestionDTO:
    """Call with the tender lock held. 409 `stale_match` when the suggestion's quotation version or
    BoQ line is no longer current; 409 `match_conflict` when confirming would give the BoQ line a
    second confirmed match for the same supplier. Repeating the current state changes nothing."""
    ctx.require(Permission.REVIEW_DATA)
    repo = MatchRepo(session, ctx)
    m, item, quotation, supplier = repo.joined_one(suggestion_id)
    if (
        item.document_version_id not in current_quote_version_ids
        or m.boq_item_id not in current_boq_ids
        or item.review_status == "rejected"
    ):
        raise Conflict(
            "This suggestion belongs to an older version. Reload the list.", code="stale_match"
        )
    target = _TARGET[action]
    if m.status != target:
        if action == "confirm" and repo.other_confirmed(m):
            raise Conflict(
                "This BoQ line already has a confirmed match for this supplier. "
                "Reject or reset that one first.",
                code="match_conflict",
            )
        try:  # the unique index is the last word if a writer slipped past the lock
            with session.begin_nested():
                m.status = target
                m.decided_by, m.decided_at = (
                    (None, None) if action == "reset" else (ctx.user_id, datetime.now(UTC))
                )
                session.flush()
        except IntegrityError:
            session.refresh(m)
            raise Conflict(
                "This BoQ line already has a confirmed match for this supplier.",
                code="match_conflict",
            ) from None
        audit.record(
            session, ctx, "match_suggestion", m.id, _AUDIT[action],
            {"status": target},
        )  # fmt: skip
    return _suggestion_dto(m, item, quotation, supplier)


def confirm_clear(
    session: Session,
    ctx: OrgContext,
    tender_id: UUID,
    current_quote_version_ids: Collection[UUID],
    current_boq_ids: Collection[UUID],
) -> ConfirmClearResult:
    """Call with the tender lock held. Confirms every undecided `clear` suggestion of a current
    BoQ line and quotation item, except where the BoQ line already has a confirmed match for the
    supplier or another row confirmed in this call took the slot (counted as `skipped`)."""
    ctx.require(Permission.REVIEW_DATA)
    repo = MatchRepo(session, ctx)
    rows = repo.joined(current_boq_ids, current_quote_version_ids, "suggested", "clear")
    rows.sort(key=lambda r: (r[0].boq_item_id.int, r[0].supplier_id.int, -float(r[0].score),
                             r[0].id.int))  # fmt: skip
    taken = repo.confirmed_slots(current_boq_ids)
    confirmed = skipped = 0
    now = datetime.now(UTC)
    for m, _item, _quotation, _supplier in rows:
        slot = (m.boq_item_id, m.supplier_id)
        if slot in taken:
            skipped += 1
            continue
        taken.add(slot)
        m.status, m.decided_by, m.decided_at = "confirmed", ctx.user_id, now
        confirmed += 1
    session.flush()
    audit.record(
        session, ctx, "tender", tender_id, "match_confirm_clear",
        {"confirmed": confirmed, "skipped": skipped},
    )  # fmt: skip
    return ConfirmClearResult(confirmed=confirmed, skipped=skipped)


# --- quotations and their items (API side) -----------------------------------------------------


def _quotation_dto(q: Quotation, supplier_name: str, count: int) -> QuotationDTO:
    return QuotationDTO(
        id=q.id, document_version_id=q.document_version_id, supplier_id=q.supplier_id,
        supplier_name=supplier_name, reference=q.reference, quote_date=q.quote_date,
        valid_until=q.valid_until, currency=q.currency, prices_include_vat=q.prices_include_vat,
        flags=list(q.flags), item_count=count, created_at=q.created_at,
    )  # fmt: skip


def list_quotations(
    session: Session, ctx: OrgContext, version_ids: Sequence[UUID]
) -> list[QuotationDTO]:
    ctx.require(Permission.READ)
    rows = QuotationRepo(session, ctx).list_for_versions(list(version_ids))
    return [_quotation_dto(q, name, n) for q, name, n in rows]


def get_quotation_tender_version(session: Session, ctx: OrgContext, quotation_id: UUID) -> UUID:
    """The document version of a quotation, so the router can resolve and lock its tender."""
    ctx.require(Permission.REVIEW_DATA)
    return QuotationRepo(session, ctx).get(quotation_id).document_version_id


def update_quotation(
    session: Session, ctx: OrgContext, quotation_id: UUID, patch: QuotationPatch
) -> QuotationDTO:
    """Call with the tender lock held. Switching the supplier moves the quotation's matches too."""
    ctx.require(Permission.REVIEW_DATA)
    repo = QuotationRepo(session, ctx)
    quotation = repo.get(quotation_id)
    changed: list[str] = []
    for name in sorted(patch.model_fields_set):
        value = getattr(patch, name)
        if value == getattr(quotation, name):
            continue
        if name == "supplier_id":
            suppliers_repo = SupplierRepo(session, ctx)
            suppliers_repo.get(value)  # NotFound for a supplier of another organisation
            if repo.confirmed_boq_ids(quotation_id) & suppliers_repo.confirmed_boq_ids(value):
                raise Conflict(
                    "The new supplier already has a confirmed match for the same BoQ line. "
                    "Reject one of them first.",
                    code="match_conflict",
                )
            try:  # the tender lock prevents a concurrent change; if one still lands, undo
                with session.begin_nested():
                    quotation.supplier_id = value
                    repo.move_matches(quotation_id, value)
                    session.flush()
            except IntegrityError:
                raise Conflict("The suppliers changed. Try again.", code="try_again") from None
        else:
            setattr(quotation, name, value)
        changed.append(name)
    if changed:
        fields = ("reference", "quote_date", "valid_until", "currency", "prices_include_vat")
        quotation.flags = _header_flags(
            "NO_SUPPLIER_NAME" in quotation.flags, {k: getattr(quotation, k) for k in fields}
        )
        session.flush()
        audit.record(
            session, ctx, "quotation", quotation.id, "quotation_updated", {"fields": changed}
        )
    name, count = repo.with_supplier_name(quotation)
    return _quotation_dto(quotation, name, count)


def _item_dto(item: QuotationItem) -> QuotationItemDTO:
    return QuotationItemDTO(
        id=item.id, quotation_id=item.quotation_id, document_version_id=item.document_version_id,
        run_id=item.run_id, position=item.position, description=item.description, sku=item.sku,
        unit=item.unit,
        quantity=None if item.quantity is None else str(item.quantity),
        unit_price=None if item.unit_price is None else str(item.unit_price),
        raw_unit=item.raw_unit, raw_quantity=item.raw_quantity, raw_price=item.raw_price,
        flags=list(item.flags), page_number=item.page_number, sheet=item.sheet,
        cell_range=item.cell_range, review_status=item.review_status,
        corrected_value=item.corrected_value, original_value=dict(item.original_value or {}),
        reviewed_by=item.reviewed_by, reviewed_at=item.reviewed_at,
    )  # fmt: skip


def list_quotation_items(
    session: Session, ctx: OrgContext, version_id: UUID, limit: int = 200, offset: int = 0
) -> list[QuotationItemDTO]:
    ctx.require(Permission.READ)
    limit = max(1, min(limit, 1000))
    rows = QuotationItemRepo(session, ctx).for_version(version_id, limit, max(0, offset))
    return [_item_dto(i) for i in rows]


def quotation_item_version(session: Session, ctx: OrgContext, item_id: UUID) -> UUID:
    """The version an item belongs to, so the caller can take the locks first."""
    ctx.require(Permission.REVIEW_DATA)
    return QuotationItemRepo(session, ctx).version_id_of(item_id)


def _apply_item(row: QuotationItem, patch: QuotationItemPatch) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for name in patch.model_fields_set:
        new: Any = getattr(patch, name)
        if name in ("quantity", "unit_price") and new is not None:
            new = Decimal(new)
            if name == "unit_price" and new <= 0:
                raise ValidationFailed("The unit price must be above zero. Clear it instead.")
        if new == getattr(row, name):
            continue
        setattr(row, name, new)
        changes[name] = str(new) if isinstance(new, Decimal) else new
    flags = list(row.flags)
    if "quantity" in changes:
        flags = [
            f for f in flags if f not in ("missing_quantity", "quantity_unparsed", "zero_quantity")
        ]
        if row.quantity is None:
            flags.append("missing_quantity")
        elif row.quantity == 0:
            flags.append("zero_quantity")
    if "unit_price" in changes:
        price_flags = ("missing_price", "price_unparsed", "zero_price", "negative_price")
        flags = [f for f in flags if f not in price_flags]
        if row.unit_price is None:
            flags.append("missing_price")
    if "quantity" in changes or "unit_price" in changes:
        flags = [f for f in flags if f != "ambiguous_separator"]  # a person has read the figure
    row.flags = flags  # a new list, so the JSONB change is detected
    return changes


def review_quotation_item(
    session: Session,
    ctx: OrgContext,
    item_id: UUID,
    action: Literal["confirm", "reject", "correct"],
    patch: QuotationItemPatch | None = None,
) -> QuotationItemDTO:
    """Call with the tender and extraction locks held. An item a re-run deleted since the caller
    looked it up is `row_replaced`."""
    ctx.require(Permission.REVIEW_DATA)
    row = QuotationItemRepo(session, ctx).fresh(item_id)
    if row is None:
        raise Conflict(
            "This line was replaced by a newer extraction. Reload the list.", code="row_replaced"
        )
    fields: list[str] = []
    if action == "correct":
        if patch is None:
            raise ValidationFailed("No changes were given.")
        changes = _apply_item(row, patch)
        if not changes:
            return _item_dto(row)
        row.corrected_value = {**(row.corrected_value or {}), **changes}
        row.review_status = "corrected"
        fields = sorted(changes)
    else:
        row.review_status = "confirmed" if action == "confirm" else "rejected"
    row.reviewed_by, row.reviewed_at = ctx.user_id, datetime.now(UTC)
    audit.record(
        session, ctx, "quotation_item", row.id, f"review_{row.review_status}",
        {"status": row.review_status, "fields": fields},
    )  # fmt: skip
    session.flush()
    return _item_dto(row)
