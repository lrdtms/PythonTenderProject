"""A real organisation with quotation documents and extraction runs, for store and matching tests.

The quotation documents are uploaded but not drained, so the worker never runs `extract_quotation`
on them: the tests call `store_quotation` themselves. Each version gets a `quotation` run that
borrows the ingest job's id (the (job_id, kind) pair is free), as `seed_review_rows` does."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import session_scope
from app.kernel import OrgContext, Role
from app.modules.estimating.models import BoqItem
from app.modules.pipeline.models import ExtractionRun
from app.modules.suppliers.models import QuotationItem
from app.modules.suppliers.public import store_quotation
from tests.conftest import make_tender, make_xlsx, register, upload
from tests.review_helpers import boq_version

QUOTE_ROWS = [["#", "Description", "Unit", "Qty", "Unit price"], ["1", "Cable", "m", "10", "5"]]


@dataclass
class QuotationContext:
    session: Session
    ctx: OrgContext
    versions: list[UUID]
    runs: list[UUID]
    boq_item_id: UUID | None
    tender_id: UUID | None = None
    supplier_ids: list[UUID] = field(default_factory=list)
    quotation_ids: list[UUID] = field(default_factory=list)

    @property
    def version_id(self) -> UUID:
        return self.versions[0]

    @property
    def run_id(self) -> UUID:
        return self.runs[0]

    def items(self) -> list[QuotationItem]:
        """Quotation items of the first version, in order."""
        stmt = (
            select(QuotationItem)
            .where(QuotationItem.document_version_id == self.version_id)
            .order_by(QuotationItem.position)
        )
        return list(self.session.scalars(stmt))


@contextmanager
def quotation_context(
    versions: int = 1, with_boq: bool = False, quotation_rows: list[dict] | None = None
) -> Iterator[QuotationContext]:
    actor = register("store@example.com")
    if with_boq:
        actor, tender_id, _ = boq_version(actor)  # drains: BoQ ingest and extraction run now
    else:
        tender_id = make_tender(actor)
    uploads = [
        upload(actor, tender_id, make_xlsx(QUOTE_ROWS), f"quote{n}.xlsx", kind="quotation").json()
        for n in range(versions)
    ]
    ctx = OrgContext(UUID(actor.me["user_id"]), UUID(actor.org_id), Role.ADMIN)
    with session_scope() as session:
        version_ids, run_ids = [], []
        for body in uploads:
            run = ExtractionRun(
                organisation_id=ctx.organisation_id,
                document_version_id=UUID(body["version"]["id"]),
                job_id=UUID(body["job_id"]),
                kind="quotation",
            )
            session.add(run)
            session.flush()
            version_ids.append(run.document_version_id)
            run_ids.append(run.id)
        boq_item_id = session.scalar(
            select(BoqItem.id).where(BoqItem.organisation_id == ctx.organisation_id)
        )
        qc = QuotationContext(session, ctx, version_ids, run_ids, boq_item_id, UUID(tender_id))
        if quotation_rows is not None:  # real items without the worker; one supplier per version
            for n, (version_id, run_id) in enumerate(zip(version_ids, run_ids, strict=True)):
                stored = store_quotation(
                    session, ctx, version_id, run_id, {"supplier_name": f"Supplier {n}"},
                    quotation_rows, f"quote{n}",
                )  # fmt: skip
                qc.supplier_ids.append(stored.supplier_id)
                qc.quotation_ids.append(stored.quotation_id)
        yield qc
