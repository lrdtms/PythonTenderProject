"""Plan limits are enforced on every creating path, race-safely, per organisation."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text

from app.db.session import session_scope
from app.modules.documents.models import DocumentVersion
from app.modules.reporting.models import Export
from tests.conftest import (
    STRONG_PASSWORD,
    Actor,
    add_member,
    make_client,
    make_pdf,
    make_tender,
    register,
    upload,
)

PLAN = "/api/v1/usage/plan"
USAGE = "/api/v1/usage"


def _starter(actor: Actor) -> None:
    assert actor.client.put(PLAN, json={"plan_code": "starter"}).status_code == 200


def _refused(r) -> None:
    assert r.status_code == 403, r.text
    assert r.json()["error"]["code"] == "limit_exceeded"


def _pdf(n: int = 1) -> bytes:
    return make_pdf([f"page {n}"])


def test_fourth_tender_refused_403_limit_exceeded_and_nothing_created(admin: Actor) -> None:
    _starter(admin)
    for _ in range(3):
        make_tender(admin)
    r = admin.client.post("/api/v1/tenders", json={"title": "One too many"})
    _refused(r)
    assert len(admin.client.get("/api/v1/tenders").json()) == 3


def test_message_names_resource_limit_and_plan(admin: Actor) -> None:
    _starter(admin)
    for _ in range(3):
        make_tender(admin)
    message = admin.client.post("/api/v1/tenders", json={"title": "x"}).json()["error"]["message"]
    assert message == "Active tenders limit reached on the Starter plan (3 of 3)."


def test_archive_frees_a_tender_slot(admin: Actor) -> None:
    _starter(admin)
    ids = [make_tender(admin) for _ in range(3)]
    _refused(admin.client.post("/api/v1/tenders", json={"title": "x"}))
    assert admin.client.post(f"/api/v1/tenders/{ids[0]}/archive").status_code == 200
    assert admin.client.post("/api/v1/tenders", json={"title": "x"}).status_code == 201


def test_eleventh_upload_in_month_refused_and_last_month_does_not_count(admin: Actor) -> None:
    _starter(admin)
    tender = make_tender(admin)
    for i in range(10):
        assert upload(admin, tender, _pdf(i), f"d{i}.pdf").status_code == 201
    _refused(upload(admin, tender, _pdf(99), "late.pdf"))
    last_month = datetime.now(UTC) - timedelta(days=40)
    with session_scope() as s:
        for v in s.scalars(select(DocumentVersion)).all()[:3]:
            v.created_at = last_month
    assert upload(admin, tender, _pdf(100), "again.pdf").status_code == 201


def test_new_version_counts_as_an_upload(admin: Actor) -> None:
    _starter(admin)
    tender = make_tender(admin)
    first = upload(admin, tender, _pdf(0), "d0.pdf").json()
    for i in range(1, 10):
        assert upload(admin, tender, _pdf(i), f"d{i}.pdf").status_code == 201
    r = admin.client.post(
        f"/api/v1/documents/{first['document']['id']}/versions",
        files={"file": ("v2.pdf", _pdf(50), "application/pdf")},
    )
    _refused(r)


def test_storage_limit_counts_incoming_bytes_and_stores_nothing(admin: Actor) -> None:
    with session_scope() as s:
        s.execute(
            text(
                "INSERT INTO plans VALUES ('tiny', 'Tiny', 25, 200, 1, 200, 10)"
                " ON CONFLICT DO NOTHING"
            )
        )
    try:
        assert admin.client.put(PLAN, json={"plan_code": "tiny"}).status_code == 200
        tender = make_tender(admin)
        big = _pdf(1) + b"\n%" + b"x" * 1_200_000 + b"\n"
        r = upload(admin, tender, big, "big.pdf")
        _refused(r)
        assert "Storage limit reached on the Tiny plan" in r.json()["error"]["message"]
        assert admin.client.get(f"/api/v1/tenders/{tender}/documents").json() == []
        assert upload(admin, tender, _pdf(2), "small.pdf").status_code == 201
    finally:
        with session_scope() as s:
            s.execute(text("DELETE FROM organisation_plans"))
            s.execute(text("DELETE FROM plans WHERE code = 'tiny'"))


def _fill_exports(actor: Actor, tender_id: str, n: int) -> None:
    with session_scope() as s:
        for _ in range(n):
            s.add(
                Export(
                    organisation_id=UUID(actor.org_id),
                    tender_id=UUID(tender_id),
                    kind="checklist_pdf",
                    label="draft",
                    file_key=f"k/{uuid4()}",
                    file_name="x.pdf",
                    content_type="application/pdf",
                    file_size=1,
                    sha256="0" * 64,
                    row_count=0,
                    generated_by=UUID(actor.me["user_id"]),
                    generated_at=datetime.now(UTC),
                )
            )


def test_twenty_first_export_refused(admin: Actor) -> None:
    _starter(admin)
    tender = make_tender(admin)
    _fill_exports(admin, tender, 20)
    _refused(admin.client.post(f"/api/v1/tenders/{tender}/exports", json={"kind": "checklist_pdf"}))


def test_fourth_member_refused_and_reactivation_refused_at_limit(admin: Actor) -> None:
    _starter(admin)
    est = add_member(admin, "a@example.com", "estimator")
    add_member(admin, "b@example.com", "estimator")
    body = {"name": "C", "email": "c@example.com", "role": "estimator", "password": STRONG_PASSWORD}
    _refused(admin.client.post("/api/v1/members", json=body))
    members = admin.client.get("/api/v1/members").json()
    target = next(m for m in members if m["email"] == "a@example.com")
    assert (
        admin.client.post(f"/api/v1/members/{target['membership_id']}/deactivate").status_code
        == 200
    )
    assert admin.client.post("/api/v1/members", json=body).status_code == 201
    _refused(admin.client.post(f"/api/v1/members/{target['membership_id']}/reactivate"))
    assert est is not None


def test_reactivating_an_already_active_member_at_the_limit_is_not_blocked(admin: Actor) -> None:
    _starter(admin)
    add_member(admin, "a@example.com", "estimator")
    add_member(admin, "b@example.com", "estimator")
    members = admin.client.get("/api/v1/members").json()
    active = next(m for m in members if m["email"] == "a@example.com")
    assert (
        admin.client.post(f"/api/v1/members/{active['membership_id']}/reactivate").status_code
        == 200
    )


def test_reads_and_edits_not_blocked_when_over_limit(admin: Actor) -> None:
    ids = [make_tender(admin) for _ in range(5)]
    _starter(admin)
    assert len(admin.client.get("/api/v1/tenders").json()) == 5
    assert admin.client.get(f"/api/v1/tenders/{ids[0]}").status_code == 200
    assert (
        admin.client.patch(f"/api/v1/tenders/{ids[0]}", json={"title": "renamed"}).status_code
        == 200
    )
    _refused(admin.client.post("/api/v1/tenders", json={"title": "x"}))
    assert admin.client.get(USAGE).status_code == 200


def test_demo_plan_does_not_limit_normal_use(admin: Actor) -> None:
    for _ in range(6):
        make_tender(admin)
    tender = make_tender(admin)
    for i in range(3):
        assert upload(admin, tender, _pdf(i), f"d{i}.pdf").status_code == 201
    add_member(admin, "a@example.com", "estimator")


def test_other_organisation_usage_does_not_count(admin: Actor) -> None:
    other = register("b@example.com", org="Org B")
    for _ in range(3):
        make_tender(other)
    _starter(admin)
    assert admin.client.post("/api/v1/tenders", json={"title": "mine"}).status_code == 201


def _same_session_clients(actor: Actor, n: int):
    clients = []
    for _ in range(n):
        c = make_client()
        c.cookies.update(actor.client.cookies)
        clients.append(c)
    return clients


def _race(actor: Actor, call) -> list[int]:
    clients = _same_session_clients(actor, 2)
    barrier = threading.Barrier(2)

    def go(c):
        barrier.wait()
        return call(c).status_code

    with ThreadPoolExecutor(2) as pool:
        return sorted(pool.map(go, clients))


def test_last_slot_race_tenders(admin: Actor) -> None:
    _starter(admin)
    make_tender(admin)
    make_tender(admin)
    assert _race(admin, lambda c: c.post("/api/v1/tenders", json={"title": "race"})) == [201, 403]
    assert len(admin.client.get("/api/v1/tenders").json()) == 3


def test_last_slot_race_members(admin: Actor) -> None:
    _starter(admin)
    add_member(admin, "a@example.com", "estimator")
    counter = iter(range(10))

    def call(c):
        body = {
            "name": "N",
            "email": f"race{next(counter)}@example.com",
            "role": "estimator",
            "password": STRONG_PASSWORD,
        }
        return c.post("/api/v1/members", json=body)

    assert _race(admin, call) == [201, 403]
    assert len(admin.client.get("/api/v1/members").json()) == 3
