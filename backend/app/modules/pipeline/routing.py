"""Which extraction runs for which document kind (spec section 4)."""

from __future__ import annotations

from app.modules.documents import public as documents

ROUTING: dict[str, tuple[str, ...]] = {
    "tender_document": (documents.EXTRACT_BOQ_JOB, documents.EXTRACT_REQUIREMENTS_JOB),
    "boq": (documents.EXTRACT_BOQ_JOB,),
    "quotation": (documents.EXTRACT_QUOTATION_JOB,),
    "other": (documents.EXTRACT_REQUIREMENTS_JOB,),
}
KIND_OF_JOB = {
    documents.EXTRACT_BOQ_JOB: "boq",
    documents.EXTRACT_REQUIREMENTS_JOB: "requirements",
    documents.EXTRACT_QUOTATION_JOB: "quotation",
}


def job_types_for_kind(document_kind: str) -> tuple[str, ...]:
    return ROUTING.get(document_kind, ())
