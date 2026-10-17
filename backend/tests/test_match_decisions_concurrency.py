"""Match decisions against concurrent decisions, re-extraction and matching.

Each test forces the interleaving. A `Holder` thread takes the tender's advisory lock in its own
transaction, so the request under test must block on it; the test checks that the request has
not finished, lets the holder write and commit, then checks what the blocked request saw."""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.estimating.models import BoqItem
from app.modules.suppliers import public as suppliers
from app.modules.suppliers.models import MatchSuggestion
from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import Actor, add_member
from tests.test_extraction_pipeline import API, drain
from tests.test_matches_api import _decide, _flat, _get, _two_candidates
from tests.test_suppliers_api import _matched_org


class Holder:
    """Holds the tender lock until `finish()`, running `work(session)` under it first."""

    def __init__(self, actor: Actor, tender_id: str, work: Callable[[Session], None] | None = None):
        self.locked, self._go = threading.Event(), threading.Event()
        self._ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
        self._tender, self._work = UUID(tender_id), work
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            with session_scope() as s:
                suppliers.lock_tender(s, self._ctx, self._tender)
                self.locked.set()
                assert self._go.wait(60)
                if self._work:
                    self._work(s)
        except BaseException as e:  # noqa: BLE001
            self.error = e
            self.locked.set()

    def __enter__(self) -> Holder:
        self._thread.start()
        assert self.locked.wait(30) and self.error is None
        return self

    def finish(self) -> None:
        self._go.set()
        self._thread.join(30)
        assert not self._thread.is_alive() and self.error is None, self.error

    def __exit__(self, *exc) -> None:
        self._go.set()
        self._thread.join(30)


def _confirm_directly(match_id: str, user_id: str) -> Callable[[Session], None]:
    def work(s: Session) -> None:
        m = s.get(MatchSuggestion, UUID(match_id))
        m.status, m.decided_at, m.decided_by = "confirmed", datetime.now(UTC), UUID(user_id)

    return work


def test_a_decision_blocked_on_the_lock_sees_the_decision_that_committed_first() -> None:
    actor, tender_id = _matched_org("mc1@example.com")
    first, second = _two_candidates(actor, tender_id)
    with Holder(actor, tender_id, _confirm_directly(second, actor.me["user_id"])) as holder:
        with ThreadPoolExecutor(1) as pool:
            blocked = pool.submit(_decide, actor, first, "confirm")
            done = threading.Event()
            threading.Timer(1.0, done.set).start()
            assert done.wait(5) and not blocked.done(), "the decision must wait for the lock"
            holder.finish()
            r = blocked.result(30)
    assert r.status_code == 409 and r.json()["error"]["code"] == "match_conflict", r.text
    statuses = {s["id"]: s["status"] for s in _flat(_get(actor, tender_id, limit=500))}
    assert (statuses[first], statuses[second]) == ("suggested", "confirmed")


def test_two_simultaneous_confirms_of_the_same_slot_leave_exactly_one() -> None:
    actor, tender_id = _matched_org("mc2@example.com")
    first, second = _two_candidates(actor, tender_id)
    partner = add_member(actor, "mc2b@example.com", "estimator")
    barrier = threading.Barrier(2)

    def go(who: Actor, match_id: str):
        barrier.wait(10)
        return _decide(who, match_id, "confirm")

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(go, actor, first), pool.submit(go, partner, second)]
        results = [f.result(60) for f in futures]
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409], [r.text for r in results]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["error"]["code"] == "match_conflict"
    with session_scope() as db:
        rows = db.scalars(
            select(MatchSuggestion).where(MatchSuggestion.id.in_([UUID(first), UUID(second)]))
        ).all()
        assert sorted(m.status for m in rows) == ["confirmed", "suggested"]


def test_extraction_rerun_waits_for_a_decision_and_keeps_the_decided_line() -> None:
    actor, tender_id = _matched_org("mc3@example.com")
    s = _flat(_get(actor, tender_id, limit=500))[0]
    boq_ids_before = set(
        _all_boq_ids(),
    )
    boq_version = _boq_version(tender_id)
    r = actor.client.post(f"{API}/document-versions/{boq_version}/extract", json={})
    assert r.status_code == 202, r.text
    with Holder(actor, tender_id, _confirm_directly(s["id"], actor.me["user_id"])) as holder:
        with ThreadPoolExecutor(1) as pool:
            rerun = pool.submit(process_one, handlers.HANDLERS)
            done = threading.Event()
            threading.Timer(1.5, done.set).start()
            assert done.wait(5) and not rerun.done(), "the re-run must wait for the lock"
            holder.finish()
            assert rerun.result(60) is True
    drain()
    with session_scope() as db:
        match = db.get(MatchSuggestion, UUID(s["id"]))
        assert match is not None and match.status == "confirmed"
        assert db.get(BoqItem, UUID(s["boq_item_id"])) is not None  # same id, not re-created
    assert boq_ids_before >= {UUID(s["boq_item_id"])}
    assert (
        next(x for x in _flat(_get(actor, tender_id, limit=500)) if x["id"] == s["id"])["status"]
        == "confirmed"
    )


def _all_boq_ids() -> list[UUID]:
    with session_scope() as db:
        return list(db.scalars(select(BoqItem.id)))


def _boq_version(tender_id: str) -> str:
    with session_scope() as db:
        return str(db.scalars(select(BoqItem.document_version_id)).first())


def test_matching_and_confirm_clear_racing_leave_no_duplicates() -> None:
    actor, tender_id = _matched_org("mc4@example.com")
    partner = add_member(actor, "mc4b@example.com", "estimator")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def confirm_clear():
        barrier.wait(10)
        return partner.client.post(f"{API}/tenders/{tender_id}/match-suggestions/confirm-clear")

    def match():
        barrier.wait(10)
        queued = actor.client.post(f"{API}/tenders/{tender_id}/match")
        try:
            process_one(handlers.HANDLERS)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)
        return queued

    for _ in range(3):  # a few rounds: the outcome must not depend on who wins the lock
        barrier.reset()
        with ThreadPoolExecutor(2) as pool:
            a, b = pool.submit(confirm_clear), pool.submit(match)
            cleared, queued = a.result(60), b.result(60)
        assert cleared.status_code == 200 and queued.status_code == 202, (cleared.text, queued.text)
    assert not errors, errors
    drain()
    lines = _get(actor, tender_id, limit=500)
    slots = [
        (s["boq_item_id"], s["supplier"]["id"]) for s in _flat(lines) if s["status"] == "confirmed"
    ]
    assert slots and len(slots) == len(set(slots))
    pairs = [(s["boq_item_id"], s["quotation_item"]["id"]) for s in _flat(lines)]
    assert len(pairs) == len(set(pairs)), "no duplicate suggestion rows"
    with session_scope() as db:
        confirmed = db.scalars(
            select(MatchSuggestion).where(MatchSuggestion.status == "confirmed")
        ).all()
        keys = [(m.boq_item_id, m.supplier_id) for m in confirmed]
        assert len(keys) == len(set(keys))


def test_the_match_job_takes_the_tender_lock_before_it_reads(monkeypatch) -> None:
    actor, tender_id = _matched_org("mc5@example.com")
    calls: list[str] = []
    real_lock, real_inputs = handlers.suppliers.lock_tender, handlers._tender_inputs
    monkeypatch.setattr(
        handlers.suppliers, "lock_tender", lambda *a: (calls.append("lock"), real_lock(*a))[1]
    )
    monkeypatch.setattr(
        handlers, "_tender_inputs", lambda *a: (calls.append("read"), real_inputs(*a))[1]
    )
    assert actor.client.post(f"{API}/tenders/{tender_id}/match").status_code == 202
    drain()
    assert calls[:2] == ["lock", "read"], calls
