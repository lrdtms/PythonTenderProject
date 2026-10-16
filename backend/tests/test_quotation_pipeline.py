"""Quotations through the real worker."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.db.session import session_scope
from app.modules.suppliers.models import Quotation, QuotationItem, Supplier
from tests.conftest import make_pdf, make_tender, make_xlsx, register, upload
from tests.test_extraction_pipeline import API, drain

PACKS = Path(__file__).parent / "fixtures" / "packs"


def _upload(actor, tender_id, pack: str, name: str):
    data = (PACKS / pack / name).read_bytes()
    body = upload(actor, tender_id, data, name, kind="quotation").json()
    drain()
    return body["version"]["id"]


def _quotation_run(actor, version_id: str) -> dict:
    kinds = actor.client.get(f"{API}/document-versions/{version_id}/extraction").json()["kinds"]
    return next(k for k in kinds if k["kind"] == "quotation")


def test_pdf_and_xlsx_quotations_are_extracted_end_to_end() -> None:
    actor = register("q@example.com")
    tender_id = make_tender(actor)
    pdf = _upload(actor, tender_id, "pack02", "quotation_1_sparkmore_supplies.pdf")
    xlsx = _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    with session_scope() as s:
        names = sorted(s.scalars(select(Supplier.name)))
        assert names == ["Greenvale Cable and Conduit", "Sparkmore Supplies"]
        counts = {
            str(q.document_version_id): len(
                s.scalars(select(QuotationItem).where(QuotationItem.quotation_id == q.id)).all()
            )
            for q in s.scalars(select(Quotation))
        }
        assert counts == {pdf: 15, xlsx: 15}
    quotation = _quotation_run(actor, pdf)
    assert quotation["job"]["status"] in ("succeeded", "succeeded_with_warnings")
    assert quotation["run"]["counts"]["items"] == 15


def test_two_quotes_from_one_supplier_share_the_supplier_row() -> None:
    actor = register("q2@example.com")
    tender_id = make_tender(actor)
    _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    _upload(actor, tender_id, "pack03", "quotation_1_greenvale_cable_and_conduit.pdf")
    with session_scope() as s:
        assert s.scalars(select(Supplier.name)).all() == ["Greenvale Cable and Conduit"]
        assert len(s.scalars(select(Quotation)).all()) == 2


def test_rerun_through_the_api_keeps_one_quotation_and_replaces_items() -> None:
    actor = register("q3@example.com")
    tender_id = make_tender(actor)
    version = _upload(actor, tender_id, "pack02", "quotation_2_greenvale_cable_and_conduit.xlsx")
    url = f"{API}/document-versions/{version}/extract"
    assert actor.client.post(url, json={"deep_scan": False}).status_code == 202
    drain()
    with session_scope() as s:
        assert len(s.scalars(select(Quotation)).all()) == 1
        assert len(s.scalars(select(QuotationItem)).all()) == 15


def test_a_quotation_without_a_table_completes_with_a_warning() -> None:
    actor = register("q4@example.com")
    tender_id = make_tender(actor)
    pdf = make_pdf(["Dear sir, we regret we cannot quote."])
    body = upload(actor, tender_id, pdf, "q.pdf", kind="quotation").json()
    drain()
    run = _quotation_run(actor, body["version"]["id"])["run"]
    assert run["status"] == "succeeded_with_warnings"
    assert {"code": "NO_QUOTATION_FOUND"} in run["warnings"]
    with session_scope() as s:
        assert s.scalars(select(QuotationItem)).all() == []


def test_header_gaps_become_warnings() -> None:
    actor = register("q5@example.com")
    tender_id = make_tender(actor)
    rows = [["#", "Description", "Unit", "Qty", "Unit price"], ["1", "Cable", "m", "10", "5"]]
    xlsx = make_xlsx(rows, sheet="Quote")
    body = upload(actor, tender_id, xlsx, "mystery quote.xlsx", kind="quotation").json()
    drain()
    run = _quotation_run(actor, body["version"]["id"])["run"]
    codes = {w["code"] for w in run["warnings"]}
    assert {"NO_SUPPLIER_NAME", "NO_CURRENCY", "NO_VALIDITY"} <= codes
    with session_scope() as s:
        assert s.scalars(select(Supplier.name)).all() == ["Mystery Quote"]


def test_other_documents_do_not_get_a_quotation_job() -> None:
    actor = register("q6@example.com")
    tender_id = make_tender(actor)
    body = upload(actor, tender_id, make_pdf(["General conditions."]), "t.pdf").json()
    drain()
    url = f"{API}/document-versions/{body['version']['id']}/extraction"
    kinds = {k["kind"]: k for k in actor.client.get(url).json()["kinds"]}
    assert kinds["quotation"]["job"] is None
