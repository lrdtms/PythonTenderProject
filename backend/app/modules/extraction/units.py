"""Canonical units. Mirrors the evaluation harness so the scores line up."""

from __future__ import annotations

import re

UNIT_CANON = {
    "m": "m", "metre": "m", "metres": "m", "meter": "m", "mtr": "m", "lm": "m",
    "no": "no", "nr": "no", "each": "no", "ea": "no", "number": "no",
    "item": "item", "items": "item",
    "sum": "sum", "ls": "sum", "lump sum": "sum", "l/s": "sum",
    "m2": "m2", "sqm": "m2", "sq m": "m2",
    "m3": "m3", "roll": "roll", "kg": "kg", "hr": "hr", "hour": "hr", "day": "day",
    "set": "set", "pair": "pair",
}  # fmt: skip


def _norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def canon_unit(raw: object) -> str | None:
    if raw is None:
        return None
    key = re.sub(r"[.\s²³]+$", "", _norm(raw).replace("²", "2").replace("³", "3")).replace(".", "")
    return UNIT_CANON.get(key, key or None)
