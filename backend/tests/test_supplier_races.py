"""Race-safety of supplier creation and the tender lock extraction takes."""

from __future__ import annotations

import threading
import time
from uuid import UUID

from sqlalchemy import func, select, text

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import Supplier
from app.modules.suppliers.repo import SupplierRepo
from app.worker import handlers
from tests.conftest import make_tender, register
from tests.quotation_helpers import quotation_context
from tests.test_matching_pipeline import QUOTES, _up


def _ctx(actor) -> OrgContext:
    return OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)


def test_get_or_create_concurrently_yields_one_supplier() -> None:
    actor = register("race1@example.com")
    ctx = _ctx(actor)
    barrier = threading.Barrier(2)
    results: list[tuple[UUID, bool]] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            with session_scope() as s:
                barrier.wait(timeout=10)
                supplier, created = SupplierRepo(s, ctx).get_or_create("New Co", "new co")
                time.sleep(0.2)  # hold the transaction open so the other insert has to wait
                results.append((supplier.id, created))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(results) == 2 and results[0][0] == results[1][0]
    assert sorted(created for _, created in results) == [False, True]
    with session_scope() as s:
        count = s.scalar(
            select(func.count())
            .select_from(Supplier)
            .where(Supplier.organisation_id == ctx.organisation_id)
        )
        assert count == 1


def test_store_quotation_for_two_versions_shares_one_new_supplier() -> None:
    with quotation_context(versions=2) as qc:
        ctx, versions, runs = qc.ctx, list(qc.versions), list(qc.runs)
    first_done = threading.Event()
    results: list[UUID] = []
    errors: list[BaseException] = []

    def store(n: int, name: str) -> None:
        try:
            with session_scope() as s:
                if n == 1:
                    assert first_done.wait(timeout=10)
                stored = suppliers.store_quotation(
                    s, ctx, versions[n], runs[n], {"supplier_name": name}, QUOTE_ROWS_DICTS, "f"
                )
                results.append(stored.supplier_id)
                if n == 0:
                    first_done.set()
                    time.sleep(0.5)  # commit late: the second insert must wait for it
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=store, args=(0, "Racer Supplies")),
        threading.Thread(target=store, args=(1, "racer supplies (Pty) Ltd")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors, errors
    assert len(results) == 2 and results[0] == results[1]
    with session_scope() as s:
        names = list(
            s.scalars(select(Supplier.name).where(Supplier.organisation_id == ctx.organisation_id))
        )
        assert len(names) == 1


QUOTE_ROWS_DICTS = [
    {"description": "Cable", "unit": "m", "quantity": "10", "unit_price": "5", "source_order": 0}
]


def _try_lock(tender_id: UUID) -> bool:
    key = int.from_bytes(tender_id.bytes[:8], "big", signed=True)
    with session_scope() as s:
        return bool(s.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key}))


def test_a_decision_transaction_holding_the_tender_lock_blocks_others() -> None:
    actor = register("race3@example.com")
    ctx = _ctx(actor)
    tender_id = UUID(make_tender(actor))
    with session_scope() as holder:
        suppliers.lock_tender(holder, ctx, tender_id)
        assert _try_lock(tender_id) is False  # extraction's lock cannot be taken meanwhile
        assert _try_lock(UUID(int=tender_id.int ^ (1 << 100))) is True  # other tenders are free
    assert _try_lock(tender_id) is True  # released on commit


def test_extraction_handlers_take_the_tender_lock(monkeypatch) -> None:
    locked: list[UUID] = []
    real = suppliers.lock_tender

    def spy(session, ctx, tender_id):
        locked.append(tender_id)
        real(session, ctx, tender_id)

    monkeypatch.setattr(handlers.suppliers, "lock_tender", spy)
    actor = register("race4@example.com")
    tender_id = make_tender(actor)
    _up(actor, tender_id, "boq.xlsx", "boq")
    _up(actor, tender_id, QUOTES[0], "quotation")
    assert len(locked) >= 2 and set(locked) == {UUID(tender_id)}
