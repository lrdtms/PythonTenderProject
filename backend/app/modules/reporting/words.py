"""Plain-words vocabulary for export files (no internal codes reach a reader)."""

_FALLBACK = "Needs attention"

_FLAGS = {
    "currency_differs": "The quote is in a different currency from the estimate.",
    "currency_missing": "The quote does not state a currency.",
    "vat_basis_unknown": "It is not known whether the quoted price includes VAT.",
    "price_missing": "The chosen quote has no unit price.",
    "quantity_missing": "The bill of quantities has no usable quantity for this line.",
    "unit_missing": "The bill of quantities has no unit for this line.",
    "unit_mismatch": "The quote unit differs from the bill of quantities unit.",
    "unreviewed_source": "The source quote line has not been reviewed by a person.",
    "source_changed": "Source changed since this line was priced.",
}

_MARKUP_BASIS = {"cost": "Markup on cost", "selling_price": "Markup on selling price"}
_ESTIMATE_STATUS = {"draft": "Draft", "reviewed": "Reviewed", "approved": "Approved"}
_REVIEW_STATUS = {
    "unreviewed": "Not yet reviewed",
    "confirmed": "Confirmed by a person",
    "corrected": "Corrected by a person",
    "rejected": "Rejected",
}
_MANDATORY = {
    "mandatory": "Mandatory",
    "conditional": "Conditional",
    "informational": "For information",
}
_PRICE_SOURCE = {
    "supplier": "Supplier quote",
    "manual": "Entered by hand",
    "excluded": "Excluded from the estimate",
    "unresolved": "Not priced yet",
}


def flag_text(code: str) -> str:
    return _FLAGS.get(code, _FALLBACK)


def markup_basis_text(basis: str) -> str:
    return _MARKUP_BASIS.get(basis, _FALLBACK)


def vat_basis_text(includes_vat: bool | None) -> str:
    if includes_vat is None:
        return "VAT basis not stated"
    return "Includes VAT" if includes_vat else "Excludes VAT"


def estimate_status_text(status: str) -> str:
    return _ESTIMATE_STATUS.get(status, _FALLBACK)


def review_status_text(status: str) -> str:
    return _REVIEW_STATUS.get(status, _FALLBACK)


def mandatory_text(status: str) -> str:
    return _MANDATORY.get(status, _FALLBACK)


def price_source_text(source: str) -> str:
    return _PRICE_SOURCE.get(source, _FALLBACK)
