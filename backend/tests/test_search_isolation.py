"""F4 retrieval canary: search never returns another organisation's or tender's chunks."""

from __future__ import annotations

import pytest

from app.worker import handlers
from app.worker.runner import process_one
from tests.conftest import make_pdf, make_tender, register, upload

API = "/api/v1"
CANARY = "ZXQ-CANARY-7731"
SHARED = "switchgear"


def ingest(actor, tender_id: str, pages: list[str], name: str) -> dict:
    body = upload(actor, tender_id, make_pdf(pages), name).json()
    assert process_one(handlers.HANDLERS) is True  # the ingest job
    while process_one(handlers.HANDLERS):  # the extraction jobs that ingest queued
        pass
    return body


def search(actor, tender_id: str, q: str):
    return actor.client.get(f"{API}/tenders/{tender_id}/search", params={"q": q})


def test_search_never_crosses_organisations() -> None:
    a = register("a@example.com", org="Org A")
    b = register("b@example.com", org="Org B")
    tender_a, tender_b = make_tender(a, "A tender"), make_tender(b, "B tender")
    doc_a = ingest(a, tender_a, [f"A {SHARED} schedule for the plant room"], "a-doc.pdf")
    doc_b = ingest(b, tender_b, [f"B {SHARED} schedule {CANARY} secret"], "b-doc.pdf")

    # The canary lives only in B's document.
    assert search(a, tender_a, CANARY).json() == []

    shared_hits = search(a, tender_a, SHARED).json()
    assert shared_hits, "A should find its own document"
    assert {h["version_id"] for h in shared_hits} == {doc_a["version"]["id"]}
    assert {h["document_title"] for h in shared_hits} == {doc_a["document"]["title"]}
    assert CANARY not in str(shared_hits) and doc_b["version"]["id"] not in str(shared_hits)

    # B's tender id is invisible to A.
    for q in (CANARY, SHARED):
        r = search(a, tender_b, q)
        assert r.status_code == 404
        assert CANARY not in r.text and "b-doc" not in r.text

    own = search(b, tender_b, CANARY).json()
    assert own and own[0]["version_id"] == doc_b["version"]["id"]


def test_search_is_scoped_to_one_tender_within_an_organisation() -> None:
    a = register("a@example.com", org="Org A")
    tender_1, tender_2 = make_tender(a, "Tender 1"), make_tender(a, "Tender 2")
    doc_1 = ingest(a, tender_1, [f"First {SHARED} clause"], "one.pdf")
    doc_2 = ingest(a, tender_2, [f"Second {SHARED} clause {CANARY}"], "two.pdf")

    assert search(a, tender_1, CANARY).json() == []
    hits_1 = search(a, tender_1, SHARED).json()
    assert hits_1 and {h["version_id"] for h in hits_1} == {doc_1["version"]["id"]}
    hits_2 = search(a, tender_2, SHARED).json()
    assert hits_2 and {h["version_id"] for h in hits_2} == {doc_2["version"]["id"]}
    assert search(a, tender_2, CANARY).json()


@pytest.mark.parametrize(
    "q",
    ["' OR 1=1 --", "a & b | !c", "unbalanced 'quote", 'double " quote', "x" * 200],
    ids=["sql-or", "tsquery-ops", "single-quote", "double-quote", "max-length"],
)
def test_search_metacharacters_do_not_error(q: str) -> None:
    a = register("a@example.com", org="Org A")
    tender = make_tender(a)
    ingest(a, tender, [f"plain {SHARED} text"], "doc.pdf")
    r = search(a, tender, q)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)


def test_search_query_over_200_characters_is_rejected() -> None:
    a = register("a@example.com", org="Org A")
    tender = make_tender(a)
    assert search(a, tender, "x" * 201).status_code == 422
