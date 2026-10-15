"""Normalisation helpers shared by the scorers."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

UNIT_CANON = {
    "m": "m", "metre": "m", "metres": "m", "meter": "m", "mtr": "m",
    "no": "no", "nr": "no", "each": "no", "ea": "no", "number": "no",
    "item": "item", "items": "item",
    "sum": "sum", "ls": "sum", "lump sum": "sum", "l/s": "sum",
    "m2": "m2", "sqm": "m2", "roll": "roll",
}  # fmt: skip

MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
FACT_PATTERN = re.compile(
    rf"\b\d{{1,2}}:\d{{2}}\b|\b\d+\b|\b\d[a-z]{{1,2}}\b|\b(?:{MONTHS})\b", re.IGNORECASE
)


def norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def tokens(text: object) -> set[str]:
    return set(norm(text).split())


def jaccard(a: object, b: object) -> float:
    sa, sb = tokens(a), tokens(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def canon_unit(unit: object) -> str | None:
    if unit is None:
        return None
    key = re.sub(r"[.\s²]+$", "", norm(unit).replace("²", "2")).replace(".", "")
    return UNIT_CANON.get(key, key or None)


def parse_quantity(value: object) -> Decimal | None:
    """Parse '1 250', '1,250.00', '250,5', 250 ... Returns None for missing or unparseable."""
    if value is None:
        return None
    text = str(value).strip().replace(" ", " ").replace(" ", " ").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def fact_tokens(text: str) -> set[str]:
    """Numbers, times, grades and month names in a sentence: the values that must survive."""
    return {m.group(0).lower() for m in FACT_PATTERN.finditer(text)}
