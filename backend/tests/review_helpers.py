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


def seed_review_rows(actor: Actor, version_id: str, job_id: str) -> dict[str, str]:
    """Give an organisation one BoQ line and one requirement without running a worker job, so
    sweeps of the review routes have real rows to be refused. Uses the ingest job's id for the
    two runs (the (job_id, kind) pair is free)."""
    from uuid import UUID

    from sqlalchemy import select

    from app.db.session import session_scope
    from app.kernel import OrgContext, Role
    from app.modules.checklist import public as checklist
    from app.modules.checklist.models import Requirement
    from app.modules.estimating import public as estimating
    from app.modules.estimating.models import BoqItem
    from app.modules.pipeline.models import ExtractionRun

    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as s:
        for kind in ("boq", "requirements"):
            run = ExtractionRun(
                organisation_id=ctx.organisation_id,
                document_version_id=UUID(version_id),
                job_id=UUID(job_id),
                kind=kind,
            )
            s.add(run)
            s.flush()
            if kind == "boq":
                estimating.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"item_no": "1", "description": "seeded-b-line"}],
                )  # fmt: skip
            else:
                checklist.replace_unreviewed(
                    s, ctx, run.document_version_id, run.id,
                    [{"description": "seeded-b-rule", "requirement_type": "other",
                      "mandatory_status": "mandatory", "evidence_quote": "seeded-b-quote"}],
                )  # fmt: skip
        return {
            "boq_item_id": str(
                s.scalar(select(BoqItem.id).where(BoqItem.organisation_id == ctx.organisation_id))
            ),
            "requirement_id": str(
                s.scalar(
                    select(Requirement.id).where(Requirement.organisation_id == ctx.organisation_id)
                )
            ),
        }


def seed_supplier_rows(actor: Actor) -> dict[str, str]:
    """Give an organisation one supplier (no quotation), for sweeps of the supplier routes."""
    from uuid import UUID

    from app.db.session import session_scope
    from app.kernel import OrgContext, Role
    from app.modules.suppliers.repo import SupplierRepo

    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as s:
        supplier, _ = SupplierRepo(s, ctx).get_or_create("Seeded B Supplies", "seeded b supplies")
        return {"supplier_id": str(supplier.id)}
