"""Builders shared by the review tests."""

from __future__ import annotations

from tests.conftest import Actor, make_tender, make_xlsx, register, upload
from tests.test_extraction_pipeline import API, CLAUSE, drain, req_json, tender_pdf

BOQ_ROWS = [
    ["Item", "Description", "Unit", "Quantity", "Rate", "Amount"],
    ["1.1", "Cable 4mm", "Metre", "10", "5", ""],
    ["1.2", "Board 63 A", "each", "2", "", ""],
    ["1.3", "Conduit 20mm", "Metre", "", "", ""],
]


def boq_version(actor: Actor | None = None, rows: list[list[object]] | None = None):
    """An organisation with an extracted XLSX BoQ. Returns (actor, tender_id, version_id)."""
    actor = actor or register("est@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_xlsx(rows or BOQ_ROWS), "boq.xlsx", kind="boq").json()
    drain()
    return actor, tender_id, body["version"]["id"]


def boq_items(actor: Actor, version_id: str) -> list[dict]:
    return actor.client.get(f"{API}/document-versions/{version_id}/boq-items").json()


def requirement_version(fake_llm, actor: Actor | None = None):
    """An organisation with one extracted requirement. Returns (actor, tender_id, version_id)."""
    fake_llm([req_json(CLAUSE)])
    actor = actor or register("est@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, tender_pdf(), "t.pdf").json()
    drain()
    return actor, tender_id, body["version"]["id"]


def requirements(actor: Actor, version_id: str) -> list[dict]:
    return actor.client.get(f"{API}/document-versions/{version_id}/requirements").json()
