"""Number parsing for BoQ cells. Never rounds silently."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"[\s\u00a0\u2009\u202f]")
_THOUSANDS_COMMA = re.compile(r"\d{1,3}(,\d{3})+")
_MAX_DECIMALS = 4  # NUMERIC(18,4)


def parse_decimal(value: object) -> tuple[Decimal | None, bool]:
    """Return (number, lossy). `lossy` is True when the text is a number with more than four
    decimals: the caller keeps the raw text and flags it instead of rounding."""
    text = _SPACES.sub("", str(value if value is not None else ""))
    text = re.sub(r"^[Rr](?=[\d.,])", "", text)
    if not text or text in {"-", "–", "—"}:
        return None, False
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(",", "") if _THOUSANDS_COMMA.fullmatch(text) else text.replace(",", ".")
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None, False
    if not number.is_finite():
        return None, False
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_MAX_DECIMALS:
        return None, True
    return number, False
