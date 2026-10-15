"""Which extraction runs for which document kind (spec section 4)."""

from __future__ import annotations

from app.modules.documents import public as documents

ROUTING: dict[str, tuple[str, ...]] = {
    "tender_document": (documents.EXTRACT_BOQ_JOB, documents.EXTRACT_REQUIREMENTS_JOB),
    "boq": (documents.EXTRACT_BOQ_JOB,),
    "quotation": (),  # Slice 5
    "other": (documents.EXTRACT_REQUIREMENTS_JOB,),
}
KIND_OF_JOB = {documents.EXTRACT_BOQ_JOB: "boq", documents.EXTRACT_REQUIREMENTS_JOB: "requirements"}


def job_types_for_kind(document_kind: str) -> tuple[str, ...]:
    return ROUTING.get(document_kind, ())
