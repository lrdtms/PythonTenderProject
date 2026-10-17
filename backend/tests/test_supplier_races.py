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


def test_extract_boq_blocks_while_another_transaction_holds_the_tender_lock() -> None:
    from app.modules.jobs.models import Job
    from app.worker.runner import process_one
    from tests.conftest import upload
    from tests.test_matching_pipeline import PACK

    actor = register("race5@example.com")
    ctx = _ctx(actor)
    tender_id = make_tender(actor)
    upload(actor, tender_id, (PACK / "boq.xlsx").read_bytes(), "boq.xlsx", kind="boq")
    assert process_one(handlers.HANDLERS)  # ingest; it queues extract_boq
    finished: list[bool] = []
    thread = threading.Thread(target=lambda: finished.append(process_one(handlers.HANDLERS)))
    with session_scope() as holder:
        suppliers.lock_tender(holder, ctx, UUID(tender_id))  # e.g. a match decision
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), "extract_boq must wait for the tender lock"
    thread.join(timeout=30)
    assert finished == [True]
    with session_scope() as s:
        job = s.scalars(select(Job).where(Job.job_type == "extract_boq")).one()
        assert job.status == "succeeded"


def test_archive_waits_for_the_tender_lock() -> None:
    actor = register("race7@example.com")
    ctx = _ctx(actor)
    tender_id = make_tender(actor)
    responses: list[int] = []
    thread = threading.Thread(
        target=lambda: responses.append(
            actor.client.post(f"/api/v1/tenders/{tender_id}/archive").status_code
        )
    )
    with session_scope() as holder:
        suppliers.lock_tender(holder, ctx, UUID(tender_id))  # e.g. a match decision in flight
        thread.start()
        thread.join(timeout=2)
        assert thread.is_alive(), "archiving must wait for the tender lock"
    thread.join(timeout=30)
    assert responses == [200]
    assert actor.client.get(f"/api/v1/tenders/{tender_id}").json()["status"] == "archived"


def _request_while_locked(actor, ctx, tender_id: str, method: str, path: str, body=None) -> int:
    """Send a request from another thread while a transaction holds the tender lock.

    Returns the status; fails when the request is still waiting after 3 seconds."""
    out: list[int] = []
    thread = threading.Thread(
        target=lambda: out.append(actor.client.request(method, path, json=body).status_code)
    )
    with session_scope() as holder:
        suppliers.lock_tender(holder, ctx, UUID(tender_id))
        thread.start()
        thread.join(timeout=3)
        assert not thread.is_alive(), f"{method} {path} waited on a lock it may not take"
    thread.join(timeout=30)
    return out[0]


def test_archive_refuses_foreign_and_reviewer_callers_without_waiting() -> None:
    from tests.conftest import add_member

    owner = register("race8@example.com")
    ctx = _ctx(owner)
    tender_id = make_tender(owner)
    path = f"/api/v1/tenders/{tender_id}/archive"
    foreign = register("race8b@example.com")
    assert _request_while_locked(foreign, ctx, tender_id, "POST", path) == 404
    reviewer = add_member(owner, "race8c@example.com", "reviewer")
    assert _request_while_locked(reviewer, ctx, tender_id, "POST", path) == 403


def test_other_write_routes_refuse_unauthorised_callers_without_waiting() -> None:
    from uuid import uuid4

    from tests.conftest import add_member

    owner = register("race9@example.com")
    ctx = _ctx(owner)
    tender_id = make_tender(owner)
    foreign = register("race9b@example.com")
    reviewer = add_member(owner, "race9c@example.com", "reviewer")
    routes = [
        ("POST", f"/api/v1/quotation-items/{uuid4()}/confirm", None),
        ("PATCH", f"/api/v1/quotations/{uuid4()}", {"currency": "ZAR"}),
        ("POST", f"/api/v1/match-suggestions/{uuid4()}/confirm", None),
        ("POST", f"/api/v1/tenders/{tender_id}/match-suggestions/confirm-clear", None),
        ("POST", f"/api/v1/suppliers/{uuid4()}/merge", {"into_id": str(uuid4())}),
    ]
    for method, path, body in routes:
        status = _request_while_locked(foreign, ctx, tender_id, method, path, body)
        assert status == 404, (method, path, status)
        status = _request_while_locked(reviewer, ctx, tender_id, method, path, body)
        assert status == 403, (method, path, status)


def test_get_or_create_gives_try_again_when_the_twin_keeps_vanishing(monkeypatch) -> None:
    import pytest

    from app.kernel import Conflict

    actor = register("race6@example.com")
    monkeypatch.setattr(SupplierRepo, "by_key", lambda self, key: None)
    with session_scope() as s, pytest.raises(Conflict) as err:
        SupplierRepo(s, _ctx(actor)).get_or_create("Ghost", "ghost")
    assert err.value.code == "try_again"
