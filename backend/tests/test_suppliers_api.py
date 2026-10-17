"""Suppliers API: list, create, rename, notes, merge, roles."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.suppliers.models import MatchSuggestion, Supplier
from tests.conftest import Actor, add_member, make_tender, register, upload
from tests.test_extraction_pipeline import API, drain

PACKS = Path(__file__).parent / "fixtures" / "packs"
PACK02 = PACKS / "pack02"
QUOTES = ("quotation_1_sparkmore_supplies.pdf", "quotation_2_greenvale_cable_and_conduit.xlsx")
GREENVALE_3 = PACKS / "pack03" / "quotation_1_greenvale_cable_and_conduit.pdf"
URL = f"{API}/suppliers"


def _quote(actor: Actor, tender_id: str, path: Path) -> None:
    r = upload(actor, tender_id, path.read_bytes(), path.name, kind="quotation")
    assert r.status_code == 201, r.text
    drain()


def _two_quotes(email: str = "sup@example.com"):
    actor = register(email)
    tender_id = make_tender(actor)
    for name in QUOTES:
        _quote(actor, tender_id, PACK02 / name)
    return actor, tender_id


def _by_name(actor: Actor) -> dict[str, dict]:
    return {s["name"]: s for s in actor.client.get(URL).json()}


def test_list_shows_suppliers_with_quotation_counts() -> None:
    actor, tender_id = _two_quotes()
    suppliers = actor.client.get(URL).json()
    assert len(suppliers) == 2
    assert [s["quotation_count"] for s in suppliers] == [1, 1]
    assert {"id", "name", "notes", "quotation_count", "created_at"} == set(suppliers[0])
    _quote(actor, tender_id, GREENVALE_3)
    after = actor.client.get(URL).json()
    assert len(after) == 2, "Greenvale must appear once"
    assert sorted(s["quotation_count"] for s in after) == [1, 2]
    one = actor.client.get(f"{URL}/{after[0]['id']}")
    assert one.status_code == 200 and one.json() == after[0]


def test_create_then_duplicate_name_is_refused() -> None:
    actor = register("c1@example.com")
    r = actor.client.post(URL, json={"name": "Acme (Pty) Ltd", "notes": "Cable house"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["name"], body["notes"], body["quotation_count"]) == (
        "Acme (Pty) Ltd",
        "Cable house",
        0,
    )
    dup = actor.client.post(URL, json={"name": "acme"})
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "supplier_exists"
    assert len(actor.client.get(URL).json()) == 1


def test_patch_renames_updates_key_and_sets_and_clears_notes() -> None:
    actor = register("p1@example.com")
    a = actor.client.post(URL, json={"name": "Alpha Supplies"}).json()
    b = actor.client.post(URL, json={"name": "Beta Supplies"}).json()
    r = actor.client.patch(f"{URL}/{a['id']}", json={"name": "Gamma Electrical", "notes": "n"})
    assert r.status_code == 200 and r.json()["name"] == "Gamma Electrical"
    assert r.json()["notes"] == "n"
    clash = actor.client.patch(f"{URL}/{b['id']}", json={"name": "gamma electrical (pty) ltd"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "supplier_exists"
    # the old key is free again, the new one is taken
    assert actor.client.post(URL, json={"name": "alpha supplies"}).status_code == 201
    assert actor.client.post(URL, json={"name": "Gamma Electrical"}).status_code == 409
    cleared = actor.client.patch(f"{URL}/{a['id']}", json={"notes": None})
    assert cleared.status_code == 200 and cleared.json()["notes"] is None
    assert cleared.json()["name"] == "Gamma Electrical"


def test_patch_validation() -> None:
    actor = register("p2@example.com")
    a = actor.client.post(URL, json={"name": "Alpha"}).json()
    for body in ({}, {"name": None}, {"name": ""}, {"name": "a\x00b"}, {"notes": "x\x00"},
                 {"unknown": 1}):  # fmt: skip
        r = actor.client.patch(f"{URL}/{a['id']}", json=body)
        assert r.status_code == 422, (body, r.text)
    assert actor.client.post(URL, json={"name": "a\x00b"}).status_code == 422
    assert actor.client.post(URL, json={"name": "x" * 201}).status_code == 422


def test_merge_moves_quotations_and_deletes_the_source() -> None:
    actor, tender_id = _two_quotes("m1@example.com")
    _quote(actor, tender_id, GREENVALE_3)
    by = _by_name(actor)
    spark = next(s for n, s in by.items() if "park" in n)
    green = next(s for n, s in by.items() if "reen" in n)
    assert (spark["quotation_count"], green["quotation_count"]) == (1, 2)
    r = actor.client.post(f"{URL}/{spark['id']}/merge", json={"into_id": green["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == green["id"] and r.json()["quotation_count"] == 3
    assert actor.client.get(f"{URL}/{spark['id']}").status_code == 404
    assert [s["id"] for s in actor.client.get(URL).json()] == [green["id"]]
    with session_scope() as s:  # matches follow their quotations
        assert not [
            m for m in s.scalars(select(MatchSuggestion)) if str(m.supplier_id) == spark["id"]
        ]


def _confirm_pair(actor: Actor, boq_item_id: UUID, quote_item_id: UUID, supplier_id: str) -> None:
    with session_scope() as s:
        s.add(MatchSuggestion(
            organisation_id=UUID(actor.org_id), boq_item_id=boq_item_id,
            quotation_item_id=quote_item_id, supplier_id=UUID(supplier_id), score=0.9,
            classification="clear", evidence={}, status="confirmed",
            decided_at=datetime.now(UTC), decided_by=UUID(actor.me["user_id"]),
        ))  # fmt: skip


def test_merge_with_a_confirmed_collision_changes_nothing() -> None:
    from app.modules.estimating.models import BoqItem
    from app.modules.suppliers.models import Quotation, QuotationItem
    from tests.test_matching_pipeline import _up

    actor = register("m2@example.com")
    tender_id = make_tender(actor)
    _up(actor, tender_id, "boq.xlsx", "boq")
    for name in QUOTES:
        _up(actor, tender_id, name, "quotation")
    by = _by_name(actor)
    ids = [s["id"] for s in by.values()]
    with session_scope() as s:
        s.query(MatchSuggestion).delete()
        boq_id = s.scalars(select(BoqItem.id)).first()
        items = {}
        for sid in ids:
            items[sid] = s.scalars(
                select(QuotationItem.id)
                .join(Quotation, Quotation.id == QuotationItem.quotation_id)
                .where(Quotation.supplier_id == UUID(sid))
            ).first()
    for sid in ids:  # confirmed for the same BoQ line, one per supplier
        _confirm_pair(actor, boq_id, items[sid], sid)
    r = actor.client.post(f"{URL}/{ids[0]}/merge", json={"into_id": ids[1]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "match_conflict", r.text
    after = _by_name(actor)
    assert {s["id"]: s["quotation_count"] for s in after.values()} == {
        s["id"]: s["quotation_count"] for s in by.values()
    }
    with session_scope() as s:
        assert s.scalar(select(Supplier).where(Supplier.id == UUID(ids[0]))) is not None


def test_merge_into_self_and_unknown_target() -> None:
    actor, _ = _two_quotes("m3@example.com")
    sid = actor.client.get(URL).json()[0]["id"]
    r = actor.client.post(f"{URL}/{sid}/merge", json={"into_id": sid})
    assert r.status_code == 422 and "Choose a different supplier." in r.text
    other = register("m3b@example.com", org="Other")
    foreign = other.client.post(URL, json={"name": "Foreign"}).json()["id"]
    r = actor.client.post(f"{URL}/{sid}/merge", json={"into_id": foreign})
    assert r.status_code == 404
    r = actor.client.post(f"{URL}/{sid}/merge", json={"into_id": str(UUID(int=7))})
    assert r.status_code == 404
    assert len(actor.client.get(URL).json()) == 2


def test_roles_reviewer_and_project_manager_read_only() -> None:
    admin, _ = _two_quotes("r1@example.com")
    ids = [s["id"] for s in admin.client.get(URL).json()]
    for n, role in enumerate(("reviewer", "project_manager")):
        member = add_member(admin, f"role{n}@example.com", role)
        assert member.client.get(URL).status_code == 200
        assert member.client.get(f"{URL}/{ids[0]}").status_code == 200
        assert member.client.post(URL, json={"name": "New"}).status_code == 403
        assert member.client.patch(f"{URL}/{ids[0]}", json={"notes": "x"}).status_code == 403
        merge = member.client.post(f"{URL}/{ids[0]}/merge", json={"into_id": ids[1]})
        assert merge.status_code == 403
    estimator = add_member(admin, "est2@example.com", "estimator")
    assert estimator.client.post(URL, json={"name": "By Estimator"}).status_code == 201


def test_merge_refuses_when_an_affected_tender_is_archived() -> None:
    actor, tender_id = _two_quotes("a1@example.com")
    ids = [s["id"] for s in actor.client.get(URL).json()]
    assert actor.client.post(f"{API}/tenders/{tender_id}/archive").status_code == 200
    r = actor.client.post(f"{URL}/{ids[0]}/merge", json={"into_id": ids[1]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "tender_archived", r.text
    assert len(actor.client.get(URL).json()) == 2


def test_foreign_ids_are_404() -> None:
    a = register("f1@example.com", org="Org A")
    b = register("f2@example.com", org="Org B")
    foreign = b.client.post(URL, json={"name": "Secret Supplies"}).json()["id"]
    assert a.client.get(f"{URL}/{foreign}").status_code == 404
    assert a.client.patch(f"{URL}/{foreign}", json={"notes": "x"}).status_code == 404
    mine = a.client.post(URL, json={"name": "Mine"}).json()["id"]
    assert a.client.post(f"{URL}/{foreign}/merge", json={"into_id": mine}).status_code == 404
    assert "Secret" not in a.client.get(URL).text
