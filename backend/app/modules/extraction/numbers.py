"""Number parsing for BoQ cells. Never rounds silently."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SPACES = re.compile(r"[\s\u00a0\u2009\u202f]")
_THOUSANDS_COMMA = re.compile(r"\d{1,3}(,\d{3})+")
_MAX_DECIMALS = 4  # NUMERIC(18,4)
_MAX_INTEGER_DIGITS = 14  # NUMERIC(18,4): |value| < 10**14
_EXPONENT_FORM = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)[eE][+-]?\d+")


def parse_decimal(value: object) -> tuple[Decimal | None, bool]:
    """Return (number, lossy). `lossy` is True when the text is a number the column cannot hold
    exactly (more than four decimals, or |value| >= 10**14, or an absurd exponent): the caller
    keeps the raw text and flags it instead of rounding or overflowing."""
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
        # A number whose exponent is beyond Decimal's own range: a number, but not storable.
        return None, bool(_EXPONENT_FORM.fullmatch(text))
    if not number.is_finite():
        return None, False
    exponent = number.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_MAX_DECIMALS:
        return None, True
    if number.is_zero():
        return (Decimal(0) if isinstance(exponent, int) and exponent > 0 else number), False
    # adjusted() is the exponent of the leading digit: checked without materialising the value.
    if number.adjusted() >= _MAX_INTEGER_DIGITS:
        return None, True
    return number, False


_SINGLE_COMMA_THREE = re.compile(r"\d{1,3},\d{3}")


def is_ambiguous_separator(value: object) -> bool:
    """True for a lone comma followed by exactly three digits (`1,500`). South African usage
    can mean 1.5 or 1500; `parse_decimal` reads it as 1500 and the line is flagged for review."""
    text = _SPACES.sub("", str(value if value is not None else ""))
    text = re.sub(r"^[Rr](?=[\d.,])", "", text)
    return _SINGLE_COMMA_THREE.fullmatch(text) is not None
